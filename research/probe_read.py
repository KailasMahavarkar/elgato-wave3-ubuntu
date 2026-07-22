#!/usr/bin/env python3
"""Read-only probe of the Elgato Wave:3 vendor control interface.

Sends only IN (device-to-host) control transfers. No writes, no DFU,
no state mutation. A STALL is recorded as unsupported and skipped.
"""

import ctypes
import ctypes.util
import sys

VID, PID = 0x0FD9, 0x0070

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


def read(rt, req, wval, widx, length, timeout=500):
    buf = (ctypes.c_ubyte * length)()
    n = lib.libusb_control_transfer(h, rt, req, wval, widx, buf, length, timeout)
    return n, bytes(buf[:n]) if n > 0 else b""


REQTYPES = [(0xA1, "class-IN"), (0xC1, "vendor-IN")]
WINDICES = [0x3303, 0x3300, 0x0003]

print("=== phase 1: locate responsive (bmRequestType, bRequest, wIndex) ===")
hits = []
for rt, rtname in REQTYPES:
    for widx in WINDICES:
        for req in (0x85, 0x05, 0x81, 0x01, 0x82, 0x83, 0x84, 0x86, 0x87):
            n, data = read(rt, req, 0x0000, widx, 64)
            if n > 0:
                print(f"  HIT rt=0x{rt:02X}({rtname}) req=0x{req:02X} widx=0x{widx:04X} "
                      f"len={n} data={data.hex()}")
                hits.append((rt, req, widx))

if not hits:
    print("  no response on any combination")
    sys.exit(0)

rt, req, widx = hits[0]
print(f"\n=== phase 2: wValue sweep on rt=0x{rt:02X} req=0x{req:02X} widx=0x{widx:04X} ===")
for wval in range(0, 0x20):
    n, data = read(rt, req, wval, widx, 255)
    if n > 0:
        print(f"  wValue=0x{wval:04X} len={n:3d}  {data.hex()}")
