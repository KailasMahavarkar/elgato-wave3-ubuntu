"""Custom mixer widgets: level meter, fader, channel strip.

Per DESIGN.md: one pre-fader meter per channel, two faders (Stream and
Monitor) because there is one signal and two independent destinations.
"""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gdk, Gtk  # noqa: E402

from . import meters  # noqa: E402

METER_FLOOR_DB = -60.0
METER_WARN_DB = -12.0
METER_PEAK_DB = -3.0

DECAY_DB_PER_SECOND = 96.0
PEAK_HOLD_MS = 1200

SAFE_RGB = (0.36, 0.82, 0.53)
WARN_RGB = (0.94, 0.76, 0.31)
PEAK_RGB = (0.91, 0.35, 0.31)
BED_RGB = (0.16, 0.17, 0.19)

SEGMENT_PX = 3
SEGMENT_GAP = 1

# Short captions so the two faders stay distinguishable at strip width.
SHORT_LABEL = {"stream": "STRM", "monitor": "MON"}


def db_to_fraction(db):
    if db <= METER_FLOOR_DB:
        return 0.0
    return min(1.0, (db - METER_FLOOR_DB) / (0.0 - METER_FLOOR_DB))


def zone_rgb(db):
    if db >= METER_PEAK_DB:
        return PEAK_RGB
    if db >= METER_WARN_DB:
        return WARN_RGB
    return SAFE_RGB


class LevelMeter(Gtk.DrawingArea):
    """Segmented vertical peak meter with decay and peak-hold.

    Rise is instantaneous; only the fall is smoothed. A meter that lags on
    attack lies about transients, which is the one thing a meter must not do.
    """

    def __init__(self, width=10):
        super().__init__()
        self.set_content_width(width)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self.add_css_class("level-meter")
        self.set_can_focus(False)
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)

        self._db = METER_FLOOR_DB
        self._displayed = METER_FLOOR_DB
        self._hold_db = METER_FLOOR_DB
        self._hold_expiry = 0
        self._last_tick = GLib.get_monotonic_time()
        self._reduced_motion = False

    def set_reduced_motion(self, reduced):
        self._reduced_motion = reduced

    def push(self, db):
        self._db = db
        now = GLib.get_monotonic_time()
        if db >= self._hold_db or now > self._hold_expiry:
            self._hold_db = db
            self._hold_expiry = now + PEAK_HOLD_MS * 1000

    def tick(self):
        now = GLib.get_monotonic_time()
        elapsed = (now - self._last_tick) / 1_000_000.0
        self._last_tick = now

        if self._db >= self._displayed or self._reduced_motion:
            self._displayed = self._db
        else:
            self._displayed = max(self._db, self._displayed - DECAY_DB_PER_SECOND * elapsed)

        if now > self._hold_expiry:
            self._hold_db = self._displayed

        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        step = SEGMENT_PX + SEGMENT_GAP
        count = max(1, height // step)
        lit = int(db_to_fraction(self._displayed) * count)
        hold_index = int(db_to_fraction(self._hold_db) * count)

        for i in range(count):
            y = height - (i + 1) * step
            db_at = METER_FLOOR_DB + (i / count) * (0.0 - METER_FLOOR_DB)
            if i < lit:
                cr.set_source_rgb(*zone_rgb(db_at))
            elif i == hold_index - 1 and hold_index > 0:
                r, g, b = zone_rgb(db_at)
                cr.set_source_rgb(r * 0.75, g * 0.75, b * 0.75)
            else:
                cr.set_source_rgb(*BED_RGB)
            cr.rectangle(0, y, width, SEGMENT_PX)
            cr.fill()


class Fader(Gtk.Box):
    """Vertical fader with a monospace dB readout underneath."""

    def __init__(self, label, on_change, tooltip):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._on_change = on_change
        self._syncing = False

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
        self.scale.set_inverted(True)
        self.scale.set_draw_value(False)
        self.scale.set_vexpand(True)
        self.scale.set_tooltip_text(tooltip)
        self.scale.add_css_class("fader")
        self.scale.connect("value-changed", self._emit)
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])

        # Caption above the readout. Below the readout it collided visually
        # with the mute button and read as another control.
        self.caption = Gtk.Label(label=label)
        self.caption.add_css_class("fader-caption")

        self.readout = Gtk.Label(label="0")
        self.readout.add_css_class("db-readout")

        self.append(self.scale)
        self.append(self.caption)
        self.append(self.readout)

    def _emit(self, _scale):
        if self._syncing:
            return
        self._update_readout()
        self._on_change(self.value)

    def _update_readout(self):
        pct = self.scale.get_value()
        if pct <= 0:
            self.readout.set_text("-inf")
        else:
            db = 60.0 * math.log10(pct / 100.0)
            self.readout.set_text(f"{db:+.0f}")

    @property
    def value(self):
        return self.scale.get_value()

    def sync(self, pct):
        if abs(self.scale.get_value() - pct) < 0.5:
            return
        self._syncing = True
        self.scale.set_value(pct)
        self._syncing = False
        self._update_readout()


class MuteButton(Gtk.ToggleButton):
    """Mute toggle. Carries an icon and a border change, never colour alone."""

    def __init__(self, label, tooltip, on_toggle):
        super().__init__()
        self.set_child(
            Gtk.Image.new_from_icon_name("audio-volume-muted-symbolic")
        )
        self.set_tooltip_text(tooltip)
        self.add_css_class("mute-button")
        self.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
        self._syncing = False
        self._on_toggle = on_toggle
        self.connect("toggled", self._emit)

    def _emit(self, _button):
        if self._syncing:
            return
        self._on_toggle(self.get_active())

    def sync(self, muted):
        if self.get_active() == muted:
            return
        self._syncing = True
        self.set_active(muted)
        self._syncing = False


class ChannelStrip(Gtk.Box):
    """One channel: name, pre-fader meter, Stream fader, Monitor fader."""

    def __init__(self, channel, mixes, mix_labels, on_level, on_mute, badge=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.channel = channel
        self.mixes = mixes
        self._on_level = on_level
        self._link_guard = False
        self.add_css_class("channel-strip")

        title = Gtk.Label(label=channel.name.upper())
        title.add_css_class("strip-title")
        title.set_ellipsize(3)
        title.set_max_width_chars(10)
        self.append(title)

        # The badge slot always exists, empty or not. Without it the one strip
        # that has a badge pushes its faders down and every baseline in the row
        # stops lining up.
        chip = Gtk.Label(label=badge or "")
        chip.add_css_class("strip-badge")
        if not badge:
            chip.add_css_class("empty")
        self.append(chip)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.set_vexpand(True)
        body.set_halign(Gtk.Align.CENTER)

        self.meter = LevelMeter(width=8)
        meter_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        meter_wrap.add_css_class("meter-frame")
        meter_wrap.set_valign(Gtk.Align.FILL)
        meter_wrap.append(self.meter)
        meter_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        meter_column.append(meter_wrap)
        meter_cap = Gtk.Label(label="LVL")
        meter_cap.add_css_class("fader-caption")
        meter_column.append(meter_cap)
        spacer = Gtk.Label(label="")
        spacer.add_css_class("db-readout")
        meter_column.append(spacer)
        body.append(meter_column)

        self.faders = {}
        self.mutes = {}
        mute_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mute_row.set_halign(Gtk.Align.CENTER)
        for mix in mixes:
            fader = Fader(
                SHORT_LABEL[mix],
                lambda v, m=mix: self._level_changed(m, v),
                f"{channel.name} level on {mix_labels[mix]} mix",
            )
            mute = MuteButton(
                "M",
                f"Mute {channel.name} on {mix_labels[mix]} mix",
                lambda muted, m=mix: on_mute(channel, m, muted),
            )
            self.faders[mix] = fader
            self.mutes[mix] = mute
            body.append(fader)
            mute_row.append(mute)

        self.append(body)
        self.append(mute_row)

        self.link = Gtk.ToggleButton(label="link")
        self.link.set_tooltip_text("Move Stream and Monitor faders together")
        self.link.add_css_class("link-button")
        self.append(self.link)

    def _level_changed(self, mix, value):
        if self._link_guard:
            return
        if self.link.get_active():
            self._link_guard = True
            for other in self.mixes:
                if other != mix:
                    self.faders[other].sync(value)
                    self._on_level(self.channel, other, value)
            self._link_guard = False
        self._on_level(self.channel, mix, value)

    def sync(self, mix, pct, muted):
        self.faders[mix].sync(pct)
        self.mutes[mix].sync(muted)

    def tick(self, db):
        self.meter.push(db)
        self.meter.tick()


class MasterMeter(Gtk.Box):
    """Wide horizontal readout for a mix bus."""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_css_class("master-meter")

        label = Gtk.Label(label=title.upper())
        label.add_css_class("master-label")
        label.set_width_chars(12)
        label.set_xalign(0)
        self.append(label)

        self.area = Gtk.DrawingArea()
        self.area.set_content_height(10)
        self.area.set_hexpand(True)
        self.area.set_draw_func(self._draw)
        self.area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)

        well = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        well.add_css_class("master-meter-well")
        well.set_hexpand(True)
        well.set_valign(Gtk.Align.CENTER)
        well.append(self.area)
        self.append(well)

        self.readout = Gtk.Label(label="-inf")
        self.readout.add_css_class("db-readout")
        self.readout.set_width_chars(6)
        self.readout.set_xalign(1)
        self.append(self.readout)

        self._db = METER_FLOOR_DB
        self._displayed = METER_FLOOR_DB
        self._last_tick = GLib.get_monotonic_time()
        self._reduced_motion = False

    def set_reduced_motion(self, reduced):
        self._reduced_motion = reduced

    def tick(self, db):
        self._db = db
        now = GLib.get_monotonic_time()
        elapsed = (now - self._last_tick) / 1_000_000.0
        self._last_tick = now
        if db >= self._displayed or self._reduced_motion:
            self._displayed = db
        else:
            self._displayed = max(db, self._displayed - DECAY_DB_PER_SECOND * elapsed)
        self.readout.set_text(
            "-inf" if self._displayed <= METER_FLOOR_DB else f"{self._displayed:.0f}"
        )
        self.area.queue_draw()

    def _draw(self, _area, cr, width, height):
        step = SEGMENT_PX + SEGMENT_GAP
        count = max(1, width // step)
        lit = int(db_to_fraction(self._displayed) * count)
        for i in range(count):
            x = i * step
            db_at = METER_FLOOR_DB + (i / count) * (0.0 - METER_FLOOR_DB)
            cr.set_source_rgb(*(zone_rgb(db_at) if i < lit else BED_RGB))
            cr.rectangle(x, 0, SEGMENT_PX, height)
            cr.fill()


def prefers_reduced_motion():
    settings = Gtk.Settings.get_default()
    if settings is None:
        return False
    return settings.get_property("gtk-enable-animations") is False
