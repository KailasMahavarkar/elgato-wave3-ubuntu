#!/usr/bin/env bash
# Build and install the RNNoise LADSPA plugin used by Voice mode.
#
# Not shipped in the .deb: it is GPL-3 and not packaged for Ubuntu, so wave3
# loads it at runtime if present and falls back to the multiband gate if not.
#
#   packaging/build-rnnoise.sh
set -euo pipefail

REPO="https://github.com/werman/noise-suppression-for-voice.git"
TARGET="/usr/lib/ladspa/librnnoise_ladspa.so"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -e "$TARGET" ]; then
    echo "Already installed: $TARGET"
    echo "Delete it first if you want to rebuild."
    exit 0
fi

for tool in git cmake make g++; do
    command -v "$tool" >/dev/null || {
        echo "Missing $tool. Install with:"
        echo "  sudo apt install git cmake build-essential"
        exit 1
    }
done

echo "Cloning $REPO"
git clone --depth 1 --recursive "$REPO" "$WORK/src"

echo "Building"
cmake -S "$WORK/src" -B "$WORK/build" \
      -DCMAKE_BUILD_TYPE=Release -Wno-dev >/dev/null
cmake --build "$WORK/build" --target rnnoise_ladspa -j"$(nproc)" >/dev/null

BUILT="$WORK/build/bin/ladspa/librnnoise_ladspa.so"
[ -f "$BUILT" ] || { echo "Build produced no plugin at $BUILT"; exit 1; }

echo "Installing to $TARGET (needs sudo)"
sudo install -Dm0644 "$BUILT" "$TARGET"

echo
echo "Done. Restart wave3 and the Voice page will show AI denoise as active."
