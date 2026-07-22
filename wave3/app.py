"""GTK4 control panel for the Elgato Wave:3.

Every row is writable, but writes are transactional: the block is read
back and restored if any byte outside the target field moved. Fields whose
offset has been confirmed by watching the hardware change it are badged
"verified"; the rest are badged "guarded" and rely on the rollback.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import deck  # noqa: E402
from . import fx  # noqa: E402
from . import mixer  # noqa: E402
from . import protocol as p  # noqa: E402
from .device import DeviceError, GuardViolation, PermissionError_, Wave3  # noqa: E402
from .deckview import DeckPage  # noqa: E402
from .fxview import FxPage  # noqa: E402
from .mixerview import MixerPage  # noqa: E402

POLL_MS = 100
WRITE_DEBOUNCE_MS = 180

# Wider than Adwaita's 600px default so a maximised window is not
# mostly empty, narrow enough that rows stay scannable.
CONTENT_WIDTH = 1040
GROUPS = ("Microphone", "Monitoring", "Device")

STATE_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "wave3"
)
STATE_FILE = os.path.join(STATE_DIR, "verified.json")

UDEV_HINT = (
    "Run 'sudo make install-udev' from the project root, then replug the "
    "microphone. Until then the panel needs to be started with sudo."
)


def load_verified():
    verified = set(p.PROVEN_BY_OBSERVATION)
    try:
        with open(STATE_FILE) as fh:
            verified |= set(json.load(fh))
    except (OSError, ValueError):
        pass
    return verified


def save_verified(verified):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STATE_FILE, "w") as fh:
            json.dump(sorted(verified), fh, indent=2)
    except OSError:
        pass


class DeviceApi:
    """Config-block access for the deck.

    Deck writes go through Wave3.set_field, so they get the same read-back and
    rollback protection as the Microphone page. Reads are cached briefly
    because the deck polls several actions at 4 Hz and each uncached read is a
    USB control transfer.
    """

    CACHE_SECONDS = 0.2

    def __init__(self, dev):
        self.dev = dev
        self._config = None
        self._fetched = 0.0

    def ready(self):
        return self.dev.connected

    def invalidate(self):
        self._config = None

    def _block(self):
        now = GLib.get_monotonic_time() / 1_000_000.0
        if self._config is None or now - self._fetched > self.CACHE_SECONDS:
            self._config = self.dev.read_config()
            self._fetched = now
        return self._config

    def read(self, path):
        return p.decode_field(p.BY_PATH[path], self._block())

    def write(self, path, value):
        result = self.dev.set_field(p.BY_PATH[path], value)
        self._config = bytearray(result.actual)
        self._fetched = GLib.get_monotonic_time() / 1_000_000.0


class FieldRow:
    """Wraps one Adwaita row and keeps it in sync with a config field."""

    def __init__(self, field, on_change):
        self.field = field
        self._on_change = on_change
        self._syncing = False
        self.verified = False

        self.badge = Gtk.Label(label="guarded", css_classes=["accent", "caption"])
        self.badge.set_tooltip_text(
            "Offset recovered from static analysis. Every write is read back "
            "and rolled back if it disturbs any other byte."
        )

        if field.kind == p.BOOL:
            self.row = Adw.SwitchRow(title=field.label)
            self.row.connect("notify::active", self._emit)
        elif field.kind == p.ENUM:
            model = Gtk.StringList.new([p.VOLUME_SELECT[k] for k in sorted(p.VOLUME_SELECT)])
            self.row = Adw.ComboRow(title=field.label, model=model)
            self.row.connect("notify::selected", self._emit)
        else:
            adjustment = Gtk.Adjustment(
                lower=field.minimum, upper=field.maximum,
                step_increment=field.step, page_increment=field.step * 2,
            )
            digits = 0 if field.step >= 1 else 1
            self.row = Adw.SpinRow(title=field.label, adjustment=adjustment, digits=digits)
            if field.unit:
                self.row.set_subtitle(field.unit)
            self.row.connect("notify::value", self._emit)

        self.row.add_suffix(self.badge)

    def _emit(self, *_args):
        if self._syncing:
            return
        self._on_change(self.field, self.value)

    @property
    def value(self):
        if self.field.kind == p.BOOL:
            return self.row.get_active()
        if self.field.kind == p.ENUM:
            return sorted(p.VOLUME_SELECT)[self.row.get_selected()]
        return self.row.get_value()

    def matches(self, value):
        if self.field.kind == p.BOOL:
            return self.row.get_active() == bool(value)
        if self.field.kind == p.ENUM:
            return self.value == value
        return abs(self.row.get_value() - value) < self.field.step / 2.0

    def sync(self, value):
        if self.matches(value):
            return
        self._syncing = True
        if self.field.kind == p.BOOL:
            self.row.set_active(bool(value))
        elif self.field.kind == p.ENUM:
            order = sorted(p.VOLUME_SELECT)
            if value in order:
                self.row.set_selected(order.index(value))
        else:
            self.row.set_value(value)
        self._syncing = False

    def unlock(self):
        if self.verified:
            return
        self.verified = True
        self.badge.set_label("verified")
        self.badge.set_css_classes(["success", "caption"])
        self.badge.set_tooltip_text("Offset confirmed by observing the hardware change it.")


class Window(Adw.ApplicationWindow):
    def __init__(self, app, dev):
        super().__init__(
            application=app, title="Wave:3",
            default_width=1040, default_height=700,
        )
        self.dev = dev
        self.verified = load_verified()
        self.rows = {}
        self._last_config = None
        self._writing = False
        self._alert = False
        self._pending = {}
        self._intent = {}

        # Adw.PreferencesPage hard-clamps its content to roughly 600px with no
        # public way to widen it, which leaves most of a maximised window empty.
        # Same groups, own clamp, wider ceiling.
        groups = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        groups.set_margin_top(20)
        groups.set_margin_bottom(24)
        groups.set_margin_start(18)
        groups.set_margin_end(18)

        page_clamp = Adw.Clamp(maximum_size=CONTENT_WIDTH, tightening_threshold=680)
        page_clamp.set_child(groups)

        page = Gtk.ScrolledWindow()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.set_vexpand(True)
        page.set_child(page_clamp)

        # A banner is for things that need attention now. The verified/guarded
        # explanation is standing context, so it lives with the controls it
        # describes and the banner stays hidden until something actually fails.
        self.banner = Adw.Banner(title="", revealed=False)

        self.legend = Adw.PreferencesGroup(
            title="Hardware controls",
            description=(
                "Offsets badged verified were confirmed by watching the device "
                "change them. Guarded offsets come from static analysis; each "
                "write is read back and rolled back if it disturbs any other byte."
            ),
        )
        groups.append(self.legend)

        for group_name in GROUPS:
            group = Adw.PreferencesGroup(title=group_name)
            for field in p.CONFIG_FIELDS:
                if field.group != group_name:
                    continue
                row = FieldRow(field, self._apply)
                self.rows[field.path] = row
                group.add(row.row)
            groups.append(group)

        self.status_group = Adw.PreferencesGroup(title="Device information")
        self.info_rows = {}
        for key, label in (
            ("api", "Protocol API"),
            ("firmware", "Firmware"),
            ("serial", "Serial"),
            ("/touch_pressed_ms", "Mute pad held"),
            ("/touch_signal", "Mute pad capacitance"),
        ):
            row = Adw.ActionRow(title=label)
            value = Gtk.Label(label="-", css_classes=["dim-label"])
            row.add_suffix(value)
            self.info_rows[key] = value
            self.status_group.add(row)
        groups.append(self.status_group)

        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(
            page, "device", "Microphone", "audio-input-microphone-symbolic"
        )

        self.mixer_page = None
        self.runtime = mixer.Runtime()
        try:
            self.runtime.refresh()
            channels = mixer.load_channels()
            mixer.resolve_sources(
                channels, fx.FX_SOURCE if fx.installed() else None
            )
            if any(
                ch.playback_node(m) in self.runtime.nodes
                for ch in channels for m in mixer.MIXES
            ):
                self.mixer_page = MixerPage(
                    self.runtime, channels, mixer.load_levels(),
                    fx_active=fx.installed(),
                )
                self.stack.add_titled_with_icon(
                    self.mixer_page, "mixer", "Mixer", "multimedia-volume-control-symbolic"
                )
        except Exception as exc:
            self.stack.add_titled_with_icon(
                self._mixer_missing(str(exc)), "mixer", "Mixer",
                "multimedia-volume-control-symbolic",
            )

        self.fx_runtime = fx.Runtime()
        rack = None
        if fx.installed() and self.fx_runtime.refresh() is not None:
            rack = fx.apply_state(fx.build_rack(), fx.load_state())
            # Compressor meters read the raw capsule (chain input) and the
            # rack output, which is the only honest pair available.
            capsule = mixer.resolve_node(mixer.WAVE3_SOURCE_MATCH, "Audio/Source")
            comp_devices = (capsule, fx.FX_SOURCE) if capsule else None
            self.stack.add_titled_with_icon(
                FxPage(self.fx_runtime, rack, comp_devices), "fx", "Effects",
                "applications-multimedia-symbolic",
            )

        self.device_api = DeviceApi(self.dev)
        try:
            actions, self.deck_state = deck.build_actions(
                self.device_api, mixer, self.runtime,
                self.mixer_page.channels if self.mixer_page else [],
                self.fx_runtime if rack else None, rack,
            )
            self.stack.add_titled_with_icon(
                DeckPage(actions), "deck", "Deck", "view-grid-symbolic"
            )
        except Exception as exc:
            self._flash(f"Deck unavailable: {exc}")

        # Mixer is the primary surface; the device page is a settings detour.
        if self.mixer_page is not None:
            self.stack.set_visible_child_name("mixer")

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self.banner)
        toolbar.set_content(self.stack)
        self.set_content(toolbar)

        for path in self.verified:
            if path in self.rows:
                self.rows[path].unlock()
        self._refresh_banner()

        try:
            info = self.dev.read_version()
            for key in ("api", "firmware", "serial"):
                self.info_rows[key].set_label(info.get(key, "-"))
        except DeviceError as exc:
            self._alert_banner(f"Version read failed: {exc}")

        GLib.timeout_add(POLL_MS, self._poll)

    def _mixer_missing(self, reason):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Mixer not installed",
            description=(
                f"The PipeWire topology is not loaded ({reason}). Run "
                "'make install-mixer' from the project root, then restart "
                "this panel."
            ),
        )
        page.add(group)
        return page

    def _refresh_banner(self):
        """Update the standing legend. Never reveals the banner."""
        if self._alert:
            return
        verified = sum(1 for r in self.rows.values() if r.verified)
        total = len(self.rows)
        self.legend.set_title(f"Hardware controls - {verified} of {total} verified")

    def _flash(self, text, seconds=4):
        """Transient note that clears itself."""
        self.banner.remove_css_class("error")
        self.banner.set_title(text)
        self.banner.set_revealed(True)
        GLib.timeout_add_seconds(
            seconds, lambda: (self.banner.set_revealed(False), GLib.SOURCE_REMOVE)[1]
        )

    def _alert_banner(self, text):
        self._alert = True
        self.banner.set_title(text)
        self.banner.add_css_class("error")
        self.banner.set_revealed(True)

    def _clear_alert(self):
        if not self._alert:
            return
        self._alert = False
        self.banner.remove_css_class("error")
        self.banner.set_revealed(False)
        self._refresh_banner()

    def _apply(self, field, value):
        """Record the user's intent, then schedule the write.

        The intent entry makes _poll leave this row alone until the
        transaction resolves; without it the poll would flip the widget
        back to the stale device value while the write is still pending.

        Discrete controls commit on the next main-loop iteration. Only
        continuous ones debounce, to coalesce a drag into one write.
        """
        self._intent[field.path] = value

        handle = self._pending.pop(field.path, None)
        if handle is not None:
            GLib.source_remove(handle)

        delay = 0 if field.kind in (p.BOOL, p.ENUM) else WRITE_DEBOUNCE_MS
        self._pending[field.path] = GLib.timeout_add(delay, self._commit, field, value)

    def _commit(self, field, value):
        self._pending.pop(field.path, None)
        self._writing = True
        try:
            result = self.dev.set_field(field, value)
        except GuardViolation as exc:
            self._alert_banner(str(exc))
            self._resync(field)
        except DeviceError as exc:
            self._alert_banner(f"Write to {field.path} failed: {exc}")
            self._resync(field)
        else:
            self._clear_alert()
            self._last_config = bytearray(result.actual)
            self.rows[field.path].sync(p.decode_field(field, result.actual))
            if result.normalized:
                shown = p.format_value(field, p.decode_field(field, result.actual))
                self._flash(f"{field.label} adjusted by firmware to {shown}")
        finally:
            self._intent.pop(field.path, None)
            self._writing = False
        return GLib.SOURCE_REMOVE

    def _resync(self, field):
        """Snap one row back to whatever the device actually holds."""
        try:
            config = self.dev.read_config()
        except DeviceError:
            return
        self._last_config = config
        self.rows[field.path].sync(p.decode_field(field, config))

    def _poll(self):
        if self._writing:
            return True
        try:
            config = self.dev.read_config()
            status = self.dev.read_status()
        except DeviceError as exc:
            self._alert_banner(str(exc))
            return True

        if self._last_config is not None and config != self._last_config:
            self._verify_changes(config)

        for path, row in self.rows.items():
            if path in self._intent:
                continue
            row.sync(p.decode_field(row.field, config))

        self.info_rows["/touch_pressed_ms"].set_label(f"{status['/touch_pressed_ms']} ms")
        self.info_rows["/touch_signal"].set_label(str(status["/touch_signal"]))

        self._last_config = config
        return True

    def _verify_changes(self, config):
        """Promote any field the hardware changed on its own to verified."""
        changed = {
            p.owning_offset(i)
            for i in range(p.CONFIG_LEN)
            if config[i] != self._last_config[i]
        }
        newly = False
        for offset in changed:
            field = p.BY_OFFSET.get(offset)
            if field is None or field.path in self.verified:
                continue
            self.verified.add(field.path)
            self.rows[field.path].unlock()
            newly = True
        if newly:
            save_verified(self.verified)
            self._refresh_banner()


def load_css():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
    if not os.path.exists(path):
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(path)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.orkait.Wave3")
        self.dev = Wave3()

    def do_activate(self):
        # Dark only: a mixer sits next to a bright preview in a dim room.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        load_css()
        try:
            self.dev.open()
            self.dev.read_config()
        except PermissionError_:
            self._fail("Permission denied on the USB device", UDEV_HINT)
            return
        except DeviceError as exc:
            self._fail("Wave:3 not available", str(exc))
            return
        Window(self, self.dev).present()

    def _fail(self, heading, body):
        dialog = Adw.MessageDialog(heading=heading, body=body)
        dialog.add_response("quit", "Quit")
        dialog.connect("response", lambda *_: self.quit())
        dialog.present()


def main():
    return Application().run(sys.argv)
