"""Preset picker and reset button, shared by every effect panel."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from . import presets  # noqa: E402

CUSTOM = "Custom"


class PresetBar(Gtk.Box):
    """Choose a preset, or put the effect back to its default.

    on_apply(preset) is called with the chosen preset. The bar shows "Custom"
    when the live values match no preset, so hand tweaking is never silently
    relabelled as a preset.
    """

    def __init__(self, effect, on_apply, bands=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.effect = effect
        self.bands = bands
        self._on_apply = on_apply
        self._syncing = False

        self.presets = presets.for_effect(effect.ident)
        self._names = [p.name for p in self.presets]

        label = Gtk.Label(label="PRESET")
        label.add_css_class("section-heading")
        self.append(label)

        self.combo = Gtk.DropDown.new_from_strings(self._names + [CUSTOM])
        self.combo.set_tooltip_text("Load a starting point for this effect")
        self.combo.connect("notify::selected", self._chosen)
        self.append(self.combo)

        self.summary = Gtk.Label(label="")
        self.summary.add_css_class("eq-hint")
        self.summary.set_xalign(0)
        self.summary.set_hexpand(True)
        self.summary.set_ellipsize(3)
        self.append(self.summary)

        self.reset = Gtk.Button(label="Reset")
        self.reset.set_tooltip_text(
            f"Put {effect.label} back to its default settings"
        )
        self.reset.add_css_class("flat")
        self.reset.connect("clicked", self._reset_clicked)
        self.append(self.reset)

        self.sync()

    def _chosen(self, *_a):
        if self._syncing:
            return
        index = self.combo.get_selected()
        if index >= len(self.presets):
            return
        preset = self.presets[index]
        self.summary.set_text(preset.summary)
        self._on_apply(preset)

    def _reset_clicked(self, _b):
        preset = presets.default_for(self.effect.ident)
        if preset is not None:
            self._on_apply(preset)
            self.sync()

    def sync(self):
        """Match the picker to whatever the effect currently holds."""
        name = presets.identify(self.effect, self.bands)
        self._syncing = True
        if name in self._names:
            self.combo.set_selected(self._names.index(name))
            self.summary.set_text(self.presets[self._names.index(name)].summary)
        else:
            self.combo.set_selected(len(self._names))
            self.summary.set_text("Hand-tuned settings")
        self._syncing = False


def reset_dialog(parent, on_confirm):
    """Confirm a full reset. Destructive, so it spells out what is lost."""
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Reset all settings?",
        body=(
            "This puts the effects rack back to its defaults and returns every "
            "mixer fader to its starting position.\n\n"
            "Your hardware settings (gain, Clipguard, low cut, headphone "
            "volume) are left alone, and so is everything the app has learned "
            "about your device. This cannot be undone."
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("reset", "Reset Everything")
    dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def responded(_d, response):
        if response == "reset":
            on_confirm()

    dialog.connect("response", responded)
    dialog.present()
