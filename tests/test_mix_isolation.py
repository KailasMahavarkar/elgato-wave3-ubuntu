"""Prove Stream and Monitor carry genuinely independent per-channel levels.

Plays a tone into one channel sink, records both mix monitors at the same
time, and checks the tone lands only where the faders say it should. This
is the behaviour that makes the thing a Wave Link replacement rather than
just a pile of virtual sinks.
"""

import math
import struct
import subprocess
import sys
import wave

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import mixer  # noqa: E402

SCRATCH = "/tmp/claude-1000/-mnt-storage-codespace-code-orkait-elgato-wave3-ubuntu/136f542b-3bb8-4467-9663-92c4d84679ab/scratchpad"
TONE = f"{SCRATCH}/tone.wav"
RATE = 48000
FREQ = 440.0
SECONDS = 3


def make_tone():
    frames = bytearray()
    for i in range(RATE * SECONDS):
        v = int(28000 * math.sin(2 * math.pi * FREQ * i / RATE))
        frames += struct.pack("<hh", v, v)
    with wave.open(TONE, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


def rms(path):
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        if n == 0:
            return 0.0
        width = w.getsampwidth()
        data = w.readframes(n)
    if width != 2:
        return -1.0
    count = len(data) // 2
    vals = struct.unpack(f"<{count}h", data[: count * 2])
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals)) / 32768.0


def run_case(rt, channels, game, stream_vol, monitor_vol):
    for ch in channels:
        for mix in mixer.MIXES:
            rt.set_level(ch, mix, 0.0)
    rt.set_level(game, mixer.STREAM, stream_vol)
    rt.set_level(game, mixer.MONITOR, monitor_vol)

    s_out = f"{SCRATCH}/cap_stream.wav"
    m_out = f"{SCRATCH}/cap_monitor.wav"
    # stream.capture.sink is required to attach to a sink's monitor ports;
    # without it pw-record silently falls back to the default source.
    recs = [
        subprocess.Popen(
            ["timeout", str(SECONDS), "pw-record",
             "-P", "stream.capture.sink=true", "--target", target, out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for target, out in (
            (mixer.STREAM_SINK, s_out),
            (mixer.MONITOR_SINK, m_out),
        )
    ]
    player = subprocess.Popen(
        ["pw-play", "--target", game.sink_name, TONE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    player.wait(timeout=SECONDS + 5)
    for r in recs:
        r.wait(timeout=10)
    return rms(s_out), rms(m_out)


def main():
    make_tone()
    channels = mixer.load_channels()
    mixer.resolve_sources(channels)
    game = next(c for c in channels if c.ident == "game")

    rt = mixer.Runtime()
    found = rt.refresh()
    missing = [
        ch.playback_node(mix)
        for ch in channels for mix in mixer.MIXES
        if ch.playback_node(mix) not in found
    ]
    if missing:
        print("FAIL: loopback nodes missing:", missing[:4])
        return 1

    print(f"resolved {len(found)} wave3 nodes")

    probe = rt.set_level(game, mixer.STREAM, 0.5)
    reading = rt.get_level(game, mixer.STREAM)
    print(f"level control reachable: set={probe} readback={reading}\n")
    if not probe or reading is None:
        print("FAIL: cannot set loopback volume")
        return 1

    cases = [
        ("stream only  (stream=1.0 monitor=0.0)", 1.0, 0.0),
        ("monitor only (stream=0.0 monitor=1.0)", 0.0, 1.0),
        ("both         (stream=1.0 monitor=1.0)", 1.0, 1.0),
        ("neither      (stream=0.0 monitor=0.0)", 0.0, 0.0),
    ]

    results = []
    for label, sv, mv in cases:
        s, m = run_case(rt, channels, game, sv, mv)
        results.append((label, sv, mv, s, m))
        print(f"  {label}\n      stream rms={s:.4f}   monitor rms={m:.4f}")

    print()
    floor = 0.005
    signal = 0.05
    checks = [
        ("tone reaches Stream when only Stream is up", results[0][3] > signal),
        ("tone absent from Monitor when Monitor is down", results[0][4] < floor),
        ("tone reaches Monitor when only Monitor is up", results[1][4] > signal),
        ("tone absent from Stream when Stream is down", results[1][3] < floor),
        ("both mixes carry it when both are up", results[2][3] > signal and results[2][4] > signal),
        ("silence on both when both are down", results[3][3] < floor and results[3][4] < floor),
    ]
    ok = True
    for name, passed in checks:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    print()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
