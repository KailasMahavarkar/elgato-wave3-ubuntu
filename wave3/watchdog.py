"""Capture-stream wedge detection and recovery.

The Wave:3 capture stream can reach a state where ALSA reports the substream
RUNNING yet hw_ptr never advances: no period ever arrives, every meter reads
-90 dB and nothing appears in any log. The shipped WirePlumber rule disables
suspend, which removes PipeWire's incidental recovery path, so recovery has to
be deliberate. Detection reads hw_ptr from /proc/asound because "no samples"
and "silence" are indistinguishable at the PipeWire layer.
"""

import glob
import os
import subprocess
import threading
import time

USB_ID = "0fd9:0070"

# A wedged stream shows zero movement indefinitely; a healthy one at 48 kHz
# advances every few milliseconds. Two seconds is beyond any legitimate
# scheduling gap.
STALL_SECONDS = 2.0
POLL_SECONDS = 0.5

# The device needs a moment with the profile released before it hands back a
# working stream; cycling too fast reproduces the wedge.
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


def _set_profile(name, profile, attempts=3):
    """Set a card profile, retrying, and report whether it took effect."""
    for attempt in range(attempts):
        try:
            subprocess.run(["pactl", "set-card-profile", name, profile],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        if active_profile(name) == profile:
            return True
        time.sleep(0.5 * (attempt + 1))
    return False


def recover(last_good=None):
    """Cycle the card profile to re-open the capture stream.

    Least invasive action that clears the wedge; restarting PipeWire also
    works but tears down every application's audio.

    The restore must not be skipped: a card left on "off" disappears entirely
    and its closed stream then reads as legitimately idle, so the wedge is
    never retried. It runs from a finally block and is verified, not assumed.
    """
    name = card_name()
    if name is None:
        return False

    profile = active_profile(name)
    if profile == "off":
        # Stranded by a previous interrupted recovery; fall back to the
        # remembered profile rather than refusing.
        profile = last_good
    if not profile or profile == "off":
        return False

    restored = False
    try:
        try:
            subprocess.run(["pactl", "set-card-profile", name, "off"],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        time.sleep(PROFILE_SETTLE)
    finally:
        restored = _set_profile(name, profile)

    if not restored:
        return False
    time.sleep(PROFILE_SETTLE)
    return True


# A profile cycle that does not clear the stall will not clear it on the tenth
# attempt either, and each cycle tears down every stream bound to the card, so
# back off and then stop.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0, 5.0, 20.0)


class CaptureWatchdog:
    """Watches the capture stream and recovers it when it stalls."""

    def __init__(self, on_recover=None, on_give_up=None):
        self.on_recover = on_recover
        self.on_give_up = on_give_up
        self.recoveries = 0
        self.wedged = False
        self.gave_up = False
        self._thread = None
        self._stop = threading.Event()
        self._lifecycle = threading.Lock()
        self._last_good_profile = None

    def start(self):
        # The lifecycle lock stops a start() from re-clearing the stop event
        # while a previous thread is still mid-recovery, which would leave two
        # threads cycling the same card profile against each other.
        with self._lifecycle:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self, timeout=6.0):
        """Stop watching and wait for any in-flight recovery to finish.

        A recovery interrupted between "profile off" and "profile restored"
        leaves the card with no profile at all.
        """
        with self._lifecycle:
            thread = self._thread
            self._stop.set()
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
            self._thread = None

    def _attempt_recovery(self, card):
        """Try to clear a stall, verifying the pointer actually moves after."""
        for attempt in range(MAX_ATTEMPTS):
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            if delay and self._stop.wait(delay):
                return False

            name = card_name()
            if name:
                current = active_profile(name)
                if current and current != "off":
                    self._last_good_profile = current

            if not recover(self._last_good_profile):
                continue

            # Recovery is only real if data starts arriving again.
            card = find_card() or card
            first = hw_pointer(card)
            if self._stop.wait(0.5):
                return False
            if first is not None and hw_pointer(card) != first:
                self.recoveries += 1
                if self.on_recover:
                    self.on_recover(self.recoveries)
                return True

        self.gave_up = True
        if self.on_give_up:
            self.on_give_up()
        return False

    def _run(self):
        last_pointer = None
        last_movement = time.monotonic()

        while not self._stop.is_set():
            card = find_card()
            if card is None:
                last_pointer = None
                self.gave_up = False       # a replug resets the give-up state
                if self._stop.wait(POLL_SECONDS):
                    return
                continue

            pointer = hw_pointer(card)
            now = time.monotonic()

            if pointer is None or not is_running(card):
                # Not open, or legitimately idle.
                last_pointer = None
                last_movement = now
                self.wedged = False
            elif pointer != last_pointer:
                last_pointer = pointer
                last_movement = now
                self.wedged = False
                self.gave_up = False
            elif now - last_movement > STALL_SECONDS and not self.gave_up:
                self.wedged = True
                self._attempt_recovery(card)
                # Keep the last real reading. Resetting to None would make the
                # next sample read as movement and clear gave_up, restarting
                # the cycle just abandoned.
                last_pointer = hw_pointer(card)
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
