#!/usr/bin/env bash
# Installs all system dependencies for CaptureViewer on Debian/Ubuntu.
# Run:  ./install-deps.sh
set -euo pipefail

PACKAGES=(
  # Python + GObject introspection bindings
  python3-gi
  gir1.2-gtk-4.0
  gir1.2-adw-1
  gir1.2-gstreamer-1.0
  gir1.2-gst-plugins-base-1.0
  gir1.2-manette-0.2            # game controller support (libmanette)
  # GStreamer core + plugins
  gstreamer1.0-tools
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good      # v4l2src (video capture)
  gstreamer1.0-plugins-bad
  gstreamer1.0-plugins-ugly
  gstreamer1.0-libav
  gstreamer1.0-gtk4              # gtk4paintablesink
  gstreamer1.0-pipewire          # audio via PipeWire
  # Video4Linux utilities (device inspection / debugging)
  v4l-utils
  # Flatpak packaging toolchain
  flatpak
  flatpak-builder
)

echo "Installing ${#PACKAGES[@]} packages (sudo password required)..."
sudo apt update
sudo apt install -y "${PACKAGES[@]}"

echo
echo "Done. GStreamer / GTK4 / libadwaita and Flatpak tooling are installed."
echo "Verify gtk4paintablesink is available:"
echo "  gst-inspect-1.0 gtk4paintablesink | head -5"
