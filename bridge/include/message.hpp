
#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace teleop {

enum class MessageType : std::uint8_t {
    Video = 1,
    FastCommand = 2,
    ReliableCommand = 3,
    RobotState = 4,
    Query = 5,
    Reply = 6,
    ExecutionAck = 7
};

struct Message {
    MessageType type;
    std::uint8_t stream_id;
    std::uint64_t sequence;
    std::uint64_t timestamp_ns;
    std::vector<std::uint8_t> payload;
};

constexpr std::uint32_t MAGIC = 0x54454C31; // "TEL1"
constexpr std::size_t HEADER_SIZE = 26;
constexpr std::size_t MAX_PAYLOAD = 1024 * 1024;

// Timestamp from a monotonic clock.
// Suitable for elapsed-time measurements on one machine.
inline std::uint64_t now_ns() {
    using namespace std::chrono;

    return static_cast<std::uint64_t>(
        duration_cast<nanoseconds>(
            steady_clock::now().time_since_epoch()
        ).count()
    );
}

// Write an integer in network byte order (big-endian).
inline void write_uint(
    std::vector<std::uint8_t>& out,
    std::uint64_t value,
    int bytes
) {
    for (int i = bytes - 1; i >= 0; --i) {
        out.push_back(static_cast<std::uint8_t>(
            (value >> (i * 8)) & 0xFF
        ));
    }
}

// Read an unsigned integer in network byte order.
inline std::uint64_t read_uint(
    const std::vector<std::uint8_t>& data,
    std::size_t& offset,
    int bytes
) {
    if (offset + bytes > data.size()) {
        throw std::runtime_error("Truncated message");
    }

    std::uint64_t value = 0;

    for (int i = 0; i < bytes; ++i) {
        value = (value << 8) | data[offset++];
    }

    return value;
}

inline std::vector<std::uint8_t> serialize(
    const Message& msg
) {
    if (msg.payload.size() > MAX_PAYLOAD) {
        throw std::runtime_error("Payload too large");
    }

    std::vector<std::uint8_t> result;
    result.reserve(HEADER_SIZE + msg.payload.size());

    write_uint(result, MAGIC, 4);
    result.push_back(static_cast<std::uint8_t>(msg.type));
    result.push_back(msg.stream_id);
    write_uint(result, msg.sequence, 8);
    write_uint(result, msg.timestamp_ns, 8);
    write_uint(result, msg.payload.size(), 4);

    result.insert(
        result.end(),
        msg.payload.begin(),
        msg.payload.end()
    );

    return result;
}

inline Message deserialize(
    const std::vector<std::uint8_t>& data
) {
    if (data.size() < HEADER_SIZE) {
        throw std::runtime_error("Message too short");
    }

    std::size_t offset = 0;

    auto magic = read_uint(data, offset, 4);

    if (magic != MAGIC) {
        throw std::runtime_error("Invalid magic/version");
    }

    Message msg{};

    msg.type = static_cast<MessageType>(
        read_uint(data, offset, 1)
    );

    msg.stream_id = static_cast<std::uint8_t>(
        read_uint(data, offset, 1)
    );

    msg.sequence = read_uint(data, offset, 8);
    msg.timestamp_ns = read_uint(data, offset, 8);

    auto payload_size = read_uint(data, offset, 4);

    if (payload_size > MAX_PAYLOAD ||
        payload_size != data.size() - HEADER_SIZE) {
        throw std::runtime_error("Invalid payload length");
    }

    msg.payload.assign(
        data.begin() + offset,
        data.end()
    );

    return msg;
}

} // namespace teleop
