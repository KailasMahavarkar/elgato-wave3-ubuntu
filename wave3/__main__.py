"""Entry point and command-line setup.

No arguments launches the GUI. The subcommands install or remove the per-user
PipeWire topology and effects rack without needing the source-tree Makefile.
"""

import argparse
import os
import sys

from . import __version__


def _install_mixer():
    from . import fx, mixer
    channels = mixer.load_channels()
    source = fx.FX_SOURCE if fx.installed() else None
    path, unresolved, hardware_out = mixer.install(channels, fx_source=source)
    mixer.save_channels(channels)
    mixer.restart_pipewire()
    print(f"mixer topology installed: {path}")
    print(f"monitor routed to: {hardware_out or 'no Wave:3 output found'}")
    if unresolved:
        print(f"unresolved mic sources: {[c.ident for c in unresolved]}")


def _uninstall_mixer():
    from . import mixer
    removed = mixer.uninstall()
    mixer.restart_pipewire()
    print("mixer topology removed" if removed else "no mixer topology installed")


def _install_fx():
    from . import fx, mixer
    source = mixer.resolve_node(mixer.WAVE3_SOURCE_MATCH, "Audio/Source")
    if source is None:
        sys.exit("Wave:3 capsule not found - is the microphone connected?")
    rack = fx.apply_state(fx.build_rack(), fx.load_state())
    path = fx.install(rack, source)
    fx.save_state(fx.rack_to_state(rack))
    channels = mixer.load_channels()
    mixer.install(channels, fx_source=fx.FX_SOURCE)
    mixer.restart_pipewire()
    print(f"effects rack installed: {path}")


def _uninstall_fx():
    from . import fx, mixer
    removed = fx.uninstall()
    channels = mixer.load_channels()
    mixer.install(channels)
    mixer.restart_pipewire()
    print("effects rack removed" if removed else "no effects rack installed")


def _doctor():
    """Report on the parts that fail silently."""
    from . import fx, mixer, watchdog

    card = watchdog.find_card()
    print(f"Wave:3 on USB:      {'card ' + card if card else 'NOT FOUND'}")
    if card is None:
        sys.exit("Connect the microphone and try again.")

    healthy, message = watchdog.check_once()
    print(f"Capture stream:     {message}")

    try:
        from .device import Wave3
        dev = Wave3()
        dev.open()
        info = dev.read_version()
        print(f"USB control:        ok (firmware {info.get('firmware', '?')}, "
              f"serial {info.get('serial', '?')})")
    except Exception as exc:
        print(f"USB control:        FAILED - {exc}")

    print(f"Mixer topology:     {'installed' if os.path.exists(mixer.CONF_PATH) else 'NOT installed'}")
    print(f"Effects rack:       {'installed' if fx.installed() else 'NOT installed'}")

    if not healthy:
        print()
        print("The capture stream is wedged. Recovering...")
        if watchdog.recover():
            ok, message = watchdog.check_once()
            print(f"After recovery:     {message}")
        else:
            print("Recovery failed. Replug the microphone.")
        sys.exit(0 if ok else 1)


def _setup():
    _install_mixer()
    _install_fx()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wave3", description="Elgato Wave:3 control panel")
    parser.add_argument("--version", action="version", version=f"wave3 {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="install the mixer topology and effects rack")
    sub.add_parser("doctor", help="diagnose the capture stream and USB control")
    sub.add_parser("install-mixer", help="install the PipeWire mixer topology")
    sub.add_parser("uninstall-mixer", help="remove the PipeWire mixer topology")
    sub.add_parser("install-fx", help="install the mic effects rack")
    sub.add_parser("uninstall-fx", help="remove the mic effects rack")

    args, _ = parser.parse_known_args(argv)

    handlers = {
        "setup": _setup,
        "doctor": _doctor,
        "install-mixer": _install_mixer,
        "uninstall-mixer": _uninstall_mixer,
        "install-fx": _install_fx,
        "uninstall-fx": _uninstall_fx,
    }
    if args.command in handlers:
        handlers[args.command]()
        return 0

    from .app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
