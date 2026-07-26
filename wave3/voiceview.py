"""Voice page: one switch and five sliders in front of the whole chain."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import voice  # noqa: E402

APPLY_DEBOUNCE_MS = 80


class VoicePage(Gtk.Box):
    def __init__(self, runtime, values, on_mode_change=None, active=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.runtime = runtime
        self.values = dict(values)
        self._on_mode_change = on_mode_change
        self._rows = {}
        self._pending = {}
        self._syncing = False

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_top(20)
        body.set_margin_bottom(24)
        body.set_margin_start(18)
        body.set_margin_end(18)

        chain = voice.chain_stages(voice.rnnoise_available())
        has_nr = voice.rnnoise_available()

        intro = Adw.PreferencesGroup(
            title="Voice mode",
            description=(
                "One processed-sounding chain, tuned with a few controls "
                "instead of every plugin parameter. Turning this on replaces "
                "the manual effects rack; the Effects page stays available as "
                "the expert view."
            ),
        )

        self.enable = Adw.SwitchRow(
            title="Use voice mode",
            subtitle=" -> ".join(name for name, _p, _l in chain),
        )
        self.enable.set_active(active)
        self.enable.connect("notify::active", self._toggled)
        intro.add(self.enable)

        status = Adw.ActionRow(
            title="AI noise suppression",
            subtitle=("RNNoise found and in use" if has_nr else
                      "RNNoise not installed - using the multiband gate"),
        )
        badge = Gtk.Label(
            label="active" if has_nr else "fallback",
            css_classes=["success" if has_nr else "accent", "caption"],
        )
        status.add_suffix(badge)
        intro.add(status)
        body.append(intro)

        self.controls = Adw.PreferencesGroup(title="Sound")
        for key, label, low, high, unit, description in voice.CONTROLS:
            step = 1.0 if unit == "%" else 0.5
            adjustment = Gtk.Adjustment(
                lower=low, upper=high, step_increment=step,
                page_increment=step * 10, value=self.values[key],
            )
            row = Adw.SpinRow(
                title=label, subtitle=description,
                adjustment=adjustment, digits=0 if unit == "%" else 1,
            )
            row.connect("notify::value", self._changed, key)
            self._rows[key] = row
            self.controls.add(row)

        reset = Adw.ActionRow(
            title="Reset voice settings",
            subtitle="Return these five controls to their defaults",
        )
        button = Gtk.Button(label="Reset")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", self._reset)
        reset.add_suffix(button)
        self.controls.add(reset)
        body.append(self.controls)

        clamp = Adw.Clamp(maximum_size=880, tightening_threshold=680)
        clamp.set_child(body)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(clamp)
        self.append(scroller)

        self._sync_sensitivity()

    def _sync_sensitivity(self):
        self.controls.set_sensitive(self.enable.get_active())

    def _toggled(self, *_a):
        if self._syncing:
            return
        self._sync_sensitivity()
        if self._on_mode_change:
            self._on_mode_change(self.enable.get_active())

    def _changed(self, row, _param, key):
        if self._syncing:
            return
        self.values[key] = row.get_value()
        handle = self._pending.pop(key, None)
        if handle is not None:
            GLib.source_remove(handle)
        self._pending[key] = GLib.timeout_add(APPLY_DEBOUNCE_MS, self._commit, key)

    def _commit(self, key):
        self._pending.pop(key, None)
        self.runtime.apply(self.values)
        voice.save_settings(self.values)
        return GLib.SOURCE_REMOVE

    def _reset(self, _button):
        self.values = dict(voice.DEFAULTS)
        self._syncing = True
        for key, row in self._rows.items():
            row.set_value(self.values[key])
        self._syncing = False
        self.runtime.apply(self.values)
        voice.save_settings(self.values)

    def set_active(self, active):
        self._syncing = True
        self.enable.set_active(active)
        self._syncing = False
        self._sync_sensitivity()
