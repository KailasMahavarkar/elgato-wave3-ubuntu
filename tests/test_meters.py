"""Every metered device must actually carry audio.

Three separate bugs made these read a confident -90 dB, which is worse than
an obviously broken meter because it looks like silence:

1. parecord defaults to a ~2 second buffer and delivers one burst per buffer.
   Fixed with --latency-msec.
2. The Wave:3 capsule suspends when idle and then serves digital silence
   rather than resuming. Fixed with a WirePlumber rule.
3. A sink named "wave3.monitor" produces the monitor source
   "wave3.monitor.monitor", which PulseAudio cannot resolve by name - capture
   silently yields zeros. Fixed by renaming the mix sinks.
"""

import math
import struct
import subprocess
import sys
import time

sys.path.insert(0, "/home/kai/orkait/elgato-wave3-ubuntu")

from wave3 import fx, meters, mixer  # noqa: E402

SCRATCH = "/tmp/claude-1000/-mnt-storage-codespace-code-orkait-elgato-wave3-ubuntu/136f542b-3bb8-4467-9663-92c4d84679ab/scratchpad"
TONE = f"{SCRATCH}/tone.wav"
RATE = 48000


def make_tone():
    import wave as wavemod
    frames = bytearray()
    for i in range(RATE * 3):
        v = int(28000 * math.sin(2 * math.pi * 440.0 * i / RATE))
        frames += struct.pack("<hh", v, v)
    with wavemod.open(TONE, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


def sample(reader, count=5, gap=0.12):
    reads = []
    for _ in range(count):
        time.sleep(gap)
        reads.append(reader.db)
    return reads


def with_tone(device, target, threshold=-30.0):
    r = meters.PeakReader(device)
    r.start()
    time.sleep(0.6)
    p = subprocess.Popen(
        ["pw-play", "--target", target, TONE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.9)
    reads = sample(r)
    p.terminate()
    p.wait(timeout=5)
    r.stop()
    return reads, sum(1 for x in reads if x > threshold)


def main():
    make_tone()
    channels = mixer.load_channels()
    mixer.resolve_sources(channels, fx.FX_SOURCE if fx.installed() else None)
    capsule = mixer.resolve_node(mixer.WAVE3_SOURCE_MATCH, "Audio/Source")

    runtime = mixer.Runtime()
    runtime.refresh()
    game = next(c for c in channels if c.ident == "game")
    for mix in mixer.MIXES:
        runtime.set_level(game, mix, 1.0)
        runtime.set_mute(game, mix, False)

    results = []

    print("=== channel strip meters ===")
    for channel in channels:
        if channel.is_mic:
            continue
        reads, steady = with_tone(f"{channel.sink_name}.monitor", channel.sink_name)
        ok = steady >= 4
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {channel.name:12s} "
              f"{max(reads):6.1f} dBFS, {steady}/5 steady")

    print("\n=== master bus meters ===")
    for mix in mixer.MIXES:
        reads, steady = with_tone(f"{mixer.MIX_SINK[mix]}.monitor", game.sink_name)
        ok = steady >= 4
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {mix:8s} "
              f"{max(reads):6.1f} dBFS, {steady}/5 steady")

    print("\n=== mic path (needs the capsule un-suspended) ===")
    r = meters.PeakReader(capsule)
    r.start()
    time.sleep(1.2)
    reads = sample(r, count=10)
    r.stop()
    live = any(x > -89 for x in reads)
    results.append(live)
    print(f"  [{'PASS' if live else 'FAIL'}] capsule carries room noise: "
          f"max {max(reads):6.1f} dBFS")
    if not live:
        print("         capsule is suspended - check "
              "~/.config/wireplumber/main.lua.d/51-wave3.lua")

    print()
    ok = all(results)
    print(f"ALL PASS ({sum(results)}/{len(results)})" if ok
          else f"FAILURES: {len(results) - sum(results)} of {len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
