#!/usr/bin/env python3
"""Live Wave:3 config-block watcher. Read-only.

Polls the 16-byte vendor config block and prints a diff whenever a byte
changes. Interact with the physical device (dial, mute button, headphone
jack) and every hardware control maps itself to a byte offset.
"""

import ctypes
import ctypes.util
import struct
import sys
import time

VID, PID = 0x0FD9, 0x0070
RT_IN, REQ_READ, WINDEX = 0xA1, 0x85, 0x3303

lib = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0")
lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
lib.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
lib.libusb_control_transfer.argtypes = [
    ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8,
    ctypes.c_uint16, ctypes.c_uint16,
    ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint16, ctypes.c_uint,
]
lib.libusb_control_transfer.restype = ctypes.c_int

ctx = ctypes.c_void_p()
lib.libusb_init(ctypes.byref(ctx))
h = lib.libusb_open_device_with_vid_pid(ctx, VID, PID)
if not h:
    sys.exit("Wave:3 not found (need root?)")


def read_config():
    buf = (ctypes.c_ubyte * 16)()
    n = lib.libusb_control_transfer(h, RT_IN, REQ_READ, 0x0000, WINDEX, buf, 16, 800)
    return bytearray(buf[:n]) if n > 0 else None


VOLUME_SELECT = {1: "MIC", 2: "HEADPHONE", 3: "MIX"}

FIELDS = {
    0: ("/input_gain", "q88db"),
    4: ("/input_mute", "bool"),
    5: ("/clipguard_enable", "bool"),
    6: ("/lowcut_enable", "bool"),
    7: ("/headphone_volume", "q88db"),
    9: ("/headphone_mute", "bool"),
    10: ("/direct_monitor", "q88pct"),
    12: ("/volume_select", "enum"),
    13: ("/all_leds_off", "bool"),
    14: ("/leds_flip", "bool"),
    15: ("/gain_lock", "bool"),
}

OWNER = {1: 0, 8: 7, 11: 10}  # continuation bytes of 16-bit fields


def decode(cfg, off):
    off = OWNER.get(off, off)
    if off not in FIELDS:
        return off, f"UNMAPPED byte = 0x{cfg[off]:02x}"
    name, kind = FIELDS[off]
    if kind == "q88db":
        return off, f"{name} = {struct.unpack_from('<h', cfg, off)[0] / 256.0:+.2f} dB"
    if kind == "q88pct":
        return off, f"{name} = {struct.unpack_from('<h', cfg, off)[0] / 256.0:.1f} %"
    if kind == "enum":
        v = cfg[off]
        return off, f"{name} = {v} ({VOLUME_SELECT.get(v, '?')})"
    return off, f"{name} = {'ON' if cfg[off] else 'off'}"


def dump(cfg):
    for off in sorted(FIELDS):
        print("           " + decode(cfg, off)[1])


print("Watching Wave:3 config block. Ctrl-C to stop.\n")
print("Do these one at a time, pausing between each:")
print("  1. press the dial       -> expect /volume_select 1 -> 2 -> 3")
print("  2. rotate in MIC mode   -> expect /input_gain")
print("  3. rotate in HP mode    -> expect /headphone_volume")
print("  4. rotate in MIX mode   -> expect /direct_monitor")
print("  5. tap the mute pad     -> expect /input_mute")
print("  6. unplug/replug phones -> expect any byte, or none\n")

prev = read_config()
print(f"baseline: {prev.hex()}")
dump(prev)
print()

seen = set()
t0 = time.time()

try:
    while True:
        cur = read_config()
        if cur is None:
            time.sleep(0.2)
            continue
        if cur != prev:
            ts = time.time() - t0
            changed = {i for i in range(16) if prev[i] != cur[i]}
            print(f"[{ts:7.2f}s] {cur.hex()}")
            for off in sorted({decode(cur, i)[0] for i in changed}):
                seen.add(off)
                print("           " + decode(cur, off)[1])
            prev = cur
        time.sleep(0.05)
except KeyboardInterrupt:
    confirmed = sorted(seen)
    missing = sorted(set(FIELDS) - seen)
    print("\n=== verified by hardware ===")
    for off in confirmed:
        print(f"  [{off:2d}] {FIELDS.get(off, ('UNMAPPED',))[0]}")
    print("=== not exercised ===")
    for off in missing:
        print(f"  [{off:2d}] {FIELDS[off][0]}")
