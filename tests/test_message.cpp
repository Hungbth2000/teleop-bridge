
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

#include "message.hpp"

int main() {
    using namespace teleop;

    Message original{
        MessageType::Video,
        1,
        105,
        now_ns(),
        {0x00, 0x01, 0xFF, 0x00, 0x48, 0x49}
    };

    auto encoded = serialize(original);

    assert(
        encoded.size() ==
        HEADER_SIZE + original.payload.size()
    );

    auto decoded = deserialize(encoded);

    assert(decoded.type == original.type);
    assert(decoded.stream_id == original.stream_id);
    assert(decoded.sequence == original.sequence);
    assert(decoded.timestamp_ns == original.timestamp_ns);
    assert(decoded.payload == original.payload);

    // Test rejection of an incomplete message.
    bool rejected = false;

    try {
        auto truncated = encoded;
        truncated.pop_back();
        deserialize(truncated);
    } catch (const std::runtime_error&) {
        rejected = true;
    }

    assert(rejected);

    std::cout
        << "Message serialization tests passed!\n"
        << "Header size: " << HEADER_SIZE << " bytes\n"
        << "Encoded size: " << encoded.size() << " bytes\n"
        << "Sequence: " << decoded.sequence << '\n';

    return 0;
}
