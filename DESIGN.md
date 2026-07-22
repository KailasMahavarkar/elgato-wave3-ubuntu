# Wave:3 Control Panel - Design Contract

Status: **awaiting approval**. No visual code ships before this is signed off.

## The problem with what exists

Three stock `Adw.PreferencesPage`s with generic rows. Every control works, and the
whole thing is wrong for the job.

A preferences list is a **sequential** interface: one setting, then the next, read
top to bottom. A mixer is a **parallel** interface: you compare nine channels at a
glance, spot which one is clipping, and pull that fader. Those are opposite
information structures. Stacking faders vertically in a list destroys the one
property that makes a mixer usable - side-by-side comparison.

Nobody has shipped a horizontal-list mixer since 1975. The vertical strip is not
skeuomorphism, it is the correct encoding: level maps to height, so scanning a row
of strips is a single saccade instead of nine.

## Design intent (from `designer_resolve_intent`)

| Field | Resolved | Using |
|---|---|---|
| Personality | technical-developer | yes |
| Style | soft-ui | yes, restrained |
| Mode | dark | yes |
| Density | normal | **overridden to compact** |
| Colour mood | trust blue + single accent | yes |
| Emotional target | technical | yes |

### Documented deviations

**Density: normal → compact.** A mixer's value is simultaneous visibility. Nine
strips at web-comfortable density needs ~1600px before any strip is usable. Compact
puts all nine plus meters in ~980px. Pro-audio convention and information density
both point the same way.

**Meter colour zones exceed the "max 2 accent colours" rule.** Green/amber/red on a
level meter is not chrome, it is a data encoding, and it is the single most
universal convention in audio. Overriding it would make the app harder to read for
anyone who has touched a mixer. Mitigation: the *primary* encoding is bar height,
colour is secondary, which also satisfies "colour not sole state indicator".

**Industry `saas` was low-confidence and is ignored.** This is a desktop pro-audio
tool. SaaS layout conventions do not apply.

## Layout

Three views behind a view switcher, unchanged in scope, rebuilt in form.

### Mixer (primary view)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Wave:3        ( Mixer │ Microphone │ Effects )                 ─ □ ✕ │
├──────────────────────────────────────────────────────────────────────┤
│  STREAM MIX  ▐███████▌·······          MONITOR MIX  ▐█████▌·········  │  master meters
├──────────────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│ │MICROPHONE│ │ SYSTEM  │ │  MUSIC  │ │ BROWSER │ │  CHAT   │   ...    │
│ │  ● fx    │ │         │ │         │ │         │ │         │          │
│ │          │ │         │ │         │ │         │ │         │          │
│ │ ▍  ┃  ┃  │ │ ▍  ┃  ┃ │ │ ▍  ┃  ┃ │ │ ▍  ┃  ┃ │ │ ▍  ┃  ┃ │          │
│ │ ▍  ▓  ▓  │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │          │
│ │ ▍  ▓  ▓  │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │ │ ▍  ▓  ▓ │          │
│ │ ▍  ▓  ▓  │ │    ▓  ▓ │ │    ▓  ▓ │ │    ▓  ▓ │ │    ▓  ▓ │          │
│ │meter S  M│ │         │ │         │ │         │ │         │          │
│ │          │ │         │ │         │ │         │ │         │          │
│ │ -6   -12 │ │ 0    -3 │ │ -8   -8 │ │ -4   -4 │ │ 0    0  │          │  dB, tabular
│ │ [S]  [M] │ │[S]  [M] │ │[S]  [M] │ │[S]  [M] │ │[S]  [M] │          │  mute buttons
│ │   ⇄ link │ │  ⇄ link │ │  ⇄ link │ │  ⇄ link │ │  ⇄ link │          │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
└──────────────────────────────────────────────────────────────────────┘
```

One strip per channel. Inside each strip, left to right: **one** pre-fader level
meter (the channel's own signal), then **two** faders - Stream and Monitor. That
asymmetry is deliberate and correct: there is one signal but two independent
destinations, which is exactly what Wave Link's model is.

Horizontal scroll past the viewport width; strips never compress below legibility.

### Microphone

Hardware controls. Keeps the verified/guarded badge system - that distinction is
load-bearing trust information and must stay visible. Grouped as Gain, Monitoring,
Device, with the read-only device facts demoted to a footer.

### Effects

The rack as a signal chain, in signal order, reading left to right like the audio
actually flows - not four unrelated preference groups.

```
  capsule ──▶ ┌────────┐ ──▶ ┌────────┐ ──▶ ┌────────┐ ──▶ ┌────────┐ ──▶ mixes
              │  GATE  │     │   EQ   │     │  COMP  │     │ LIMIT  │
              │  ●on   │     │  ●on   │     │  ●on   │     │  ●on   │
              └────────┘     └────────┘     └────────┘     └────────┘
```

Selecting a stage reveals its controls below. Disabled stages dim to exactly 0.5
opacity (per gotchas) and the chain arrow greys - bypass is visible in the diagram,
not just in a switch.

## Colour

Dark only. A mixer is used in a dim room next to a bright preview; a light mixer is
a glare source. libadwaita dark tokens as the base so the app matches the system.

| Role | Value | Use |
|---|---|---|
| Surface | `@window_bg_color` | window |
| Strip | `@card_bg_color` | channel strip body |
| Strip raised | `mix(@card_bg_color, white, 4%)` | hovered strip |
| Accent | `@accent_bg_color` | fader handle, active toggle, focus ring |
| Meter safe | `oklch(0.72 0.17 150)` green | below -12 dBFS |
| Meter warn | `oklch(0.80 0.16 85)` amber | -12 to -3 dBFS |
| Meter peak | `oklch(0.63 0.22 27)` red | above -3 dBFS |
| Meter bed | `mix(@window_bg_color, black, 30%)` | unlit meter segments |
| Muted | `@warning_color` on the mute button | mute engaged |

Exactly one accent for interaction. Meter greens/ambers/reds are data, not chrome.

## Typography

| Use | Font | Size | Weight |
|---|---|---|---|
| Channel name | system sans | 11px, uppercase, 0.06em tracking | 700 |
| dB readout | system **monospace** | 12px | 500 |
| Section label | system sans | 10px uppercase | 600, dimmed |
| Body / controls | system sans | default | regular |

dB values are monospace and tabular so digits do not jitter while a fader moves.
This is the single highest-value typography decision in the whole app.

## Spacing

Varied by semantic context, not a uniform 24px (named anti-pattern).

| Context | Value |
|---|---|
| Inside a strip, between related controls | 4px |
| Between control clusters in a strip | 10px |
| Between strips | 8px |
| Strip padding | 12px |
| Between master bar and strip row | 16px |
| View padding | 18px |

## Motion

Restrained - "excessive animation" is on the never-use list.

| Element | Motion |
|---|---|
| Meter fall | 300ms linear decay; rise is instant (attack must be truthful) |
| Peak hold | 1200ms hold, then drop |
| Fader | none - follows the pointer exactly |
| Hover/press | 120ms ease-out background only |
| View switch | libadwaita default crossfade |

All transitions wrapped in `prefers-reduced-motion`; meter decay becomes instant
rather than animated when reduced motion is set.

## Meters - the honest part

Meters do not exist today. They are the biggest gap between this and a real mixer,
and they are what makes a fader worth having.

Implementation: one `pw-record` per metered node at 8 kHz mono s16, peak computed
per chunk, read through a `GLib` IO watch. ~16 KB/s and negligible CPU per channel.

**Risk:** ten extra capture streams in the graph. If that destabilises PipeWire or
audibly costs latency, meters get cut back to the two mix buses plus mic (three
streams) rather than shipped broken. This is stated up front because discovering it
after the UI depends on it would be expensive.

## Accessibility

From `ui_ux_get_checklist(accessibility)`, applied honestly to desktop:

- [ ] Focus ring on every interactive element - 2px accent, 2px offset
- [ ] Full keyboard reach: Tab between strips, arrows move the focused fader
- [ ] `prefers-reduced-motion` respected for meter decay and hovers
- [ ] Colour never the sole indicator - mute has an icon **and** a border change;
      meter level is height first, colour second
- [ ] Disabled state exactly 0.5 opacity
- [ ] Every icon-only button has a tooltip and an accessible label
- [ ] Meters marked as presentational; dB values carry the text for screen readers

Touch-target minimums are relaxed - this is pointer-and-keyboard desktop, not
mobile. Hit targets stay at or above 24×24px, which is the WCAG 2.2 AA desktop
target.

## Non-goals

- Light theme
- Drag-to-reorder strips or FX
- Skeuomorphic knobs, brushed metal, faux LEDs
- Any window chrome that is not libadwaita default

## Files

| File | Change |
|---|---|
| `wave3/style.css` | new - all styling, single source |
| `wave3/widgets.py` | new - `LevelMeter`, `Fader`, `ChannelStrip` |
| `wave3/meters.py` | new - peak reader |
| `wave3/mixerview.py` | rewritten to strips |
| `wave3/fxview.py` | rewritten to signal chain |
| `wave3/app.py` | header/switcher restructure, CSS load |
| `wave3/protocol.py`, `device.py`, `mixer.py`, `fx.py` | **untouched** - verified, no reason to disturb |

## Success criteria

1. Nine channels with meters and both faders visible at ≤1000px wide
2. Meters track audio with no visible stutter
3. Every existing control still reachable, nothing regressed
4. Full keyboard operation without a mouse
5. `tests/test_ui_race.py` and `tests/test_mix_isolation.py` still pass

---

# Amendment 1 - Deck view

Status: **approved in principle** (requested directly), built as specified below.

## Why in-app rather than an OpenDeck plugin

No OpenDeck install and no Stream Deck hardware on this machine, so a plugin
could not be run or verified even once. Untestable integration code is a guess
wearing a costume.

Mitigation: actions live in `wave3/deck.py` as a registry with no GTK import.
`deckview.py` renders them. An OpenDeck plugin, a global hotkey daemon, or an
MQTT bridge can later consume the same registry without the UI changing.

## Layout

Fourth view, tile grid. Sized for a glance and a stab, not for precision.

```
┌──────────────────────────────────────────────────────────────┐
│  MICROPHONE                                                  │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                 │
│  │   1    │ │   2    │ │   3    │ │   4    │                 │
│  │   🎤   │ │   ⛨   │ │   ⌁    │ │   🔇   │                 │
│  │ MIC    │ │CLIPGRD │ │LOW CUT │ │ DIM    │                 │
│  │ MUTE   │ │  ON    │ │  ON    │ │MONITOR │                 │
│  └────────┘ └────────┘ └────────┘ └────────┘                 │
│  EFFECTS                                                     │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                 │
│  │   5    │ │   6    │ │   7    │ │   8    │                 │
│  │  GATE  │ │   EQ   │ │ COMP   │ │ LIMIT  │                 │
│  └────────┘ └────────┘ └────────┘ └────────┘                 │
│  STREAM MIX                                                  │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                 │
│  │   9    │ │   0    │ │        │ │        │                 │
│  │ MUSIC  │ │ GAME   │ │ CHAT   │ │ PANIC  │                 │
│  └────────┘ └────────┘ └────────┘ └────────┘                 │
└──────────────────────────────────────────────────────────────┘
```

Tile: 132x104 minimum. Number badge top-left is the keyboard shortcut for the
first ten tiles. Icon centred, label beneath, state word under that.

## Tile states

| State | Treatment |
|---|---|
| Off / inactive | card background, dimmed icon, label at 0.6 opacity |
| On / engaged | accent fill, full-opacity icon, state word reads the engaged term |
| Danger engaged (panic) | `@error_bg_color` fill |
| Unavailable | 0.5 opacity, non-interactive, tooltip explains why |

Colour is never the only signal: every tile's third line spells the state in
words (`MUTED` / `LIVE`, `ON` / `OFF`).

## Action semantics

| Action | Type | Notes |
|---|---|---|
| Mic mute | toggle | hardware `/input_mute`, same guarded write path as the Microphone page |
| Clipguard, Low cut | toggle | hardware, guarded |
| Dim monitor | toggle | drops every Monitor fader by 20 dB, restores exact prior values on release |
| Gate / EQ / Comp / Limiter | toggle | filter-chain Bypass, live |
| Music / Game / Chat mute | toggle | Stream-mix mute for that channel only |
| Panic | toggle | mutes every channel on Stream except the mic, restores prior state |

Dim and Panic must be perfectly reversible - they capture prior state in memory
and restore it exactly, never a guessed default.

## Non-goals

- Editing which tiles appear (fixed set for now)
- Profiles / pages of tiles
- Actual Stream Deck hardware output
