"""Application controller: wires config, devices, pipelines and the window."""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Adw, Gst, Gio, GLib, Gdk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION
from .config import Config
from .devices import DeviceManager, device_identity, _match_score
from .gamepad import GamepadManager
from .pipeline import VideoPipeline, AudioPipeline
from .settings_dialog import SettingsDialog
from .window import CaptureWindow

_CSS = b"""
.capture-surface { background-color: black; }
"""

# Many USB/HDMI capture cards expose their video and audio as one physical
# device, and opening the V4L2 video node resets the card's USB audio
# interface. Grabbing the audio source in the same instant then yields a silent
# stream, so we let the card settle before starting audio on launch/hot-plug.
_AUDIO_START_DELAY_MS = 1000

# How much a single controller press (or one auto-repeat tick) moves the
# volume; matches the volume slider's step increment.
_VOLUME_STEP = 0.05


class CaptureViewerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._config = Config()
        self._devices = DeviceManager()
        self._video = VideoPipeline()
        self._audio = AudioPipeline()
        self._window = None
        self._settings_dialog = None
        self._gamepad = GamepadManager()
        self._video_active = False
        self._audio_active = False
        self._save_source = None
        self._audio_start_source = None

        self._video.connect("error", self._on_pipeline_error)
        self._audio.connect("error", self._on_audio_error)

    # ------------------------------------------------------------------
    def do_startup(self):
        Adw.Application.do_startup(self)
        self._devices.start()
        self._devices.connect("device-added", self._on_device_added)
        self._devices.connect("device-removed", self._on_device_removed)

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._add_action("settings", self._on_settings_action, ["<Primary>comma", "F1"])
        self._add_action("about", self._on_about_action)
        self._add_action("quit", lambda *_: self.quit(), ["<Primary>q"])

    def _add_action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self):
        if self._window is None:
            self._window = CaptureWindow(
                self, initial_volume=self._config.get("volume", 1.0)
            )
            self._window.connect("settings-requested", lambda *_: self._open_settings())
            self._window.connect("play-toggled", self._on_play_toggled)
            self._window.connect("volume-changed", self._on_volume_changed)
            self._window.connect("fullscreen-changed", self._on_fullscreen_changed)

            self._install_window_shortcuts()

            # Drive the whole UI from a game controller (Steam Gaming Mode /
            # gamescope has no keyboard or mouse). No-op if libmanette is
            # unavailable, e.g. a bare host run outside the Flatpak runtime.
            self._gamepad.connect("button", self._on_gamepad_button)
            self._gamepad.connect("direction", self._on_gamepad_direction)
            self._gamepad.start()

        self._window.present()
        self._window.apply_fullscreen(bool(self._config.get("fullscreen")))

        if self._config.is_configured:
            self._start_from_config()
        else:
            self._window.show_message(
                "No capture device configured",
                "Open Settings to choose a video capture device.",
            )
            self._open_settings()

    def _install_window_shortcuts(self):
        # F11 is the only way to toggle fullscreen; Escape quits the app.
        toggle = Gio.SimpleAction.new("toggle-fullscreen", None)
        toggle.connect(
            "activate",
            lambda *_: self._window.apply_fullscreen(not self._window.is_fullscreen()),
        )
        self._window.add_action(toggle)
        self.set_accels_for_action("win.toggle-fullscreen", ["F11"])

        self.set_accels_for_action("app.quit", ["<Primary>q", "Escape"])

    # ------------------------------------------------------------------
    # Settings
    def _open_settings(self):
        if self._settings_dialog is not None:
            return
        dialog = SettingsDialog(self._devices, self._config)
        dialog.connect("video-selected", self._on_video_selected)
        dialog.connect("audio-selected", self._on_audio_selected)
        dialog.connect("closed", self._on_settings_closed)
        self._settings_dialog = dialog
        dialog.present(self._window)

    def _on_settings_closed(self, *_):
        self._settings_dialog = None

    # ------------------------------------------------------------------
    # Game controller input. When the settings dialog is open it consumes all
    # input (menu navigation); otherwise buttons drive the header controls.
    def _on_gamepad_button(self, _manager, name):
        if self._settings_dialog is not None:
            self._settings_dialog.gamepad_button(name)
            return
        if name == "a":
            self._window.toggle_play()
        elif name == "start":
            self._open_settings()
        elif name == "y":
            self._window.toggle_fullscreen()
        elif name == "rb":
            self._window.adjust_volume(_VOLUME_STEP)
        elif name == "lb":
            self._window.adjust_volume(-_VOLUME_STEP)

    def _on_gamepad_direction(self, _manager, direction):
        if self._settings_dialog is not None:
            self._settings_dialog.gamepad_direction(direction)
            return
        if direction == "up":
            self._window.adjust_volume(_VOLUME_STEP)
        elif direction == "down":
            self._window.adjust_volume(-_VOLUME_STEP)

    def _on_settings_action(self, *_):
        if self._window:
            self._open_settings()

    def _on_video_selected(self, _dialog, device):
        self._config.set("video_device", device_identity(device))
        self._config.save()
        self._start_video(device)

    def _on_audio_selected(self, _dialog, device):
        if device is None:
            self._config.set("audio_device", None)
            self._config.save()
            self._stop_audio()
        else:
            self._config.set("audio_device", device_identity(device))
            self._config.save()
            self._start_audio(device)

    # ------------------------------------------------------------------
    # Pipeline lifecycle
    def _start_from_config(self):
        video_device = self._devices.find_device(self._config.get("video_device"))
        if video_device is None:
            self._window.set_playing(False)
            self._window.show_message(
                "Capture device not connected",
                "Waiting for the saved capture device. Connect it, or open "
                "Settings to choose another.",
            )
            return
        self._start_video(video_device)

        audio_id = self._config.get("audio_device")
        if audio_id:
            audio_device = self._devices.find_device(audio_id)
            if audio_device is not None:
                self._schedule_audio_start(audio_device)

    def _start_video(self, device):
        try:
            paintable = self._video.build(device)
        except Exception as exc:  # noqa: BLE001 - surface to the user
            self._window.show_message(
                "Could not start video", str(exc), icon="dialog-error-symbolic"
            )
            return
        self._window.set_paintable(paintable)
        self._video.start()
        self._video_active = True
        self._window.show_video()
        self._window.set_playing(True)

    def _schedule_audio_start(self, device):
        """Start audio a beat after video so the capture card can settle.

        Starting immediately alongside video produces a silent stream on many
        cards; the only previous workaround was to re-pick the same source in
        Settings once the card had warmed up. See _AUDIO_START_DELAY_MS.
        """
        self._cancel_audio_start()
        self._audio_start_source = GLib.timeout_add(
            _AUDIO_START_DELAY_MS, self._fire_audio_start, device
        )

    def _fire_audio_start(self, device):
        self._audio_start_source = None
        self._start_audio(device)
        return GLib.SOURCE_REMOVE

    def _cancel_audio_start(self):
        if self._audio_start_source is not None:
            GLib.source_remove(self._audio_start_source)
            self._audio_start_source = None

    def _start_audio(self, device):
        self._cancel_audio_start()
        try:
            self._audio.build(
                device,
                volume=self._config.get("volume", 1.0),
                muted=self._config.get("muted", False),
            )
        except Exception as exc:  # noqa: BLE001
            # Audio is non-fatal; keep video running.
            self._audio_active = False
            return
        self._audio.start()
        self._audio_active = True

    def _stop_audio(self):
        self._cancel_audio_start()
        self._audio.stop()
        self._audio_active = False

    def _stop_all(self):
        self._video.stop()
        self._stop_audio()
        self._video_active = False
        self._window.set_playing(False)

    def _on_play_toggled(self, _window, playing):
        if playing:
            if self._config.is_configured:
                self._start_from_config()
            else:
                self._window.set_playing(False)
                self._open_settings()
        else:
            self._stop_all()

    # ------------------------------------------------------------------
    # Volume / fullscreen persistence
    def _on_volume_changed(self, _window, value):
        self._audio.set_volume(value)
        self._config.set("volume", round(value, 3))
        self._config.set("muted", value <= 0.0)
        self._schedule_save()

    def _on_fullscreen_changed(self, _window, fullscreen):
        self._config.set("fullscreen", bool(fullscreen))
        self._schedule_save()

    def _schedule_save(self):
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(800, self._flush_save)

    def _flush_save(self):
        self._save_source = None
        self._config.save()
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------
    # Hotplug
    def _on_device_added(self, _manager, device):
        ident = device_identity(device)
        if ident["klass"] == "video" and not self._video_active:
            saved = self._config.get("video_device")
            if saved and _match_score(saved, device) > 0:
                self._start_video(device)
                # Bring audio back too if its device is present.
                audio_id = self._config.get("audio_device")
                if audio_id and not self._audio_active:
                    audio_device = self._devices.find_device(audio_id)
                    if audio_device is not None:
                        self._schedule_audio_start(audio_device)
        elif ident["klass"] == "audio" and not self._audio_active:
            saved = self._config.get("audio_device")
            if saved and _match_score(saved, device) > 0 and self._video_active:
                self._schedule_audio_start(device)

    def _on_device_removed(self, _manager, device):
        ident = device_identity(device)
        if ident["klass"] == "video":
            saved = self._config.get("video_device")
            if saved and _match_score(saved, device) > 0 and self._video_active:
                self._video.stop()
                self._stop_audio()
                self._video_active = False
                self._window.set_playing(False)
                self._window.show_message(
                    "Capture device disconnected",
                    "The device was unplugged. Reconnect it to resume "
                    "automatically.",
                )
        else:
            saved = self._config.get("audio_device")
            if saved and _match_score(saved, device) > 0 and self._audio_active:
                self._stop_audio()

    # ------------------------------------------------------------------
    def _on_pipeline_error(self, _pipeline, message):
        self._video_active = False
        self._stop_audio()
        self._window.set_playing(False)
        self._window.show_message(
            "Video error", message, icon="dialog-error-symbolic"
        )

    def _on_audio_error(self, _pipeline, message):
        # Audio problems shouldn't tear down the video view.
        self._stop_audio()

    def _on_about_action(self, *_):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="CaptureViewer",
            comments="Use a video capture card as a monitor.",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self._window)


def main():
    Gst.init(None)
    app = CaptureViewerApp()
    return app.run(sys.argv)
