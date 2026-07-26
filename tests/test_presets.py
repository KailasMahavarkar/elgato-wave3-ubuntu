"""Presets must be applicable, in range, and Reset must be a true reset.

The last one is easy to break: changing a default in fx.py without changing
the matching "Default" preset makes Reset restore something that is not the
default, silently.
"""

import sys

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import eq, fx, presets  # noqa: E402


def main():
    rack = {e.ident: e for e in fx.build_rack()}
    results = []

    print("=== every preset value is a real port, in range, covering all controls ===")
    for ident, plist in presets.BY_EFFECT.items():
        effect = rack[ident]
        ports = {c.port: c for c in effect.controls}
        problems = []
        for preset in plist:
            for port, value in preset.controls.items():
                control = ports.get(port)
                if control is None:
                    problems.append(f"{preset.name}: unknown port {port!r}")
                elif not (control.minimum <= value <= control.maximum):
                    problems.append(
                        f"{preset.name}: {port}={value} outside "
                        f"[{control.minimum},{control.maximum}]"
                    )
            if preset.controls:
                missing = set(ports) - set(preset.controls)
                if missing:
                    problems.append(f"{preset.name}: does not set {sorted(missing)}")
        ok = not problems
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {ident:6s} {len(plist)} presets"
              + ("" if ok else f" -> {problems}"))

    print("\n=== EQ presets cover all six bands with valid values ===")
    problems = []
    for preset in presets.EQUALISER:
        if len(preset.bands) != len(eq.DEFAULT_BANDS):
            problems.append(f"{preset.name}: {len(preset.bands)} bands")
            continue
        for kind, frequency, gain, q in preset.bands:
            if kind not in eq.TYPE_NAMES:
                problems.append(f"{preset.name}: bad filter type {kind}")
            if not (eq.FREQ_MIN <= frequency <= eq.FREQ_MAX):
                problems.append(f"{preset.name}: frequency {frequency}")
            if not (eq.GAIN_MIN <= gain <= eq.GAIN_MAX):
                problems.append(f"{preset.name}: gain {gain}")
            if not (eq.Q_MIN <= q <= eq.Q_MAX):
                problems.append(f"{preset.name}: Q {q}")
    ok = not problems
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {len(presets.EQUALISER)} EQ presets"
          + ("" if ok else f" -> {problems}"))

    print("\n=== a gate never closes above where it opens ===")
    problems = []
    for preset in presets.GATE:
        open_db = preset.controls["Curve threshold (G)"]
        close_db = preset.controls["Hysteresis threshold (G)"]
        if close_db > open_db:
            problems.append(f"{preset.name}: close {close_db} above open {open_db}")
    ok = not problems
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] hysteresis ordering"
          + ("" if ok else f" -> {problems}"))

    print("\n=== Reset restores the actual defaults ===")
    for ident in ("gate", "comp", "limit"):
        ok = presets.matches(rack[ident], presets.default_for(ident))
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {ident:6s} Default == build_rack()")
    ok = presets.matches(rack["eq"], presets.default_for("eq"), eq.build_bands())
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] eq     Default == build_bands()")

    print("\n=== apply then identify round trip ===")
    effect = rack["comp"]
    presets.apply_to_effect(effect, presets.COMPRESSOR[3])
    named = presets.identify(effect) == presets.COMPRESSOR[3].name
    presets.apply_to_effect(effect, presets.default_for("comp"))
    back = presets.identify(effect) == "Default"
    effect.controls[1].default = 7.77
    custom = presets.identify(effect) is None
    ok = named and back and custom
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] apply -> identify -> reset -> custom")

    print("\n=== saved values outside a narrowed range are clamped ===")
    # Ranges have tightened between releases (ratio was 1..100, release was
    # 0..5000). A config written by an older version must not push an illegal
    # value into the plugin or draw a handle off the end of the track.
    fresh = fx.build_rack()
    stale = {
        "comp": {"enabled": True, "controls": {"Ratio": 64.0,
                                               "Release time (ms)": 4000.0,
                                               "Makeup gain (G)": -99.0}},
    }
    fx.apply_state(fresh, stale)
    comp = next(e for e in fresh if e.ident == "comp")
    out = [(c.port, c.default, c.minimum, c.maximum) for c in comp.controls
           if not (c.minimum <= c.default <= c.maximum)]
    ok = not out
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] stale config clamped into range"
          + ("" if ok else f" -> {out}"))

    bands = eq.build_bands()
    presets.apply_to_bands(bands, presets.EQUALISER[2])
    eq_named = presets.identify(rack["eq"], bands) == presets.EQUALISER[2].name
    results.append(eq_named)
    print(f"  [{'PASS' if eq_named else 'FAIL'}] EQ apply -> identify")

    print()
    good = all(results)
    print(f"ALL PASS ({sum(results)}/{len(results)})" if good
          else f"FAILURES: {len(results) - sum(results)} of {len(results)}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
