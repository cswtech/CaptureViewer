"""Settings dialog: pick the video capture device and audio source.

Uses libadwaita combo rows inside a dialog with an explicit **Apply** button.
Applying reads whatever is currently selected — including the default first
item — and emits it, so a single-device setup works without having to change
the selection. The device lists refresh automatically on hotplug.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GObject  # noqa: E402

from .devices import _match_score


class SettingsDialog(Adw.Dialog):
    """Emits 'video-selected' / 'audio-selected' with a device or None on Apply."""

    __gsignals__ = {
        "video-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "audio-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, device_manager, config):
        super().__init__()
        self.set_title("Settings")
        self.set_content_width(520)
        self.set_content_height(440)
        self._devices = device_manager
        self._config = config
        self._video_list = []          # index -> Gst.Device
        self._audio_list = [None]      # index 0 == "No audio"
        self._devices_handler = None

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        self._apply_button = Gtk.Button(label="Apply")
        self._apply_button.add_css_class("suggested-action")
        self._apply_button.connect("clicked", self._on_apply)
        header.pack_end(self._apply_button)

        page = Adw.PreferencesPage()
        toolbar_view.set_content(page)
        self.set_child(toolbar_view)

        video_group = Adw.PreferencesGroup(
            title="Video",
            description="The capture card whose input you want to view.",
        )
        page.add(video_group)
        self._video_row = Adw.ComboRow(title="Capture device")
        video_group.add(self._video_row)

        audio_group = Adw.PreferencesGroup(
            title="Audio",
            description="Source routed to your default output. Choose "
            "“No audio” for capture cards without sound.",
        )
        page.add(audio_group)
        self._audio_row = Adw.ComboRow(title="Audio source")
        audio_group.add(self._audio_row)

        self._populate()
        self._devices_handler = self._devices.connect(
            "devices-changed", lambda *_: self._populate()
        )
        self.connect("closed", self._on_closed)

    # ------------------------------------------------------------------
    def _populate(self):
        self._video_list = list(self._devices.video_devices())
        self._audio_list = [None] + list(self._devices.audio_devices())

        if self._video_list:
            video_names = [d.get_display_name() for d in self._video_list]
            self._video_row.set_sensitive(True)
            self._apply_button.set_sensitive(True)
        else:
            video_names = ["No capture devices found"]
            self._video_row.set_sensitive(False)
            self._apply_button.set_sensitive(False)
        self._video_row.set_model(Gtk.StringList.new(video_names))

        audio_names = ["No audio"] + [
            d.get_display_name() for d in self._audio_list[1:]
        ]
        self._audio_row.set_model(Gtk.StringList.new(audio_names))

        self._select_saved()

    def _select_saved(self):
        saved_video = self._config.get("video_device")
        if saved_video and self._video_list:
            idx = self._best_index(saved_video, self._video_list)
            if idx is not None:
                self._video_row.set_selected(idx)

        saved_audio = self._config.get("audio_device")
        if saved_audio:
            idx = self._best_index(saved_audio, self._audio_list[1:])
            self._audio_row.set_selected(idx + 1 if idx is not None else 0)
        else:
            self._audio_row.set_selected(0)

    @staticmethod
    def _best_index(saved_identity, devices):
        best_idx, best_score = None, 0
        for i, device in enumerate(devices):
            score = _match_score(saved_identity, device)
            if score > best_score:
                best_idx, best_score = i, score
        return best_idx

    # ------------------------------------------------------------------
    def _on_apply(self, *_):
        if self._video_list:
            idx = self._video_row.get_selected()
            if 0 <= idx < len(self._video_list):
                self.emit("video-selected", self._video_list[idx])

        aidx = self._audio_row.get_selected()
        audio = self._audio_list[aidx] if 0 <= aidx < len(self._audio_list) else None
        self.emit("audio-selected", audio)

        self.close()

    def _on_closed(self, *_):
        if self._devices_handler is not None:
            self._devices.disconnect(self._devices_handler)
            self._devices_handler = None
