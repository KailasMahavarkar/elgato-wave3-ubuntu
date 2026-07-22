"""Interactive EQ curve editor.

Drag a node to move its frequency and gain, scroll on it to change Q, right
click it to change filter type. The curve is drawn from the same maths the
filter runs, so what you see is what the audio does.
"""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import eq  # noqa: E402

PLOT_HEIGHT = 300
PADDING_LEFT = 42
PADDING_RIGHT = 14
PADDING_TOP = 14
PADDING_BOTTOM = 40

NODE_RADIUS = 7.0
GRAB_RADIUS = 16.0

CURVE_RGB = (0.42, 0.55, 0.98)
GRID_RGB = (1.0, 1.0, 1.0)
TEXT_RGB = (1.0, 1.0, 1.0)


class EqCurve(Gtk.DrawingArea):
    def __init__(self, bands, on_change):
        super().__init__()
        self.bands = bands
        self._on_change = on_change
        self.selected = None
        self._hover = None
        self._dragging = None

        self.set_content_height(PLOT_HEIGHT)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self.set_focusable(True)
        self.add_css_class("eq-curve")

        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        self.add_controller(click)

        secondary = Gtk.GestureClick()
        secondary.set_button(3)
        secondary.connect("pressed", self._right_pressed)
        self.add_controller(secondary)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll.connect("scroll", self._scroll)
        self.add_controller(scroll)

        self.menu = Gtk.Popover()
        self.menu.set_parent(self)
        self.menu.set_has_arrow(True)
        self._build_menu()

    # -- geometry ---------------------------------------------------------

    def _plot(self, width, height):
        return (
            PADDING_LEFT,
            PADDING_TOP,
            max(1, width - PADDING_LEFT - PADDING_RIGHT),
            max(1, height - PADDING_TOP - PADDING_BOTTOM),
        )

    def _band_xy(self, band, width, height):
        x0, y0, w, h = self._plot(width, height)
        x = x0 + eq.freq_to_fraction(band.frequency) * w
        gain = band.gain_db if band.shapes_gain else 0.0
        y = y0 + eq.gain_to_fraction(gain) * h
        return x, y

    def _hit(self, px, py):
        width = self.get_width()
        height = self.get_height()
        best = None
        best_distance = GRAB_RADIUS
        for band in self.bands:
            if not band.active:
                continue
            bx, by = self._band_xy(band, width, height)
            distance = math.hypot(px - bx, py - by)
            if distance <= best_distance:
                best = band
                best_distance = distance
        return best

    # -- interaction ------------------------------------------------------

    def _pressed(self, gesture, n_press, x, y):
        band = self._hit(x, y)
        self.selected = band
        self._dragging = band
        if band is not None and n_press == 2 and band.shapes_gain:
            band.gain_db = 0.0
            self._emit(band)
        self.grab_focus()
        self.queue_draw()

    def _released(self, *_a):
        if self._dragging is not None:
            self._emit(self._dragging)
        self._dragging = None
        self.queue_draw()

    def _motion(self, _c, x, y):
        if self._dragging is not None:
            width = self.get_width()
            height = self.get_height()
            x0, y0, w, h = self._plot(width, height)
            band = self._dragging
            band.frequency = eq.fraction_to_freq((x - x0) / w)
            if band.shapes_gain:
                band.gain_db = eq.fraction_to_gain((y - y0) / h)
            self._emit(band)
            self.queue_draw()
            return
        hover = self._hit(x, y)
        if hover is not self._hover:
            self._hover = hover
            self.set_cursor(
                Gdk.Cursor.new_from_name("grab" if hover else "default")
            )
            self.queue_draw()

    def _leave(self, *_a):
        self._hover = None
        self.queue_draw()

    def _scroll(self, _c, _dx, dy):
        band = self._hover or self.selected
        if band is None or not band.active:
            return False
        factor = 0.88 if dy > 0 else 1.0 / 0.88
        band.q = max(eq.Q_MIN, min(eq.Q_MAX, band.q * factor))
        self._emit(band)
        self.queue_draw()
        return True

    def _right_pressed(self, _g, _n, x, y):
        band = self._hit(x, y)
        if band is None:
            return
        self.selected = band
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.menu.set_pointing_to(rect)
        self.menu.popup()
        self.queue_draw()

    def _build_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for kind in eq.MENU_TYPES:
            button = Gtk.Button(label=eq.TYPE_NAMES[kind])
            button.add_css_class("flat")
            button.connect("clicked", self._menu_chose, kind)
            box.append(button)
        separator = Gtk.Separator()
        box.append(separator)
        off = Gtk.Button(label="Disable band")
        off.add_css_class("flat")
        off.connect("clicked", self._menu_chose, eq.OFF)
        box.append(off)
        self.menu.set_child(box)

    def _menu_chose(self, _button, kind):
        if self.selected is not None:
            self.selected.kind = kind
            self._emit(self.selected)
        self.menu.popdown()
        self.queue_draw()

    def _emit(self, band):
        if self._on_change:
            self._on_change(band)

    # -- drawing ----------------------------------------------------------

    def _draw(self, _area, cr, width, height):
        x0, y0, w, h = self._plot(width, height)

        cr.set_source_rgba(*GRID_RGB, 0.03)
        cr.rectangle(x0, y0, w, h)
        cr.fill()

        self._draw_grid(cr, x0, y0, w, h)
        self._draw_band_fills(cr, x0, y0, w, h)
        self._draw_curve(cr, x0, y0, w, h)
        self._draw_nodes(cr, width, height)
        self._draw_labels(cr, x0, y0, w, h)

    def _draw_grid(self, cr, x0, y0, w, h):
        cr.set_line_width(1.0)
        for frequency in eq.GRID_FREQUENCIES:
            x = x0 + eq.freq_to_fraction(frequency) * w
            cr.set_source_rgba(*GRID_RGB, 0.07)
            cr.move_to(x, y0)
            cr.line_to(x, y0 + h)
            cr.stroke()
        for gain in eq.GRID_GAINS:
            y = y0 + eq.gain_to_fraction(gain) * h
            cr.set_source_rgba(*GRID_RGB, 0.12 if gain == 0 else 0.06)
            cr.move_to(x0, y)
            cr.line_to(x0 + w, y)
            cr.stroke()

    def _draw_band_fills(self, cr, x0, y0, w, h):
        columns = max(2, int(w))
        zero_y = y0 + eq.gain_to_fraction(0.0) * h
        for band in self.bands:
            if not band.active:
                continue
            cr.set_source_rgba(*band.colour, 0.16)
            cr.move_to(x0, zero_y)
            for i in range(columns):
                frequency = eq.fraction_to_freq(i / (columns - 1))
                db = eq.band_response_db(band, frequency)
                y = y0 + eq.gain_to_fraction(db) * h
                cr.line_to(x0 + i * w / (columns - 1), max(y0, min(y0 + h, y)))
            cr.line_to(x0 + w, zero_y)
            cr.close_path()
            cr.fill()

    def _draw_curve(self, cr, x0, y0, w, h):
        columns = max(2, int(w))
        cr.set_source_rgb(*CURVE_RGB)
        cr.set_line_width(2.4)
        cr.set_line_join(1)
        for i in range(columns):
            frequency = eq.fraction_to_freq(i / (columns - 1))
            db = eq.composite_response_db(self.bands, frequency)
            y = y0 + eq.gain_to_fraction(db) * h
            y = max(y0 - 40, min(y0 + h + 40, y))
            x = x0 + i * w / (columns - 1)
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

    def _draw_nodes(self, cr, width, height):
        for band in self.bands:
            if not band.active:
                continue
            x, y = self._band_xy(band, width, height)
            radius = NODE_RADIUS
            if band is self.selected or band is self._hover:
                cr.set_source_rgba(*band.colour, 0.30)
                cr.arc(x, y, radius + 6, 0, 2 * math.pi)
                cr.fill()
                radius += 1
            cr.set_source_rgb(*band.colour)
            cr.arc(x, y, radius, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.set_line_width(1.5)
            cr.arc(x, y, radius, 0, 2 * math.pi)
            cr.stroke()

    def _text(self, cr, text, x, y, size=10, alpha=0.5, align_right=False,
              centre=False):
        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription()
        description.set_size(int(size * Pango.SCALE))
        layout.set_font_description(description)
        layout.set_text(text, -1)
        tw, th = layout.get_pixel_size()
        if align_right:
            x -= tw
        elif centre:
            x -= tw / 2
        cr.set_source_rgba(*TEXT_RGB, alpha)
        cr.move_to(x, y - th / 2)
        PangoCairo.show_layout(cr, layout)

    def _draw_labels(self, cr, x0, y0, w, h):
        for gain in eq.GRID_GAINS:
            if gain % 6 and gain != 0:
                continue
            y = y0 + eq.gain_to_fraction(gain) * h
            self._text(cr, f"{gain:+d}" if gain else "0", x0 - 8, y,
                       align_right=True, alpha=0.45)

        for frequency in (20, 100, 500, 1000, 5000, 20000):
            x = x0 + eq.freq_to_fraction(frequency) * w
            self._text(cr, eq.format_frequency(frequency), x, y0 + h + 12,
                       centre=True, alpha=0.45)

        for band in self.bands:
            if not band.active:
                continue
            x = x0 + eq.freq_to_fraction(band.frequency) * w
            self._text(cr, band.name.upper(), x, y0 + h + 28,
                       size=8, centre=True, alpha=0.38)


class EqPanel(Gtk.Box):
    """Curve plus a readout of the selected band."""

    def __init__(self, bands, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.bands = bands
        self._on_change = on_change

        self.curve = EqCurve(bands, self._changed)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("eq-frame")
        frame.append(self.curve)
        self.append(frame)

        self.readout = Gtk.Label(label="")
        self.readout.add_css_class("eq-readout")
        self.readout.set_xalign(0)
        self.append(self.readout)

        hint = Gtk.Label(
            label="Drag a node to move it. Scroll on it for width. "
                  "Right click for filter type. Double click to flatten."
        )
        hint.add_css_class("eq-hint")
        hint.set_xalign(0)
        hint.set_wrap(True)
        self.append(hint)

        self._update_readout(bands[0])

    def _changed(self, band):
        self._update_readout(band)
        if self._on_change:
            self._on_change(band)

    def _update_readout(self, band):
        gain = f"{band.gain_db:+.1f} dB   " if band.shapes_gain else ""
        self.readout.set_markup(
            f"<b>{GLib.markup_escape_text(band.name)}</b>   "
            f"{eq.TYPE_NAMES[band.kind]}   "
            f"{eq.format_frequency(band.frequency)}   "
            f"{gain}Q {band.q:.2f}"
        )
