"""GStreamer pipelines: one for video (into a GTK4 paintable), one for audio.

Video:  <source> ! decodebin ! videoconvert ! queue ! gtk4paintablesink
Audio:  <source> ! queue ! audioconvert ! audioresample ! volume ! autoaudiosink

decodebin makes the video pipeline format-agnostic: raw (YUY2) capture
cards pass straight through, while MJPEG cards get a jpegdec inserted
automatically. The leaky queues keep latency low for a live "monitor" feel
by dropping stale buffers instead of building a backlog.
"""

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GObject  # noqa: E402

# Gst queue "leaky" enum: 2 == downstream (drop old buffers).
_LEAKY_DOWNSTREAM = 2


class _BasePipeline(GObject.Object):
    __gsignals__ = {
        # A fatal pipeline error occurred; argument is a human-readable message.
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.pipeline = None

    def _make(self, factory):
        element = Gst.ElementFactory.make(factory, None)
        if element is None:
            raise RuntimeError(
                f"Missing GStreamer element '{factory}'. "
                "Are all gstreamer1.0-* plugins installed?"
            )
        return element

    def _watch_bus(self):
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_eos)

    def _on_error(self, _bus, message):
        err, debug = message.parse_error()
        detail = f"{err.message}"
        if debug:
            detail += f"\n{debug}"
        self.emit("error", detail)

    def _on_eos(self, _bus, _message):
        self.emit("error", "The device stopped sending data (end of stream).")

    def start(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None


class VideoPipeline(_BasePipeline):
    def __init__(self):
        super().__init__()
        self.paintable = None
        self._convert = None

    def build(self, device):
        """Build the pipeline for a Gst.Device and return its Gdk.Paintable."""
        self.stop()
        self.pipeline = Gst.Pipeline.new("video-pipeline")

        source = self._make_video_source(device)
        decode = self._make("decodebin")
        convert = self._make("videoconvert")
        queue = self._make("queue")
        queue.set_property("leaky", _LEAKY_DOWNSTREAM)
        queue.set_property("max-size-buffers", 3)
        queue.set_property("max-size-time", 0)
        queue.set_property("max-size-bytes", 0)
        sink = self._make("gtk4paintablesink")

        for element in (source, decode, convert, queue, sink):
            self.pipeline.add(element)

        if not source.link(decode):
            raise RuntimeError("Failed to link video source to decoder.")
        if not convert.link(queue) or not queue.link(sink):
            raise RuntimeError("Failed to link video conversion chain.")

        # decodebin exposes its output pad only once it knows the format.
        self._convert = convert
        decode.connect("pad-added", self._on_pad_added)

        self.paintable = sink.get_property("paintable")
        self._watch_bus()
        return self.paintable

    def _make_video_source(self, device):
        """Prefer a direct v4l2src.

        On PipeWire systems ``Gst.Device.create_element()`` for a capture card
        returns a ``pipewiresrc`` bound to the camera portal, which fails with
        "target not found" outside a portal session. The device still exposes
        its ``/dev/videoN`` path, so we drive ``v4l2src`` directly and only fall
        back to the device's own element if no path is available.
        """
        props = device.get_properties()
        path = None
        if props is not None:
            for key in ("api.v4l2.path", "device.path"):
                if props.has_field(key):
                    value = props.get_string(key)
                    if value and value.startswith("/dev/"):
                        path = value
                        break
        if path:
            source = Gst.ElementFactory.make("v4l2src", None)
            if source is not None:
                source.set_property("device", path)
                return source
        source = device.create_element(None)
        if source is None:
            raise RuntimeError("Could not create a source element for the video device.")
        return source

    def _on_pad_added(self, _decodebin, pad):
        sinkpad = self._convert.get_static_pad("sink")
        if sinkpad is None or sinkpad.is_linked():
            return
        # A decodebin src pad may not have its current caps set yet at the
        # moment it is added, so fall back to the pad's queried caps. Only
        # bail out if we can positively identify a non-video stream.
        caps = pad.get_current_caps() or pad.query_caps(None)
        if caps is not None and caps.get_size() > 0:
            name = caps.get_structure(0).get_name()
            if name and not name.startswith("video/"):
                return
        pad.link(sinkpad)


class AudioPipeline(_BasePipeline):
    def __init__(self):
        super().__init__()
        self._volume = None

    def build(self, device, volume=1.0, muted=False):
        self.stop()
        self.pipeline = Gst.Pipeline.new("audio-pipeline")

        source = device.create_element(None)
        if source is None:
            raise RuntimeError("Could not create a source element for the audio device.")
        queue = self._make("queue")
        queue.set_property("leaky", _LEAKY_DOWNSTREAM)
        queue.set_property("max-size-time", 100_000_000)  # 100 ms
        convert = self._make("audioconvert")
        resample = self._make("audioresample")
        volume_el = self._make("volume")
        sink = self._make("autoaudiosink")  # routes to the default output

        self._volume = volume_el
        volume_el.set_property("volume", float(volume))
        volume_el.set_property("mute", bool(muted))

        elements = [source, queue, convert, resample, volume_el, sink]
        for element in elements:
            self.pipeline.add(element)
        for upstream, downstream in zip(elements, elements[1:]):
            if not upstream.link(downstream):
                raise RuntimeError("Failed to link the audio pipeline.")

        self._watch_bus()

    def set_volume(self, value):
        if self._volume is not None:
            self._volume.set_property("volume", float(value))

    def set_muted(self, muted):
        if self._volume is not None:
            self._volume.set_property("mute", bool(muted))

    def stop(self):
        super().stop()
        self._volume = None
