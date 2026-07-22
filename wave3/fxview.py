"""Effects view: the rack drawn as a signal chain, in signal order.

Reads left to right the way the audio actually flows. Selecting a stage
reveals its controls; a bypassed stage dims and its arrow greys, so bypass is
visible in the diagram rather than hidden inside a switch.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import compview  # noqa: E402
from . import eq  # noqa: E402
from . import eqview  # noqa: E402
from . import fx  # noqa: E402
from . import thresholdview  # noqa: E402

APPLY_DEBOUNCE_MS = 80
DETAIL_WIDTH = 1180


class StageButton(Gtk.Box):
    def __init__(self, effect, on_select, on_toggle):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.effect = effect
        self.add_css_class("fx-stage")
        self.set_focusable(True)

        title = Gtk.Label(label=effect.label.upper())
        title.add_css_class("fx-stage-title")
        self.append(title)

        self.toggle = Gtk.Switch()
        self.toggle.add_css_class("stage-switch")
        self.toggle.set_halign(Gtk.Align.CENTER)
        self.toggle.set_active(effect.enabled)
        self.toggle.set_tooltip_text(f"Enable {effect.label}")
        self.toggle.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Enable {effect.label}"]
        )
        self.toggle.connect("notify::active", self._toggled, on_toggle)
        self.append(self.toggle)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: on_select(effect))
        self.add_controller(click)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._key, on_select)
        self.add_controller(key)

        self.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"{effect.label} stage"]
        )
        self._sync_bypass()

    def _key(self, _c, keyval, _code, _state, on_select):
        from gi.repository import Gdk
        if keyval in (Gdk.KEY_Return, Gdk.KEY_space, Gdk.KEY_KP_Enter):
            on_select(self.effect)
            return True
        return False

    def _toggled(self, switch, _param, on_toggle):
        self.effect.enabled = switch.get_active()
        self._sync_bypass()
        on_toggle(self.effect)

    def _sync_bypass(self):
        if self.effect.enabled:
            self.remove_css_class("bypassed")
        else:
            self.add_css_class("bypassed")

    def set_selected(self, selected):
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")


class ControlRow:
    def __init__(self, effect, control, on_change):
        self.effect = effect
        self.control = control
        self._on_change = on_change
        self._syncing = False

        if control.kind == fx.ENUM:
            names = [fx.FILTER_TYPES[k] for k in sorted(fx.FILTER_TYPES)]
            self.row = Adw.ComboRow(title=control.label, model=Gtk.StringList.new(names))
            self.row.set_selected(int(control.default))
            self.row.connect("notify::selected", self._emit)
        else:
            adjustment = Gtk.Adjustment(
                lower=control.minimum, upper=control.maximum,
                step_increment=control.step,
                page_increment=max(control.step * 10, control.step),
                value=control.default,
            )
            self.row = Adw.SpinRow(
                title=control.label, adjustment=adjustment,
                digits=0 if control.step >= 1 else 1,
            )
            if control.unit:
                self.row.set_subtitle(control.unit)
            self.row.connect("notify::value", self._emit)

    @property
    def value(self):
        if self.control.kind == fx.ENUM:
            return float(self.row.get_selected())
        return self.row.get_value()

    def _emit(self, *_a):
        if self._syncing:
            return
        self._on_change(self.effect, self.control, self.value)


class FxPage(Gtk.Box):
    def __init__(self, runtime, rack, comp_devices=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.runtime = runtime
        self.rack = rack
        self._comp_devices = comp_devices
        self._comp_panel = None
        self.stages = {}
        self._pending = {}
        self._selected = rack[0]
        self._detail_group = None
        self._eq_bands = self._load_eq_bands(rack)

        chain = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chain.set_halign(Gtk.Align.CENTER)
        chain.set_margin_top(20)
        chain.set_margin_bottom(4)
        chain.set_margin_start(18)
        chain.set_margin_end(18)

        chain.append(self._caption("CAPSULE"))
        self.arrows = []
        for index, effect in enumerate(rack):
            arrow = Gtk.Label(label="→")
            arrow.add_css_class("fx-arrow")
            chain.append(arrow)
            self.arrows.append((arrow, effect))

            stage = StageButton(effect, self._select, self._toggled)
            self.stages[effect.ident] = stage
            chain.append(stage)

        tail = Gtk.Label(label="→")
        tail.add_css_class("fx-arrow")
        chain.append(tail)
        chain.append(self._caption("MIXES"))
        self.arrows.append((tail, rack[-1]))

        self.append(chain)
        self.append(Gtk.Separator(margin_top=16))

        # Adw.PreferencesPage clamps its own content to ~600px internally, so
        # wrapping one in a wider clamp achieves nothing. Same groups, plain
        # box, our clamp - which is what actually gives the EQ graph its width.
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.detail.set_margin_top(18)
        self.detail.set_margin_bottom(24)
        self.detail.set_margin_start(18)
        self.detail.set_margin_end(18)

        detail_clamp = Adw.Clamp(maximum_size=DETAIL_WIDTH, tightening_threshold=760)
        detail_clamp.set_child(self.detail)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(detail_clamp)
        self.append(scroller)

        self._render_detail()
        self._refresh_selection()

    @staticmethod
    def _load_eq_bands(rack):
        """Rebuild the band model from whatever the EQ ports currently hold."""
        bands = eq.build_bands()
        effect = next((e for e in rack if e.ident == "eq"), None)
        if effect is None:
            return bands
        by_port = {c.port: c for c in effect.controls}
        for band in bands:
            ports = eq.ports_for_band(band)
            if ports["type"] in by_port:
                band.kind = int(by_port[ports["type"]].default)
            if ports["frequency"] in by_port:
                band.frequency = float(by_port[ports["frequency"]].default)
            if ports["gain"] in by_port:
                band.gain_db = float(by_port[ports["gain"]].default)
            if ports["q"] in by_port:
                band.q = max(eq.Q_MIN, float(by_port[ports["q"]].default))
        return bands

    @staticmethod
    def _caption(text):
        label = Gtk.Label(label=text)
        label.add_css_class("chain-caption")
        return label

    def _select(self, effect):
        self._selected = effect
        self._render_detail()
        self._refresh_selection()

    def _refresh_selection(self):
        for ident, stage in self.stages.items():
            stage.set_selected(ident == self._selected.ident)
        for arrow, effect in self.arrows:
            if effect.enabled:
                arrow.remove_css_class("bypassed")
            else:
                arrow.add_css_class("bypassed")

    def _render_detail(self):
        if self._detail_group is not None:
            self.detail.remove(self._detail_group)
            self._detail_group = None

        effect = self._selected
        group = Adw.PreferencesGroup(
            title=effect.label, description=effect.description
        )

        # EQ gets a curve editor and the compressor a waveform, because a
        # parametric EQ and a threshold are both spatial, not numeric.
        if effect.ident == "eq":
            group.add(self._wrap(eqview.EqPanel(self._eq_bands, self._eq_band_changed)))
        elif effect.ident == "comp" and self._comp_devices:
            self._comp_panel = compview.CompressorPanel(
                self.runtime, effect, *self._comp_devices, self._changed
            )
            group.add(self._wrap(self._comp_panel))
        elif effect.ident == "gate" and self._comp_devices:
            # Gate is first in the chain, so its input is the raw capsule.
            group.add(self._wrap(thresholdview.GatePanel(
                self.runtime, effect, self._comp_devices[0], self._changed
            )))
        elif effect.ident == "limit" and self._comp_devices:
            # Limiter is last, so the chain output is its output.
            group.add(self._wrap(thresholdview.LimiterPanel(
                self.runtime, effect, self._comp_devices[1], self._changed
            )))
        else:
            for control in effect.controls:
                group.add(ControlRow(effect, control, self._changed).row)

        self.detail.append(group)
        self._detail_group = group

    @staticmethod
    def _wrap(widget):
        row = Adw.PreferencesRow()
        row.set_activatable(False)
        widget.set_margin_top(10)
        widget.set_margin_bottom(10)
        widget.set_margin_start(10)
        widget.set_margin_end(10)
        row.set_child(widget)
        return row

    def _eq_band_changed(self, band):
        """Push one band's state to its five LSP ports."""
        effect = next(e for e in self.rack if e.ident == "eq")
        ports = eq.ports_for_band(band)
        values = {
            ports["type"]: float(band.kind),
            ports["frequency"]: band.frequency,
            ports["gain"]: band.gain_db if band.shapes_gain else 0.0,
            ports["q"]: band.q,
        }
        by_port = {c.port: c for c in effect.controls}
        for port, value in values.items():
            control = by_port.get(port)
            if control is None:
                continue
            control.default = value
            self.runtime.set_control(effect, control, value)
        self._persist()

    def _persist(self):
        fx.save_state(fx.rack_to_state(self.rack))

    def _toggled(self, effect):
        self.runtime.set_enabled(effect, effect.enabled)
        self._refresh_selection()
        self._persist()

    def _changed(self, effect, control, value):
        key = (effect.ident, control.port)
        handle = self._pending.pop(key, None)
        if handle is not None:
            GLib.source_remove(handle)
        self._pending[key] = GLib.timeout_add(
            APPLY_DEBOUNCE_MS, self._commit, effect, control, value
        )

    def _commit(self, effect, control, value):
        self._pending.pop((effect.ident, control.port), None)
        control.default = value
        self.runtime.set_control(effect, control, value)
        self._persist()
        return GLib.SOURCE_REMOVE
