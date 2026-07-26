"""Drawn slider controls for the Voice page.

Adwaita spin rows put a number behind two small buttons, which reads as a
form field rather than a control you sweep. These draw a track, a fill and a
pale cap, in the manner of a console fader.
"""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

TRACK_HEIGHT = 10
HANDLE_RADIUS = 9.0
GRAB_PX = 22.0
ROW_HEIGHT = 64

ACCENT = (0.298, 0.553, 1.0)
CAP_RGB = (0.788, 0.808, 0.847)
CAP_HOVER = (0.949, 0.957, 0.973)
TRACK_RGB = (0.047, 0.051, 0.063)


class GameSlider(Gtk.DrawingArea):
    """Horizontal slider: track, accent fill, pale cap. Drag, scroll or arrows."""

    def __init__(self, low, high, value, step, on_change, bipolar=False):
        super().__init__()
        self.low = low
        self.high = high
        self.step = step
        self.value = max(low, min(high, value))
        self.bipolar = bipolar
        self._on_change = on_change
        self._dragging = False
        self._hover = False

        self.set_content_height(TRACK_HEIGHT + 22)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_focusable(True)

        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll.connect("scroll", self._scroll)
        self.add_controller(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    @property
    def fraction(self):
        span = self.high - self.low
        return 0.0 if span == 0 else (self.value - self.low) / span

    def _set_from_x(self, x, width):
        pad = HANDLE_RADIUS + 2
        usable = max(1.0, width - pad * 2)
        frac = max(0.0, min(1.0, (x - pad) / usable))
        raw = self.low + frac * (self.high - self.low)
        stepped = round(raw / self.step) * self.step
        self._commit(max(self.low, min(self.high, stepped)))

    def _commit(self, value):
        if abs(value - self.value) < 1e-9:
            return
        self.value = value
        self.queue_draw()
        if self._on_change:
            self._on_change(value)

    def _pressed(self, _g, _n, x, _y):
        self._dragging = True
        self.grab_focus()
        self._set_from_x(x, self.get_width())

    def _released(self, *_a):
        self._dragging = False

    def _motion(self, _c, x, _y):
        if self._dragging:
            self._set_from_x(x, self.get_width())
            return
        near = True
        if near != self._hover:
            self._hover = near
            self.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            self.queue_draw()

    def _leave(self, *_a):
        self._hover = False
        self.queue_draw()

    def _scroll(self, _c, _dx, dy):
        self._commit(max(self.low, min(self.high,
                                       self.value - self.step * (1 if dy > 0 else -1))))
        return True

    def _key(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Down):
            self._commit(max(self.low, self.value - self.step))
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_Up):
            self._commit(min(self.high, self.value + self.step))
            return True
        return False

    def set_value(self, value):
        self.value = max(self.low, min(self.high, value))
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        pad = HANDLE_RADIUS + 2
        usable = max(1.0, width - pad * 2)
        cy = TRACK_HEIGHT / 2 + 6

        # track
        cr.set_source_rgb(*TRACK_RGB)
        self._rounded(cr, pad, cy - TRACK_HEIGHT / 2, usable, TRACK_HEIGHT,
                      TRACK_HEIGHT / 2)
        cr.fill()

        frac = self.fraction
        if self.bipolar:
            centre = pad + usable / 2
            handle_x = pad + frac * usable
            left, right = min(centre, handle_x), max(centre, handle_x)
            fill_w = right - left
            fill_x = left
        else:
            fill_x = pad
            fill_w = frac * usable
            handle_x = pad + fill_w

        if fill_w > 1:
            cr.set_source_rgba(*ACCENT, 0.85)
            self._rounded(cr, fill_x, cy - TRACK_HEIGHT / 2, fill_w,
                          TRACK_HEIGHT, TRACK_HEIGHT / 2)
            cr.fill()

        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.arc(handle_x, cy + 1, HANDLE_RADIUS, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*(CAP_HOVER if self._hover else CAP_RGB))
        cr.arc(handle_x, cy, HANDLE_RADIUS, 0, 2 * math.pi)
        cr.fill()

        if self.has_focus():
            cr.set_source_rgba(*ACCENT, 0.95)
            cr.set_line_width(2.0)
            cr.arc(handle_x, cy, HANDLE_RADIUS + 4, 0, 2 * math.pi)
            cr.stroke()

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


class SliderRow(Gtk.Box):
    """Label, description, big value and a GameSlider."""

    def __init__(self, title, description, low, high, value, step, unit,
                 on_change, bipolar=False, digits=0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.add_css_class("slider-row")
        self._unit = unit
        self._digits = digits
        self._on_change = on_change

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.set_hexpand(True)

        name = Gtk.Label(label=title.upper())
        name.add_css_class("slider-title")
        name.set_xalign(0)
        text.append(name)

        if description:
            sub = Gtk.Label(label=description)
            sub.add_css_class("slider-sub")
            sub.set_xalign(0)
            sub.set_wrap(True)
            text.append(sub)
        header.append(text)

        self.readout = Gtk.Label(label="")
        self.readout.add_css_class("slider-value")
        self.readout.set_valign(Gtk.Align.CENTER)
        header.append(self.readout)
        self.append(header)

        self.slider = GameSlider(low, high, value, step, self._changed,
                                 bipolar=bipolar)
        self.append(self.slider)
        self._render(value)

    def _render(self, value):
        text = f"{value:+.{self._digits}f}" if self.slider.bipolar \
            else f"{value:.{self._digits}f}"
        self.readout.set_text(f"{text}{self._unit}")

    def _changed(self, value):
        self._render(value)
        if self._on_change:
            self._on_change(value)

    def set_value(self, value):
        self.slider.set_value(value)
        self._render(value)


class ControlRows(Gtk.Box):
    """Slider rows for a plugin's controls, minus any the panel draws itself."""

    def __init__(self, effect, controls, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rows = {}
        for control in controls:
            row = SliderRow(
                control.label, "", control.minimum, control.maximum,
                control.default, control.step, control.unit,
                lambda value, c=control: on_change(effect, c, value),
                bipolar=(control.minimum < 0 < control.maximum),
                digits=0 if control.step >= 1 else 1,
            )
            self.rows[control.port] = row
            self.append(row)
