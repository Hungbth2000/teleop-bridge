
#pragma once

#include "message.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>

namespace teleop {

struct VideoFrameId {
    std::uint8_t stream_id;
    std::uint64_t frame_id;

    bool operator==(const VideoFrameId& other) const {
        return stream_id == other.stream_id &&
               frame_id == other.frame_id;
    }
};

inline std::optional<VideoFrameId> video_frame_id(
    const ByteBuffer& message
) {
    // TEL1 header: 26 bytes.
    // VFR1 header: 34 bytes.
    constexpr std::size_t VIDEO_HEADER_SIZE = 34;

    if (message.size() < HEADER_SIZE + VIDEO_HEADER_SIZE) {
        return std::nullopt;
    }

    if (message[0] != 'T' ||
        message[1] != 'E' ||
        message[2] != 'L' ||
        message[3] != '1' ||
        message[4] != static_cast<std::uint8_t>(
            MessageType::Video
        )) {
        return std::nullopt;
    }

    const std::size_t offset = HEADER_SIZE;

    if (message[offset] != 'V' ||
        message[offset + 1] != 'F' ||
        message[offset + 2] != 'R' ||
        message[offset + 3] != '1') {
        return std::nullopt;
    }

    // VFR1:
    // bytes 0-3: magic
    // byte 4: version
    // byte 5: camera stream ID
    // bytes 6-13: frame ID (big-endian)
    if (message[offset + 4] != 1) {
        return std::nullopt;
    }

    std::uint64_t frame_id = 0;

    for (std::size_t i = 0; i < 8; ++i) {
        frame_id =
            (frame_id << 8) |
            message[offset + 6 + i];
    }

    return VideoFrameId{
        message[offset + 5],
        frame_id
    };
}

} // namespace teleop
