"""Gate and limiter views.

A gate threshold is impossible to set from a number, because the number is
only meaningful relative to how loud you actually are. Both panels put the
live level and the threshold on the same axis so the setting is a comparison
rather than a guess.

The open/closed and catching indicators are derived from measured level
against the threshold you set. They are not read from the plugin - PipeWire
does not publish LADSPA output ports - so they ignore hysteresis and the
attack/release envelope. Close enough to aim with, not a plugin readout.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import meters  # noqa: E402

FPS_MS = 33
FLOOR_DB = -60.0

BAR_HEIGHT = 34
PAD_X = 10
SCALE_HEIGHT = 18

SEGMENT_PX = 4
SEGMENT_GAP = 1
GRAB_PX = 12.0

BED_RGB = (0.16, 0.17, 0.19)
BELOW_RGB = (0.38, 0.40, 0.46)
ABOVE_RGB = (0.36, 0.82, 0.53)
OVER_RGB = (0.91, 0.35, 0.31)
MARKER_RGB = (0.95, 0.95, 0.98)

SCALE_MARKS = (-60, -48, -36, -24, -12, -6, 0)


def db_to_fraction(db):
    if db <= FLOOR_DB:
        return 0.0
    return min(1.0, (db - FLOOR_DB) / (0.0 - FLOOR_DB))


def fraction_to_db(fraction):
    return FLOOR_DB + max(0.0, min(1.0, fraction)) * (0.0 - FLOOR_DB)


class ThresholdBar(Gtk.DrawingArea):
    """Horizontal level meter with a draggable threshold marker."""

    def __init__(self, on_change, over_is_bad=False):
        super().__init__()
        self._on_change = on_change
        self.over_is_bad = over_is_bad
        self.threshold_db = -24.0
        self.level_db = FLOOR_DB
        self._dragging = False
        self._hover = False

        self.set_content_height(BAR_HEIGHT + SCALE_HEIGHT)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.add_css_class("threshold-bar")

        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)

    @property
    def open(self):
        return self.level_db >= self.threshold_db

    def push(self, db):
        self.level_db = db
        self.queue_draw()

    def _marker_x(self, width):
        usable = max(1, width - PAD_X * 2)
        return PAD_X + db_to_fraction(self.threshold_db) * usable

    def _pressed(self, _g, _n, x, y):
        if abs(x - self._marker_x(self.get_width())) <= GRAB_PX:
            self._dragging = True
            self._apply(x)

    def _released(self, *_a):
        self._dragging = False

    def _motion(self, _c, x, _y):
        if self._dragging:
            self._apply(x)
            return
        near = abs(x - self._marker_x(self.get_width())) <= GRAB_PX
        if near != self._hover:
            self._hover = near
            self.set_cursor(
                Gdk.Cursor.new_from_name("ew-resize" if near else "default")
            )
            self.queue_draw()

    def _leave(self, *_a):
        self._hover = False
        self.queue_draw()

    def _apply(self, x):
        usable = max(1, self.get_width() - PAD_X * 2)
        self.threshold_db = fraction_to_db((x - PAD_X) / usable)
        self.queue_draw()
        if self._on_change:
            self._on_change(self.threshold_db)

    def _draw(self, _area, cr, width, height):
        usable = max(1, width - PAD_X * 2)
        step = SEGMENT_PX + SEGMENT_GAP
        count = max(1, int(usable // step))
        lit = int(db_to_fraction(self.level_db) * count)
        marker = int(db_to_fraction(self.threshold_db) * count)

        for i in range(count):
            x = PAD_X + i * step
            if i < lit:
                if self.over_is_bad:
                    rgb = OVER_RGB if i >= marker else ABOVE_RGB
                else:
                    rgb = ABOVE_RGB if i >= marker else BELOW_RGB
            else:
                rgb = BED_RGB
            cr.set_source_rgb(*rgb)
            cr.rectangle(x, 0, SEGMENT_PX, BAR_HEIGHT)
            cr.fill()

        mx = self._marker_x(width)
        cr.set_source_rgba(*MARKER_RGB, 0.95 if self._hover else 0.75)
        cr.set_line_width(2.5 if self._hover else 1.8)
        cr.move_to(mx, -2)
        cr.line_to(mx, BAR_HEIGHT + 2)
        cr.stroke()

        cr.set_source_rgba(*MARKER_RGB, 0.95)
        cr.move_to(mx - 5, BAR_HEIGHT + 2)
        cr.line_to(mx + 5, BAR_HEIGHT + 2)
        cr.line_to(mx, BAR_HEIGHT - 4)
        cr.close_path()
        cr.fill()

        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription()
        description.set_size(int(8 * Pango.SCALE))
        layout.set_font_description(description)
        for mark in SCALE_MARKS:
            x = PAD_X + db_to_fraction(mark) * usable
            layout.set_text(str(mark), -1)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.move_to(min(width - tw, max(0, x - tw / 2)), BAR_HEIGHT + 4)
            PangoCairo.show_layout(cr, layout)


class _ControlRows(Adw.PreferencesGroup):
    """Plain numeric rows for the controls a bar cannot express."""

    def __init__(self, effect, controls, on_change):
        super().__init__()
        for control in controls:
            adjustment = Gtk.Adjustment(
                lower=control.minimum, upper=control.maximum,
                step_increment=control.step,
                page_increment=max(control.step * 10, control.step),
                value=control.default,
            )
            row = Adw.SpinRow(
                title=control.label, adjustment=adjustment,
                digits=0 if control.step >= 1 else 1,
            )
            if control.unit:
                row.set_subtitle(control.unit)
            row.connect(
                "notify::value",
                lambda r, _p, c=control: on_change(effect, c, r.get_value()),
            )
            self.add(row)


class _BarPanel(Gtk.Box):
    """Shared scaffolding: bar, state line, remaining controls, meter loop."""

    THRESHOLD_PORT = ""
    OVER_IS_BAD = False

    def __init__(self, runtime, effect, device, on_change, hint):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.runtime = runtime
        self.effect = effect
        self._on_change = on_change
        self._source = None
        self.controls = {c.port: c for c in effect.controls}

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.state = Gtk.Label(label="")
        self.state.add_css_class("gate-state")
        self.state.set_xalign(0)
        self.state.set_hexpand(True)
        header.append(self.state)

        self.threshold_label = Gtk.Label(label="")
        self.threshold_label.add_css_class("db-readout")
        header.append(self.threshold_label)
        self.append(header)

        self.bar = ThresholdBar(self._threshold_changed, self.OVER_IS_BAD)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("eq-frame")
        frame.append(self.bar)
        self.append(frame)

        note = Gtk.Label(label=hint)
        note.add_css_class("eq-hint")
        note.set_xalign(0)
        note.set_wrap(True)
        self.append(note)

        control = self.controls.get(self.THRESHOLD_PORT)
        if control is not None:
            self.bar.threshold_db = float(control.default)

        rest = [c for c in effect.controls if c.port != self.THRESHOLD_PORT]
        if rest:
            self.append(_ControlRows(effect, rest, on_change))

        self.bank = meters.MeterBank()
        self.bank.add("level", device)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self._refresh_labels()

    def _on_map(self, *_a):
        self.bank.start()
        if self._source is None:
            self._source = GLib.timeout_add(FPS_MS, self._tick)

    def _on_unmap(self, *_a):
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None
        self.bank.stop()

    def _tick(self):
        self.bar.push(self.bank.db("level"))
        self._refresh_labels()
        return True

    def _threshold_changed(self, db):
        control = self.controls.get(self.THRESHOLD_PORT)
        if control is not None:
            self._on_change(self.effect, control, db)
        self._refresh_labels()

    def _refresh_labels(self):
        raise NotImplementedError


class GatePanel(_BarPanel):
    THRESHOLD_PORT = "Curve threshold (G)"

    def __init__(self, runtime, effect, device, on_change):
        super().__init__(
            runtime, effect, device, on_change,
            "Drag the marker to where your voice sits above the room. "
            "Green means signal is over the threshold. Open and closed are "
            "derived from level, so they ignore hysteresis and timing.",
        )

    def _refresh_labels(self):
        if self.bar.open:
            self.state.set_markup("<b>OPEN</b>  passing audio")
            self.state.remove_css_class("closed")
        else:
            self.state.set_markup("<b>CLOSED</b>  below threshold")
            self.state.add_css_class("closed")
        self.threshold_label.set_text(f"{self.bar.threshold_db:.1f} dB")


class LimiterPanel(_BarPanel):
    THRESHOLD_PORT = "Threshold (G)"
    OVER_IS_BAD = True

    def __init__(self, runtime, effect, device, on_change):
        super().__init__(
            runtime, effect, device, on_change,
            "The marker is your ceiling. Red means output reached it and the "
            "limiter is working. Measured on the chain output, so it reflects "
            "everything before it too.",
        )

    def _refresh_labels(self):
        headroom = self.bar.threshold_db - self.bar.level_db
        if self.bar.level_db <= FLOOR_DB:
            self.state.set_markup("<b>QUIET</b>  no signal")
            self.state.remove_css_class("closed")
        elif headroom <= 0:
            self.state.set_markup("<b>LIMITING</b>  at ceiling")
            self.state.add_css_class("closed")
        else:
            self.state.set_markup(f"<b>CLEAR</b>  {headroom:.0f} dB headroom")
            self.state.remove_css_class("closed")
        self.threshold_label.set_text(f"{self.bar.threshold_db:.1f} dB")
