"""Parametric EQ band model and frequency-response maths.

No GTK here. The response curve comes from RBJ cookbook biquads evaluated on
the unit circle, which is what LSP's para_equalizer runs with its filter mode
set to APO (DR), so the drawn curve matches the running filter. It models the
filter response, not the measured output of the chain.
"""

import cmath
import math
from dataclasses import dataclass

SAMPLE_RATE = 48000.0

OFF = 0
BELL = 1
HIPASS = 2
HISHELF = 3
LOPASS = 4
LOSHELF = 5
NOTCH = 6

TYPE_NAMES = {
    OFF: "Off",
    BELL: "Bell",
    HIPASS: "High Pass",
    HISHELF: "High Shelf",
    LOPASS: "Low Pass",
    LOSHELF: "Low Shelf",
    NOTCH: "Notch",
}

# Order shown in the filter-type menu.
MENU_TYPES = (HIPASS, HISHELF, BELL, NOTCH, LOSHELF, LOPASS)

# APO (DR) is the plain digital biquad the maths below describes.
APO_MODE = 6

FREQ_MIN = 20.0
FREQ_MAX = 20000.0
GAIN_MIN = -12.0
GAIN_MAX = 12.0
Q_MIN = 0.1
Q_MAX = 12.0


@dataclass
class Band:
    index: int
    name: str
    kind: int
    frequency: float
    gain_db: float
    q: float
    colour: tuple

    @property
    def active(self):
        return self.kind != OFF

    @property
    def shapes_gain(self):
        """True when the gain control does anything for this filter type."""
        return self.kind in (BELL, HISHELF, LOSHELF)


# Each band sits inside the Elgato zone it is named after. The high-pass sits
# at the top of the rumble zone so it removes that zone rather than half of it;
# the air shelf sits at the bottom of its zone so it lifts the whole thing.
DEFAULT_BANDS = (
    (0, "Rumble / Sub-bass", HIPASS, 80.0, 0.0, 0.7, (0.97, 0.45, 0.75)),
    (1, "Boom / Warmth", BELL, 155.0, 0.0, 1.0, (0.98, 0.82, 0.35)),
    (2, "Boxy", BELL, 650.0, 0.0, 1.2, (0.98, 0.60, 0.30)),
    (3, "Nasal", BELL, 2650.0, 0.0, 1.4, (0.55, 0.85, 0.55)),
    (4, "Presence", BELL, 7700.0, 0.0, 1.0, (0.93, 0.35, 0.55)),
    (5, "Air", HISHELF, 12000.0, 0.0, 0.7, (0.42, 0.83, 0.90)),
)


def build_bands():
    return [Band(*spec) for spec in DEFAULT_BANDS]


def _coefficients(band):
    """RBJ cookbook biquad for one band. Returns (b0,b1,b2,a0,a1,a2)."""
    f0 = max(FREQ_MIN, min(FREQ_MAX, band.frequency))
    w0 = 2.0 * math.pi * f0 / SAMPLE_RATE
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    q = max(Q_MIN, band.q)
    alpha = sin_w0 / (2.0 * q)
    amp = 10.0 ** (band.gain_db / 40.0)

    if band.kind == BELL:
        return (
            1 + alpha * amp, -2 * cos_w0, 1 - alpha * amp,
            1 + alpha / amp, -2 * cos_w0, 1 - alpha / amp,
        )
    if band.kind == HIPASS:
        return (
            (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2,
            1 + alpha, -2 * cos_w0, 1 - alpha,
        )
    if band.kind == LOPASS:
        return (
            (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2,
            1 + alpha, -2 * cos_w0, 1 - alpha,
        )
    if band.kind == NOTCH:
        return (1, -2 * cos_w0, 1, 1 + alpha, -2 * cos_w0, 1 - alpha)
    if band.kind == LOSHELF:
        sqrt_term = 2.0 * math.sqrt(amp) * alpha
        return (
            amp * ((amp + 1) - (amp - 1) * cos_w0 + sqrt_term),
            2 * amp * ((amp - 1) - (amp + 1) * cos_w0),
            amp * ((amp + 1) - (amp - 1) * cos_w0 - sqrt_term),
            (amp + 1) + (amp - 1) * cos_w0 + sqrt_term,
            -2 * ((amp - 1) + (amp + 1) * cos_w0),
            (amp + 1) + (amp - 1) * cos_w0 - sqrt_term,
        )
    if band.kind == HISHELF:
        sqrt_term = 2.0 * math.sqrt(amp) * alpha
        return (
            amp * ((amp + 1) + (amp - 1) * cos_w0 + sqrt_term),
            -2 * amp * ((amp - 1) + (amp + 1) * cos_w0),
            amp * ((amp + 1) + (amp - 1) * cos_w0 - sqrt_term),
            (amp + 1) - (amp - 1) * cos_w0 + sqrt_term,
            2 * ((amp - 1) - (amp + 1) * cos_w0),
            (amp + 1) - (amp - 1) * cos_w0 - sqrt_term,
        )
    return (1, 0, 0, 1, 0, 0)


def band_response_db(band, frequency):
    """Magnitude response of one band at one frequency, in dB."""
    if not band.active:
        return 0.0
    b0, b1, b2, a0, a1, a2 = _coefficients(band)
    w = 2.0 * math.pi * frequency / SAMPLE_RATE
    z1 = cmath.exp(-1j * w)
    z2 = z1 * z1
    numerator = b0 + b1 * z1 + b2 * z2
    denominator = a0 + a1 * z1 + a2 * z2
    if denominator == 0:
        return 0.0
    magnitude = abs(numerator / denominator)
    if magnitude <= 1e-9:
        return -90.0
    return 20.0 * math.log10(magnitude)


def composite_response_db(bands, frequency):
    """Cascade of every active band. Series filters multiply, so dB add."""
    return sum(band_response_db(b, frequency) for b in bands)


def log_frequencies(count, low=FREQ_MIN, high=FREQ_MAX):
    """Frequencies spaced evenly on a log axis, one per pixel column."""
    if count < 2:
        return [low]
    ratio = math.log(high / low)
    return [low * math.exp(ratio * i / (count - 1)) for i in range(count)]


def freq_to_fraction(frequency, low=FREQ_MIN, high=FREQ_MAX):
    frequency = max(low, min(high, frequency))
    return math.log(frequency / low) / math.log(high / low)


def fraction_to_freq(fraction, low=FREQ_MIN, high=FREQ_MAX):
    fraction = max(0.0, min(1.0, fraction))
    return low * math.exp(fraction * math.log(high / low))


def gain_to_fraction(gain_db, low=GAIN_MIN, high=GAIN_MAX):
    gain_db = max(low, min(high, gain_db))
    return 1.0 - (gain_db - low) / (high - low)


def fraction_to_gain(fraction, low=GAIN_MIN, high=GAIN_MAX):
    fraction = max(0.0, min(1.0, fraction))
    return high - fraction * (high - low)



# Frequency zones recovered from Wave Link 3.2.2 (float64 table at
# __DATA_CONST.__const 0x100dfb4a0 of the x86_64 slice; see
# research/dump/DSP_DEFAULTS.md). Names and descriptions are Elgato's own,
# from Resources/en.lproj/Localizable.strings.
#
# The naming is shifted from common studio usage: Elgato's "Presence" is
# 5-12 kHz, which most engineers call sibilance, and their "Nasal" is what is
# usually called presence. Their descriptions are self-consistent with it, so
# the whole scheme is adopted rather than half of it.
ZONES = (
    (20.0, 80.0, "Rumble / Sub-bass",
     "Deep sounding noises often caused by mechanical influences"),
    (80.0, 300.0, "Boom / Warmth",
     "Too much leads to boominess; too little makes the voice sound thin"),
    (300.0, 1400.0, "Boxy",
     "Balance carefully to avoid a boxy or hollow sound"),
    (1400.0, 5000.0, "Nasal",
     "Vocals compete with other audio sources such as game sound here"),
    (5000.0, 12000.0, "Presence",
     "Voices can sound harsh here; can also be tamed with a de-esser"),
    (12000.0, 20000.0, "Air",
     "This range can help brighten the overall sound impression"),
)

ZONE_BOUNDARIES = (20.0, 80.0, 300.0, 1400.0, 5000.0, 12000.0, 20000.0)

GRID_FREQUENCIES = (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)
GRID_GAINS = (12, 9, 6, 3, 0, -3, -6, -9, -12)


def format_frequency(frequency):
    if frequency >= 1000:
        text = f"{frequency / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text} kHz"
    return f"{frequency:.0f} Hz"


def ports_for_band(band):
    """LSP port names carrying this band's state."""
    return {
        "type": f"Filter type {band.index}",
        "mode": f"Filter mode {band.index}",
        "frequency": f"Frequency {band.index} (Hz)",
        "gain": f"Gain {band.index} (G)",
        "q": f"Quality factor {band.index}",
    }
