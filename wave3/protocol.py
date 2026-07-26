"""Elgato Wave:3 vendor control protocol.

Field map recovered from LWT::Wave3::known_apis in the macOS WaveAPI
framework and cross-checked against live hardware. Offsets 4 and 7 are
confirmed by observation; the rest come from static analysis only and
stay write-locked until the hardware demonstrates them.
"""

import struct
from dataclasses import dataclass

VENDOR_ID = 0x0FD9
PRODUCT_ID = 0x0070

RT_CLASS_IN = 0xA1
RT_CLASS_OUT = 0x21
BREQUEST_READ = 0x85
BREQUEST_WRITE = 0x05

# 0x33 is the firmware magic; the low byte must name an unclaimed
# interface or the kernel refuses to forward the transfer. Interface 3
# is the vendor control interface and snd-usb-audio never binds it.
WINDEX = 0x3303

SEL_CONFIG = 0x0000
SEL_STATUS = 0x0001
SEL_VERSION = 0x000A

CONFIG_LEN = 16
STATUS_LEN = 8

Q88 = 256.0

BOOL = "bool"
Q88_DB = "q88db"
Q88_PCT = "q88pct"
ENUM = "enum"

VOLUME_SELECT = {1: "Microphone", 2: "Headphone", 3: "Mix"}


@dataclass(frozen=True)
class Field:
    path: str
    label: str
    offset: int
    kind: str
    size: int
    minimum: float = 0.0
    maximum: float = 0.0
    step: float = 1.0
    unit: str = ""
    group: str = "Microphone"


CONFIG_FIELDS = (
    Field("/input_gain", "Gain", 0, Q88_DB, 2, 0.0, 40.0, 0.5, "dB", "Microphone"),
    Field("/input_mute", "Mute", 4, BOOL, 1, group="Microphone"),
    Field("/clipguard_enable", "Clipguard", 5, BOOL, 1, group="Microphone"),
    Field("/lowcut_enable", "Low cut", 6, BOOL, 1, group="Microphone"),
    Field("/gain_lock", "Gain lock", 15, BOOL, 1, group="Microphone"),
    Field("/headphone_volume", "Headphone volume", 7, Q88_DB, 2, -60.0, 0.0, 0.5, "dB", "Monitoring"),
    Field("/headphone_mute", "Headphone mute", 9, BOOL, 1, group="Monitoring"),
    Field("/direct_monitor", "Mic / PC balance", 10, Q88_PCT, 2, 0.0, 100.0, 5.0, "%", "Monitoring"),
    Field("/volume_select", "Dial mode", 12, ENUM, 1, group="Device"),
    Field("/all_leds_off", "LEDs off", 13, BOOL, 1, group="Device"),
    Field("/leds_flip", "Flip LED direction", 14, BOOL, 1, group="Device"),
)

BY_PATH = {f.path: f for f in CONFIG_FIELDS}
BY_OFFSET = {f.offset: f for f in CONFIG_FIELDS}

# Bytes 2-3 are unused in this API revision and must survive a
# read-modify-write cycle untouched.
RESERVED = (2, 3)

# Offsets confirmed by observing the hardware change them. Seeds the
# persisted verification store.
#   /input_gain       dial sweep, 40.00 -> 6.15 dB in 6.15 dB detents
#   /input_mute       ALSA numid=5 toggle, byte 4 followed it
#   /headphone_volume ALSA numid=4 at 20/73/100, all three matched Q8.8 dB
PROVEN_BY_OBSERVATION = ("/input_gain", "/input_mute", "/headphone_volume")

_CONTINUATION = {}
for _f in CONFIG_FIELDS:
    for _i in range(1, _f.size):
        _CONTINUATION[_f.offset + _i] = _f.offset


def owning_offset(offset):
    """Map any byte offset to the offset of the field that contains it."""
    return _CONTINUATION.get(offset, offset)


def decode_field(field, buf):
    if field.kind == BOOL:
        return bool(buf[field.offset])
    if field.kind == ENUM:
        return buf[field.offset]
    raw = struct.unpack_from("<h", buf, field.offset)[0]
    return raw / Q88


def encode_field(field, buf, value):
    """Write value into a mutable copy of the config block."""
    out = bytearray(buf)
    if field.kind == BOOL:
        out[field.offset] = 1 if value else 0
    elif field.kind == ENUM:
        out[field.offset] = int(value) & 0xFF
    else:
        clamped = max(field.minimum, min(field.maximum, float(value)))
        struct.pack_into("<h", out, field.offset, int(round(clamped * Q88)))
    return out


def decode_config(buf):
    return {f.path: decode_field(f, buf) for f in CONFIG_FIELDS}


def format_value(field, value):
    if field.kind == BOOL:
        return "on" if value else "off"
    if field.kind == ENUM:
        return VOLUME_SELECT.get(value, f"unknown ({value})")
    return f"{value:.2f} {field.unit}".strip()


def decode_status(buf):
    pressed_ms, signal = struct.unpack_from("<II", buf, 0)
    return {"/touch_pressed_ms": pressed_ms, "/touch_signal": signal}


def decode_version(buf):
    """Parse the /version block. Layout depends on the API revision."""
    api_major, api_minor = buf[0], buf[1]
    info = {"api": f"{api_major}.{api_minor}"}
    if (api_major, api_minor) >= (5, 4):
        serial_end = 50
    else:
        serial_end = 48
    if len(buf) >= 24:
        info["firmware"] = f"{buf[21]}.{buf[22]}.{buf[23]}"
    if len(buf) >= serial_end:
        info["serial"] = bytes(buf[36:serial_end]).decode("ascii", "replace").rstrip("\x00")
    return info
