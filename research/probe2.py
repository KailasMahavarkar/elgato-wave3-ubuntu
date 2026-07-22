#!/usr/bin/env python3
"""Wave:3 probe phase 2 - full wValue sweep + ALSA-mediated offset mapping.

Still no vendor writes. The only mutations go through standard ALSA UAC
controls (reversible, kernel-mediated) and are restored afterwards.
"""

import ctypes
import ctypes.util
import subprocess
import sys
import time

VID, PID = 0x0FD9, 0x0070
RT_IN, REQ_READ, WINDEX = 0xA1, 0x85, 0x3303
CARD = "1"

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


def read(wval, length=4096):
    buf = (ctypes.c_ubyte * length)()
    n = lib.libusb_control_transfer(h, RT_IN, REQ_READ, wval, WINDEX, buf, length, 800)
    return (n, bytes(buf[:n])) if n > 0 else (n, b"")


def cget(numid):
    out = subprocess.run(["amixer", "-c", CARD, "cget", f"numid={numid}"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ": values=" in line:
            return line.split("=")[-1].strip()
    return None


def cset(numid, val):
    subprocess.run(["amixer", "-c", CARD, "cset", f"numid={numid}", str(val)],
                   capture_output=True, text=True)
    time.sleep(0.25)


print("=== wValue sweep 0x00-0xFF ===")
found = {}
for wval in range(0x100):
    n, data = read(wval)
    if n > 0:
        found[wval] = data
        print(f"  wValue=0x{wval:02X} len={n:4d}  {data[:48].hex()}{'...' if n > 48 else ''}")

print(f"\n  responsive wValues: {[hex(k) for k in found]}")

print("\n=== ALSA-mediated offset mapping (config block, wValue=0) ===")
base_hp = cget(4)
base_gain = cget(6)
print(f"  baseline ALSA: PCM Playback Volume={base_hp}  Mic Capture Volume={base_gain}")


def cfg():
    return read(0x0000, 64)[1]


rows = []
rows.append(("baseline", base_hp, base_gain, cfg()))

for hp in (20, 100):
    cset(4, hp)
    rows.append((f"hp={hp}", hp, base_gain, cfg()))
cset(4, base_hp)

for g in (0, 40, 80):
    cset(6, g)
    rows.append((f"gain={g}", base_hp, g, cfg()))
cset(6, base_gain)

print("  mute toggle test")
cset(5, "off")
rows.append(("mic muted", base_hp, base_gain, cfg()))
cset(5, "on")
rows.append(("mic unmuted", base_hp, base_gain, cfg()))

print()
for label, hp, g, data in rows:
    print(f"  {label:14s} {data.hex()}")

print("\n=== per-byte diff vs baseline ===")
base = rows[0][3]
for label, hp, g, data in rows[1:]:
    diff = [(i, base[i], data[i]) for i in range(min(len(base), len(data))) if base[i] != data[i]]
    print(f"  {label:14s} -> " + (", ".join(f"[{i}] {a:02x}->{b:02x}" for i, a, b in diff) or "no change"))

print(f"\n  restored: PCM={cget(4)} Mic={cget(6)} Switch={cget(5)}")
