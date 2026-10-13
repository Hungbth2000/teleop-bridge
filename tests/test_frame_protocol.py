
import unittest

from mock.video.frame_protocol import (
    HEAD,
    LEFT_WRIST,
    FRAME_DEADLINE_NS,
    FrameReassembler,
    fragment_frame,
)


class FrameProtocolTests(unittest.TestCase):

    def test_single_fragment(self):
        data = b"A" * 500
        capture_ns = 1_000_000_000

        packets = fragment_frame(
            data, HEAD, 1, capture_ns
        )

        self.assertEqual(len(packets), 1)

        receiver = FrameReassembler()
        result = receiver.push(
            packets[0],
            received_ns=capture_ns + 5_000_000,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.data, data)
        self.assertEqual(result.latency_ms, 5.0)

    def test_multiple_fragments_out_of_order(self):
        data = bytes(range(256)) * 20
        capture_ns = 2_000_000_000

        packets = fragment_frame(
            data, HEAD, 2, capture_ns
        )

        receiver = FrameReassembler()
        result = None

        for packet in reversed(packets):
            completed = receiver.push(
                packet,
                received_ns=capture_ns + 20_000_000,
            )
            if completed is not None:
                result = completed

        self.assertIsNotNone(result)
        self.assertEqual(result.data, data)

    def test_missing_fragment_expires(self):
        data = b"B" * 3000
        capture_ns = 3_000_000_000

        packets = fragment_frame(
            data, LEFT_WRIST, 3, capture_ns
        )

        receiver = FrameReassembler()

        receiver.push(
            packets[0],
            received_ns=capture_ns + 10_000_000,
        )

        receiver.expire(
            capture_ns + FRAME_DEADLINE_NS + 1
        )

        self.assertEqual(receiver.completed, 0)
        self.assertEqual(receiver.expired, 1)

    def test_duplicate_fragment_is_ignored(self):
        data = b"C" * 2500
        capture_ns = 4_000_000_000

        packets = fragment_frame(
            data, HEAD, 4, capture_ns
        )

        receiver = FrameReassembler()

        receiver.push(
            packets[0],
            received_ns=capture_ns + 5_000_000,
        )
        receiver.push(
            packets[0],
            received_ns=capture_ns + 6_000_000,
        )

        result = None

        for packet in packets[1:]:
            result = receiver.push(
                packet,
                received_ns=capture_ns + 7_000_000,
            )

        self.assertIsNotNone(result)
        self.assertEqual(receiver.completed, 1)
        self.assertEqual(result.data, data)

    def test_late_complete_frame_rejected(self):
        data = b"D" * 1800
        capture_ns = 5_000_000_000

        packets = fragment_frame(
            data, HEAD, 5, capture_ns
        )

        receiver = FrameReassembler()

        for packet in packets:
            result = receiver.push(
                packet,
                received_ns=(
                    capture_ns +
                    FRAME_DEADLINE_NS + 1
                ),
            )
            self.assertIsNone(result)

        self.assertEqual(receiver.completed, 0)
        self.assertEqual(receiver.expired, 1)

    def test_corrupt_fragment_rejected(self):
        data = b"E" * 2200
        capture_ns = 6_000_000_000

        packets = fragment_frame(
            data, HEAD, 6, capture_ns
        )

        corrupted = bytearray(packets[1])
        corrupted[-1] ^= 0x01
        packets[1] = bytes(corrupted)

        receiver = FrameReassembler()

        result = None

        for packet in packets:
            result = receiver.push(
                packet,
                received_ns=capture_ns + 8_000_000,
            )

        self.assertIsNone(result)
        self.assertEqual(receiver.completed, 0)
        self.assertEqual(receiver.invalid, 1)


if __name__ == "__main__":
    unittest.main()
