"""Mixer view: a row of channel strips above two master mix meters."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import meters, mixer  # noqa: E402
from .widgets import ChannelStrip, MasterMeter, prefers_reduced_motion  # noqa: E402

APPLY_DEBOUNCE_MS = 60
METER_FPS_MS = 33

# Strips grow into the available height up to this ceiling, which keeps fader
# travel usable on a tall screen without leaving a maximised window empty.
MIN_STRIP_HEIGHT = 360
MAX_STRIP_HEIGHT = 520

# Bus meters clamp separately - they are horizontal and need far less width.
MASTER_WIDTH = 1180

# Applications start attenuated so the mic sits above them; the mic starts at
# unity because its level belongs to the hardware gain knob.
DEFAULT_PCT = 75.0
DEFAULT_MIC_PCT = 100.0

MIX_LABELS = {mixer.STREAM: "STREAM", mixer.MONITOR: "MONITOR"}


class MixerPage(Gtk.Box):
    def __init__(self, runtime, channels, levels, fx_active=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.runtime = runtime
        self.channels = channels
        self.levels = levels
        self.strips = {}
        self._pending = {}
        self._reduced = prefers_reduced_motion()

        masters = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.master_meters = {}
        for mix in mixer.MIXES:
            meter = MasterMeter(f"{MIX_LABELS[mix]} MIX")
            meter.set_reduced_motion(self._reduced)
            self.master_meters[mix] = meter
            masters.append(meter)

        # A bus meter spanning a full-width window is unreadable.
        master_clamp = Adw.Clamp(maximum_size=MASTER_WIDTH, tightening_threshold=720)
        master_clamp.set_child(masters)
        master_clamp.set_margin_top(14)
        master_clamp.set_margin_start(18)
        master_clamp.set_margin_end(18)
        self.append(master_clamp)
        self.append(Gtk.Separator(margin_top=14))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("strip-row")
        row.set_halign(Gtk.Align.CENTER)
        row.set_valign(Gtk.Align.FILL)
        row.set_vexpand(True)
        for channel in channels:
            strip = ChannelStrip(
                channel, mixer.MIXES, MIX_LABELS,
                self._level, self._mute,
                badge="FX" if (fx_active and channel.is_mic) else None,
            )
            strip.meter.set_reduced_motion(self._reduced)
            strip.set_size_request(-1, MIN_STRIP_HEIGHT)
            self.strips[channel.ident] = strip
            row.append(strip)

        height_clamp = Adw.Clamp(
            orientation=Gtk.Orientation.VERTICAL,
            maximum_size=MAX_STRIP_HEIGHT,
            tightening_threshold=MAX_STRIP_HEIGHT,
        )
        height_clamp.set_child(row)
        height_clamp.set_vexpand(True)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add_css_class("mixer-scroller")
        scroller.set_child(height_clamp)
        self.append(scroller)

        self.bank = meters.MeterBank()
        for channel in channels:
            device = channel.source if channel.is_mic else f"{channel.sink_name}.monitor"
            self.bank.add(channel.ident, device)
        for mix in mixer.MIXES:
            self.bank.add(f"__{mix}", f"{mixer.MIX_SINK[mix]}.monitor")

        self.load_levels()
        self._meter_source = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_a):
        # The deck can change levels while this view is hidden (Dim, Panic),
        # and the next fader touch would otherwise write a stale value back.
        self.resync_from_runtime()
        self.bank.start()
        if self._meter_source is None:
            self._meter_source = GLib.timeout_add(METER_FPS_MS, self._tick_meters)

    def resync_from_runtime(self):
        """Pull the live volumes back into the fader positions."""
        for channel in self.channels:
            strip = self.strips.get(channel.ident)
            if strip is None:
                continue
            for mix in mixer.MIXES:
                reading = self.runtime.get_level(channel, mix)
                if reading is None:
                    continue
                linear, muted = reading
                strip.sync(mix, linear_to_pct(linear), muted)

    def _on_unmap(self, *_a):
        if self._meter_source is not None:
            GLib.source_remove(self._meter_source)
            self._meter_source = None
        self.bank.stop()

    def _tick_meters(self):
        for ident, strip in self.strips.items():
            strip.tick(self.bank.db(ident))
        for mix, meter in self.master_meters.items():
            meter.tick(self.bank.db(f"__{mix}"))
        return True

    def load_levels(self):
        for channel in self.channels:
            saved = self.levels.get(channel.ident, {})
            for mix in mixer.MIXES:
                entry = saved.get(mix, {})
                # The mic sits at unity by default: its level is set by the
                # hardware gain knob, so attenuating it here just throws away
                # signal-to-noise and makes the voice sound damped.
                pct = entry.get("level", DEFAULT_MIC_PCT if channel.is_mic
                                else DEFAULT_PCT)
                muted = entry.get("muted", False)
                self.strips[channel.ident].sync(mix, pct, muted)
                self.runtime.set_level(channel, mix, pct_to_linear(pct))
                self.runtime.set_mute(channel, mix, muted)

    def _store(self, channel, mix, **kv):
        entry = self.levels.setdefault(channel.ident, {}).setdefault(mix, {})
        entry.update(kv)
        mixer.save_levels(self.levels)

    def _level(self, channel, mix, pct):
        key = (channel.ident, mix)
        handle = self._pending.pop(key, None)
        if handle is not None:
            GLib.source_remove(handle)
        self._pending[key] = GLib.timeout_add(
            APPLY_DEBOUNCE_MS, self._commit_level, channel, mix, pct
        )

    def _commit_level(self, channel, mix, pct):
        self._pending.pop((channel.ident, mix), None)
        self.runtime.set_level(channel, mix, pct_to_linear(pct))
        self._store(channel, mix, level=pct)
        return GLib.SOURCE_REMOVE

    def _mute(self, channel, mix, muted):
        self.runtime.set_mute(channel, mix, muted)
        self._store(channel, mix, muted=muted)


def pct_to_linear(pct):
    """Cubic taper, matching how PulseAudio presents volume percentages."""
    return (pct / 100.0) ** 3


def linear_to_pct(linear):
    return max(0.0, min(1.0, linear)) ** (1.0 / 3.0) * 100.0
