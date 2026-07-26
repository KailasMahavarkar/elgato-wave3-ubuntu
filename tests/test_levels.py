"""The batched fader read must agree with the per-node one.

wpctl reports the cube root of a node's channelVolumes. Reading every fader
from a single pw-dump is roughly eight times faster than one wpctl call per
node, but only if that conversion is right: a wrong exponent would move every
fader in the mixer the first time the page synced, and nothing else would
notice.
"""

import sys
import time

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import mixer  # noqa: E402

TOLERANCE = 2e-3


def main():
    results = []
    runtime = mixer.Runtime()
    runtime.refresh()
    channels = mixer.load_channels()

    print("=== batched read agrees with per-node read ===")
    batched = runtime.get_levels(channels)
    single = {}
    for channel in channels:
        for mix in mixer.MIXES:
            reading = runtime.get_level(channel, mix)
            if reading is not None:
                single[(channel.ident, mix)] = reading

    if not single:
        print("  [SKIP] no wave3 topology present")
        return 0

    missing = [key for key in single if key not in batched]
    drift = [
        (key, batched[key][0], value[0])
        for key, value in single.items()
        if key in batched and abs(batched[key][0] - value[0]) > TOLERANCE
    ]
    muted = [
        key for key, value in single.items()
        if key in batched and batched[key][1] != value[1]
    ]

    ok = not missing and not drift and not muted
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {len(single)} faders match")
    for key, a, b in drift[:4]:
        print(f"        {key}: batched {a:.4f} vs wpctl {b:.4f}")
    for key in missing[:4]:
        print(f"        missing from batch: {key}")

    print("\n=== the batch is worth having ===")
    start = time.monotonic()
    runtime.get_levels(channels)
    batch_ms = (time.monotonic() - start) * 1000
    start = time.monotonic()
    for channel in channels:
        for mix in mixer.MIXES:
            runtime.get_level(channel, mix)
    single_ms = (time.monotonic() - start) * 1000

    faster = batch_ms < single_ms
    results.append(faster)
    print(f"  [{'PASS' if faster else 'FAIL'}] batched {batch_ms:.0f} ms "
          f"vs per-node {single_ms:.0f} ms")

    print("\n=== a missing topology degrades quietly ===")
    empty = mixer.Runtime().get_levels([])
    ok = empty == {}
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] no channels gives an empty mapping")

    print()
    good = all(results)
    print(f"ALL PASS ({sum(results)}/{len(results)})" if good
          else f"FAILURES: {len(results) - sum(results)} of {len(results)}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
