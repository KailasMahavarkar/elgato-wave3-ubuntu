<div align="center">

# 🎙️ wave3

**Elgato Wave:3 control panel and Wave Link replacement for Linux**

Hardware controls, a dual-mix mixer, a live EQ curve and an effects rack - native GTK4, no Wine, no Windows VM.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![GTK4](https://img.shields.io/badge/GTK-4.14-4A86CF?style=flat-square&logo=gtk&logoColor=white)](https://gtk.org)
[![libadwaita](https://img.shields.io/badge/libadwaita-1.5-7D4698?style=flat-square)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![PipeWire](https://img.shields.io/badge/PipeWire-1.0-3584E4?style=flat-square)](https://pipewire.org)
[![LSP Plugins](https://img.shields.io/badge/DSP-LSP%20LADSPA-2E9E4F?style=flat-square)](https://lsp-plug.in)

</div>

---

Elgato ships Wave Link for Windows and macOS only. The Wave:3 itself is a fine USB microphone on Linux out of the box, but everything that makes it worth the money - Clipguard, the low cut, the mic/PC balance dial, and the whole Stream/Monitor mixing model - lives in software you cannot run. This is that software, rebuilt natively.

The hardware protocol was recovered by reverse engineering, then verified against a real device. Nothing here is guessed: the field map is cross-checked against live hardware, and every write is transactional.

## ✨ What it does

| | |
|---|---|
| 🎛️ **Hardware control** | Gain, mute, Clipguard, low cut, headphone volume, mic/PC balance, dial mode, LEDs |
| 🎚️ **Dual-mix mixer** | Nine channels, independent Stream and Monitor faders per channel, exactly like Wave Link |
| 📊 **Live metering** | Per-channel and per-bus peak meters with decay and peak hold |
| 🎨 **EQ curve editor** | Six bands, drag to shape, named for how voices actually go wrong |
| 🔊 **Effects rack** | Gate, EQ, compressor, limiter as LADSPA inside PipeWire - no extra process |
| ⚡ **Deck** | Large quick-action tiles with keyboard shortcuts, for use mid-stream |
| 📹 **OBS ready** | The Stream Mix appears as a normal capture source |

## 🚀 Quick start

```bash
git clone https://github.com/KailasMahavarkar/elgato-wave3-ubuntu.git
cd elgato-wave3-ubuntu

sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                 lsp-plugins-ladspa pipewire-pulse

sudo make install-udev     # USB access without root
make install-mixer         # PipeWire topology
make install-fx            # effects rack
make run
```

Then in OBS add an **Audio Input Capture** and pick **Monitor of Wave:3 Stream Mix**.

## 🏗️ How it works

```
                    ┌─── hardware control ───┐
                    │  USB iface 3, EP0      │
                    │  bRequest 0x85 / 0x05  │
                    └────────────┬───────────┘
                                 │
  capsule ─▶ gate ─▶ EQ ─▶ comp ─▶ limiter ─▶ wave3.fx.mic
                                                    │
  apps ─▶ [wave3.ch.*] ──────────┬─────────────────┤
                                 │                  │
                    ┌────────────▼────┐   ┌────────▼─────────┐
                    │ wave3.streammix │   │ wave3.monitormix │
                    └────────┬────────┘   └────────┬─────────┘
                             ▼                     ▼
                            OBS              Wave:3 headphones
```

One signal, two destinations, independent levels. That asymmetry is the whole point of Wave Link and it is what this reproduces.

<details>
<summary><b>🔌 The USB control protocol</b></summary>

The Wave:3 exposes a vendor interface (class `ff`, subclass `f0`) with **zero endpoints** - everything happens through control transfers on EP0.

```
bmRequestType  0xA1 read / 0x21 write
bRequest       0x85 read / 0x05 write
wIndex         0x3303
wValue         0x0000 config (16B) | 0x0001 status (8B) | 0x000A version
```

`wIndex` is the interesting part. The firmware wants the `0x33` prefix, and the low byte must name an interface the kernel considers unclaimed. Interface 3 qualifies, so `0x3303` passes through without detaching `snd-usb-audio` - audio never drops.

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

Full writeup with methodology in [`research/dump/PROTOCOL.md`](research/dump/PROTOCOL.md).

</details>

<details>
<summary><b>🛡️ Why writes are safe</b></summary>

Offsets 4 and 7 were confirmed by watching the hardware change them. The rest came from static analysis, which is good evidence and not proof. So every write is a transaction:

1. read the current block
2. apply one field
3. write
4. read back
5. if **any** byte outside the target field moved, restore the original block and raise

The UI badges each control `verified` or `guarded` accordingly. Move a physical control and the matching row promotes itself to `verified` permanently.

The DFU interface is never touched.

</details>

<details>
<summary><b>🎚️ Effects rack details</b></summary>

Ubuntu builds `libpipewire-module-filter-chain` **without** LV2 support - `strings` on the module lists exactly `builtin` and `ladspa`. So the rack is LADSPA, using [LSP Plugins](https://lsp-plug.in):

| Stage | Plugin | Stands in for |
|---|---|---|
| Noise Gate | `gate_mono` | ReaGate |
| Equaliser | `para_equalizer_x16_mono` | ReaEQ / Elgato EQ |
| Compressor | `compressor_mono` | ReaComp |
| Limiter | `limiter_mono` | - |

Controls apply live via `pw-cli` param sets. No restart, no audio glitch.

The EQ curve is computed from RBJ cookbook biquads, and every band's filter mode is pinned to APO (DR) - the plain digital biquad those equations describe - so the drawn curve is the curve the plugin actually runs.

</details>

<details>
<summary><b>⚠️ Known limitations</b></summary>

- **No per-plugin gain reduction.** PipeWire publishes only LADSPA *input* control ports, so a plugin's own GR meter cannot be read. The compressor shows a measured `GAIN Δ` across the whole chain instead, labelled as such rather than dressed up as compressor GR.
- **Gate open/closed and limiter catching are derived** from measured level against your threshold. They ignore hysteresis and the attack/release envelope.
- **No RNNoise.** Not packaged for Ubuntu; needs a source build. It is LADSPA, so it drops into the chain once built.
- **No Windows VST support.** Would need Wine plus yabridge plus a separate host process.
- Channel set is fixed at nine; renaming means editing `~/.config/wave3/channels.json`.
- Dark theme only.

</details>

## 🧪 Tests

```bash
make test
```

| Suite | Proves |
|---|---|
| `test_mix_isolation.py` | Stream and Monitor carry genuinely independent levels |
| `test_meters.py` | Every metered device actually carries audio |
| `test_ui_race.py` | One toggle produces one visual transition, no bounce |

Three bugs made meters read a confident `-90 dB`, which is worse than an obviously broken meter because it looks like silence: `parecord`'s two-second default buffer, the capsule suspending and then serving digital silence, and a sink named `wave3.monitor` producing a `wave3.monitor.monitor` source that PulseAudio cannot resolve by name. All three are covered by `test_meters.py`.

## 🙏 Credits

- [LSP Plugins](https://lsp-plug.in) - the DSP doing the actual work
- [openwave](https://github.com/rikkichy/openwave) - proved the `wIndex=0x3303` transport on the Wave XLR
- [PipeWire](https://pipewire.org) and [WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/)

Not affiliated with or endorsed by Elgato or Corsair. "Elgato", "Wave:3" and "Wave Link" are trademarks of their respective owners. This project ships no Elgato code or assets.

## 📄 License

[MIT](LICENSE)
