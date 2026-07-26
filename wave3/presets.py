"""Starting points for the effects rack.

Values follow published guidance for spoken word rather than being invented:
high-pass at 80-100 Hz, presence lifted gently between 1-5 kHz in 2-4 dB
moves, 200-400 Hz cut when muddy; compression at 2:1 to 4:1 with a 20-30 ms
attack and 80-150 ms release, going to 5:1-10:1 with a ~3 ms attack for very
dynamic delivery; gate attack at or under 5 ms with a close threshold set
below the open threshold so it does not chatter between syllables.

Values are in the same UI domain the controls use: dB for thresholds and
gains, milliseconds for times, hertz for frequencies. EQ presets carry whole
bands because a band is only meaningful as type + frequency + gain + Q.

The first entry of each list is the default and is what Reset restores.
"""

from dataclasses import dataclass, field

from . import eq


@dataclass
class Preset:
    name: str
    summary: str
    controls: dict = field(default_factory=dict)
    bands: tuple = ()


GATE = [
    Preset("Default", "A sensible middle setting", {
        "Curve threshold (G)": -26.0,
        "Hysteresis threshold (G)": -34.0,
        "Reduction (G)": -48.0,
        "Attack (ms)": 5.0,
        "Release (ms)": 150.0,
        "Makeup gain (G)": 0.0,
    }),
    Preset("Off", "Passes everything, useful for A/B", {
        "Curve threshold (G)": -60.0,
        "Hysteresis threshold (G)": -60.0,
        "Reduction (G)": 0.0,
        "Attack (ms)": 1.0,
        "Release (ms)": 50.0,
        "Makeup gain (G)": 0.0,
    }),
    Preset("Gentle", "Quiet room. Closes softly so word tails survive", {
        "Curve threshold (G)": -38.0,
        "Hysteresis threshold (G)": -46.0,
        "Reduction (G)": -18.0,
        "Attack (ms)": 3.0,
        "Release (ms)": 250.0,
        "Makeup gain (G)": 0.0,
    }),
    Preset("Broadcast", "Normal room with some background", {
        "Curve threshold (G)": -30.0,
        "Hysteresis threshold (G)": -38.0,
        "Reduction (G)": -40.0,
        "Attack (ms)": 4.0,
        "Release (ms)": 180.0,
        "Makeup gain (G)": 0.0,
    }),
    Preset("Aggressive", "Noisy room, keyboard and fans. Cuts hard", {
        "Curve threshold (G)": -20.0,
        "Hysteresis threshold (G)": -27.0,
        "Reduction (G)": -60.0,
        "Attack (ms)": 2.0,
        "Release (ms)": 120.0,
        "Makeup gain (G)": 0.0,
    }),
]

COMPRESSOR = [
    Preset("Default", "Even out the loud and quiet parts", {
        "Attack threshold (G)": -18.0,
        "Ratio": 3.0,
        "Attack time (ms)": 22.0,
        "Release time (ms)": 120.0,
        "Makeup gain (G)": 4.0,
    }),
    Preset("Off", "Leaves your dynamics alone", {
        "Attack threshold (G)": -6.0,
        "Ratio": 1.0,
        "Attack time (ms)": 20.0,
        "Release time (ms)": 150.0,
        "Makeup gain (G)": 0.0,
    }),
    Preset("Gentle", "Light 2:1 touch, keeps most of your dynamics", {
        "Attack threshold (G)": -16.0,
        "Ratio": 2.0,
        "Attack time (ms)": 28.0,
        "Release time (ms)": 150.0,
        "Makeup gain (G)": 2.0,
    }),
    Preset("Broadcast", "Steady, forward voice. The usual choice", {
        "Attack threshold (G)": -20.0,
        "Ratio": 4.0,
        "Attack time (ms)": 20.0,
        "Release time (ms)": 100.0,
        "Makeup gain (G)": 5.0,
    }),
    Preset("Heavy", "Very level, for shouty or swingy delivery", {
        "Attack threshold (G)": -24.0,
        "Ratio": 8.0,
        "Attack time (ms)": 3.0,
        "Release time (ms)": 100.0,
        "Makeup gain (G)": 7.0,
    }),
]

LIMITER = [
    Preset("Default", "Catches peaks just below clipping", {
        "Threshold (G)": -1.0,
        "Lookahead (ms)": 5.0,
        "Release time (ms)": 5.0,
    }),
    Preset("Transparent", "Only the very worst peaks", {
        "Threshold (G)": -0.5,
        "Lookahead (ms)": 8.0,
        "Release time (ms)": 8.0,
    }),
    Preset("Safe", "More headroom for a platform that re-encodes", {
        "Threshold (G)": -3.0,
        "Lookahead (ms)": 5.0,
        "Release time (ms)": 6.0,
    }),
    Preset("Tight", "Fast and firm, for unpredictable levels", {
        "Threshold (G)": -2.0,
        "Lookahead (ms)": 2.0,
        "Release time (ms)": 2.0,
    }),
]

# (type, frequency, gain_db, q) per band, in the band order of eq.DEFAULT_BANDS.
EQUALISER = [
    Preset("Default", "High-pass only, otherwise flat", bands=(
        (eq.HIPASS, 80.0, 0.0, 0.7),
        (eq.BELL, 160.0, 0.0, 1.0),
        (eq.BELL, 400.0, 0.0, 1.2),
        (eq.BELL, 1200.0, 0.0, 1.4),
        (eq.BELL, 4000.0, 0.0, 1.0),
        (eq.HISHELF, 11000.0, 0.0, 0.7),
    )),
    Preset("Flat", "Every band off, no shaping at all", bands=(
        (eq.OFF, 80.0, 0.0, 0.7),
        (eq.OFF, 160.0, 0.0, 1.0),
        (eq.OFF, 400.0, 0.0, 1.2),
        (eq.OFF, 1200.0, 0.0, 1.4),
        (eq.OFF, 4000.0, 0.0, 1.0),
        (eq.OFF, 11000.0, 0.0, 0.7),
    )),
    Preset("Broadcast", "Radio voice: tight lows, clear presence", bands=(
        (eq.HIPASS, 90.0, 0.0, 0.7),
        (eq.BELL, 180.0, -2.0, 1.0),
        (eq.BELL, 450.0, -3.0, 1.2),
        (eq.BELL, 1500.0, -1.5, 1.4),
        (eq.BELL, 3000.0, 3.0, 1.0),
        (eq.HISHELF, 11000.0, 2.0, 0.7),
    )),
    Preset("Warm", "Fuller and closer, less top end", bands=(
        (eq.HIPASS, 70.0, 0.0, 0.7),
        (eq.BELL, 200.0, 3.0, 1.0),
        (eq.BELL, 500.0, -1.5, 1.2),
        (eq.BELL, 1200.0, -1.0, 1.4),
        (eq.BELL, 3000.0, 1.5, 1.0),
        (eq.HISHELF, 12000.0, -1.5, 0.7),
    )),
    Preset("Bright", "Cuts mud, opens the top", bands=(
        (eq.HIPASS, 100.0, 0.0, 0.7),
        (eq.BELL, 200.0, -2.5, 1.0),
        (eq.BELL, 400.0, -4.0, 1.4),
        (eq.BELL, 1200.0, -1.0, 1.2),
        (eq.BELL, 4500.0, 3.0, 1.0),
        (eq.HISHELF, 10000.0, 2.5, 0.7),
    )),
    Preset("De-boom", "For close mic work with heavy proximity", bands=(
        (eq.HIPASS, 120.0, 0.0, 0.8),
        (eq.BELL, 250.0, -5.0, 1.2),
        (eq.BELL, 500.0, -2.0, 1.2),
        (eq.BELL, 1500.0, 1.0, 1.4),
        (eq.BELL, 4000.0, 2.5, 1.0),
        (eq.HISHELF, 11000.0, 1.5, 0.7),
    )),
]

BY_EFFECT = {
    "gate": GATE,
    "eq": EQUALISER,
    "comp": COMPRESSOR,
    "limit": LIMITER,
}


def for_effect(ident):
    return BY_EFFECT.get(ident, [])


def default_for(ident):
    """The preset Reset restores, which is always the first entry."""
    presets = for_effect(ident)
    return presets[0] if presets else None


def apply_to_effect(effect, preset):
    """Write a preset onto an Effect's controls. Returns changed controls."""
    by_port = {c.port: c for c in effect.controls}
    changed = []
    for port, value in preset.controls.items():
        control = by_port.get(port)
        if control is None or control.default == value:
            continue
        control.default = value
        changed.append(control)
    return changed


def apply_to_bands(bands, preset):
    """Write a preset onto the EQ band model. Returns changed bands."""
    changed = []
    for band, spec in zip(bands, preset.bands):
        kind, frequency, gain_db, q = spec
        if (band.kind, band.frequency, band.gain_db, band.q) == spec:
            continue
        band.kind = kind
        band.frequency = frequency
        band.gain_db = gain_db
        band.q = q
        changed.append(band)
    return changed


def matches(effect, preset, bands=None):
    """True when current values already equal this preset."""
    if preset.bands:
        if bands is None:
            return False
        return all(
            (b.kind, b.frequency, b.gain_db, b.q) == spec
            for b, spec in zip(bands, preset.bands)
        )
    by_port = {c.port: c for c in effect.controls}
    return all(
        port in by_port and by_port[port].default == value
        for port, value in preset.controls.items()
    )


def identify(effect, bands=None):
    """Name of the preset currently in effect, or None when custom."""
    for preset in for_effect(effect.ident):
        if matches(effect, preset, bands):
            return preset.name
    return None
