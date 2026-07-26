"""Voice mode: one processed-sounding chain behind a few plain controls.

    capsule -> RNNoise -> high-pass -> de-esser -> compressor -> limiter -> out

The Effects page exposes every plugin parameter. This exposes five things a
person can actually reason about, and maps each onto whatever the chain needs.

Both modes write the same drop-in and publish the same node name, so exactly
one of them is installed at a time and the mixer never has to know which.

RNNoise is optional and detected at runtime: it is GPL-3 and not packaged for
Ubuntu, so it is loaded by PipeWire rather than linked, and the chain falls
back to a multiband gate when it is absent.
"""

import json
import math
import os

from . import fx

RNNOISE_PATH = "/usr/lib/ladspa/librnnoise_ladspa.so"
RNNOISE_LABEL = "noise_suppressor_mono"

LSP = fx.LADSPA_LIB
LSP_URI = "http://lsp-plug.in/plugins/ladspa"

STATE_FILE = os.path.join(fx.STATE_DIR, "voice.json")
MODE_FILE = os.path.join(fx.STATE_DIR, "mode.json")

RACK = "rack"
VOICE = "voice"


def rnnoise_available():
    return os.path.exists(RNNOISE_PATH)


def current_mode():
    try:
        with open(MODE_FILE) as fh:
            mode = json.load(fh).get("mode")
    except (OSError, ValueError):
        return RACK
    return mode if mode in (RACK, VOICE) else RACK


def save_mode(mode):
    os.makedirs(fx.STATE_DIR, exist_ok=True)
    with open(MODE_FILE, "w") as fh:
        json.dump({"mode": mode}, fh, indent=2)


DEFAULTS = {
    "noise": 60.0,      # percent
    "deess": 40.0,      # percent
    "warmth": 0.0,      # dB
    "presence": 2.0,    # dB
    "leveling": 50.0,   # percent
}

CONTROLS = (
    ("noise", "Noise removal", 0.0, 100.0, "%",
     "Removes fans, keyboards and room hiss while you talk"),
    ("deess", "De-ess", 0.0, 100.0, "%",
     "Softens harsh S and T sounds"),
    ("warmth", "Warmth", -6.0, 6.0, "dB",
     "Body and fullness in the lower part of your voice"),
    ("presence", "Presence", -6.0, 6.0, "dB",
     "Clarity and forwardness, so you sit on top of the mix"),
    ("leveling", "Leveling", 0.0, 100.0, "%",
     "Evens out loud and quiet delivery"),
)


def load_settings():
    values = dict(DEFAULTS)
    try:
        with open(STATE_FILE) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return values
    for key, _l, low, high, _u, _d in CONTROLS:
        if key in saved:
            try:
                values[key] = max(low, min(high, float(saved[key])))
            except (TypeError, ValueError):
                pass
    return values


def save_settings(values):
    os.makedirs(fx.STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as fh:
        json.dump(values, fh, indent=2)


def _db(value):
    return 10.0 ** (value / 20.0)


def _lerp(fraction, low, high):
    return low + max(0.0, min(1.0, fraction)) * (high - low)


def derive(values):
    """Map the five simple controls onto concrete plugin parameters.

    Kept separate from config rendering so the mapping can be tested and so
    the live-update path and the install path cannot disagree.
    """
    noise = values["noise"] / 100.0
    deess = values["deess"] / 100.0
    level = values["leveling"] / 100.0

    derived = {}

    # RNNoise decides speech vs noise; a higher threshold is more aggressive.
    derived["nr"] = {"VAD Threshold (%)": _lerp(noise, 5.0, 95.0)}

    # Multiband gate stands in when RNNoise is missing, and also cleans up
    # under RNNoise when the user asks for a lot of removal.
    derived["mbgate"] = {"Bypass": 0.0 if noise > 0.02 else 1.0}

    # De-ess is a compressor listening only above 6 kHz: the more de-ess, the
    # lower the threshold and the harder the ratio.
    derived["deess"] = {
        "Attack threshold (G)": _db(_lerp(deess, -6.0, -30.0)),
        "Ratio": _lerp(deess, 1.5, 8.0),
        "Attack time (ms)": 1.0,
        "Release time (ms)": 60.0,
        "High-pass filter mode": 1.0,
        "High-pass filter frequency (Hz)": 6000.0,
        "Makeup gain (G)": 1.0,
        "Bypass": 0.0 if deess > 0.02 else 1.0,
    }

    # Tone: a low shelf for warmth and a presence bell, on the EQ stage.
    derived["tone"] = {
        "Filter type 0": 2.0,          # high pass, always on
        "Frequency 0 (Hz)": 85.0,
        "Filter mode 0": 6.0,
        "Filter type 1": 5.0,          # low shelf = warmth
        "Frequency 1 (Hz)": 220.0,
        "Gain 1 (G)": _db(values["warmth"]),
        "Quality factor 1": 0.7,
        "Filter mode 1": 6.0,
        "Filter type 2": 1.0,          # bell = presence
        "Frequency 2 (Hz)": 3000.0,
        "Gain 2 (G)": _db(values["presence"]),
        "Quality factor 2": 1.0,
        "Filter mode 2": 6.0,
    }

    # Leveling: more means a lower threshold, a harder ratio and more makeup.
    derived["comp"] = {
        "Attack threshold (G)": _db(_lerp(level, -10.0, -28.0)),
        "Ratio": _lerp(level, 1.5, 6.0),
        "Attack time (ms)": 22.0,
        "Release time (ms)": 120.0,
        "Makeup gain (G)": _db(_lerp(level, 0.0, 8.0)),
        "Bypass": 0.0 if level > 0.02 else 1.0,
    }

    # Always-on safety net.
    derived["limit"] = {
        "Threshold (G)": _db(-1.0),
        "Lookahead (ms)": 5.0,
        "Release time (ms)": 5.0,
    }
    return derived


def _controls_block(values):
    return "\n".join(f'                          "{k}" = {v:.6f}'
                     for k, v in values.items())


def _node(name, plugin, label, values):
    return (
        f"                    {{ type = ladspa  name = {name}\n"
        f'                      plugin = "{plugin}"\n'
        f'                      label = "{label}"\n'
        f"                      control = {{\n{_controls_block(values)}\n"
        f"                      }} }}"
    )


def chain_stages(with_rnnoise):
    """Stage order. RNNoise first so everything downstream sees clean audio."""
    stages = []
    if with_rnnoise:
        stages.append(("nr", RNNOISE_PATH, RNNOISE_LABEL))
    stages.append(("mbgate", LSP, f"{LSP_URI}/mb_gate_mono"))
    stages.append(("tone", LSP, f"{LSP_URI}/para_equalizer_x16_mono"))
    stages.append(("deess", LSP, f"{LSP_URI}/compressor_mono"))
    stages.append(("comp", LSP, f"{LSP_URI}/compressor_mono"))
    stages.append(("limit", LSP, f"{LSP_URI}/limiter_mono"))
    return stages


def generate_config(values, source, with_rnnoise=None):
    if with_rnnoise is None:
        with_rnnoise = rnnoise_available()
    derived = derive(values)
    stages = chain_stages(with_rnnoise)

    nodes = "\n".join(
        _node(name, plugin, label, derived.get(name, {}))
        for name, plugin, label in stages
    )
    links = "\n".join(
        f'                    {{ output = "{a[0]}:Output"  input = "{b[0]}:Input" }}'
        for a, b in zip(stages, stages[1:])
    )
    order = " -> ".join(name for name, _p, _l in stages)

    return f"""# Generated by wave3 - do not edit by hand.
#
# Voice mode: {order}
# Publishes the same source name as the manual rack, so only one is installed.

context.modules = [
    {{  name = libpipewire-module-filter-chain
        flags = [ nofail ]
        args = {{
            node.description = "Wave:3 Voice"
            media.name       = "Wave:3 Voice"
            filter.graph = {{
                nodes = [
{nodes}
                ]
                links = [
{links}
                ]
                inputs  = [ "{stages[0][0]}:Input" ]
                outputs = [ "{stages[-1][0]}:Output" ]
            }}
            capture.props = {{
                node.name        = "{fx.FX_CAPTURE}"
                node.description = "Wave:3 Voice input"
                media.class      = Stream/Input/Audio
                target.object    = "{source}"
                audio.position   = [ MONO ]
            }}
            playback.props = {{
                node.name        = "{fx.FX_SOURCE}"
                node.description = "Wave:3 Mic (Voice)"
                media.class      = Audio/Source
                audio.position   = [ MONO ]
            }}
        }}
    }}
]
"""


def install(values, source):
    os.makedirs(fx.CONF_DIR, exist_ok=True)
    with open(fx.CONF_PATH, "w") as fh:
        fh.write(generate_config(values, source))
    save_settings(values)
    save_mode(VOICE)
    return fx.CONF_PATH


class Runtime(fx.Runtime):
    """Live control over the voice chain, keyed by stage name."""

    def apply(self, values):
        """Push every derived parameter. Returns True when all writes land."""
        ok = True
        for stage, params in derive(values).items():
            for port, value in params.items():
                if not self._set(f"{stage}:{port}", f"{float(value):.6f}"):
                    ok = False
        return ok
