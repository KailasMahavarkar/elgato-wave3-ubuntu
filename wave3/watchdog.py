"""Capture-stream wedge detection and recovery.

The Wave:3 is a UAC1 device whose capture stream can enter a state where USB
reports the stream running and ALSA reports the substream RUNNING, yet the
hardware pointer never advances - not one period ever arrives. Every meter
then reads a confident -90 dB and the microphone is silent everywhere, with
nothing in any log to say why.

Normally PipeWire would suspend the idle device and re-open it, which clears
the wedge as a side effect. The WirePlumber rule this project ships disables
suspend (session.suspend-timeout-seconds = 0) to stop a *different* failure
where the capsule suspends and then serves digital silence. That trade removes
the accidental recovery path, so recovery has to be deliberate: this module.

Detection reads hw_ptr straight from /proc/asound rather than inferring from
audio levels, because "no samples" and "silence" are indistinguishable at the
PipeWire layer and only one of them is a fault.
"""

import glob
import os
import subprocess
import threading
import time

USB_ID = "0fd9:0070"

# A wedged stream shows zero movement indefinitely, while a healthy one at
# 48 kHz advances every few milliseconds. Two seconds is far beyond any
# legitimate scheduling gap and still recovers before a take is ruined.
STALL_SECONDS = 2.0
POLL_SECONDS = 0.5

# The device needs a moment with the profile released before it will hand back
# a working stream; cycling too fast reproduces the wedge.
PROFILE_SETTLE = 1.5


def find_card():
    """ALSA card index for the Wave:3, or None.

    Matched on USB id rather than card name or index: both change across
    replug and reboot, the vendor id does not.
    """
    for path in glob.glob("/proc/asound/card*/usbid"):
        try:
            with open(path) as fh:
                if fh.read().strip() == USB_ID:
                    return os.path.basename(os.path.dirname(path)).replace("card", "")
        except OSError:
            continue
    return None


def capture_status(card):
    """Parsed capture substream status, or None when it is not open."""
    pattern = f"/proc/asound/card{card}/pcm*c/sub0/status"
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        if "closed" in text:
            continue
        status = {}
        for line in text.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                status[key.strip()] = value.strip()
        if status:
            return status
    return None


def hw_pointer(card):
    status = capture_status(card)
    if not status:
        return None
    try:
        return int(status.get("hw_ptr", "0"))
    except ValueError:
        return None


def is_running(card):
    status = capture_status(card)
    return bool(status) and status.get("state") == "RUNNING"


def card_name():
    """PulseAudio card name for the Wave:3, needed to cycle its profile."""
    try:
        out = subprocess.run(
            ["pactl", "list", "short", "cards"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "Elgato_Wave_3" in parts[1]:
            return parts[1]
    return None


def active_profile(name):
    try:
        out = subprocess.run(
            ["pactl", "list", "cards"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    current = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            current = stripped[6:]
        elif stripped.startswith("Active Profile: ") and current == name:
            return stripped[16:]
    return None


def recover():
    """Cycle the card profile off and back to re-open the capture stream.

    This is the least invasive action that clears the wedge. Restarting
    PipeWire also works but tears down every application's audio, which is
    not acceptable mid-stream.
    """
    name = card_name()
    if name is None:
        return False
    profile = active_profile(name)
    if not profile or profile == "off":
        return False
    try:
        subprocess.run(["pactl", "set-card-profile", name, "off"],
                       capture_output=True, timeout=10)
        time.sleep(PROFILE_SETTLE)
        subprocess.run(["pactl", "set-card-profile", name, profile],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    time.sleep(PROFILE_SETTLE)
    return True


class CaptureWatchdog:
    """Watches the capture stream and recovers it when it stalls."""

    def __init__(self, on_recover=None):
        self.on_recover = on_recover
        self.recoveries = 0
        self.wedged = False
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def _run(self):
        last_pointer = None
        last_movement = time.monotonic()

        while not self._stop.is_set():
            card = find_card()
            if card is None:
                last_pointer = None
                if self._stop.wait(POLL_SECONDS):
                    return
                continue

            pointer = hw_pointer(card)
            now = time.monotonic()

            if pointer is None or not is_running(card):
                # Not open, or legitimately idle. Nothing to judge.
                last_pointer = None
                last_movement = now
                self.wedged = False
            elif pointer != last_pointer:
                last_pointer = pointer
                last_movement = now
                self.wedged = False
            elif now - last_movement > STALL_SECONDS:
                self.wedged = True
                if recover():
                    self.recoveries += 1
                    if self.on_recover:
                        self.on_recover(self.recoveries)
                last_pointer = None
                last_movement = time.monotonic()
                self.wedged = False

            if self._stop.wait(POLL_SECONDS):
                return


def check_once():
    """One-shot health report. Returns (ok, message)."""
    card = find_card()
    if card is None:
        return False, "Wave:3 not found on USB"

    status = capture_status(card)
    if not status:
        return True, f"card {card}: capture stream closed (idle)"

    if status.get("state") != "RUNNING":
        return True, f"card {card}: capture {status.get('state', 'unknown')}"

    first = hw_pointer(card)
    time.sleep(0.4)
    second = hw_pointer(card)
    if first is None or second is None:
        return False, f"card {card}: cannot read hw_ptr"
    if second == first:
        return False, (
            f"card {card}: capture WEDGED - hw_ptr stuck at {first}, "
            "no audio is arriving from the device"
        )
    return True, f"card {card}: healthy, hw_ptr {first} -> {second}"
