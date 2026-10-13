
"""Video frame fragmentation and reassembly.

This format is carried inside the existing zenoh Video payload.
The C++ bridge's TEL1 header is separate.
"""

import math
import struct
import time
import zlib
from dataclasses import dataclass, field

MAGIC = b"VFR1"
VERSION = 1

HEAD = 1
LEFT_WRIST = 2
RIGHT_WRIST = 3

# magic, version, stream_id, frame_id, capture_ns,
# fragment_index, fragment_count, frame_size, CRC32
HEADER = struct.Struct("!4sBBQQHHII")

FRAGMENT_DATA_SIZE = 1000
MAX_FRAME_SIZE = 1_000_000
MAX_FRAGMENTS = math.ceil(
    MAX_FRAME_SIZE / FRAGMENT_DATA_SIZE
)
FRAME_DEADLINE_NS = 200_000_000


@dataclass(frozen=True)
class CompleteFrame:
    stream_id: int
    frame_id: int
    capture_ns: int
    completed_ns: int
    data: bytes

    @property
    def latency_ms(self):
        return (
            self.completed_ns - self.capture_ns
        ) / 1e6


@dataclass
class PendingFrame:
    stream_id: int
    frame_id: int
    capture_ns: int
    fragment_count: int
    frame_size: int
    crc32: int
    fragments: dict = field(default_factory=dict)


def fragment_frame(
    data,
    stream_id,
    frame_id,
    capture_ns=None,
):
    """Split one encoded frame into transport fragments."""
    if capture_ns is None:
        capture_ns = time.monotonic_ns()

    if not isinstance(data, bytes):
        raise TypeError("Frame data must be bytes")

    if not 1 <= stream_id <= 255:
        raise ValueError("Invalid stream ID")

    if not 0 <= frame_id < 2**64:
        raise ValueError("Invalid frame ID")

    if not 0 <= capture_ns < 2**64:
        raise ValueError("Invalid capture timestamp")

    if not 0 < len(data) <= MAX_FRAME_SIZE:
        raise ValueError("Invalid frame size")

    count = math.ceil(
        len(data) / FRAGMENT_DATA_SIZE
    )

    checksum = zlib.crc32(data)

    packets = []

    for index in range(count):
        start = index * FRAGMENT_DATA_SIZE
        chunk = data[
            start:start + FRAGMENT_DATA_SIZE
        ]

        header = HEADER.pack(
            MAGIC,
            VERSION,
            stream_id,
            frame_id,
            capture_ns,
            index,
            count,
            len(data),
            checksum,
        )

        packets.append(header + chunk)

    return packets


class FrameReassembler:
    """Reassemble frames with a 200 ms capture deadline."""

    def __init__(self, deadline_ns=FRAME_DEADLINE_NS):
        self.deadline_ns = deadline_ns
        self.pending = {}
        self.closed = {}

        self.completed = 0
        self.expired = 0
        self.invalid = 0

    def _close(self, key, capture_ns):
        # Prevent retransmitted or late fragments from
        # recreating an already completed/expired frame.
        self.closed[key] = capture_ns

    def expire(self, now_ns=None):
        if now_ns is None:
            now_ns = time.monotonic_ns()

        for key, frame in list(self.pending.items()):
            if now_ns - frame.capture_ns > self.deadline_ns:
                del self.pending[key]
                self._close(key, frame.capture_ns)
                self.expired += 1

        # Retain recent closed IDs long enough to reject
        # late fragments, but bound metadata growth.
        retention_ns = 10_000_000_000

        for key, capture_ns in list(self.closed.items()):
            if now_ns - capture_ns > retention_ns:
                del self.closed[key]

    def push(self, packet, received_ns=None):
        """Return CompleteFrame when all fragments arrive."""
        if received_ns is None:
            received_ns = time.monotonic_ns()

        self.expire(received_ns)

        if len(packet) <= HEADER.size:
            self.invalid += 1
            return None

        try:
            (
                magic,
                version,
                stream_id,
                frame_id,
                capture_ns,
                index,
                count,
                frame_size,
                checksum,
            ) = HEADER.unpack_from(packet)
        except struct.error:
            self.invalid += 1
            return None

        chunk = packet[HEADER.size:]

        if (
            magic != MAGIC
            or version != VERSION
            or stream_id not in (
                HEAD, LEFT_WRIST, RIGHT_WRIST
            )
            or count == 0
            or count > MAX_FRAGMENTS
            or index >= count
            or frame_size == 0
            or frame_size > MAX_FRAME_SIZE
            or count != math.ceil(
                frame_size / FRAGMENT_DATA_SIZE
            )
            or len(chunk) != (
                FRAGMENT_DATA_SIZE
                if index < count - 1
                else frame_size -
                    (count - 1) * FRAGMENT_DATA_SIZE
            )
        ):
            self.invalid += 1
            return None

        key = (stream_id, frame_id)

        if key in self.closed:
            return None

        if received_ns - capture_ns > self.deadline_ns:
            self._close(key, capture_ns)
            self.expired += 1
            return None

        frame = self.pending.get(key)

        if frame is None:
            frame = PendingFrame(
                stream_id=stream_id,
                frame_id=frame_id,
                capture_ns=capture_ns,
                fragment_count=count,
                frame_size=frame_size,
                crc32=checksum,
            )
            self.pending[key] = frame

        elif (
            frame.capture_ns != capture_ns
            or frame.fragment_count != count
            or frame.frame_size != frame_size
            or frame.crc32 != checksum
        ):
            self.invalid += 1
            return None

        # Ignore duplicate fragments. Do not let them
        # inflate the number of received fragments.
        if index in frame.fragments:
            if frame.fragments[index] != chunk:
                self.invalid += 1
            return None

        frame.fragments[index] = chunk

        if len(frame.fragments) != count:
            return None

        data = b"".join(
            frame.fragments[i]
            for i in range(count)
        )

        del self.pending[key]
        self._close(key, capture_ns)

        if (
            len(data) != frame_size
            or zlib.crc32(data) != checksum
        ):
            self.invalid += 1
            return None

        # All fragments arrived within the deadline.
        self.completed += 1

        return CompleteFrame(
            stream_id=stream_id,
            frame_id=frame_id,
            capture_ns=capture_ns,
            completed_ns=received_ns,
            data=data,
        )
