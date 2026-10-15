import time
import av


class FrameDecoder:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.decoder = av.CodecContext.create("h264", "r")

        self.decoded = 0
        self.failed = 0
        self.unmatched = 0

    def decode(self, complete_frame):
        try:
            packet = av.Packet(complete_frame.data)
            images = self.decoder.decode(packet)
        except av.FFmpegError:
            self.failed += 1
            return None

        # This test expects one decoded image per
        # access unit, without decoder reordering.
        if len(images) != 1:
            self.unmatched += 1
            return None

        image = images[0]

        if (
            image.width != self.width
            or image.height != self.height
        ):
            self.failed += 1
            return None

        decoded_ns = time.monotonic_ns()

        latency_ms = (
            decoded_ns - complete_frame.capture_ns
        ) / 1e6

        self.decoded += 1

        return {
            "stream_id": complete_frame.stream_id,
            "frame_id": complete_frame.frame_id,
            "capture_ns": complete_frame.capture_ns,
            "reassembly_ns": complete_frame.completed_ns,
            "decoded_ns": decoded_ns,
            "latency_ms": latency_ms,
            "within_200ms": latency_ms <= 200.0,
        }
