# Elgato Wave:3 (0fd9:0070) vendor-control protocol

Recovered by static analysis of `WaveAPI` (Mach-O universal, x86_64 slice) from Elgato Wave Link for macOS.
Every offset below comes from a static initializer that builds a `LWT::PackedStructView` table; the code
address of each write is cited. Nothing here is inferred from guessing byte patterns.

Binary: `.../WaveAPI.framework/Versions/A/WaveAPI`
x86_64 slice: fat offset `16384`, size `13450672`. All addresses below are file/vaddr offsets **inside that slice**.

The whole device model lives in one translation unit, `Wave3Device.cpp`:

| Symbol | vaddr | Meaning |
|---|---:|---|
| `LWT::Wave3Device::open(bool)` | `0x00b16120` | entry point, loads the API table |
| `__GLOBAL__sub_I_Wave3Device.cpp` | `0x00b16230` | static ctor, builds every table below |
| `LWT::Wave3::known_apis` | `0x00c5bdc0` | 3 x {version, span<PackedStructView>} |
| `LWT::Wave3::defaultAudioConf` | `0x00c750b8` | `{0x0fd9, 0x0070}` |
| `LWT::Wave3::defaultDfuConf` | `0x00c750d0` | `{0x0fd9, 0x0071}` |
| `LWT::Wave3::APIv5::Minor4::api` | `0x00c75290` | 3 blocks |
| `LWT::Wave3::APIv5::Minor3::api` | `0x00c75378` | 3 blocks |
| `LWT::Wave3::APIv5::Minor2::api` | `0x00c75460` | 3 blocks |

Product-ID proof: `0x00b1697f  mov dword [rbp - 0xdf0], 0x700fd9` immediately followed by
`0x00b16989  lea rdi, [0x00c750b8]` (= `LWT::Wave3::defaultAudioConf`) and a call to
`LewittDeviceConf::LewittDeviceConf(initializer_list<pair<u16,u16>>)` with `edx = 1`.
The pair decodes little-endian as `vid = 0x0fd9, pid = 0x0070`. The DFU conf right after is `0x0fd9:0x0071`.

---

## 1. Transport (confirms the working Linux transport)

`Wave3Device::open` tail-calls `LegacyWaveDevice::open` (`0x00b16131`), which calls
`VendorUSBLewittDeviceBackend::setBackendType(2)` (`0x0058ed87: mov esi, 2`).
In `setBackendType` (`0x0058edb0`), `esi == 2` selects
`LWT::LegacyUAC1VendorUSBBackendStrategy` (`0x0058ee9d  lea rcx, vtable_for_LWT::LegacyUAC1VendorUSBBackendStrategy`)
and logs the literal `"LegacyUAC1 backend"`. So the Wave:3 does use the `LWT34LegacyUAC1VendorUSBBackendStrategy`
class as expected.

| Operation | Code | bmRequestType | bRequest | wValue | wIndex | wLength |
|---|---|---|---|---|---|---|
| read | `0x00006910` | class / IN / interface (`0xA1`) | `0x85` | messageId | `0x3300 \| bInterfaceNumber` | block length |
| write | `0x00006980` | class / OUT / interface (`0x21`) | `0x05` | messageId | `0x3300 \| bInterfaceNumber` | block length |
| proto version probe | `0x000068c0` | class / IN / interface | `0x85` | `0x000A` | `0x3300 \| bIfNum` | `2` |

Evidence for the request codes:

```
LegacyUAC1VendorUSBBackendStrategy::read   @ 0x00006957   mov edx, 0x85     ; bRequest
                                              0x0000695c   mov r8d, 0x3300   ; wIndex base
                                              0x00006955   xor esi, esi      ; isVendorRequest = false -> CLASS request
LegacyUAC1VendorUSBBackendStrategy::write  @ 0x000069c7   mov edx, 5        ; bRequest
                                              0x000069cc   mov r8d, 0x3300
```

The low byte of `wIndex` is overwritten with the interface number by the backend:

```
LewittDeviceThesyconMacBackend::inCtrlRequest @ 0x00b86edc  mov r8b, byte [rbp + 0x18]  ; interface
                                                0x00b86eff  movzx r8d, r8w             ; -> wIndex = 0x33XX
```

That is exactly why `wIndex = 0x3303` works on Linux: `0x3300 | 3`.

`wValue` is the block's `messageId`, proven by `LWT::SessionAPI::Impl::Message::messageId()`:

```
0x000484f0  mov rax, qword [rdi + 8]     ; -> PackedStructView*
0x000484f8  movzx eax, byte [rax + 0x10] ; messageId  == wValue
```

`wLength` is `PackedStructView + 0x18`, proven in `SessionAPI::Impl::Impl` (`0x00042c10`):
`0x00042cc0  mov rbx, qword [r14 + r13 - 0x18]` then `operator new(rbx)` + `bzero`, where
`r14 = span.data + 0x30` and `r13 = i * 0x40`.

---

## 2. Recovered data structures (for reference / reproducibility)

`sizeof(LWT::PackedStructView) == 0x40`, proven by `std::array<PackedStructView,14>::~array()` at `0x0004b390`
destroying element vectors at `+0x368` and `+0x328` (stride `0x40`, element 0 at `+0x28`).

| PackedStructView offset | Type | Meaning | Proof |
|---:|---|---|---|
| `0x00` | `const char*` | block name (`/config`, `/status`, `/version`) | `0x00b178d8` |
| `0x08` | `size_t` | name length | `0x00b178e6` |
| `0x10` | `u8` | **messageId == wValue** | `Message::messageId` `0x000484f8` |
| `0x11` | `u8` | isReadable | `Message::isReadable` `0x00048508` |
| `0x12` | `u8` | isWritable | `Message::isWritable` `0x00048518` |
| `0x13` | `u8` | apiMajorVersion | `Message::apiMajorVersion` `0x00048528` |
| `0x18` | `size_t` | **block length in bytes == wLength** | `0x00042cc0` |
| `0x20` | `u8` | unknown flag (see note) | `0x00b17906` |
| `0x28` | `vector<Field>` | field list | `0x00042e1e` |

Note on `+0x20`: it is copied verbatim into the runtime `ViewDataPair` but no read of it was located.
Observed values: Wave:3 `/config` = 1, `/status` = 0, `/version` = 0; Wave XLR `/config` = 1, `/status` = 1,
`/version` = 0. **Meaning unknown - do not rely on it.**

`sizeof(LWT::PackedStructView::Field) == 0xb0 (176)`, proven twice: stack stride in the ctor, and the
division `sar rcx,4; imul rcx, 0x2e8ba2e8ba2e8ba3` (divide by 11 after >>4 = divide by 176) at `0x00042e0c`.

| Field offset | Type | Meaning |
|---:|---|---|
| `0x00` / `0x08` | `char* / size_t` | path string_view (e.g. `/headphone_volume`) |
| `0x10` | `u16` | **byte offset inside the block** |
| `0x12` | `u16` | **byte size** |
| `0x18` / `0x20` | `char* / size_t` | type code string (1 char) |
| `0x28` | `u8` | `q`: fractional bits. `b`: bit index inside the field |
| `0x2c` | `u8` | scale/valid flag (always 1 here; if 0 the getter throws) |
| `0x30` | `optional<Limits>` payload | `variant min` (value `+0x00`, index `+0x18`) |
| `0x50` | | `variant max` |
| `0x70` | | `variant step` |
| `0x90` | `u8` | optional engaged |
| `0x98` / `0xa0` | `char* / size_t` | human description |
| `0xa8` | `const Enum*` | enum descriptor or null |

`variant<int, unsigned, float, string, bool>` -> index `0` = int, `1` = unsigned, `2` = float, `3` = string, `4` = bool.

Type codes (jump table on `typecode[0]`, base `0x62 = 'b'`, in `Param::Impl::get` `0x00043860`):

| Code | Decode | Proof |
|---|---|---|
| `b` | bit `field[0x28]` of the field bytes -> bool | `0x00043965`..`0x0004398c` (`bt ecx, eax`) |
| `u` | unsigned LE integer of `size` bytes | `0x000438b0` |
| `q` | **signed** LE integer of `size` bytes, then `value / 2^field[0x28]` -> float | `0x00043cfa`..`0x00043d18` (`movsx`, `cvtsi2ss`, `divss`) |
| `c` | ASCII string of `size` bytes | string branch at `0x0004399b` |
| `n` | unsigned, then negated and scaled | `0x00043af0  cmp edx, 0x6e` |

Write path (`Param::Impl::set` `0x00044010`): clamp to `[min, max]`, quantize with
`round(x / step) * step` (`0x0004411a` `divss` -> `0x00044136` `roundss` -> `0x0004413c` `mulss`),
then `raw = (int)(x * (1 << fracbits))` (`0x000441b4`..`0x000441cb`).

---

## 3. Which API version the device speaks

`Wave3Device::open` at `0x00b16155` loads `LWT::Wave3::known_apis` with `ecx = 3` (span size).
Raw content of `0x00c5bdc0` (`{u16 major, u16 minor, pad}, {ptr, count}`):

| major.minor | table | blocks |
|---|---|---:|
| 5.4 | `0x00c75290` | 3 |
| 5.3 | `0x00c75378` | 3 |
| 5.2 | `0x00c75460` | 3 |

The running version is read by `LegacyUAC1VendorUSBBackendStrategy::protoVersion` (`0x000068c0`):
2-byte read of `wValue = 0x0A`, `[0] = major`, `[1] = minor`.
`BaseWaveDevice::Impl::lookupSessionAPI` (`0x0058d280`) then picks the matching entry.

**Read `/version` bytes 0 and 1 first and branch on them.** The 16-byte `/config` you observed means the
device is on **5.3 or 5.4** (5.2 has a 14-byte config).

---

## 4. `/config` block - wValue `0x0000`, 16 bytes, read + write

API v5.3 and v5.4 are byte-identical here (v5.4 table at `0x00c75290`, v5.3 at `0x00c75378`).

Header written at `0x00b178d8`..`0x00b17906`:
`name = "/config"`, `messageId = 0x00`, `readable = 1`, `writable = 1`, `apiMajor = 5`, `length = 0x10`.
Field vector built at `0x00b17bac` with `ecx = 0x0b` (11 fields).

| Off | Size | Type | Field | Encoding | Range (min, max, step) | Code |
|---:|---:|---|---|---|---|---|
| 0 | 2 | `q` frac 8 | `/input_gain` | int16 LE Q8.8, dB | 0.0, 40.0, 0.5 | `0x00b1744c` |
| 2 | 2 | - | *(unused / padding)* | - | - | - |
| 4 | 1 | `b` bit 0 | `/input_mute` | 0 / 1 | - | `0x00b17500` |
| 5 | 1 | `b` bit 0 | `/clipguard_enable` | 0 / 1 | - | `0x00b1757f` |
| 6 | 1 | `b` bit 0 | `/lowcut_enable` | 0 / 1 | - | `0x00b175f7` |
| 7 | 2 | `q` frac 8 | `/headphone_volume` | int16 LE Q8.8, dB | -60.0, 0.0, 0.5 | `0x00b1766f` |
| 9 | 1 | `b` bit 0 | `/headphone_mute` | 0 / 1 | - | `0x00b1771c` |
| 10 | 2 | `q` frac 8 | `/direct_monitor` | int16 LE Q8.8, percent | 0.0, 100.0, 5.0 | `0x00b17794` |
| 12 | 1 | `u` | `/volume_select` | enum, see below | 1, 3, 1 | `0x00b17841` |
| 13 | 1 | `b` bit 0 | `/all_leds_off` | 0 / 1 | - | `0x00b17a16` |
| 14 | 1 | `b` bit 0 | `/leds_flip` | 0 / 1 | - | `0x00b17a96` |
| 15 | 1 | `b` bit 0 | `/gain_lock` | 0 / 1 | - | `0x00b17b16` |

Descriptions straight out of the binary:

| Field | Description string |
|---|---|
| `/input_gain` | `Microphone gain in dB` |
| `/input_mute` | `Microphone mute` |
| `/clipguard_enable` | `Clipguard enable` |
| `/lowcut_enable` | `Low-cut filter enable` |
| `/headphone_volume` | `Headphone output in dB` |
| `/headphone_mute` | `Headphone output mute` |
| `/direct_monitor` | `Direct monitoring/playback mix in percent` |
| `/volume_select` | `Knob control select ENUM: MIC_SETTINGS_T_volume_select_t LIMITS: [ 1, 3, 1 ]` |
| `/all_leds_off` | `All LEDs are off` |
| `/leds_flip` | `Reverse the direction of LEDs and knob to use when mic is used upside down (e.g., on a boom arm).` |
| `/gain_lock` | `Ignore input volume change (SET_CUR) requests sent from the OS.` |

### `/volume_select` enum `MIC_SETTINGS_T_volume_select_t`

Built at `0x00b173c9`..`0x00b1740f` (entry stride `0x18`, `{char* name, size_t len, u32 value}`):

| Value | Name |
|---:|---|
| 1 | `MIC` |
| 2 | `HEADPHONE` |
| 3 | `MIX` |

### `/config` on API v5.2 (14 bytes, 9 fields)

Table at `0x00c75460`, field vector built at `0x00b1a7b7` with `ecx = 9`, `length = 14`.
Offsets 0..13 are identical to the above; `/leds_flip` (14) and `/gain_lock` (15) do not exist.

### Cross-check against your live device

`00 28 00 00 00 01 01 80 e8 00 00 00 01 00 00 01`

| Field | Raw | Decoded | In declared range |
|---|---|---|---|
| `/input_gain` | `0x2800` | 40.00 dB | yes (max) |
| `/input_mute` | `0x00` | false | yes |
| `/clipguard_enable` | `0x01` | true | yes |
| `/lowcut_enable` | `0x01` | true | yes |
| `/headphone_volume` | `0xE880` (-6016) | -23.50 dB | yes, matches your ALSA verification |
| `/headphone_mute` | `0x00` | false | yes |
| `/direct_monitor` | `0x0000` | 0.00 % | yes |
| `/volume_select` | `0x01` | `MIC` | yes |
| `/all_leds_off` | `0x00` | false | yes |
| `/leds_flip` | `0x00` | false | yes |
| `/gain_lock` | `0x01` | true | yes |

All 11 fields land inside their declared limits and all booleans are exactly 0/1. Independent corroboration
that the layout is right.

---

## 5. `/status` block - wValue `0x0001`, 8 bytes, read-only

Header at `0x00b17bb1`..`0x00b17bdf`: `messageId = 0x01`, `readable = 1`, `writable = 0`, `length = 8`.
Field vector at `0x00b17cd4`, `ecx = 2`. Identical across v5.2 / v5.3 / v5.4.

| Off | Size | Type | Field | Code |
|---:|---:|---|---|---|
| 0 | 4 | `u` (uint32 LE) | `/touch_pressed_ms` | `0x00b17bff` |
| 4 | 4 | `u` (uint32 LE) | `/touch_signal` | `0x00b17c6b` |

**This is not an audio meter.** It is the capacitive-touch state of the mute pad: how long the pad has been
pressed (ms) and the raw capacitive reading. Compare against `/touch_signal_thr/lower` and
`/touch_signal_thr/upper` from the `/version` block.

The Wave:3 exposes **no level-meter block** in any of its three API versions.

---

## 6. `/version` (device-info) block - wValue `0x000A`, read-only

Header at `0x00b1848b`..`0x00b184b9`: `messageId = 0x0a`, `readable = 1`, `writable = 0`.
Field vector at `0x00b18621`, `ecx = 0x12` (18 fields) for all three versions.

### API v5.4 - 54 bytes

| Off | Size | Type | Field | Code |
|---:|---:|---|---|---|
| 0 | 1 | `u` | `/api_version/major` | `0x00b17cf2` |
| 1 | 1 | `u` | `/api_version/minor` | `0x00b17d72` |
| 2 | 2 | `q` frac 8 | `/vbus_voltage` (int16 Q8.8 volts) | `0x00b17deb` |
| 4 | 1 | `u` | `/mic_type` (`PCB type: Schubert=1, Strauss=2`) | `0x00b17e6b` |
| 5 | 1 | `u` | `/hw_version_board` (`1....20`) | `0x00b17eeb` |
| 6 | 1 | `u` | `/bl/major` | `0x00b17f6b` |
| 7 | 1 | `u` | `/bl/minor` | `0x00b17feb` |
| 8 | 1 | `u` | `/bl/patch` | `0x00b18064` |
| 9 | 4 | `u` | `/bl/build` (uint32 LE) | `0x00b180dd` |
| 13 | 8 | `c` | `/bl/commit` (ASCII) | `0x00b18156` |
| 21 | 1 | `u` | `/fw/major` | `0x00b181d6` |
| 22 | 1 | `u` | `/fw/minor` | `0x00b18256` |
| 23 | 1 | `u` | `/fw/patch` | `0x00b182cf` |
| 24 | 4 | `u` | `/fw/build` (uint32 LE) | `0x00b18348` |
| 28 | 8 | `c` | `/fw/commit` (ASCII) | `0x00b183c1` |
| 36 | 14 | `c` | `/serial` (ASCII, also in the USB string descriptors) | `0x00b1843a` |
| 50 | 2 | `u` | `/touch_signal_thr/lower` (uint16 LE) | `0x00b184ef` |
| 52 | 2 | `u` | `/touch_signal_thr/upper` (uint16 LE) | `0x00b1856f` |

### API v5.3 and v5.2 - 52 bytes

Identical up to offset 35. Then:

| Off | Size | Field |
|---:|---:|---|
| 36 | 12 | `/serial` (12 ASCII chars, not 14) |
| 48 | 2 | `/touch_signal_thr/lower` |
| 50 | 2 | `/touch_signal_thr/upper` |

(v5.3 table at `0x00c753f8`, v5.2 at `0x00c754e0`; both declare `length = 52`.)

### Correcting the Wave XLR parser in `openwave/wavexlr/device.py`

The XLR is a **different** layout (`__GLOBAL__sub_I_WaveXLRDevice.cpp` at `0x00b25410`,
`LWT::WaveXLR::known_apis` at `0x00c5bee8`, API major 1, minors 2 / 3 / 4 / 7).

| device.py | Actual (XLR api 1.2 / 1.3, `/version` = 51 bytes) | Verdict |
|---|---|---|
| `api = data[0], data[1]` | `/api_version/major` @0, `/api_version/minor` @1 | correct |
| `fw = data[6], data[7], data[8]` | `/fw/major` @20, `/fw/minor` @21, `/fw/patch` @22. Offsets 6/7/8 are `/bl/minor`, `/bl/patch`, `/bl/build[0]` | **wrong** |
| `serial = data[27:47]` | `/serial` @35 len 12 (api 1.2/1.3) or @35 len 14 (api 1.4, block = 53 bytes). 27..34 is `/fw/commit` | **wrong** (picks up the FW commit hash as a prefix) |
| `CONFIG_LEN = 34` | api 1.3 / 1.4 `/config` = 34 bytes (api 1.2 = 29) | correct for 1.3+ |
| `METER_LEN = 10` | `/status` = 10 bytes | correct length |
| `read_meters -> left, right` | `/status` is `{/touch_pressed_ms @0 u32, /touch_signal @4 u32, /headphone_detected @8 u8, /gr_value_db @9 u8}` | **not a meter**, it is touch + gain-reduction |
| `OFF_GAIN=0, OFF_MUTE=4, OFF_HP_VOL=9, OFF_VOL_SELECT=14, OFF_LOW_Z=33` | `/input_gain` @0, `/input_mute` @4, `/headphone_volume` @9, `/volume_select` @14, `/low_impedance_enabled` @33 | all correct |

XLR gain limits are `0.0 .. 75.0 step 0.5` (not 0..40 like the Wave:3), same Q8.8 encoding.

---

## 7. Complete wValue selector map for the Wave:3

Exhaustive scan of every `mov dword [rip+X], imm32` in `__TEXT` whose target lands in the
`PackedStructView` header region, filtered to the `Wave3Device.cpp` table range `0x00c75260..0x00c75520`:

| Header addr | messageId (wValue) | readable | writable | apiMajor | Code |
|---|---:|---:|---:|---:|---|
| `0x00c752a0` | `0x00` | 1 | 1 | 5 | `0x00b178f1` |
| `0x00c752e0` | `0x01` | 1 | 0 | 5 | `0x00b17bca` |
| `0x00c75320` | `0x0a` | 1 | 0 | 5 | `0x00b184a4` |
| `0x00c75388` | `0x00` | 1 | 1 | 5 | `0x00b19066` |
| `0x00c753c8` | `0x01` | 1 | 0 | 5 | `0x00b19255` |
| `0x00c75408` | `0x0a` | 1 | 0 | 5 | `0x00b1937d` |
| `0x00c75470` | `0x00` | 1 | 1 | 5 | `0x00b1a60a` |
| `0x00c754b0` | `0x01` | 1 | 0 | 5 | `0x00b1a7d5` |
| `0x00c754f0` | `0x0a` | 1 | 0 | 5 | `0x00b1adcb` |

**Only `0x0000`, `0x0001` and `0x000A` exist for the Wave:3.** There are exactly 9 `PackedStructView`
objects in the TU (3 API versions x 3 blocks) and no others.

For contrast, other Lewitt/Elgato devices in the same binary do use more selectors
(e.g. Wave XLR api 1.7 at `0x00c75ac8` has 10 blocks with ids `0x00 0x01 0x02 0x03 0x04 0x05 0x06 0x16 0x17 0x18`),
but none of those tables is reachable from `Wave3::known_apis`.

Firmware update uses a separate path entirely: DFU class requests on PID `0x0071`
(`LWT::TLDFUBackend`, `DfuDevice::*`).

---

## 8. Which named paths the Wave:3 implements

Out of the 506 entries in `named_paths.txt`, the Wave:3 implements exactly **31** (API v5.3 / v5.4)
or **29** (API v5.2). Everything else belongs to Wave XLR, Wave XLR Pro, Wave XLR Dock, Wave DX / Neo /
Cornell, Wave 1, or the MK2 families.

| Block | wValue | Paths |
|---|---|---|
| `/config` | `0x00` | `/input_gain`, `/input_mute`, `/clipguard_enable`, `/lowcut_enable`, `/headphone_volume`, `/headphone_mute`, `/direct_monitor`, `/volume_select`, `/all_leds_off`, `/leds_flip`*, `/gain_lock`* |
| `/status` | `0x01` | `/touch_pressed_ms`, `/touch_signal` |
| `/version` | `0x0a` | `/api_version/major`, `/api_version/minor`, `/vbus_voltage`, `/mic_type`, `/hw_version_board`, `/bl/major`, `/bl/minor`, `/bl/patch`, `/bl/build`, `/bl/commit`, `/fw/major`, `/fw/minor`, `/fw/patch`, `/fw/build`, `/fw/commit`, `/serial`, `/touch_signal_thr/lower`, `/touch_signal_thr/upper` |

`*` = API v5.3 and v5.4 only.

Explicitly **not** present on the Wave:3 (they appear in `named_paths.txt` but belong to other devices):
`/p48_enable`, `/lowcut1_enabled`, `/lowcut2_enabled`, `/low_impedance_enabled`, `/mixer/crossfade`,
`/mixer/*`, `/dspfx/*`, `/xlr1/*`, `/xlr2/*`, every `*_color_rgb/*`, `/brightness`, `/background_brightness`,
`/status_brightness`, `/indicator_brightness_*`, `/mute_enabled`, `/gr_*`, `/headphone_detected`,
`/standalone*`, `/routing`, `/writeflash`, `/sample_rate_hz`.

Note the name traps: the Wave:3 uses `/clipguard_enable` and `/lowcut_enable` (no trailing `d`), while the
XLR family uses `/clipguard_enabled` / `/lowcut1_enabled` / `/lowcut2_enabled`. Also `/direct_monitor`
**is** the mixer crossfade on the Wave:3; `/mixer/crossfade` is a different device's path.

There is no separate LED-brightness field on the Wave:3. LED control is limited to
`/all_leds_off` (offset 13) and `/leds_flip` (offset 14).

---

## 9. Value encodings, summarized

| Field | Wire type | Conversion | Valid raw range |
|---|---|---|---|
| `/input_gain` | int16 LE @0 | `dB = raw / 256.0` | `0x0000` .. `0x2800` (0.0 .. 40.0 dB), step `0x0080` (0.5 dB) |
| `/headphone_volume` | int16 LE @7 | `dB = raw / 256.0` | `0xC400` (-60.0) .. `0x0000` (0.0), step `0x0080` |
| `/direct_monitor` | int16 LE @10 | `percent = raw / 256.0` | `0x0000` .. `0x6400` (0 .. 100 %), step `0x0500` (5 %) |
| `/vbus_voltage` | int16 LE @2 of `/version` | `volts = raw / 256.0` | read-only |
| booleans | u8, **bit 0** | `bool(byte & 1)` | write `0x00` / `0x01` |
| `/volume_select` | u8 @12 | enum | `1` = MIC, `2` = HEADPHONE, `3` = MIX |
| `/touch_pressed_ms`, `/touch_signal` | uint32 LE | raw | read-only |
| `/serial`, `/fw/commit`, `/bl/commit` | ASCII, fixed length | strip trailing NULs | read-only |

Gain is **not** a raw 0..0xFFFF value like the current XLR helper assumes; it is signed Q8.8 dB, and the
firmware quantizes to 0.5 dB. `direct_monitor` is percent in Q8.8, not 0..100 raw and not a float.

Safe write recipe (matches what the macOS app does):

1. read the 16-byte `/config` block (`bRequest 0x85`, `wValue 0x0000`)
2. clamp the new value into `[min, max]`
3. quantize: `v = round(v / step) * step`
4. encode: `raw = int(v * 256)` for `q` fields, `0`/`1` for `b` fields, raw enum for `u`
5. patch the bytes in place, write all 16 bytes back (`bRequest 0x05`, `wValue 0x0000`)

Never write a partial block: `Message::size()` always returns the full block length, so the firmware
expects `wLength == 16`.

---

## 10. Unknowns (explicitly not determined)

- `PackedStructView + 0x20` boolean. Copied around but no consumer located.
- `/config` bytes 2 and 3 are not covered by any field in any of the three API versions. Preserve them on
  read-modify-write; do not write anything into them.
- Whether the firmware accepts selectors beyond `0x00 / 0x01 / 0x0A`. The macOS driver never issues any
  other selector for this product, but the firmware may still answer them.
- The exact behaviour of `Field + 0x2c` beyond "must be non-zero or the getter throws".
