"""Device enumeration and hotplug tracking via GstDeviceMonitor.

Capture cards are usually USB, so devices come and go. We wrap
Gst.DeviceMonitor and expose GObject signals the UI can react to, plus
helpers to build a stable *identity* for a device and to re-find a saved
device among the currently connected ones.
"""

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib, GObject  # noqa: E402

# Properties used to match a saved device against the connected ones across
# reboots / re-plugs. These MUST be stable per physical device: volatile keys
# such as the PipeWire ``object.serial`` (a per-session counter) or the ALSA
# ``api.alsa.path`` / ``/dev/videoN`` path (depends on enumeration order) are
# deliberately excluded — they get reassigned to *different* devices between
# sessions and cause a saved source to match the wrong hardware.
_VIDEO_KEYS = [
    "api.v4l2.cap.bus_info",  # e.g. usb-0000:00:14.0-9 (stable per USB port)
    "device.bus_info",
    "node.name",              # v4l2_input.pci-...-usb-0_9_1.0 (stable per port)
]
_AUDIO_KEYS = [
    "node.name",           # alsa_input.usb-<product>...  (stable per product)
    "alsa.card_name",      # e.g. USB Device 0x345f:0x2109
    "device.bus_path",     # USB port path
    "device.description",
]


def _structure_to_dict(structure) -> dict:
    result = {}
    if structure is None:
        return result
    for i in range(structure.n_fields()):
        name = structure.nth_field_name(i)
        try:
            value = structure.get_value(name)
        except Exception:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[name] = value
        else:
            try:
                result[name] = str(value)
            except Exception:
                pass
    return result


def is_video(device) -> bool:
    return device.get_device_class().startswith("Video")


def device_identity(device) -> dict:
    """Build a JSON-serializable identity dict for a Gst.Device."""
    klass = "video" if is_video(device) else "audio"
    props = _structure_to_dict(device.get_properties())
    wanted = _VIDEO_KEYS if klass == "video" else _AUDIO_KEYS
    keys = {k: props[k] for k in wanted if k in props}
    return {
        "klass": klass,
        "display_name": device.get_display_name(),
        "keys": keys,
    }


def _match_score(saved: dict, device) -> int:
    """Higher is better. 0 means no meaningful match."""
    if not saved:
        return 0
    ident = device_identity(device)
    if saved.get("klass") != ident.get("klass"):
        return -1
    score = 0
    saved_keys = saved.get("keys", {}) or {}
    dev_keys = ident.get("keys", {})
    for key, value in saved_keys.items():
        if dev_keys.get(key) == value:
            score += 2
    if saved.get("display_name") and saved["display_name"] == ident["display_name"]:
        score += 1
    return score


class DeviceManager(GObject.Object):
    """Live registry of Video/Source and Audio/Source devices."""

    __gsignals__ = {
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "device-added": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "device-removed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__()
        self._monitor = Gst.DeviceMonitor.new()
        self._monitor.add_filter("Video/Source", None)
        self._monitor.add_filter("Audio/Source", None)
        bus = self._monitor.get_bus()
        bus.add_watch(GLib.PRIORITY_DEFAULT, self._on_bus_message, None)
        self._started = False

    def start(self):
        if not self._started:
            self._started = self._monitor.start()
        return self._started

    def stop(self):
        if self._started:
            self._monitor.stop()
            self._started = False

    def video_devices(self):
        return [d for d in self._monitor.get_devices() if is_video(d)]

    def audio_devices(self):
        return [d for d in self._monitor.get_devices() if not is_video(d)]

    def find_device(self, saved_identity):
        """Return the connected Gst.Device best matching a saved identity."""
        if not saved_identity:
            return None
        pool = (
            self.video_devices()
            if saved_identity.get("klass") == "video"
            else self.audio_devices()
        )
        best, best_score = None, 0
        for device in pool:
            score = _match_score(saved_identity, device)
            if score > best_score:
                best, best_score = device, score
        return best

    def _on_bus_message(self, bus, message, _user_data):
        if message.type == Gst.MessageType.DEVICE_ADDED:
            device = message.parse_device_added()
            self.emit("device-added", device)
            self.emit("devices-changed")
        elif message.type == Gst.MessageType.DEVICE_REMOVED:
            device = message.parse_device_removed()
            self.emit("device-removed", device)
            self.emit("devices-changed")
        return GLib.SOURCE_CONTINUE
