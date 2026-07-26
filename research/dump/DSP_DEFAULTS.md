# Wave Link DSP values recovered from the shipped application

Analysis of `Elgato Wave Link.app` 3.2.2.2896, x86_64 slice of
`Contents/MacOS/WaveLinkMacOS` (fat offset 16384, size 17794272).

Section map used throughout:

| Section | File offset | VA | Size |
|---|---|---|---|
| `__TEXT.__text` | `0x00002a90` | `0x100002a90` | `0x00ba3b39` |
| `__TEXT.__const` | `0x00baa5d0` | `0x100baa5d0` | `0x0005ea5b` |
| `__TEXT.__cstring` | `0x00c35110` | `0x100c35110` | `0x00069dba` |
| `__DATA_CONST.__const` | `0x00dee3e0` | `0x100dee3e0` | `0x00047250` |
| `__DATA.__data` | `0x00e9e2c0` | `0x100e9e2c0` | `0x0007ecad` |

VA equals file offset plus `0x100000000` for every section above.

## 1. Equalizer frequency zones - RECOVERED

Seven `float64` values, contiguous, zero-padded on both sides, at
`__DATA_CONST.__const 0x100dfb4a0`:

```
0x100dfb498          0.0      <- padding
0x100dfb4a0         20.0
0x100dfb4a8         80.0
0x100dfb4b0        300.0
0x100dfb4b8       1400.0
0x100dfb4c0       5000.0
0x100dfb4c8      12000.0
0x100dfb4d0      20000.0
0x100dfb4d8          0.0      <- padding
```

Seven boundaries describe six zones, matching the six band names in
`Resources/en.lproj/Localizable.strings` exactly:

| Zone | Range | Key | Elgato's own title and description |
|---|---|---|---|
| Rumble / Sub-bass | 20 - 80 Hz | `...frequency.rumble` | "Low End Rumble" - deep sounding noises often caused by mechanical influences |
| Boom / Warmth | 80 - 300 Hz | `...frequency.boom` | "Core Voices" - too much leads to boominess; too little makes the voice sound thin |
| Boxy | 300 - 1400 Hz | `...frequency.boxy` | "Room Sound" - balance carefully to avoid a boxy or hollow sound |
| Nasal | 1400 - 5000 Hz | `...frequency.nasal` | "Clarity" - vocals compete with other audio sources (e.g. game sound) in this range |
| Presence | 5000 - 12000 Hz | `...frequency.presence` | "Sibilance" - voices can sound harsh in this range; it can also be tamed with a de-esser |
| Air | 12000 - 20000 Hz | `...frequency.air` | "Air" - this range can help brighten the overall sound impression |

Found by scanning `__TEXT.__const`, `__DATA_CONST.__const` and `__DATA.__data`
for runs of six ascending `float64` values inside 20 - 20000. Exactly one
audio-plausible table matched; the other four hits
(`0x100bd5b48`, `0x100bd5b78`, `0x100bd5c08`, `0x100bd5c38`, values
20/24/32/40/48/64 and 72/80/96/128/144/192) are point-size or bitrate ladders,
not frequencies.

Note the naming is shifted relative to common audio usage: Elgato's "Presence"
is 5 - 12 kHz, which most engineers would call sibilance or brilliance, and
their "Nasal" (1.4 - 5 kHz) is what is usually called presence. Their own
descriptions are self-consistent with their boundaries: `presence.title` is
literally "Sibilance".

## 2. Exposed DSP parameter surface - RECOVERED

52 `dsp.*` keys in `Localizable.strings` (UTF-16). Grouped:

| Group | Keys | What it exposes |
|---|---:|---|
| `dsp.equalizer` | 30 | six bands; per band: frequency, gain, quality, active, type |
| `dsp.settings.advanced` | 4 | Ratio, Attack, Release (hidden behind "Advanced settings") |
| `dsp.compressor` | 3 | title, description, Makeup Gain |
| `dsp.expander` | 3 | title, description, `maximum.reduction` |
| `dsp.setting` | 2 | `weak`, `strong` |
| `dsp.lowCut`, `dsp.lowCutEnhanced` | 3 | Lowcut, Enhanced Lowcut |
| `dsp.clipguard` | 2 | Clipguard |
| `dsp.voiceTune` | 2 | Voice Tune |
| `dsp.general.threshold`, `dsp.gainReduction` | 2 | Threshold, Gain Reduction |

Filter types offered per band: `lowCut` (High Pass), `lowShelf`, `peak`,
`notch`, `highShelf`, `highCut` (Low Pass).

Two findings worth carrying over:

- Elgato uses an **expander**, not a gate, for noise reduction:
  "Reduces background noise by lowering the volume of quiet signals."
  An expander attenuates progressively rather than switching, which is why
  Wave Link does not chatter on quiet passages.
- Their compressor deliberately exposes only Threshold and Makeup Gain, with
  ratio, attack and release behind an Advanced disclosure.

## 3. Numeric defaults for compressor, expander, band gain and Q - NOT DETERMINED

Not recoverable from this binary by static inspection. What was ruled out:

- No static table of per-band default gain, Q, or filter type exists in
  `__TEXT.__const`, `__DATA_CONST.__const` or `__DATA.__data`. A scan for
  six-element `float64` runs inside a Q range of 0.1 - 10 returned only
  progress and opacity ladders (`0x100bafb50`, `0x100bb89b8`, `0x100bd5aa0`,
  `0x100bd5ad0`).
- `dsp.setting.weak` (`0x100c3fe40`) and `dsp.setting.strong` (`0x100c3fe20`)
  each have exactly one xref, at `0x1003e48c0` and `0x1003cf8a0`.
  Disassembly of both shows an `NSLocalizedString` lookup against table
  `Localizable` and nothing else. They are UI labels; the values they select
  are not adjacent.
- The zone table at `0x100dfb4a0` has **zero** rip-relative xrefs from
  `__TEXT.__text`, so it is reached through Swift metadata or a relocated
  pointer rather than a direct `lea`. Following that requires resolving Swift
  reflection metadata, which was not attempted.

The most likely explanation is that band defaults are constructed in Swift
initialisers with inline immediates, or the bands simply default to inactive
and flat, in which case there is no table to find.

## Method

```
scan __TEXT.__const, __DATA_CONST.__const, __DATA.__data
  for runs of 6 ascending float64 in [20, 20000]        -> zone table
  for runs of 6 float64 in [0.1, 10]                    -> no Q table
scan __TEXT.__text for rip-relative disp32 resolving to a target VA
  -> xrefs for the weak/strong strings and the zone table
```
