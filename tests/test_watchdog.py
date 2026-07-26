"""Capture-wedge detection must fire on a stalled stream and stay quiet otherwise.

The Wave:3 wedge cannot be induced on demand, so the pointer source and the
recovery action are substituted and the decision logic is driven directly.
The recovery action itself is verified against real hardware separately - it
is the same pactl profile cycle that cleared an observed wedge.
"""

import sys
import time

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import watchdog  # noqa: E402


class Harness:
    """Drives CaptureWatchdog against a scripted hardware pointer."""

    def __init__(self, pointers):
        self.pointers = list(pointers)
        self.index = 0
        self.recoveries = 0

    def hw_pointer(self, _card):
        value = self.pointers[min(self.index, len(self.pointers) - 1)]
        self.index += 1
        return value

    def recover(self, _last_good=None):
        self.recoveries += 1
        # A real recovery restarts the stream, so the pointer moves again.
        # The watchdog verifies exactly that before counting a success.
        self.pointers = [i * 48000 for i in range(1, 500)]
        self.index = 0
        return True


def run(pointers, seconds):
    harness = Harness(pointers)
    original = (watchdog.find_card, watchdog.hw_pointer, watchdog.is_running,
                watchdog.recover, watchdog.card_name, watchdog.active_profile)
    watchdog.find_card = lambda: "5"
    watchdog.hw_pointer = harness.hw_pointer
    watchdog.is_running = lambda _c: True
    watchdog.recover = harness.recover
    watchdog.card_name = lambda: "fake-card"
    watchdog.active_profile = lambda _n: "output:analog-stereo+input:mono-fallback"
    try:
        dog = watchdog.CaptureWatchdog()
        dog.start()
        time.sleep(seconds)
        dog.stop()
    finally:
        (watchdog.find_card, watchdog.hw_pointer, watchdog.is_running,
         watchdog.recover, watchdog.card_name, watchdog.active_profile) = original
    return harness.recoveries


def main():
    results = []

    # Healthy: pointer advances every poll. Must never recover.
    advancing = [i * 48000 for i in range(1, 200)]
    fired = run(advancing, 4.0)
    ok = fired == 0
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] healthy stream is left alone "
          f"({fired} recoveries, expected 0)")

    # Wedged: pointer frozen. Must recover after STALL_SECONDS.
    fired = run([12345], 5.0)
    ok = fired >= 1
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] wedged stream is recovered "
          f"({fired} recoveries, expected >=1)")

    # Recovery must not thrash a stream that comes back healthy.
    fired = run([7] * 6 + [i * 48000 for i in range(1, 200)], 6.0)
    ok = 1 <= fired <= 2
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] recovers once then settles "
          f"({fired} recoveries, expected 1-2)")

    # A stream that never comes back must be abandoned, not cycled forever.
    class Dead(Harness):
        def recover(self, _last_good=None):
            self.recoveries += 1
            return True          # claims success but the pointer never moves

    dead = Dead([999])
    original = (watchdog.find_card, watchdog.hw_pointer, watchdog.is_running,
                watchdog.recover, watchdog.card_name, watchdog.active_profile)
    watchdog.find_card = lambda: "5"
    watchdog.hw_pointer = dead.hw_pointer
    watchdog.is_running = lambda _c: True
    watchdog.recover = dead.recover
    watchdog.card_name = lambda: "fake-card"
    watchdog.active_profile = lambda _n: "output:analog-stereo+input:mono-fallback"
    gave_up = []
    try:
        dog = watchdog.CaptureWatchdog(on_give_up=lambda: gave_up.append(1))
        dog.start()
        time.sleep(35)
        dog.stop()
    finally:
        (watchdog.find_card, watchdog.hw_pointer, watchdog.is_running,
         watchdog.recover, watchdog.card_name, watchdog.active_profile) = original
    ok = dead.recoveries <= watchdog.MAX_ATTEMPTS and bool(gave_up)
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] unrecoverable stream is abandoned "
          f"({dead.recoveries} attempts, cap {watchdog.MAX_ATTEMPTS}, gave_up={bool(gave_up)})")

    # Real hardware read path must work on this machine.
    card = watchdog.find_card()
    ok = card is not None
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] Wave:3 located by USB id: card {card}")

    if card is not None:
        healthy, message = watchdog.check_once()
        results.append(healthy)
        print(f"  [{'PASS' if healthy else 'FAIL'}] live health check: {message}")

    print()
    good = all(results)
    print(f"ALL PASS ({sum(results)}/{len(results)})" if good
          else f"FAILURES: {len(results) - sum(results)} of {len(results)}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
