"""Mic effects rack, hosted by PipeWire's filter-chain module.

    capsule -> gate -> EQ -> compressor -> limiter -> wave3.fx.mic

Constraints of the Ubuntu build:

1. filter-chain is built without LV2 support (builtin and ladspa only).
   `type = lv2` fails to load the module, and a failed mandatory module in a
   conf.d drop-in takes the whole PipeWire daemon down with it.
2. LADSPA controls are keyed by port NAME including units, e.g.
   "Curve threshold (G)", not by symbol.
3. LADSPA has no `enabled` port, only `Bypass`, which is inverted: 0 runs the
   effect, 1 skips it.

LSP expresses thresholds and gains as linear amplitude (the "(G)" suffix), so
every dB control here is converted on the way out.
"""

import json
import math
import os
from dataclasses import dataclass, field

LADSPA_LIB = "/usr/lib/ladspa/lsp-plugins-ladspa.so"
LSP = "http://lsp-plug.in/plugins/ladspa"

FX_SOURCE = "wave3.fx.mic"
FX_CAPTURE = "wave3.fx.capture"

STATE_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "wave3"
)
FX_FILE = os.path.join(STATE_DIR, "fx.json")

CONF_NAME = "59-wave3-fx.conf"
CONF_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "pipewire", "pipewire.conf.d",
)
CONF_PATH = os.path.join(CONF_DIR, CONF_NAME)

DB = "db"
PLAIN = "plain"
MS = "ms"
HZ = "hz"
RATIO = "ratio"
ENUM = "enum"

FILTER_TYPES = {
    0: "Off", 1: "Bell", 2: "Hi-pass", 3: "Hi-shelf", 4: "Lo-pass",
    5: "Lo-shelf", 6: "Notch", 7: "Resonance", 8: "Allpass",
    9: "Bandpass", 10: "Ladder-pass", 11: "Ladder-rej",
}


def db_to_linear(db):
    return 10.0 ** (db / 20.0)


def linear_to_db(linear):
    return -90.0 if linear <= 0 else 20.0 * math.log10(linear)


@dataclass
class Control:
    port: str
    label: str
    kind: str
    minimum: float
    maximum: float
    default: float
    unit: str = ""
    step: float = 1.0

    def to_plugin(self, value):
        clamped = max(self.minimum, min(self.maximum, float(value)))
        return db_to_linear(clamped) if self.kind == DB else clamped


@dataclass
class Effect:
    ident: str
    label: str
    plugin: str
    description: str
    controls: list = field(default_factory=list)
    enabled: bool = True

    @property
    def uri(self):
        return f"{LSP}/{self.plugin}"


def _eq_controls():
    """One control set per EQ band, matching wave3.eq's band model.

    Filter mode is pinned to APO (DR), the plain digital biquad, so the curve
    drawn in the editor is the curve the plugin runs.
    """
    from . import eq

    controls = []
    for spec in eq.DEFAULT_BANDS:
        index, name, kind, frequency, gain, q, _colour = spec
        controls.extend([
            Control(f"Filter type {index}", f"{name} type", ENUM, 0, 11, kind),
            Control(f"Filter mode {index}", f"{name} mode", ENUM, 0, 6, eq.APO_MODE),
            Control(f"Frequency {index} (Hz)", f"{name} frequency", HZ,
                    10.0, 24000.0, frequency, "Hz", 10.0),
            Control(f"Gain {index} (G)", f"{name} gain", DB,
                    -24.0, 24.0, gain, "dB", 0.5),
            Control(f"Quality factor {index}", f"{name} Q", PLAIN,
                    0.0, 100.0, q, "", 0.1),
        ])
    return controls


def build_rack():
    """Curated chain. The gate precedes the compressor so the compressor
    never pulls up room noise the gate exists to remove."""
    return [
        Effect(
            "gate", "Noise Gate", "gate_mono",
            "Silences the channel between words. Stands in for ReaGate.",
            [
                Control("Curve threshold (G)", "Open threshold", DB, -60.0, 0.0, -26.0, "dB", 0.5),
                Control("Hysteresis threshold (G)", "Close threshold", DB, -60.0, 0.0, -34.0, "dB", 0.5),
                # Reduction is how far a closed gate attenuates. LSP defaults
                # it to 1.0 (0 dB), leaving the gate inert unless set.
                Control("Reduction (G)", "Reduction", DB, -72.0, 0.0, -48.0, "dB", 1.0),
                Control("Attack (ms)", "Attack", MS, 0.0, 100.0, 5.0, "ms", 1.0),
                Control("Release (ms)", "Release", MS, 0.0, 800.0, 150.0, "ms", 5.0),
                Control("Makeup gain (G)", "Makeup", DB, -24.0, 24.0, 0.0, "dB", 0.5),
            ],
        ),
        Effect(
            "eq", "Equaliser", "para_equalizer_x16_mono",
            "Six bands named for how voices actually go wrong.",
            _eq_controls(),
        ),
        Effect(
            "comp", "Compressor", "compressor_mono",
            "Evens out quiet and loud delivery. Stands in for ReaComp.",
            [
                Control("Attack threshold (G)", "Threshold", DB, -60.0, 0.0, -18.0, "dB", 0.5),
                Control("Ratio", "Ratio", RATIO, 1.0, 20.0, 3.0, ":1", 0.1),
                Control("Attack time (ms)", "Attack", MS, 0.0, 100.0, 22.0, "ms", 1.0),
                Control("Release time (ms)", "Release", MS, 0.0, 800.0, 120.0, "ms", 5.0),
                Control("Makeup gain (G)", "Makeup", DB, -24.0, 24.0, 4.0, "dB", 0.5),
            ],
        ),
        Effect(
            "limit", "Limiter", "limiter_mono",
            "Final safety net so a shout never clips the stream.",
            [
                Control("Threshold (G)", "Ceiling", DB, -48.0, 0.0, -1.0, "dB", 0.5),
                Control("Lookahead (ms)", "Lookahead", MS, 0.1, 20.0, 5.0, "ms", 0.1),
                Control("Release time (ms)", "Release", MS, 0.25, 20.0, 5.0, "ms", 0.25),
            ],
        ),
    ]


def load_state():
    try:
        with open(FX_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FX_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


def apply_state(rack, state):
    for effect in rack:
        saved = state.get(effect.ident, {})
        effect.enabled = saved.get("enabled", effect.enabled)
        for control in effect.controls:
            if control.port in saved.get("controls", {}):
                # Ranges have narrowed between releases, so a value saved by an
                # older version can sit outside the control it belongs to.
                value = float(saved["controls"][control.port])
                control.default = max(control.minimum,
                                      min(control.maximum, value))
    return rack


def rack_to_state(rack):
    return {
        e.ident: {
            "enabled": e.enabled,
            "controls": {c.port: c.default for c in e.controls},
        }
        for e in rack
    }


def _node(effect):
    controls = {c.port: c.to_plugin(c.default) for c in effect.controls}
    if effect.ident == "gate":
        # Enables the second (close) threshold; without it LSP ignores the
        # hysteresis value and the gate chatters between syllables.
        controls["Hysteresis"] = 1.0
    controls["Bypass"] = 0.0 if effect.enabled else 1.0
    body = "\n".join(
        f'                          "{k}" = {v:.6f}' for k, v in controls.items()
    )
    return (
        f"                    {{ type = ladspa  name = {effect.ident}\n"
        f'                      plugin = "{LADSPA_LIB}"\n'
        f'                      label = "{effect.uri}"\n'
        f"                      control = {{\n{body}\n"
        f"                      }} }}"
    )


def generate_config(rack, source):
    """Render the filter-chain drop-in.

    Disabled effects stay in the graph and are switched via their Bypass
    port, so toggling one is a control change rather than a topology rebuild.

    flags = [ nofail ] is required: a bad control name or a missing plugin
    library would otherwise stop PipeWire from starting at all.
    """
    nodes = "\n".join(_node(e) for e in rack)
    links = "\n".join(
        f'                    {{ output = "{a.ident}:Output"  input = "{b.ident}:Input" }}'
        for a, b in zip(rack, rack[1:])
    )
    return f"""# Generated by wave3 - do not edit by hand.
#
# Mic effects rack: {" -> ".join(e.label for e in rack)}
# Output is exposed as the virtual source "{FX_SOURCE}".
#
# nofail is required: a mandatory module that fails to load prevents
# PipeWire from starting at all.

context.modules = [
    {{  name = libpipewire-module-filter-chain
        flags = [ nofail ]
        args = {{
            node.description = "Wave:3 Mic FX"
            media.name       = "Wave:3 Mic FX"
            filter.graph = {{
                nodes = [
{nodes}
                ]
                links = [
{links}
                ]
                inputs  = [ "{rack[0].ident}:Input" ]
                outputs = [ "{rack[-1].ident}:Output" ]
            }}
            capture.props = {{
                node.name        = "{FX_CAPTURE}"
                node.description = "Wave:3 Mic FX input"
                media.class      = Stream/Input/Audio
                target.object    = "{source}"
                audio.position   = [ MONO ]
            }}
            playback.props = {{
                node.name        = "{FX_SOURCE}"
                node.description = "Wave:3 Mic (FX)"
                media.class      = Audio/Source
                audio.position   = [ MONO ]
            }}
        }}
    }}
]
"""


def install(rack, source):
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CONF_PATH, "w") as fh:
        fh.write(generate_config(rack, source))
    return CONF_PATH


def uninstall():
    if os.path.exists(CONF_PATH):
        os.remove(CONF_PATH)
        return True
    return False


def installed():
    return os.path.exists(CONF_PATH)


def available():
    return os.path.exists(LADSPA_LIB)


class Runtime:
    """Live control of the loaded rack.

    filter-chain publishes every plugin control on the capture node as a Props
    param keyed "<effect>:<Port Name>", so a knob turn is a param set rather
    than a config rewrite and PipeWire restart.
    """

    def __init__(self):
        self.node_id = None

    def refresh(self):
        from . import mixer
        self.node_id = None
        for obj in mixer.pw_dump():
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            if obj.get("info", {}).get("props", {}).get("node.name") == FX_CAPTURE:
                self.node_id = obj["id"]
                break
        return self.node_id

    @property
    def available(self):
        return self.node_id is not None

    def _set(self, key, literal):
        import subprocess
        if self.node_id is None and self.refresh() is None:
            return False
        r = subprocess.run(
            ["pw-cli", "s", str(self.node_id), "Props",
             f'{{ params = [ "{key}" {literal} ] }}'],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0

    def set_control(self, effect, control, value):
        return self._set(f"{effect.ident}:{control.port}",
                         f"{control.to_plugin(value):.6f}")

    def set_enabled(self, effect, enabled):
        return self._set(f"{effect.ident}:Bypass", "false" if enabled else "true")
