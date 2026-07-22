"""Regression test for the toggle bounce.

Drives the real Adwaita widgets against a simulated device and records
every visual state change. The bug was that _poll overwrote a row while
its write was still queued, so a single user toggle produced a
new -> old -> new flicker instead of a single clean transition.

No USB hardware is touched.
"""

import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib  # noqa: E402

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import protocol as p  # noqa: E402
from wave3.app import Window  # noqa: E402
from wave3.device import WriteResult  # noqa: E402

BASE = bytearray.fromhex("0028000000010180e800000001000001")


class FakeDev:
    """In-memory stand-in with a realistic USB round-trip delay."""

    def __init__(self, latency=0.004):
        self.block = bytearray(BASE)
        self.latency = latency
        self.writes = 0

    def read_config(self):
        time.sleep(self.latency)
        return bytearray(self.block)

    def read_status(self):
        return {"/touch_pressed_ms": 0, "/touch_signal": 0}

    def read_version(self):
        return {"api": "5.3", "firmware": "1.2.2", "serial": "FAKE"}

    def set_field(self, field, value):
        before = bytearray(self.block)
        time.sleep(self.latency * 3)
        self.block = p.encode_field(field, self.block, value)
        self.writes += 1
        return WriteResult(field, bytes(before), bytes(self.block), [])


results = []


def settle(ms):
    """Let the poll loop run so rows hold real device values."""
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


def run_case(win, path, new_value, settle_ms):
    row = win.rows[path]
    assert row.value != new_value, (
        f"{path} already at {new_value}; test would be a no-op"
    )
    log = []
    signal = "notify::active" if row.field.kind == p.BOOL else "notify::value"

    def record(*_a):
        log.append(row.value)

    handler = row.row.connect(signal, record)

    if row.field.kind == p.BOOL:
        row.row.set_active(new_value)
    else:
        row.row.set_value(new_value)

    loop = GLib.MainLoop()
    GLib.timeout_add(settle_ms, lambda: (loop.quit(), False)[1])
    loop.run()
    row.row.disconnect(handler)
    return log


def on_activate(app):
    dev = FakeDev()
    win = Window(app, dev)
    settle(500)

    dev.writes = 0
    log = run_case(win, "/clipguard_enable", False, 700)
    results.append((
        "clipguard on->off: one clean transition, no bounce",
        log, dev.writes, log == [False] and dev.writes == 1,
    ))

    dev.writes = 0
    log = run_case(win, "/input_mute", True, 700)
    results.append((
        "mute off->on: one clean transition",
        log, dev.writes, log == [True] and dev.writes == 1,
    ))

    dev.writes = 0
    log = run_case(win, "/clipguard_enable", True, 700)
    results.append((
        "clipguard off->on: reverse direction also clean",
        log, dev.writes, log == [True] and dev.writes == 1,
    ))

    dev.writes = 0
    row = win.rows["/input_gain"]
    for v in (10.0, 15.0, 20.0, 25.0, 30.0):
        row.row.set_value(v)
    settle(900)
    results.append((
        "gain drag over 5 steps coalesces into one write",
        [row.value], dev.writes, dev.writes == 1 and row.value == 30.0,
    ))

    dev.writes = 0
    settle(400)
    results.append((
        "idle poll issues no writes and leaves rows alone",
        [win.rows["/clipguard_enable"].value], dev.writes, dev.writes == 0,
    ))

    app.quit()


def main():
    app = Adw.Application(application_id="com.orkait.Wave3.RaceTest")
    app.connect("activate", on_activate)
    app.run([])

    print()
    ok = True
    for name, log, writes, passed in results:
        mark = "PASS" if passed else "FAIL"
        ok &= passed
        print(f"  [{mark}] {name}")
        print(f"         visual transitions: {log}  usb writes: {writes}")

    print()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
