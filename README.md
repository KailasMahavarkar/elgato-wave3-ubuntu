<div align="center">

# 🎙️ wave3

**Your Elgato Wave:3, working properly on Linux**

Hardware controls, a real mixer, a live EQ and a full effects rack - native GTK4. No Wine, no Windows VM, no compromises.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![GTK4](https://img.shields.io/badge/GTK-4.14-4A86CF?style=flat-square&logo=gtk&logoColor=white)](https://gtk.org)
[![libadwaita](https://img.shields.io/badge/libadwaita-1.5-7D4698?style=flat-square)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![PipeWire](https://img.shields.io/badge/PipeWire-1.0-3584E4?style=flat-square)](https://pipewire.org)
[![LSP Plugins](https://img.shields.io/badge/DSP-LSP%20LADSPA-2E9E4F?style=flat-square)](https://lsp-plug.in)

<br>

<img src="docs/images/mixer.png" alt="The mixer: nine channel strips, each with its own Stream and Monitor fader and a live level meter" width="90%">

</div>

---

## 👋 What is this?

The Wave:3 is a lovely microphone, and on Linux you get maybe half of it. Plug it in and it works as a plain USB mic - but Clipguard, the low cut, the mic/PC balance dial, and the whole Stream/Monitor mixing model all live in **Wave Link**, which Elgato only ships for Windows and macOS.

This is that missing half, rebuilt as a native Linux app. It talks to the microphone over the same USB protocol Wave Link uses, and it builds the mixer out of PipeWire instead of a proprietary audio driver.

If you stream or record on Linux and you own a Wave:3, this should feel like the thing you expected to get in the box.

## ✨ What you get

|  |  |
|---|---|
| 🎛️ **Real hardware control** | Gain, mute, Clipguard, low cut, headphone volume, mic/PC balance, dial mode and the LED ring - the actual device settings, not software emulations |
| 🎚️ **Stream and Monitor mixes** | Nine channels, and every one has a separate fader for what your audience hears and what you hear. This is the whole point of Wave Link, and it works here |
| 📊 **Meters that mean something** | Per-channel and per-bus peak meters with proper decay and peak hold |
| 🎨 **An EQ you can actually use** | Six bands named for how voices really go wrong - Rumble, Boom, Boxy, Nasal, Presence, Air. Drag the dots |
| 🔊 **Gate, compressor, limiter** | Running as LADSPA plugins inside PipeWire itself, so there is no extra process and no added latency |
| ⚡ **A deck for live use** | Big tiles with number-key shortcuts for the things you need mid-stream, including a one-press panic mute |
| 📹 **Works with OBS** | Your Stream Mix shows up as an ordinary capture source |

## 🚀 Getting started

**The easy way** - grab the `.deb` from [Releases](https://github.com/KailasMahavarkar/elgato-wave3-ubuntu/releases):

```bash
sudo apt install ./wave3_1.0.1_all.deb
```

**From source:**

```bash
git clone https://github.com/KailasMahavarkar/elgato-wave3-ubuntu.git
cd elgato-wave3-ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                 lsp-plugins-ladspa pipewire-pulse
sudo make install-udev
```

Either way, finish up with:

```bash
systemctl --user restart wireplumber pipewire   # pick up the new rules
wave3 setup                                     # build the mixer and effects rack
wave3                                           # or launch it from your app menu
```

Then in OBS, add an **Audio Input Capture** and choose **Monitor of Wave:3 Stream Mix**. That is your finished mix, minus anything you have kept out of it.

> **Tip:** send apps to individual channels with `pavucontrol` (Playback tab) or from the app's own output picker, and each one gets its own pair of faders.

## 📸 A look around

<table>
<tr>
<td width="50%"><img src="docs/images/microphone.png" alt="The hardware page, with each control badged verified or guarded"><br><b>Microphone</b> - the real device settings. Each one is badged so you know how well understood it is</td>
<td width="50%"><img src="docs/images/eq.png" alt="The EQ curve editor with six draggable coloured band nodes"><br><b>Equaliser</b> - drag the dots. The curve you see is the curve the filter is running</td>
</tr>
<tr>
<td><img src="docs/images/compressor.png" alt="The compressor, showing a scrolling waveform with a draggable threshold line"><br><b>Compressor</b> - watch your voice go by and drag the threshold to suit</td>
<td><img src="docs/images/gate.png" alt="The noise gate, showing a threshold marker over a live level meter"><br><b>Noise gate</b> - set the threshold against your actual room, not a number</td>
</tr>
<tr>
<td><img src="docs/images/limiter.png" alt="The limiter, showing a ceiling marker over the output level"><br><b>Limiter</b> - your safety ceiling, so a laugh never clips the stream</td>
<td><img src="docs/images/deck.png" alt="The deck: large quick-action tiles with number-key shortcuts"><br><b>Deck</b> - press 1-9 for the things you need in a hurry</td>
</tr>
</table>

## 🏗️ How it fits together

There are two separate paths: a **control** path over USB that changes settings on the microphone itself, and an **audio** path built entirely out of PipeWire nodes.

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

That fan-out is the important part. One microphone and one set of apps, but **two completely independent destinations**. Turn the game down in your own headphones and your audience never knows; mute your browser on the stream and you can still hear it. That asymmetry is what Wave Link is really for, and it is what this reproduces.

<details>
<summary><b>Where each fader actually lives</b></summary>

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

So a fader is not a software multiplier inside the app - it is the volume of a real PipeWire loopback node. Anything else on your system that changes that node (including this app's own Deck) is reflected the next time the mixer page is shown.

</details>

<details>
<summary><b>🔌 How the hardware control works</b></summary>

The Wave:3 exposes a vendor interface (class `ff`, subclass `f0`) with no endpoints at all - everything happens through control transfers on endpoint 0.

```
bmRequestType  0xA1 read / 0x21 write
bRequest       0x85 read / 0x05 write
wIndex         0x3303
wValue         0x0000 config (16B) | 0x0001 status (8B) | 0x000A version
```

`wIndex` is the interesting bit. The firmware only checks the `0x33` prefix, and the low byte has to name an interface the kernel considers unclaimed. Interface 3 fits, so `0x3303` gets through without detaching `snd-usb-audio` - which means your audio never drops while the app is talking to the device.

The 16-byte config block:

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

The full writeup, including how it was worked out, is in [`research/dump/PROTOCOL.md`](research/dump/PROTOCOL.md).

</details>

<details>
<summary><b>🛡️ Why it is safe to let this write to your microphone</b></summary>

Two offsets were confirmed by watching the hardware change them. The rest came from analysing Wave Link, which is good evidence but not proof - so every write is treated as a transaction:

1. read the current block
2. change one field
3. write it
4. read it back
5. if **any** byte outside that field moved, put the original block back and raise

Controls are badged accordingly: **verified** means the device was seen changing that offset itself, **guarded** means it relies on the rollback above. Move a physical control and the matching row promotes itself to verified for good.

The firmware-update (DFU) interface is never touched.

</details>

<details>
<summary><b>🎚️ About the effects</b></summary>

Ubuntu builds PipeWire's `filter-chain` module without LV2 support - it only knows `builtin` and `ladspa`. So the rack is LADSPA, using the excellent [LSP Plugins](https://lsp-plug.in):

| Stage | Plugin | Roughly equivalent to |
|---|---|---|
| Noise Gate | `gate_mono` | ReaGate |
| Equaliser | `para_equalizer_x16_mono` | ReaEQ, Elgato's EQ |
| Compressor | `compressor_mono` | ReaComp |
| Limiter | `limiter_mono` | - |

Everything applies live - no restart, no glitch in your audio.

The EQ curve is computed from RBJ cookbook biquads, and each band's filter mode is pinned to APO (DR), which is exactly the filter those equations describe. So the curve on screen is the curve you are hearing, not a pretty approximation.

</details>

<details>
<summary><b>⚠️ Things it does not do</b></summary>

- **No per-plugin gain-reduction meter.** PipeWire only publishes LADSPA *input* ports, so a plugin's own GR reading is not readable. The compressor shows a measured `GAIN Δ` across the whole chain instead, and says so.
- **Gate and limiter indicators are derived** from your level versus your threshold, so they ignore hysteresis and attack/release timing. Close enough to set a threshold by, not a plugin readout.
- **No RNNoise** yet - it is not packaged for Ubuntu and needs building from source. It is LADSPA, so it will drop straight into the chain once built.
- **No Windows VST support.** That would mean Wine plus yabridge plus a separate host process.
- Nine fixed channels; renaming means editing `~/.config/wave3/channels.json`.
- Dark theme only.

</details>

## 🩺 If something seems wrong

```bash
wave3 doctor
```

It checks the capture stream, USB control and whether the topology is installed - and fixes a stalled microphone if it finds one.

<details>
<summary><b>The microphone goes silent and nothing is logged</b></summary>

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

PipeWire would normally shake this off by suspending the idle device and reopening it. The WirePlumber rule shipped here turns suspend off to prevent a *different* problem - where the capsule suspends and then hands out digital silence - so that automatic recovery is not available. Instead there is a watchdog: it reads `hw_ptr` twice a second and cycles the card profile when it stops moving. It runs whenever the app is open and tells you when it fires. If a few attempts do not help, it stops trying and says so rather than cycling your sound card forever.

To fix it by hand:

```bash
wave3 doctor
```

</details>

## 🧪 Tests

```bash
make test
```

| Suite | What it proves |
|---|---|
| `test_mix_isolation.py` | Stream and Monitor really are independent |
| `test_meters.py` | Every meter is reading actual audio |
| `test_ui_race.py` | One toggle gives one clean transition, no bouncing |
| `test_watchdog.py` | A stalled capture is spotted and recovered, a healthy one is left alone |

Most of these exist because something was quietly broken. Three separate bugs once made every meter read a confident `-90 dB`: `parecord`'s two-second default buffer, the capsule suspending and serving silence, and a sink named `wave3.monitor` producing a `wave3.monitor.monitor` source that PulseAudio cannot resolve by name. All three are covered now.

## 🙏 Credits

- [LSP Plugins](https://lsp-plug.in) - the DSP doing the real work
- [openwave](https://github.com/rikkichy/openwave) - proved the `wIndex=0x3303` transport on the Wave XLR
- [PipeWire](https://pipewire.org) and [WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/)

## 📄 Licence

[MIT](LICENSE), plus some plain-language notes on trademarks, interoperability and hardware risk.

Not affiliated with, authorised by or endorsed by Elgato or Corsair. "Elgato", "Wave:3" and "Wave Link" are their trademarks. No Elgato code or assets are included here.
