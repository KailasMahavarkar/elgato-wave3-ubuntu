"""Voice mode: the control mapping must stay sane and the chain must be whole.

The five simple controls each drive several plugin parameters, so a mapping
mistake shows up as an effect that does nothing or one that is stuck on.
"""

import math
import sys

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import voice  # noqa: E402


def db(linear):
    return 20.0 * math.log10(linear) if linear > 0 else -99.0


def main():
    results = []

    print("=== chain is complete and ordered ===")
    stages = [n for n, _p, _l in voice.chain_stages(True)]
    expected = ["nr", "mbgate", "tone", "deess", "comp", "limit"]
    ok = stages == expected
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] with RNNoise: {stages}")

    fallback = [n for n, _p, _l in voice.chain_stages(False)]
    ok = "nr" not in fallback and "mbgate" in fallback
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] without RNNoise falls back: {fallback}")

    print("\n=== every control moves something, monotonically ===")
    for key, label, low, high, unit, _desc in voice.CONTROLS:
        low_vals = dict(voice.DEFAULTS)
        low_vals[key] = low
        high_vals = dict(voice.DEFAULTS)
        high_vals[key] = high
        a, b = voice.derive(low_vals), voice.derive(high_vals)
        changed = any(a[stage] != b[stage] for stage in a)
        results.append(changed)
        print(f"  [{'PASS' if changed else 'FAIL'}] {label} changes the chain")

    print("\n=== derived values stay inside plugin ranges ===")
    problems = []
    for key, _l, low, high, _u, _d in voice.CONTROLS:
        for value in (low, (low + high) / 2, high):
            vals = dict(voice.DEFAULTS)
            vals[key] = value
            d = voice.derive(vals)
            vad = d["nr"]["VAD Threshold (%)"]
            if not (0.0 <= vad <= 99.0):
                problems.append(f"{key}={value}: VAD {vad}")
            for stage in ("deess", "comp"):
                ratio = d[stage]["Ratio"]
                thr = d[stage]["Attack threshold (G)"]
                if not (1.0 <= ratio <= 100.0):
                    problems.append(f"{key}={value}: {stage} ratio {ratio}")
                if not (0.001 <= thr <= 1.0):
                    problems.append(f"{key}={value}: {stage} threshold {thr}")
            for port in ("Gain 1 (G)", "Gain 2 (G)"):
                gain = d["tone"][port]
                if not (0.01585 <= gain <= 63.0957):
                    problems.append(f"{key}={value}: tone {port} {gain}")
    ok = not problems
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] all derived values in range"
          + ("" if ok else f" -> {problems[:4]}"))

    print("\n=== zero settings bypass rather than process silently ===")
    off = dict(voice.DEFAULTS)
    off.update(noise=0.0, deess=0.0, leveling=0.0)
    d = voice.derive(off)
    ok = (d["deess"]["Bypass"] == 1.0 and d["comp"]["Bypass"] == 1.0
          and d["mbgate"]["Bypass"] == 1.0)
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] de-ess, comp and gate bypass at zero")

    print("\n=== the limiter is always on ===")
    for key, _l, low, high, _u, _d in voice.CONTROLS:
        vals = dict(voice.DEFAULTS)
        vals[key] = low
        if voice.derive(vals)["limit"].get("Bypass", 0.0) != 0.0:
            results.append(False)
            print(f"  [FAIL] limiter bypassed when {key} is at minimum")
            break
    else:
        results.append(True)
        print("  [PASS] limiter never bypassed")

    print("\n=== settings round trip through disk ===")
    original = voice.load_settings()
    probe = dict(original)
    probe["presence"] = 4.5
    voice.save_settings(probe)
    ok = abs(voice.load_settings()["presence"] - 4.5) < 1e-6
    voice.save_settings(original)
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] save/load preserves values")

    print("\n=== out-of-range saved values are clamped on load ===")
    voice.save_settings({"presence": 999.0, "noise": -50.0})
    loaded = voice.load_settings()
    ok = loaded["presence"] <= 6.0 and loaded["noise"] >= 0.0
    voice.save_settings(original)
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] clamped to "
          f"presence={loaded['presence']}, noise={loaded['noise']}")

    print()
    good = all(results)
    print(f"ALL PASS ({sum(results)}/{len(results)})" if good
          else f"FAILURES: {len(results) - sum(results)} of {len(results)}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
