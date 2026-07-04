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
- **Distraction-free fullscreen** — the top bar hides instantly with no
  mouse-triggered reveal, ideal for a dedicated monitor
- **Full game controller support** — every action (play/stop, Settings, volume,
  fullscreen, device selection) is drivable from a gamepad, so it's usable in
  SteamOS Gaming Mode / gamescope where there's no keyboard or mouse
- Settings persisted in `~/.config/captureviewer/config.json`, keyed by stable
  device identifiers so devices are re-matched correctly across reboots

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| **F1** or **Ctrl+,** | Open Settings |
| **F11** | Toggle fullscreen (the *only* way in or out) |
| **Esc** | Quit the app immediately |
| **Ctrl+Q** | Quit |

In fullscreen the header hides immediately and stays hidden — press **F11**
again to bring it back. **Esc** closes the app.

### Game controller

Designed for SteamOS Gaming Mode / gamescope, where there's no keyboard or
mouse — the entire UI can be driven from a connected controller:

| Button | Video view | Settings dialog |
| --- | --- | --- |
| **A** | Play / Stop | Apply (or press the highlighted button) |
| **B** | — | Cancel / close |
| **Y** | Toggle fullscreen | — |
| **☰ Menu** (Start) | Open Settings | — |
| **D-pad ↑ / ↓** | Volume up / down | Move between fields |
| **D-pad ← / →** | — | Change the highlighted device / option |
| **RB / LB** | Volume up / down | — |

The **left analog stick mirrors the D-pad** in both contexts. The **Guide**
button is intentionally left to Steam, and Quit is not bound to a button to
avoid accidental exits (use Steam's Guide button, or **Ctrl+Q** / **Esc** with a
keyboard). Controllers are read via **libmanette**, which ships in the GNOME
runtime the Flatpak uses; for a source run, `install-deps.sh` pulls
`gir1.2-manette-0.2`. If libmanette is absent the app runs normally, just
without controller input.

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
flatpak install -y flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean \
  build-dir build-aux/flatpak/io.github.cswtech.CaptureViewer.yaml
flatpak run io.github.cswtech.CaptureViewer
```

> **App ID:** `io.github.cswtech.CaptureViewer` is a placeholder based on
> a GitHub-pages-style reverse-DNS ID. Rename it (files in `data/`, the manifest,
> and `APP_ID` in `captureviewer/__init__.py`) to a domain/GitHub account you
> control before publishing to Flathub.
>
> **gtk4paintablesink in Flatpak:** the GNOME 50 runtime ships it (verified,
> along with `v4l2src` and `pipewiresrc`). If `gst-inspect-1.0 gtk4paintablesink`
> ever fails inside the sandbox, add a `gst-plugin-gtk4` build module to the
> manifest.

### Sideload onto SteamOS (Steam Deck)

SteamOS has an immutable root filesystem (no native packages) and its Gaming
Mode compositor (gamescope) rejects mismatched GPU driver libraries — the two
things that make an AppImage painful there. A Flatpak avoids both: the app runs
against the GNOME runtime and picks up the Deck's own Mesa/Vulkan driver through
the `org.freedesktop.Platform.GL` extension, so it renders correctly in Desktop
*and* Gaming Mode. Since publishing to Flathub isn't an option here, ship it as a
**single-file bundle** and sideload it:

```bash
./build-aux/flatpak/build-flatpak.sh
# -> build-aux/flatpak/out/CaptureViewer.flatpak
```

Then, on the Steam Deck (**Desktop Mode**):

1. Copy `CaptureViewer.flatpak` over (USB stick, `scp`, or Warpinator).
2. Install it — the GNOME runtime is pulled from Flathub (preinstalled on the
   Deck) the first time:

   ```bash
   flatpak install --user ./CaptureViewer.flatpak
   flatpak run io.github.cswtech.CaptureViewer   # test in Desktop Mode first
   ```

3. Add it to your library so it shows up in Gaming Mode: Steam → **Add a
   Non-Steam Game** → **Browse** → enable "All Files" → point it at
   `/usr/bin/flatpak`, then set the launch options to
   `run io.github.cswtech.CaptureViewer`. (Or install
   [Flatseal](https://flathub.org/apps/com.github.tchx84.Flatseal) / a launcher
   that adds Flatpak apps to Steam automatically.)

The bundle is app-only; the ~300 MB GNOME runtime downloads once from Flathub
and is shared with every other Flatpak on the Deck. Updates are a matter of
rebuilding the bundle and re-running `flatpak install --user` on it.

## 4. Build a single-file AppImage

For sharing with someone who doesn't want to run `install-deps.sh` first,
`build-aux/appimage/build-appimage.sh` bundles the Python interpreter,
PyGObject, GTK4/libadwaita, GStreamer (core/base/good/bad/ugly/libav +
`gtk4paintablesink` + PipeWire), and glibc's dynamic linker straight from the
build machine into one self-contained file:

```bash
./install-deps.sh   # the build machine needs everything installed once
./build-aux/appimage/build-appimage.sh
# -> build-aux/appimage/out/CaptureViewer-x86_64.AppImage
```

To run it, the recipient just needs `chmod +x` and to double-click it, or:

```bash
chmod +x CaptureViewer-x86_64.AppImage
./CaptureViewer-x86_64.AppImage
# if there's no FUSE (e.g. some containers/older sandboxes):
./CaptureViewer-x86_64.AppImage --appimage-extract-and-run
```

The GPU/driver stack (`libGL`, `libEGL`, `libgbm`, `libdrm`, `libvulkan`,
VA-API/VDPAU) is **deliberately not bundled** — those are coupled to the target
machine's Mesa/kernel driver and are provided by the host at runtime. Bundling
the build machine's copies breaks GPU buffer sharing on other systems, most
visibly under SteamOS Gaming Mode (gamescope). See Troubleshooting.

**Portability:** the AppImage requires a target glibc at least as new as the
build machine's — it will *not* run on distros noticeably older than the one
it was built on. Build on the oldest common distro you can reasonably target
(ideally in an old-LTS container) for the widest reach; a bleeding-edge build
machine produces an AppImage that only runs on similarly recent systems.

## Troubleshooting

- **No devices listed:** confirm the card appears with `v4l2-ctl --list-devices`
  and that your user is in the `video` group.
- **Black screen / no video:** some cards only emit MJPEG; `decodebin` handles
  that automatically, but check `gst-launch-1.0 v4l2src ! decodebin ! videoconvert ! gtk4paintablesink`.
- **No audio:** the capture card's audio shows up as a separate *source*; pick it
  under Settings → Audio. Output always goes to the system default sink.
- **SteamOS Gaming Mode (gamescope) — black window / doesn't appear:** the
  AppImage must **not** bundle the GPU/driver stack (`libGL`, `libEGL`,
  `libgbm`, `libdrm`, `libvulkan`, …). gamescope requires the app to hand it
  GBM/dmabuf buffers that match the *host* Mesa/Vulkan driver, so those
  libraries have to come from the target machine, not the build machine. The
  build script prunes them for exactly this reason — make sure you're running
  an AppImage built after that change. If a window still fails to appear,
  launch it from a terminal (Desktop Mode → Konsole, or SSH) to see the error,
  and as a fallback try forcing software/GL rendering or Xwayland:

  ```bash
  GSK_RENDERER=gl ./CaptureViewer-x86_64.AppImage      # avoid the Vulkan renderer
  GDK_BACKEND=x11 ./CaptureViewer-x86_64.AppImage      # run via Xwayland
  ```

## Project layout

```
captureviewer/
  application.py     # Adw.Application: wires everything together
  window.py          # main window, header controls, fullscreen
  settings_dialog.py # device pickers (Adw.PreferencesDialog)
  gamepad.py         # game controller input (libmanette)
  devices.py         # GstDeviceMonitor + stable device identity/matching
  pipeline.py        # video + audio GStreamer pipelines
  config.py          # JSON config in ~/.config/captureviewer/
data/                # .desktop, AppStream metainfo, icon
build-aux/flatpak/   # Flatpak manifest
build-aux/appimage/  # AppImage build script
```
