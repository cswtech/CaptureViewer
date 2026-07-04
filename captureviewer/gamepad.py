"""Game controller support via libmanette.

This device is typically used in Steam Gaming Mode / gamescope, where there is
no keyboard or mouse — the whole UI has to be drivable from a game controller.

libmanette (the same library GNOME apps use) reads controllers straight off
evdev and integrates with the GLib main loop, so no polling thread is needed.
It ships in the org.gnome.Platform runtime; on a bare host it may be absent, in
which case this module degrades to a no-op and the app still runs normally.

GamepadManager translates raw controller events into two high-level GObject
signals that the rest of the app consumes without caring about button codes:

  * ``button`` (str)    — a discrete action button was pressed. Name is one of
                          a/b/x/y/lb/rb/select/start/guide/l3/r3.
  * ``direction`` (str) — a directional input (D-pad, hat, or left stick) in
                          up/down/left/right. Auto-repeats while held so it can
                          drive both volume changes and menu navigation.
"""

import gi

from gi.repository import GObject, GLib

try:
    gi.require_version("Manette", "0.2")
    from gi.repository import Manette
    _MANETTE_AVAILABLE = True
except (ValueError, ImportError):
    Manette = None
    _MANETTE_AVAILABLE = False


# Linux evdev codes libmanette reports after applying its standard (SDL-based)
# mapping. Face-button positions follow the Xbox layout: A=bottom, B=right,
# X=left, Y=top.
_BUTTON_NAMES = {
    0x130: "a",       # BTN_A / South
    0x131: "b",       # BTN_B / East
    0x133: "x",       # BTN_X / West
    0x134: "y",       # BTN_Y / North
    0x136: "lb",      # BTN_TL
    0x137: "rb",      # BTN_TR
    0x13a: "select",  # BTN_SELECT (View / Back)
    0x13b: "start",   # BTN_START (Menu)
    0x13c: "guide",   # BTN_MODE (Guide) — usually grabbed by Steam
    0x13d: "l3",      # BTN_THUMBL
    0x13e: "r3",      # BTN_THUMBR
}

_DPAD_BUTTONS = {
    0x220: "up",      # BTN_DPAD_UP
    0x221: "down",    # BTN_DPAD_DOWN
    0x222: "left",    # BTN_DPAD_LEFT
    0x223: "right",   # BTN_DPAD_RIGHT
}

# Left-stick and hat axis codes (ABS_*). The right stick and triggers are
# intentionally ignored.
_ABS_X = 0x00
_ABS_Y = 0x01
_HAT_X = 0x10
_HAT_Y = 0x11

# Analog-stick engage/release thresholds (hysteresis) and repeat cadence (ms).
_STICK_ENGAGE = 0.7
_STICK_RELEASE = 0.4
_REPEAT_DELAY_MS = 350
_REPEAT_INTERVAL_MS = 130


class GamepadManager(GObject.Object):
    __gsignals__ = {
        "button": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "direction": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._monitor = None
        self._devices = {}            # Manette.Device -> [handler ids]
        # Component directional state; the active direction is the first of
        # these (in priority order) that is engaged.
        self._components = {"dpad": None, "hat": None, "stick": None}
        self._hat_x = None
        self._hat_y = None
        self._stick_x = 0.0
        self._stick_y = 0.0
        self._active_dir = None
        self._repeat_id = None

    @property
    def available(self) -> bool:
        return _MANETTE_AVAILABLE

    # ------------------------------------------------------------------
    def start(self):
        """Begin monitoring for controllers. Safe to call when unavailable."""
        if not _MANETTE_AVAILABLE or self._monitor is not None:
            return
        self._monitor = Manette.Monitor.new()
        self._monitor.connect("device-connected", self._on_device_connected)
        self._monitor.connect("device-disconnected", self._on_device_disconnected)
        iterator = self._monitor.iterate()
        while True:
            ok, device = iterator.next()
            if not ok:
                break
            self._add_device(device)

    def stop(self):
        self._cancel_repeat()
        for device, handlers in self._devices.items():
            for hid in handlers:
                device.disconnect(hid)
        self._devices.clear()
        self._monitor = None

    # ------------------------------------------------------------------
    # Device lifecycle
    def _on_device_connected(self, _monitor, device):
        self._add_device(device)

    def _on_device_disconnected(self, _monitor, device):
        handlers = self._devices.pop(device, None)
        if handlers:
            for hid in handlers:
                device.disconnect(hid)
        # Drop any direction a departing controller was holding.
        self._components = {"dpad": None, "hat": None, "stick": None}
        self._hat_x = self._hat_y = None
        self._stick_x = self._stick_y = 0.0
        self._update_direction()

    def _add_device(self, device):
        if device in self._devices:
            return
        self._devices[device] = [
            device.connect("button-press-event", self._on_button_press),
            device.connect("button-release-event", self._on_button_release),
            device.connect("absolute-axis-event", self._on_absolute_axis),
            device.connect("hat-axis-event", self._on_hat_axis),
        ]

    # ------------------------------------------------------------------
    # Raw event handlers
    def _on_button_press(self, _device, event):
        ok, code = event.get_button()
        if not ok:
            return
        if code in _DPAD_BUTTONS:
            self._components["dpad"] = _DPAD_BUTTONS[code]
            self._update_direction()
        else:
            name = _BUTTON_NAMES.get(code)
            if name is not None:
                self.emit("button", name)

    def _on_button_release(self, _device, event):
        ok, code = event.get_button()
        if not ok:
            return
        if code in _DPAD_BUTTONS and self._components["dpad"] == _DPAD_BUTTONS[code]:
            self._components["dpad"] = None
            self._update_direction()

    def _on_absolute_axis(self, _device, event):
        ok, axis, value = event.get_absolute()
        if not ok:
            return
        if axis == _ABS_X:
            self._stick_x = value
        elif axis == _ABS_Y:
            self._stick_y = value
        else:
            return
        self._update_stick()

    def _on_hat_axis(self, _device, event):
        ok, axis, value = event.get_hat()
        if not ok:
            return
        if axis == _HAT_Y:
            self._hat_y = "up" if value < 0 else "down" if value > 0 else None
        elif axis == _HAT_X:
            self._hat_x = "left" if value < 0 else "right" if value > 0 else None
        else:
            return
        self._components["hat"] = self._hat_y or self._hat_x
        self._update_direction()

    # ------------------------------------------------------------------
    # Directional resolution + auto-repeat
    def _update_stick(self):
        current = self._components["stick"]
        threshold = _STICK_RELEASE if current else _STICK_ENGAGE
        x, y = self._stick_x, self._stick_y
        if abs(y) >= threshold and abs(y) >= abs(x):
            direction = "up" if y < 0 else "down"
        elif abs(x) >= threshold:
            direction = "left" if x < 0 else "right"
        else:
            direction = None
        if direction != current:
            self._components["stick"] = direction
            self._update_direction()

    def _update_direction(self):
        active = None
        for key in ("dpad", "hat", "stick"):
            if self._components[key]:
                active = self._components[key]
                break
        self._set_active_direction(active)

    def _set_active_direction(self, direction):
        if direction == self._active_dir:
            return
        self._active_dir = direction
        self._cancel_repeat()
        if direction is not None:
            self.emit("direction", direction)
            self._repeat_id = GLib.timeout_add(_REPEAT_DELAY_MS, self._repeat_first)

    def _repeat_first(self):
        self._repeat_id = None
        if self._active_dir is None:
            return GLib.SOURCE_REMOVE
        self.emit("direction", self._active_dir)
        self._repeat_id = GLib.timeout_add(_REPEAT_INTERVAL_MS, self._repeat_tick)
        return GLib.SOURCE_REMOVE

    def _repeat_tick(self):
        if self._active_dir is None:
            self._repeat_id = None
            return GLib.SOURCE_REMOVE
        self.emit("direction", self._active_dir)
        return GLib.SOURCE_CONTINUE

    def _cancel_repeat(self):
        if self._repeat_id is not None:
            GLib.source_remove(self._repeat_id)
            self._repeat_id = None
