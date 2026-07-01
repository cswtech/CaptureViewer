"""Persistent configuration stored as JSON in the XDG config directory.

Devices are stored as *identity* dicts (see devices.py) rather than raw
/dev/videoN paths, because USB capture cards can enumerate in a different
order across reboots. On startup we match the saved identity against the
currently connected devices.
"""

import json
import os
from pathlib import Path

DEFAULTS = {
    "video_device": None,   # identity dict, or None if unconfigured
    "audio_device": None,   # identity dict, or None for "no audio"
    "fullscreen": False,
    "volume": 1.0,          # 0.0 .. 1.0
    "muted": False,
}


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "captureviewer"


def _config_path() -> Path:
    return _config_dir() / "config.json"


class Config:
    def __init__(self):
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(_config_path(), "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if isinstance(loaded, dict):
            for key in DEFAULTS:
                if key in loaded:
                    self.data[key] = loaded[key]

    def save(self):
        directory = _config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = _config_path()
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)
        os.replace(tmp, path)

    # Convenience accessors ------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    @property
    def is_configured(self) -> bool:
        return self.data.get("video_device") is not None
