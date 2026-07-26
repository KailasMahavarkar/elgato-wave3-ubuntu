#!/usr/bin/env bash
# Build the wave3 .deb. Pure-Python, architecture: all.
#
#   packaging/build-deb.sh [version]
#
# Produces dist/wave3_<version>_all.deb from the current tree.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(python3 -c "import sys; sys.path.insert(0, '$REPO'); from wave3 import __version__; print(__version__)")}"
PKG="wave3"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "building $PKG $VERSION"

# --- python package ---------------------------------------------------
DIST="$STAGE/usr/lib/python3/dist-packages/wave3"
mkdir -p "$DIST"
cp "$REPO"/wave3/*.py "$DIST/"
cp "$REPO"/wave3/style.css "$DIST/"

# --- launcher ---------------------------------------------------------
mkdir -p "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/wave3" <<'LAUNCH'
#!/bin/sh
exec python3 -m wave3 "$@"
LAUNCH
chmod 0755 "$STAGE/usr/bin/wave3"

# --- desktop entry + icon --------------------------------------------
install -Dm0644 "$REPO/packaging/com.orkait.Wave3.desktop" \
  "$STAGE/usr/share/applications/com.orkait.Wave3.desktop"
install -Dm0644 "$REPO/packaging/com.orkait.Wave3.svg" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/com.orkait.Wave3.svg"

# --- udev rule (uaccess grants the logged-in user EP0 control) --------
install -Dm0644 "$REPO/70-elgato-wave3.rules" \
  "$STAGE/usr/lib/udev/rules.d/70-elgato-wave3.rules"

# --- wireplumber no-suspend rule (system-wide) ------------------------
install -Dm0644 "$REPO/51-wave3.lua" \
  "$STAGE/etc/wireplumber/main.lua.d/51-wave3.lua"

# --- docs -------------------------------------------------------------
install -Dm0644 "$REPO/README.md" "$STAGE/usr/share/doc/wave3/README.md"
install -Dm0644 "$REPO/LICENSE" "$STAGE/usr/share/doc/wave3/copyright"

# --- control metadata -------------------------------------------------
SIZE=$(du -sk "$STAGE" | cut -f1)
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-glib-2.0, pipewire-bin, pipewire-pulse, wireplumber, pulseaudio-utils, alsa-utils, lsp-plugins-ladspa, libusb-1.0-0
Recommends: obs-studio
Maintainer: Kailas Mahavarkar <kailashmahavarkar5@gmail.com>
Homepage: https://github.com/KailasMahavarkar/elgato-wave3-ubuntu
Installed-Size: $SIZE
Description: Elgato Wave:3 control panel and Wave Link replacement
 Native GTK4 control panel for the Elgato Wave:3 microphone. Hardware
 controls (gain, Clipguard, low cut, headphone volume, dial mode) via a
 reverse-engineered USB protocol, plus a dual-mix PipeWire mixer, a live
 EQ curve editor and a gate/EQ/compressor/limiter effects rack.
 .
 The mixer and effects rack are per-user; after install run 'wave3 setup'
 or use the in-app buttons to create them.
CONTROL

cp "$REPO/packaging/postinst" "$STAGE/DEBIAN/postinst"
cp "$REPO/packaging/postrm" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# --- build ------------------------------------------------------------
mkdir -p "$REPO/dist"
OUT="$REPO/dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "built: $OUT"
