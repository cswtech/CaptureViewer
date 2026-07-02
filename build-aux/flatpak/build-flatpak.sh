#!/usr/bin/env bash
# Builds a single-file Flatpak bundle of CaptureViewer for sideloading onto
# SteamOS (Steam Deck) or any other Linux desktop.
#
# Why Flatpak instead of the AppImage: SteamOS has an immutable root filesystem
# (so native packages are out) and its Gaming Mode compositor (gamescope) is
# picky about GPU driver libraries. Flatpak solves both -- the app runs against
# the GNOME runtime, and the host's Mesa/Vulkan driver is injected at runtime
# through the org.freedesktop.Platform.GL extension, so rendering works in both
# Desktop and Gaming Mode without vendoring any graphics libraries.
#
# The output is ONE .flatpak file. Copy it to the Deck and install with:
#   flatpak install --user ./CaptureViewer.flatpak
# The GNOME runtime it needs is pulled from Flathub (preconfigured on SteamOS)
# the first time; the bundle embeds that repo location so it resolves even on a
# fresh machine.
#
# Usage: ./build-aux/flatpak/build-flatpak.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$ROOT/build-aux/flatpak/io.github.cswtech.CaptureViewer.yaml"
APP_ID="io.github.cswtech.CaptureViewer"
RUNTIME_VER="50"

WORK="$ROOT/build-aux/flatpak"
BUILD_DIR="$WORK/build"
REPO_DIR="$WORK/repo"
OUT="$WORK/out"
BUNDLE="$OUT/CaptureViewer.flatpak"
FLATHUB_REPO="https://flathub.org/repo/flathub.flatpakrepo"

command -v flatpak >/dev/null || { echo "flatpak not found" >&2; exit 1; }
command -v flatpak-builder >/dev/null || { echo "flatpak-builder not found (install flatpak-builder)" >&2; exit 1; }

echo "== ensuring Flathub remote + GNOME $RUNTIME_VER runtime =="
# Only fetch what's missing. `flatpak info` (no scope flag) matches a user OR
# system install, so a runtime already present system-wide isn't re-downloaded.
if ! flatpak info "org.gnome.Platform//$RUNTIME_VER" >/dev/null 2>&1 \
   || ! flatpak info "org.gnome.Sdk//$RUNTIME_VER" >/dev/null 2>&1; then
  flatpak remote-add --user --if-not-exists flathub "$FLATHUB_REPO"
  flatpak install --user -y flathub \
    "org.gnome.Platform//$RUNTIME_VER" \
    "org.gnome.Sdk//$RUNTIME_VER"
else
  echo "  GNOME $RUNTIME_VER Platform + SDK already installed; skipping download."
fi

echo "== building into a local repo =="
mkdir -p "$OUT"
# --disable-rofiles-fuse: rofiles-fuse is a build-time anti-tampering mount that
# needs FUSE; it's unavailable in many containers/CI sandboxes and its absence
# aborts the build. Disabling it only removes that safety check, not any output.
flatpak-builder --user --force-clean \
  --disable-rofiles-fuse \
  --install-deps-from=flathub \
  --repo="$REPO_DIR" \
  "$BUILD_DIR" "$MANIFEST"

echo "== exporting single-file bundle =="
flatpak build-bundle \
  --runtime-repo="$FLATHUB_REPO" \
  "$REPO_DIR" "$BUNDLE" "$APP_ID"

echo
echo "Done: $BUNDLE"
du -h "$BUNDLE"
echo
echo "Sideload onto the Steam Deck (Desktop Mode):"
echo "  1. Copy CaptureViewer.flatpak to the Deck (USB stick, scp, or Warpinator)."
echo "  2. flatpak install --user ./CaptureViewer.flatpak"
echo "  3. In Steam: Add a Non-Steam Game -> browse -> select the launcher"
echo "     (flatpak run $APP_ID) so it appears in Gaming Mode."
