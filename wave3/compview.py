"""Compressor view: scrolling waveform with a draggable threshold.

Input meter left, waveform centre, gain and output right.

PipeWire's filter-chain publishes only the plugins' input control ports, so
the compressor's own gain-reduction meter is unreadable. The right-hand meter
instead shows the measured difference between chain input and chain output,
and is labelled chain gain rather than compressor reduction.
"""

import collections
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import meters  # noqa: E402
from .gamewidgets import ControlRows  # noqa: E402
from .widgets import LevelMeter  # noqa: E402

HISTORY = 260
FPS_MS = 33

PLOT_HEIGHT = 260
PAD_TOP = 12
PAD_BOTTOM = 12
PAD_RIGHT = 26

FLOOR_DB = -60.0

INPUT_RGB = (0.62, 0.64, 0.70)
OUTPUT_RGB = (0.36, 0.47, 0.94)
THRESHOLD_RGB = (0.92, 0.92, 0.95)
GRAB_PX = 14.0

THRESHOLD_PORT = "Attack threshold (G)"
MAKEUP_PORT = "Makeup gain (G)"


def db_to_fraction(db):
    if db <= FLOOR_DB:
        return 0.0
    return min(1.0, (db - FLOOR_DB) / (0.0 - FLOOR_DB))


def fraction_to_db(fraction):
    fraction = max(0.0, min(1.0, fraction))
    return FLOOR_DB + fraction * (0.0 - FLOOR_DB)


class Waveform(Gtk.DrawingArea):
    """Rolling envelope of input and output, with the threshold overlaid."""

    def __init__(self, on_threshold):
        super().__init__()
        self._on_threshold = on_threshold
        self.history = collections.deque(maxlen=HISTORY)
        self.threshold_db = -18.0
        self._dragging = False
        self._hover = False

        self.set_content_height(PLOT_HEIGHT)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self.add_css_class("comp-plot")

        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)

    def push(self, input_db, output_db):
        self.history.append((input_db, output_db))
        self.queue_draw()

    def _threshold_y(self, height):
        usable = height - PAD_TOP - PAD_BOTTOM
        centre = PAD_TOP + usable / 2.0
        return centre - db_to_fraction(self.threshold_db) * (usable / 2.0)

    def _pressed(self, _g, _n, x, y):
        if abs(y - self._threshold_y(self.get_height())) <= GRAB_PX:
            self._dragging = True
            self._apply(y)

    def _released(self, *_a):
        self._dragging = False

    def _motion(self, _c, x, y):
        if self._dragging:
            self._apply(y)
            return
        near = abs(y - self._threshold_y(self.get_height())) <= GRAB_PX
        if near != self._hover:
            self._hover = near
            self.set_cursor(
                Gdk.Cursor.new_from_name("ns-resize" if near else "default")
            )
            self.queue_draw()

    def _leave(self, *_a):
        self._hover = False
        self.queue_draw()

    def _apply(self, y):
        height = self.get_height()
        usable = height - PAD_TOP - PAD_BOTTOM
        centre = PAD_TOP + usable / 2.0
        fraction = max(0.0, min(1.0, (centre - y) / (usable / 2.0)))
        self.threshold_db = fraction_to_db(fraction)
        self.queue_draw()
        if self._on_threshold:
            self._on_threshold(self.threshold_db)

    def _draw(self, _area, cr, width, height):
        plot_w = max(1, width - PAD_RIGHT)
        usable = height - PAD_TOP - PAD_BOTTOM
        centre = PAD_TOP + usable / 2.0
        half = usable / 2.0

        cr.set_source_rgba(1, 1, 1, 0.03)
        cr.rectangle(0, PAD_TOP, plot_w, usable)
        cr.fill()

        if self.history:
            step = plot_w / float(HISTORY)
            for index, (in_db, out_db) in enumerate(self.history):
                x = plot_w - (len(self.history) - index) * step
                for db, rgb in ((in_db, INPUT_RGB), (out_db, OUTPUT_RGB)):
                    extent = db_to_fraction(db) * half
                    if extent <= 0.4:
                        continue
                    cr.set_source_rgb(*rgb)
                    cr.rectangle(x, centre - extent, max(1.0, step), extent * 2)
                    cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.16)
        cr.set_line_width(1.0)
        cr.move_to(0, centre)
        cr.line_to(plot_w, centre)
        cr.stroke()

        y = self._threshold_y(height)
        cr.set_source_rgba(*THRESHOLD_RGB, 0.95 if self._hover else 0.72)
        cr.set_line_width(2.0 if self._hover else 1.4)
        cr.move_to(0, y)
        cr.line_to(plot_w, y)
        cr.stroke()

        mirrored = centre + (centre - y)
        cr.set_source_rgba(*THRESHOLD_RGB, 0.28)
        cr.set_line_width(1.0)
        cr.set_dash([3.0, 3.0])
        cr.move_to(0, mirrored)
        cr.line_to(plot_w, mirrored)
        cr.stroke()
        cr.set_dash([])

        cr.set_source_rgba(*THRESHOLD_RGB, 0.9)
        cr.rectangle(plot_w + 4, y - 5, 10, 10)
        cr.fill()

        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription()
        description.set_size(int(9 * Pango.SCALE))
        layout.set_font_description(description)
        layout.set_text(f"{self.threshold_db:.0f} dB", -1)
        tw, th = layout.get_pixel_size()
        cr.set_source_rgba(*THRESHOLD_RGB, 0.75)
        cr.move_to(plot_w - tw - 6, y - th - 3)
        PangoCairo.show_layout(cr, layout)


class MeterColumn(Gtk.Box):
    """Vertical meter with a caption and a numeric readout."""

    def __init__(self, caption, tooltip=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_valign(Gtk.Align.FILL)

        self.readout = Gtk.Label(label="-inf")
        self.readout.add_css_class("db-readout")
        self.append(self.readout)

        self.meter = LevelMeter(width=10)
        well = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        well.add_css_class("meter-frame")
        well.set_vexpand(True)
        well.append(self.meter)
        self.append(well)

        label = Gtk.Label(label=caption)
        label.add_css_class("fader-caption")
        self.append(label)

        if tooltip:
            self.set_tooltip_text(tooltip)

    def tick(self, db):
        self.meter.push(db)
        self.meter.tick()
        self.readout.set_text("-inf" if db <= FLOOR_DB else f"{db:.0f}")


class CompressorPanel(Gtk.Box):
    def __init__(self, runtime, effect, input_device, output_device, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.runtime = runtime
        self.effect = effect
        self._on_change = on_change
        self._source = None

        self.controls = {c.port: c for c in effect.controls}

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_vexpand(True)

        self.input_meter = MeterColumn("INPUT", "Level entering the effects chain")
        row.append(self.input_meter)

        self.plot = Waveform(self._threshold_changed)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("eq-frame")
        frame.set_hexpand(True)
        frame.append(self.plot)
        row.append(frame)

        self.gain_meter = MeterColumn(
            "GAIN Δ",
            "Measured difference between chain input and chain output.\n"
            "Not the compressor's own gain reduction - PipeWire does not "
            "publish plugin output ports, so that value is unavailable.",
        )
        row.append(self.gain_meter)

        self.output_meter = MeterColumn("OUTPUT", "Level leaving the effects chain")
        row.append(self.output_meter)

        self.append(row)

        note = Gtk.Label(
            label="Drag the threshold line. GAIN Δ is measured across the "
                  "whole chain, not the compressor alone."
        )
        note.add_css_class("eq-hint")
        note.set_xalign(0)
        note.set_wrap(True)
        self.append(note)

        # Threshold is the draggable line, so it is not repeated as a slider.
        rest = [c for c in effect.controls if c.port != THRESHOLD_PORT]
        if rest:
            self.append(ControlRows(effect, rest, on_change))

        threshold = self.controls.get(THRESHOLD_PORT)
        if threshold is not None:
            self.plot.threshold_db = float(threshold.default)

        self.bank = meters.MeterBank()
        self.bank.add("in", input_device)
        self.bank.add("out", output_device)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

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
        in_db = self.bank.db("in")
        out_db = self.bank.db("out")
        self.plot.push(in_db, out_db)
        self.input_meter.tick(in_db)
        self.output_meter.tick(out_db)

        # Only meaningful while signal is present.
        if in_db > FLOOR_DB and out_db > FLOOR_DB:
            makeup = self.controls.get(MAKEUP_PORT)
            makeup_db = float(makeup.default) if makeup else 0.0
            delta = out_db - in_db - makeup_db
            self.gain_meter.tick(max(FLOOR_DB, min(0.0, delta)))
        else:
            self.gain_meter.tick(FLOOR_DB)
        return True

    def _threshold_changed(self, db):
        control = self.controls.get(THRESHOLD_PORT)
        if control is None:
            return
        self._on_change(self.effect, control, db)
