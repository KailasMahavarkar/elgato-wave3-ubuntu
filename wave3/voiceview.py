"""Voice page: one switch and five sliders in front of the whole chain."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import layout  # noqa: E402
from . import voice  # noqa: E402
from .gamewidgets import SliderRow  # noqa: E402

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

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        hero.add_css_class("voice-hero")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)
        title = Gtk.Label(label="VOICE MODE")
        title.add_css_class("voice-hero-title")
        title.set_xalign(0)
        text.append(title)
        sub = Gtk.Label(
            label="One tuned chain instead of every plugin parameter. "
                  "Replaces the manual rack while it is on."
        )
        sub.add_css_class("voice-hero-sub")
        sub.set_xalign(0)
        sub.set_wrap(True)
        text.append(sub)
        top.append(text)

        self.enable = Gtk.Switch()
        self.enable.set_valign(Gtk.Align.CENTER)
        self.enable.set_active(active)
        self.enable.set_tooltip_text("Switch between voice mode and the manual rack")
        self.enable.connect("notify::active", self._toggled)
        top.append(self.enable)
        hero.append(top)

        pills = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pills.set_halign(Gtk.Align.START)
        for index, (name, _p, _l) in enumerate(chain):
            if index:
                arrow = Gtk.Label(label="\u203a")
                arrow.add_css_class("fx-arrow")
                pills.append(arrow)
            label = {"nr": "AI DENOISE", "mbgate": "SPECTRAL GATE",
                     "tone": "TONE", "deess": "DE-ESS",
                     "comp": "LEVEL", "limit": "LIMIT"}.get(name, name.upper())
            pill = Gtk.Label(label=label)
            pill.add_css_class("chain-pill")
            if name == "nr" and not has_nr:
                pill.add_css_class("off")
            pills.append(pill)
        hero.append(pills)

        if not has_nr:
            warn = Gtk.Label(
                label="RNNoise is not installed, so the spectral gate is "
                      "doing the noise removal instead."
            )
            warn.add_css_class("slider-sub")
            warn.set_xalign(0)
            warn.set_wrap(True)
            hero.append(warn)
        body.append(hero)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        heading = Gtk.Label(label="SOUND")
        heading.add_css_class("section-heading")
        heading.set_xalign(0)
        self.controls.append(heading)

        for key, label, low, high, unit, description in voice.CONTROLS:
            row = SliderRow(
                label, description, low, high, self.values[key],
                1.0 if unit == "%" else 0.5, unit,
                lambda value, k=key: self._changed(value, k),
                bipolar=(low < 0), digits=0 if unit == "%" else 1,
            )
            self._rows[key] = row
            self.controls.append(row)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)
        button = Gtk.Button(label="Reset voice settings")
        button.add_css_class("flat")
        button.connect("clicked", self._reset)
        footer.append(button)
        self.controls.append(footer)
        body.append(self.controls)

        clamp = Adw.Clamp(maximum_size=layout.CONTENT_WIDTH,
                          tightening_threshold=layout.TIGHTENING)
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

    def _changed(self, value, key):
        if self._syncing:
            return
        self.values[key] = value
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
