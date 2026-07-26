"""Quick-action registry for the Deck view.

Free of any GTK import, so the same action set can be driven by another front
end. Reversible actions (Dim, Panic) capture the exact prior state in memory
and restore it rather than writing a guessed default.
"""

from dataclasses import dataclass, field

TOGGLE = "toggle"
DANGER = "danger"

MIC = "Microphone"
EFFECTS = "Effects"
STREAM = "Stream mix"


@dataclass
class Action:
    ident: str
    label: str
    icon: str
    group: str
    kind: str = TOGGLE
    on_word: str = "ON"
    off_word: str = "OFF"
    tooltip: str = ""
    is_active: object = None
    set_active: object = None
    available: object = None

    def active(self):
        try:
            return bool(self.is_active()) if self.is_active else False
        except Exception:
            return False

    def enabled(self):
        try:
            return bool(self.available()) if self.available else True
        except Exception:
            return False

    def toggle(self):
        self.set_active(not self.active())


class DeckState:
    """Owns the reversible bulk actions.

    Dim and Panic both restore prior values, so those values are held here
    rather than recomputed.
    """

    DIM_DB = 20.0

    def __init__(self, mixer_module, mixer_runtime, channels):
        self.mixer = mixer_module
        self.runtime = mixer_runtime
        self.channels = channels
        self._dim_levels = None
        self._panic_mutes = None

    # -- dim monitor ------------------------------------------------------

    @property
    def dimmed(self):
        return bool(self._dim_levels)

    # A restore is only correct if the channel still sits where dim put it.
    # Compared with a tolerance because wpctl reports two decimal places.
    RESTORE_TOLERANCE = 0.02

    def set_dimmed(self, dim):
        if dim == self.dimmed and not (dim and self._dim_levels is None):
            return
        if dim:
            captured = {}
            factor = 10.0 ** (-self.DIM_DB / 20.0)
            for ch in self.channels:
                reading = self.runtime.get_level(ch, self.mixer.MONITOR)
                if reading is None:
                    # No prior level to record; a guessed fallback would be
                    # written back as the restore value on release.
                    continue
                linear = reading[0]
                dimmed = linear * factor
                if self.runtime.set_level(ch, self.mixer.MONITOR, dimmed):
                    captured[ch.ident] = (linear, dimmed)
            self._dim_levels = captured
        else:
            for ch in self.channels:
                entry = self._dim_levels.get(ch.ident)
                if entry is None:
                    continue
                original, applied = entry
                reading = self.runtime.get_level(ch, self.mixer.MONITOR)
                if reading is not None and abs(reading[0] - applied) > self.RESTORE_TOLERANCE:
                    # Moved while dimmed, so the user's newer value wins.
                    continue
                self.runtime.set_level(ch, self.mixer.MONITOR, original)
            self._dim_levels = None

    # -- panic ------------------------------------------------------------

    @property
    def panicked(self):
        return bool(self._panic_mutes)

    def set_panicked(self, panic):
        if panic == self.panicked and not (panic and self._panic_mutes is None):
            return
        if panic:
            captured = {}
            for ch in self.channels:
                if ch.is_mic:
                    continue
                reading = self.runtime.get_level(ch, self.mixer.STREAM)
                if reading is None:
                    # No prior mute state to record; guessing "was unmuted"
                    # would un-mute a deliberately muted channel on release.
                    continue
                captured[ch.ident] = reading[1]
                self.runtime.set_mute(ch, self.mixer.STREAM, True)
            self._panic_mutes = captured
        else:
            for ch in self.channels:
                if ch.ident not in self._panic_mutes:
                    continue
                reading = self.runtime.get_level(ch, self.mixer.STREAM)
                if reading is not None and not reading[1]:
                    # Un-muted while panicked, so the user already overrode it.
                    continue
                self.runtime.set_mute(
                    ch, self.mixer.STREAM, self._panic_mutes[ch.ident]
                )
            self._panic_mutes = None


def _set_effect(fx_runtime, rack, effect, enabled):
    """Toggle an effect and persist the new rack state."""
    from . import fx as fx_module

    if not fx_runtime.set_enabled(effect, enabled):
        return False
    effect.enabled = enabled
    fx_module.save_state(fx_module.rack_to_state(rack))
    return True


def _channel_mute_action(mixer_module, runtime, channel, icon):
    def is_muted():
        reading = runtime.get_level(channel, mixer_module.STREAM)
        return bool(reading[1]) if reading else False

    def set_muted(value):
        runtime.set_mute(channel, mixer_module.STREAM, value)

    return Action(
        ident=f"mute.{channel.ident}",
        label=channel.name,
        icon=icon,
        group=STREAM,
        on_word="MUTED",
        off_word="LIVE",
        tooltip=f"Mute {channel.name} on the Stream mix only",
        is_active=is_muted,
        set_active=set_muted,
    )


CHANNEL_ICONS = {
    "music": "audio-headphones-symbolic",
    "game": "applications-games-symbolic",
    "chat": "user-available-symbolic",
    "browser": "web-browser-symbolic",
    "system": "computer-symbolic",
    "sfx": "audio-speakers-symbolic",
}

DECK_CHANNELS = ("music", "game", "chat", "browser")


def build_actions(device_api, mixer_module, mixer_runtime, channels,
                  fx_runtime=None, rack=None):
    """Assemble every quick action available in the current configuration.

    device_api exposes read()/write(path, value) against the hardware config
    block and is injected rather than imported so the deck stays testable.
    """
    actions = []
    state = DeckState(mixer_module, mixer_runtime, channels)

    if device_api is not None:
        for path, label, icon, on_word, off_word in (
            ("/input_mute", "Mic", "audio-input-microphone-symbolic", "MUTED", "LIVE"),
            ("/clipguard_enable", "Clipguard", "security-high-symbolic", "ON", "OFF"),
            ("/lowcut_enable", "Low cut", "view-filter-symbolic", "ON", "OFF"),
        ):
            actions.append(Action(
                ident=f"dev{path}",
                label=label,
                icon=icon,
                group=MIC,
                on_word=on_word,
                off_word=off_word,
                tooltip=f"Hardware {path}",
                is_active=(lambda p=path: device_api.read(p)),
                set_active=(lambda v, p=path: device_api.write(p, v)),
                available=device_api.ready,
            ))

    actions.append(Action(
        ident="dim",
        label="Dim monitor",
        icon="audio-volume-low-symbolic",
        group=MIC,
        on_word=f"-{int(DeckState.DIM_DB)} dB",
        off_word="NORMAL",
        tooltip=f"Drop every Monitor fader by {int(DeckState.DIM_DB)} dB, reversible",
        is_active=lambda: state.dimmed,
        set_active=state.set_dimmed,
    ))

    if fx_runtime is not None and rack:
        for effect in rack:
            actions.append(Action(
                ident=f"fx.{effect.ident}",
                label=effect.label,
                icon="applications-multimedia-symbolic",
                group=EFFECTS,
                tooltip=f"Bypass or enable {effect.label}",
                is_active=(lambda e=effect: e.enabled),
                set_active=(lambda v, e=effect: _set_effect(fx_runtime, rack, e, v)),
                available=lambda: fx_runtime.available,
            ))

    by_ident = {c.ident: c for c in channels}
    for ident in DECK_CHANNELS:
        channel = by_ident.get(ident)
        if channel is None:
            continue
        actions.append(_channel_mute_action(
            mixer_module, mixer_runtime, channel,
            CHANNEL_ICONS.get(ident, "audio-volume-high-symbolic"),
        ))

    actions.append(Action(
        ident="panic",
        label="Panic",
        icon="process-stop-symbolic",
        group=STREAM,
        kind=DANGER,
        on_word="ALL MUTED",
        off_word="READY",
        tooltip="Mute every channel except the mic on the Stream mix, reversible",
        is_active=lambda: state.panicked,
        set_active=state.set_panicked,
    ))

    return actions, state
