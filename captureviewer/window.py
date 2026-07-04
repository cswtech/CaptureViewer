"""Main application window: the video surface plus header controls.

The window is mostly presentational. It emits signals ('settings-requested',
'play-toggled', 'volume-changed', 'fullscreen-changed') that application.py
wires to pipeline/config actions.
"""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GObject  # noqa: E402

from . import APP_NAME


def _in_gaming_mode() -> bool:
    """True when running under SteamOS Gaming Mode / gamescope.

    gamescope always draws the focused window filling the screen, but it does
    not set GTK's 'fullscreened' state, so our fullscreen-driven chrome hiding
    never triggers and the header bar stays on top of the video. Detecting the
    compositor lets us hide the chrome outright.
    """
    if os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
        return True
    return "gamescope" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


class CaptureWindow(Adw.ApplicationWindow):
    __gsignals__ = {
        "settings-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "play-toggled": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "volume-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "fullscreen-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, application, initial_volume=1.0):
        super().__init__(application=application)
        self.set_title(APP_NAME)
        self.set_default_size(1280, 720)
        self._syncing = False
        self._gaming_mode = _in_gaming_mode()

        self._toolbar_view = Adw.ToolbarView()
        self.set_content(self._toolbar_view)

        self._build_header(initial_volume)
        self._build_content()

        # Keep the fullscreen button and top-bar visibility in sync with the
        # real window state (Esc, WM shortcuts, etc. also change it).
        self.connect("notify::fullscreened", self._on_fullscreen_state)
        # Apply the initial chrome state so gamescope launches start hidden.
        self._apply_chrome()

    # ------------------------------------------------------------------
    def _build_header(self, initial_volume):
        header = Adw.HeaderBar()
        self._toolbar_view.add_top_bar(header)

        self._play_button = Gtk.ToggleButton(icon_name="media-playback-start-symbolic")
        self._play_button.set_tooltip_text("Play / Stop")
        self._play_button.connect("toggled", self._on_play_toggled)
        header.pack_start(self._play_button)

        settings_button = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_button.set_tooltip_text("Settings")
        settings_button.connect("clicked", lambda *_: self.emit("settings-requested"))
        header.pack_end(settings_button)

        self._fullscreen_button = Gtk.ToggleButton(
            icon_name="view-fullscreen-symbolic"
        )
        self._fullscreen_button.set_tooltip_text("Fullscreen (F11)")
        self._fullscreen_button.connect("toggled", self._on_fullscreen_toggled)
        header.pack_end(self._fullscreen_button)

        self._volume_button = Gtk.ScaleButton(
            icons=[
                "audio-volume-muted-symbolic",
                "audio-volume-high-symbolic",
                "audio-volume-low-symbolic",
                "audio-volume-medium-symbolic",
            ]
        )
        self._volume_button.set_tooltip_text("Volume")
        adjustment = self._volume_button.get_adjustment()
        adjustment.set_lower(0.0)
        adjustment.set_upper(1.0)
        adjustment.set_step_increment(0.05)
        adjustment.set_page_increment(0.1)
        self._volume_button.set_value(initial_volume)
        self._volume_button.connect("value-changed", self._on_volume_changed)
        header.pack_end(self._volume_button)

    def _build_content(self):
        self._stack = Gtk.Stack()
        self._toolbar_view.set_content(self._stack)

        # Video surface on a black background.
        self._picture = Gtk.Picture()
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._picture.add_css_class("capture-surface")
        video_box = Gtk.Box()
        video_box.add_css_class("capture-surface")
        video_box.append(self._picture)
        self._picture.set_hexpand(True)
        self._picture.set_vexpand(True)
        self._stack.add_named(video_box, "video")

        self._status = Adw.StatusPage(
            icon_name="video-display-symbolic",
            title="No capture device configured",
            description="Open Settings to choose a video capture device.",
        )
        open_settings = Gtk.Button(label="Open Settings")
        open_settings.add_css_class("pill")
        open_settings.add_css_class("suggested-action")
        open_settings.set_halign(Gtk.Align.CENTER)
        open_settings.connect("clicked", lambda *_: self.emit("settings-requested"))
        self._status.set_child(open_settings)
        self._stack.add_named(self._status, "status")

        self._stack.set_visible_child_name("status")

    # ------------------------------------------------------------------
    # Public API used by the application
    def set_paintable(self, paintable):
        self._picture.set_paintable(paintable)

    def show_video(self):
        self._stack.set_visible_child_name("video")

    def show_message(self, title, description, icon="video-display-symbolic",
                     show_settings=True):
        self._status.set_title(title)
        self._status.set_description(description)
        self._status.set_icon_name(icon)
        self._status.get_child().set_visible(show_settings)
        self._stack.set_visible_child_name("status")

    def set_playing(self, playing):
        self._syncing = True
        self._play_button.set_active(playing)
        self._play_button.set_icon_name(
            "media-playback-stop-symbolic" if playing
            else "media-playback-start-symbolic"
        )
        self._syncing = False

    def set_volume(self, value):
        self._syncing = True
        self._volume_button.set_value(value)
        self._syncing = False

    def apply_fullscreen(self, fullscreen):
        if fullscreen:
            self.fullscreen()
        else:
            self.unfullscreen()

    # ------------------------------------------------------------------
    # Controller-driven equivalents of the header controls. These flip the
    # relevant widget so the normal 'toggled'/'value-changed' handlers run,
    # keeping the button state, emitted signals and persistence identical to a
    # mouse click.
    def toggle_play(self):
        self._play_button.set_active(not self._play_button.get_active())

    def toggle_fullscreen(self):
        self.apply_fullscreen(not self.is_fullscreen())

    def adjust_volume(self, delta):
        value = min(1.0, max(0.0, self._volume_button.get_value() + delta))
        self._volume_button.set_value(value)

    # ------------------------------------------------------------------
    # Signal handlers
    def _on_play_toggled(self, button):
        if self._syncing:
            return
        self.emit("play-toggled", button.get_active())

    def _on_fullscreen_toggled(self, button):
        if self._syncing:
            return
        self.apply_fullscreen(button.get_active())

    def _on_volume_changed(self, _button, value):
        if self._syncing:
            return
        self.emit("volume-changed", value)

    def _on_fullscreen_state(self, *_):
        self._apply_chrome()
        self.emit("fullscreen-changed", self.is_fullscreen())

    def _apply_chrome(self):
        # Hide the header when genuinely fullscreen, or always under gamescope
        # (Steam Gaming Mode), which fullscreens us without setting GTK's
        # fullscreen state. Extending the content under the top bar lets it be
        # hidden outright; F11 (leaving fullscreen) is the only way back.
        hidden = self.is_fullscreen() or self._gaming_mode
        self._syncing = True
        self._fullscreen_button.set_active(hidden)
        self._syncing = False
        self._toolbar_view.set_extend_content_to_top_edge(hidden)
        self._toolbar_view.set_reveal_top_bars(not hidden)
