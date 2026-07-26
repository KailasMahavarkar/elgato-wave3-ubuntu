"""PipeWire mixer topology for the Wave:3.

Each channel gets a null sink and two loopbacks, one per mix, so Stream and
Monitor carry independent levels. The topology lives in a pipewire.conf.d
drop-in; levels are applied at runtime to the loopback playback nodes.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

CONF_NAME = "60-wave3-mixer.conf"
CONF_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "pipewire", "pipewire.conf.d",
)
CONF_PATH = os.path.join(CONF_DIR, CONF_NAME)

STATE_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "wave3"
)
CHANNELS_FILE = os.path.join(STATE_DIR, "channels.json")
LEVELS_FILE = os.path.join(STATE_DIR, "levels.json")

STREAM = "stream"
MONITOR = "monitor"
MIXES = (STREAM, MONITOR)

MIX_LABEL = {STREAM: "Stream", MONITOR: "Monitor"}

# Neither sink name may end in "monitor": PulseAudio derives its monitor
# source as "<sink>.monitor", so a sink named wave3.monitor yields
# wave3.monitor.monitor, which pactl and parecord cannot resolve.
STREAM_SINK = "wave3.streammix"
MONITOR_SINK = "wave3.monitormix"
MIX_SINK = {STREAM: STREAM_SINK, MONITOR: MONITOR_SINK}

WAVE3_SINK_MATCH = "alsa_output.usb-Elgato_Systems_Elgato_Wave_3"
WAVE3_SOURCE_MATCH = "alsa_input.usb-Elgato_Systems_Elgato_Wave_3"


@dataclass
class Channel:
    ident: str
    name: str
    source: str = ""
    levels: dict = field(default_factory=dict)

    @property
    def is_mic(self):
        return bool(self.source)

    @property
    def sink_name(self):
        return f"wave3.ch.{self.ident}"

    def capture_node(self, mix):
        return f"wave3.cap.{self.ident}.{mix}"

    def playback_node(self, mix):
        return f"wave3.play.{self.ident}.{mix}"


DEFAULT_CHANNELS = [
    Channel("mic", "Microphone", source=WAVE3_SOURCE_MATCH),
    Channel("system", "System"),
    Channel("music", "Music"),
    Channel("browser", "Browser"),
    Channel("chat", "Voice Chat"),
    Channel("game", "Game"),
    Channel("sfx", "SFX"),
    Channel("aux1", "Aux 1"),
    Channel("aux2", "Aux 2"),
]


def load_channels():
    try:
        with open(CHANNELS_FILE) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return [Channel(c.ident, c.name, c.source) for c in DEFAULT_CHANNELS]
    return [Channel(c["ident"], c["name"], c.get("source", "")) for c in raw]


def save_channels(channels):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CHANNELS_FILE, "w") as fh:
        json.dump(
            [{"ident": c.ident, "name": c.name, "source": c.source} for c in channels],
            fh, indent=2,
        )


def load_levels():
    try:
        with open(LEVELS_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_levels(levels):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LEVELS_FILE, "w") as fh:
        json.dump(levels, fh, indent=2)


def _null_sink(name, description):
    return f"""    {{  factory = adapter
        args = {{
            factory.name            = support.null-audio-sink
            node.name               = "{name}"
            node.description        = "{description}"
            media.class             = Audio/Sink
            audio.position          = [ FL FR ]
            object.linger           = true
            monitor.channel-volumes = true
            node.pause-on-idle      = false
        }}
    }}"""


def _loopback(channel, mix, description):
    """One channel feeding one mix.

    Application channels capture from their own sink's monitor, mic channels
    from a real source. Remixing stays enabled so the mono capsule is upmixed
    across both channels of the stereo mixes.
    """
    if channel.is_mic:
        capture_target = f'                target.object       = "{channel.source}"'
        # The capsule is mono. Declaring the playback side stereo makes the
        # loopback map channels positionally, so the voice lands on FL and FR
        # stays silent. Keeping it mono lets the sink upmix it to both sides.
        playback_position = "MONO"
    else:
        capture_target = (
            f'                target.object       = "{channel.sink_name}"\n'
            f"                stream.capture.sink = true"
        )
        playback_position = "FL FR"
    return f"""    {{  name = libpipewire-module-loopback
        args = {{
            node.description = "{description}"
            capture.props = {{
                node.name           = "{channel.capture_node(mix)}"
                node.description    = "{description}"
                media.class         = Stream/Input/Audio
{capture_target}
                node.dont-reconnect = false
            }}
            playback.props = {{
                node.name           = "{channel.playback_node(mix)}"
                node.description    = "{description}"
                media.class         = Stream/Output/Audio
                target.object       = "{MIX_SINK[mix]}"
                audio.position      = [ {playback_position} ]
                node.dont-reconnect = false
            }}
        }}
    }}"""


def _hardware_out(target):
    """Send the Monitor Mix to the Wave:3 headphone output.

    Kept in config rather than as a runtime pw-link so it survives a PipeWire
    restart and a device replug.
    """
    return f"""    {{  name = libpipewire-module-loopback
        args = {{
            node.description = "Monitor Mix to Wave:3"
            capture.props = {{
                node.name           = "wave3.out.capture"
                node.description    = "Monitor Mix to Wave:3"
                media.class         = Stream/Input/Audio
                target.object       = "{MONITOR_SINK}"
                stream.capture.sink = true
            }}
            playback.props = {{
                node.name           = "wave3.out.playback"
                node.description    = "Monitor Mix to Wave:3"
                media.class         = Stream/Output/Audio
                target.object       = "{target}"
                audio.position      = [ FL FR ]
            }}
        }}
    }}"""


def generate_config(channels, hardware_out=None):
    """Render the pipewire.conf.d drop-in for this channel set.

    Null sinks are factory objects and belong in context.objects; loopbacks
    are modules and must go in context.modules, or PipeWire logs "unknown
    object key 'name'" and skips them.
    """
    objects = [
        _null_sink(STREAM_SINK, "Wave:3 Stream Mix"),
        _null_sink(MONITOR_SINK, "Wave:3 Monitor Mix"),
    ]
    for ch in channels:
        if not ch.is_mic:
            objects.append(_null_sink(ch.sink_name, f"Wave:3 {ch.name}"))

    modules = [
        _loopback(ch, mix, f"{ch.name} to {MIX_LABEL[mix]}")
        for ch in channels
        for mix in MIXES
    ]
    if hardware_out:
        modules.append(_hardware_out(hardware_out))

    return f"""# Generated by wave3 - do not edit by hand.
#
# Channel sinks fan out to two mix sinks through per-mix loopbacks, so
# Stream and Monitor carry independent levels for every channel.
#
#   monitor of {STREAM_SINK}  -> capture this in OBS
#   {MONITOR_SINK}            -> route to the Wave:3 headphone output

context.objects = [
{chr(10).join(objects)}
]

context.modules = [
{chr(10).join(modules)}
]
"""


def resolve_node(match, media_class):
    """Find the exact node.name of a live node whose name contains match.

    target.object needs an exact node name, and the ALSA node name carries a
    device serial, so it must be looked up rather than guessed.
    """
    for obj in pw_dump():
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = obj.get("info", {}).get("props", {})
        name = props.get("node.name", "")
        if match in name and props.get("media.class") == media_class:
            return name
    return None


def resolve_sources(channels, fx_source=None):
    """Replace prefix matches on mic channels with real node names.

    With the effects rack installed the mic channel captures the rack output
    instead of the raw capsule.
    """
    unresolved = []
    for ch in channels:
        if not ch.is_mic:
            continue
        if fx_source:
            ch.source = fx_source
            continue
        exact = resolve_node(ch.source, "Audio/Source")
        if exact is None:
            unresolved.append(ch)
        else:
            ch.source = exact
    return unresolved


def install(channels, route_to_hardware=True, fx_source=None):
    unresolved = resolve_sources(channels, fx_source)
    hardware_out = None
    if route_to_hardware:
        hardware_out = resolve_node(WAVE3_SINK_MATCH, "Audio/Sink")
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CONF_PATH, "w") as fh:
        fh.write(generate_config(channels, hardware_out))
    return CONF_PATH, unresolved, hardware_out


def uninstall():
    if os.path.exists(CONF_PATH):
        os.remove(CONF_PATH)
        return True
    return False


def restart_pipewire():
    subprocess.run(
        ["systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"],
        check=True, capture_output=True, timeout=30,
    )


def pw_dump():
    """Parse pw-dump output.

    pw-dump can emit several top-level JSON arrays back to back rather than
    one document, so decode repeatedly and concatenate.
    """
    out = subprocess.run(
        ["pw-dump"], capture_output=True, text=True, timeout=10, check=True
    ).stdout
    decoder = json.JSONDecoder()
    objects = []
    idx = 0
    end = len(out)
    while idx < end:
        while idx < end and out[idx].isspace():
            idx += 1
        if idx >= end:
            break
        chunk, idx = decoder.raw_decode(out, idx)
        if isinstance(chunk, list):
            objects.extend(chunk)
        else:
            objects.append(chunk)
    return objects


class Runtime:
    """Runtime level control over the generated topology."""

    def __init__(self):
        self.nodes = {}

    def refresh(self):
        """Map node.name -> PipeWire object id for every wave3 node."""
        self.nodes = {}
        for obj in pw_dump():
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            props = obj.get("info", {}).get("props", {})
            name = props.get("node.name", "")
            if name.startswith("wave3.") or WAVE3_SINK_MATCH in name:
                self.nodes[name] = obj["id"]
        return self.nodes

    def node_id(self, name):
        if name not in self.nodes:
            self.refresh()
        return self.nodes.get(name)

    def _wpctl(self, *args):
        return subprocess.run(
            ["wpctl", *args], capture_output=True, text=True, timeout=5
        )

    def set_level(self, channel, mix, volume):
        """volume is 0.0 - 1.0 applied to the loopback playback node."""
        node = self.node_id(channel.playback_node(mix))
        if node is None:
            return False
        r = self._wpctl("set-volume", str(node), f"{max(0.0, min(1.0, volume)):.3f}")
        return r.returncode == 0

    def set_mute(self, channel, mix, muted):
        node = self.node_id(channel.playback_node(mix))
        if node is None:
            return False
        r = self._wpctl("set-mute", str(node), "1" if muted else "0")
        return r.returncode == 0

    def get_levels(self, channels):
        """Read every fader in one pw-dump instead of one wpctl call each.

        wpctl reports the cube root of the node's channelVolumes, so the
        conversion here is what keeps a batched read agreeing with get_level.
        """
        volumes = {}
        try:
            objects = pw_dump()
        except (subprocess.SubprocessError, OSError, ValueError):
            return {}
        for obj in objects:
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            info = obj.get("info") or {}
            name = (info.get("props") or {}).get("node.name", "")
            if not name.startswith("wave3.play."):
                continue
            for entry in (info.get("params") or {}).get("Props") or []:
                if "channelVolumes" not in entry:
                    continue
                channel_volumes = entry.get("channelVolumes") or [0.0]
                volumes[name] = (max(channel_volumes) ** (1.0 / 3.0),
                                 bool(entry.get("mute")))
                break

        out = {}
        for channel in channels:
            for mix in MIXES:
                reading = volumes.get(channel.playback_node(mix))
                if reading is not None:
                    out[(channel.ident, mix)] = reading
        return out

    def get_level(self, channel, mix):
        node = self.node_id(channel.playback_node(mix))
        if node is None:
            return None
        r = self._wpctl("get-volume", str(node))
        if r.returncode != 0:
            return None
        parts = r.stdout.split()
        muted = "[MUTED]" in r.stdout
        for token in parts:
            try:
                return float(token), muted
            except ValueError:
                continue
        return None

    def wave3_sink(self):
        for name in self.refresh():
            if WAVE3_SINK_MATCH in name:
                return name
        return None

    def route_monitor_to_hardware(self):
        """Send the Monitor Mix to the Wave:3 headphone output."""
        target = self.wave3_sink()
        if target is None:
            return False
        r = subprocess.run(
            ["pw-link", f"{MONITOR_SINK}:monitor_FL", f"{target}:playback_FL"],
            capture_output=True, text=True, timeout=5,
        )
        r2 = subprocess.run(
            ["pw-link", f"{MONITOR_SINK}:monitor_FR", f"{target}:playback_FR"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r2.returncode == 0


def have_tools():
    return {t: shutil.which(t) is not None for t in ("pw-dump", "wpctl", "pw-link", "pactl")}
