# Capture Viewer

Use a video capture card as a monitor on Linux. Capture Viewer shows the live
input of a USB/HDMI capture card in a window and plays its audio through your
default output device — so a laptop plus a capture card becomes a portable
monitor.

Built with **Python + PyGObject (GTK4 / libadwaita)** and **GStreamer**
(`gtk4paintablesink` for the video surface).

## Features

- Select the video capture device and audio source in **Settings**
- Low-latency live preview (leaky queues drop stale frames)
- Audio routed to your **default output** with a volume control
- **Hotplug aware** — auto-reconnects when the capture card is replugged
- **F11** fullscreen (chrome auto-hides; move the mouse or press **Esc** to leave)
- Settings persisted in `~/.config/captureviewer/config.json`, keyed by stable
  device identifiers so devices are re-matched correctly across reboots

## 1. Install dependencies

```bash
./install-deps.sh
```

This installs GTK4, libadwaita, GStreamer (incl. `gstreamer1.0-gtk4`),
`v4l-utils`, and the Flatpak toolchain. Verify the video sink is present:

```bash
gst-inspect-1.0 gtk4paintablesink | head -5
```

## 2. Run from source

```bash
./run.sh
```

On first launch the Settings dialog opens — pick your capture device (and an
audio source, or "No audio"). The picture starts immediately.

## 3. Build the Flatpak

```bash
flatpak install -y flathub org.gnome.Platform//48 org.gnome.Sdk//48
flatpak-builder --user --install --force-clean \
  build-dir build-aux/flatpak/io.github.chamithshehan.CaptureViewer.yaml
flatpak run io.github.chamithshehan.CaptureViewer
```

> **App ID:** `io.github.chamithshehan.CaptureViewer` is a placeholder based on
> a GitHub-pages-style reverse-DNS ID. Rename it (files in `data/`, the manifest,
> and `APP_ID` in `captureviewer/__init__.py`) to a domain/GitHub account you
> control before publishing to Flathub.
>
> **gtk4paintablesink in Flatpak:** the GNOME 48 runtime ships it. If
> `gst-inspect-1.0 gtk4paintablesink` fails inside the sandbox, add a
> `gst-plugin-gtk4` build module to the manifest.

## Troubleshooting

- **No devices listed:** confirm the card appears with `v4l2-ctl --list-devices`
  and that your user is in the `video` group.
- **Black screen / no video:** some cards only emit MJPEG; `decodebin` handles
  that automatically, but check `gst-launch-1.0 v4l2src ! decodebin ! videoconvert ! gtk4paintablesink`.
- **No audio:** the capture card's audio shows up as a separate *source*; pick it
  under Settings → Audio. Output always goes to the system default sink.

## Project layout

```
captureviewer/
  application.py     # Adw.Application: wires everything together
  window.py          # main window, header controls, fullscreen
  settings_dialog.py # device pickers (Adw.PreferencesDialog)
  devices.py         # GstDeviceMonitor + stable device identity/matching
  pipeline.py        # video + audio GStreamer pipelines
  config.py          # JSON config in ~/.config/captureviewer/
data/                # .desktop, AppStream metainfo, icon
build-aux/flatpak/   # Flatpak manifest
```
