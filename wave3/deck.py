"""Quick-action registry for the Deck view.

Deliberately free of any GTK import. The UI renders these; a future OpenDeck
plugin, hotkey daemon, or MQTT bridge can drive the identical set without the
UI existing at all.

Reversible actions (Dim, Panic) capture the exact prior state in memory and
restore it. They never write a guessed default back, because "restore" that
guesses is just a second mutation wearing a friendly name.
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

    Dim and Panic both need to put things back exactly as they were, so the
    prior values live here rather than being recomputed.
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
        return self._dim_levels is not None

    def set_dimmed(self, dim):
        if dim == self.dimmed:
            return
        if dim:
            captured = {}
            factor = 10.0 ** (-self.DIM_DB / 20.0)
            for ch in self.channels:
                reading = self.runtime.get_level(ch, self.mixer.MONITOR)
                linear = reading[0] if reading else 0.0
                captured[ch.ident] = linear
                self.runtime.set_level(ch, self.mixer.MONITOR, linear * factor)
            self._dim_levels = captured
        else:
            for ch in self.channels:
                if ch.ident in self._dim_levels:
                    self.runtime.set_level(
                        ch, self.mixer.MONITOR, self._dim_levels[ch.ident]
                    )
            self._dim_levels = None

    # -- panic ------------------------------------------------------------

    @property
    def panicked(self):
        return self._panic_mutes is not None

    def set_panicked(self, panic):
        if panic == self.panicked:
            return
        if panic:
            captured = {}
            for ch in self.channels:
                if ch.is_mic:
                    continue
                reading = self.runtime.get_level(ch, self.mixer.STREAM)
                captured[ch.ident] = reading[1] if reading else False
                self.runtime.set_mute(ch, self.mixer.STREAM, True)
            self._panic_mutes = captured
        else:
            for ch in self.channels:
                if ch.ident in self._panic_mutes:
                    self.runtime.set_mute(
                        ch, self.mixer.STREAM, self._panic_mutes[ch.ident]
                    )
            self._panic_mutes = None


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

    device_api exposes read()/write(field, value) against the hardware config
    block; it is passed in rather than imported so the deck stays testable.
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
                set_active=(lambda v, e=effect: (
                    setattr(e, "enabled", v), fx_runtime.set_enabled(e, v)
                )[0]),
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
