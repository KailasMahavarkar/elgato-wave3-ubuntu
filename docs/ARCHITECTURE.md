# How wave3 works

Two separate paths: a **control** path over USB that changes settings on the microphone itself, and an **audio** path built entirely out of PipeWire nodes. Neither one needs a proprietary driver.

## Control path

```
╔═══════════════════════════════════════════════════════════════════════════╗
║  CONTROL PATH                                    USB interface 3, EP0     ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                           ║
║   wave3 app  ──── bRequest 0x85 read ───▶  ┌──────────────────┐           ║
║             ◀─── bRequest 0x05 write ────  │  Wave:3 firmware │           ║
║                   wIndex 0x3303            │  16-byte config  │           ║
║                                            └──────────────────┘           ║
║   gain · mute · clipguard · low cut · headphone vol · dial mode · LEDs     ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

The Wave:3 exposes a vendor interface (class `ff`, subclass `f0`) with no endpoints at all, so everything happens through control transfers on endpoint 0.

```
bmRequestType  0xA1 read / 0x21 write
bRequest       0x85 read / 0x05 write
wIndex         0x3303
wValue         0x0000 config (16B) | 0x0001 status (8B) | 0x000A version
```

`wIndex` is the interesting bit. The firmware only checks the `0x33` prefix, and the low byte has to name an interface the kernel considers unclaimed. Interface 3 fits, so `0x3303` gets through without detaching `snd-usb-audio`, which means your audio never drops while the app is talking to the device.

### The 16-byte config block

| Offset | Field | Type |
|---:|---|---|
| 0 | `/input_gain` | int16 LE Q8.8 dB, 0..40 |
| 4 | `/input_mute` | bool |
| 5 | `/clipguard_enable` | bool |
| 6 | `/lowcut_enable` | bool |
| 7 | `/headphone_volume` | int16 LE Q8.8 dB, -60..0 |
| 9 | `/headphone_mute` | bool |
| 10 | `/direct_monitor` | int16 LE Q8.8 percent |
| 12 | `/volume_select` | u8 enum, 1 MIC / 2 HP / 3 MIX |
| 13-15 | LED flags, gain lock | bool |

The full writeup, including how it was worked out, is in [`research/dump/PROTOCOL.md`](../research/dump/PROTOCOL.md).

### Why writing to your microphone is safe

Two offsets were confirmed by watching the hardware change them. The rest came from analysing Wave Link, which is good evidence but not proof, so every write is treated as a transaction:

1. read the current block
2. change one field
3. write it
4. read it back
5. if **any** byte outside that field moved, put the original block back and raise

The dot beside each control says which kind it is. Green means the device was seen changing that offset itself. Blue means it relies on the rollback above. Move a physical control and the matching row promotes itself to green for good.

The firmware-update (DFU) interface is never touched.

## Audio path

```
╔═══════════════════════════════════════════════════════════════════════════╗
║  AUDIO PATH                                     all PipeWire, no driver   ║
╚═══════════════════════════════════════════════════════════════════════════╝

  ┌── microphone ─────────────────────────────────────────────────┐
  │                                                               │
  │  capsule ──▶ gate ──▶ EQ ──▶ comp ──▶ limiter ──▶ wave3.fx.mic│
  │              └──────── LADSPA filter-chain ───────┘           │
  └───────────────────────────────────────────────┬───────────────┘
                                                  │
  ┌── applications ──────────────────────┐        │
  │                                      │        │
  │  game ─▶ ┐                           │        │
  │  music ─▶│                           │        │
  │  chat ──▶├─▶ wave3.ch.<name>  ───────┼────────┤
  │  browser▶│    (one null sink each)   │        │
  │  …      ─▶┘                          │        │
  └──────────────────────────────────────┘        │
                                                  │
                 every source fans out twice, with
                 an independent fader on each leg
                                                  │
                        ┌─────────────────────────┴─────────────────────────┐
                        │                                                   │
                        ▼                                                   ▼
          ┌───────────────────────────┐               ┌───────────────────────────┐
          │      wave3.streammix      │               │      wave3.monitormix     │
          │   what your audience hears│               │      what you hear        │
          └─────────────┬─────────────┘               └─────────────┬─────────────┘
                        │ .monitor                                  │
                        ▼                                           ▼
                  ╭───────────╮                             ╭───────────────╮
                  │    OBS    │                             │ Wave:3 phones │
                  ╰───────────╯                             ╰───────────────╯
```

That fan-out is the important part. One microphone and one set of apps, but **two completely independent destinations**. Turn the game down in your own headphones and your audience never knows. Mute your browser on the stream and you can still hear it. That asymmetry is what Wave Link is really for, and it is what this reproduces.

### Where each fader actually lives

Each channel strip in the mixer maps onto real PipeWire objects:

```
  ┌─ one channel strip ─────────────────────────────────────────────┐
  │                                                                 │
  │   ▁▃█  ◀── meter reads  wave3.ch.game.monitor                   │
  │                                                                 │
  │   ┃ STRM  ◀── fader sets volume on  wave3.play.game.stream      │
  │   ┃ MON   ◀── fader sets volume on  wave3.play.game.monitor     │
  │                                                                 │
  │   [M][M]  ◀── mutes the same two loopback nodes                 │
  │   ⇄ link  ◀── UI only: moves both faders together               │
  └─────────────────────────────────────────────────────────────────┘
```

A fader is not a software multiplier inside the app, it is the volume of a real PipeWire loopback node. Anything else on your system that changes that node (including this app's own Deck) shows up the next time the mixer page is drawn.

## The effects rack

Ubuntu builds PipeWire's `filter-chain` module without LV2 support, so it only knows `builtin` and `ladspa`. The rack is therefore LADSPA, using [LSP Plugins](https://lsp-plug.in):

| Stage | Plugin | Roughly equivalent to |
|---|---|---|
| Noise Gate | `gate_mono` | ReaGate |
| Equaliser | `para_equalizer_x16_mono` | ReaEQ, Elgato's EQ |
| Compressor | `compressor_mono` | ReaComp |
| Limiter | `limiter_mono` | - |

Everything applies live, with no restart and no glitch in your audio.

The EQ curve is computed from RBJ cookbook biquads, and each band's filter mode is pinned to APO (DR), which is exactly the filter those equations describe. So the curve on screen is the curve you are hearing, not a pretty approximation.

Voice mode replaces this rack with a six-stage chain driven by five plain controls: noise removal, de-ess, warmth, presence and leveling. It uses RNNoise for the noise stage when that plugin is installed, and a multiband spectral gate when it is not.

## The capture watchdog

The Wave:3 capture stream can get stuck. Every layer insists it is fine, and no audio arrives:

```
                    ┌──────────────┬───────────────────────┬──────────┐
                    │  reports     │  actually delivering  │  honest? │
  ┌─────────────────┼──────────────┼───────────────────────┼──────────┤
  │ USB / firmware  │  streaming   │      no packets       │    ✗     │
  │ ALSA substream  │  RUNNING     │      hw_ptr == 0      │    ✗     │
  │ PipeWire node   │  running     │      no periods       │    ✗     │
  │ meters          │  -90 dB      │      nothing          │    ✓ ish │
  └─────────────────┴──────────────┴───────────────────────┴──────────┘
                                                                 │
                       -90 dB is indistinguishable from a quiet room,
                       which is why this can go unnoticed for an hour
```

The one place the truth shows up is `/proc/asound`:

```
  healthy                          wedged
  ───────────────────────          ───────────────────────
  state    : RUNNING               state    : RUNNING      ← identical
  hw_ptr   : 89042  ▲ climbing     hw_ptr   : 0      ■ frozen
  avail_max: 1634                  avail_max: 0
```

So the watchdog watches `hw_ptr`, not the audio:

```
   every 0.5 s
        │
        ▼
   read hw_ptr ──── moved? ──yes──▶ healthy, reset timer
        │                                   ▲
        no                                  │
        │                                   │
        ▼                                   │
   stalled > 2 s?  ──no──────────────────────
        │
       yes
        ▼
   cycle card profile  ──▶  wait  ──▶  did hw_ptr move?
        ▲                                   │
        │                          ┌────yes─┴──no────┐
        │                          ▼                 ▼
        └── retry, backing off  recovered      3 attempts?
            0s · 5s · 20s        (tell user)         │
                                                    yes
                                                     ▼
                                            stop trying, say so
```

Backing off and then stopping matters: each profile cycle tears down every stream on that card, so an unrecoverable fault must not turn into an endless loop.

PipeWire would normally shake this off by suspending the idle device and reopening it. The WirePlumber rule shipped here turns suspend off to prevent a *different* problem, where the capsule suspends and then hands out digital silence, so that automatic recovery is not available. The watchdog fills the gap. It runs whenever the app is open and tells you when it fires.

## Tests

```bash
make test
```

| Suite | What it proves |
|---|---|
| `test_mix_isolation.py` | Stream and Monitor really are independent |
| `test_meters.py` | Every meter is reading actual audio |
| `test_ui_race.py` | One toggle gives one clean transition, no bouncing |
| `test_watchdog.py` | A stalled capture is spotted and recovered, a healthy one is left alone |
| `test_voice.py` | Every voice control moves the chain, stays in range, and bypasses at zero |
| `test_presets.py` | Every preset is in range and Reset really restores the defaults |

Most of these exist because something was quietly broken. Three separate bugs once made every meter read a confident `-90 dB`: `parecord`'s two-second default buffer, the capsule suspending and serving silence, and a sink named `wave3.monitor` producing a `wave3.monitor.monitor` source that PulseAudio cannot resolve by name. All three are covered now.
