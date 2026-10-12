
#pragma once

#include <cstdint>
#include <vector>

namespace teleop {

using ByteBuffer = std::vector<std::uint8_t>;

enum class DeliveryMode {
    Unreliable,
    ReliableOrdered
};

class ITransport {
public:
    virtual ~ITransport() = default;

    // Transmit one serialized application message.
    // true does NOT mean the remote application executed it.
    virtual bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) = 0;

    // Receive one complete serialized message.
    // Returns false when the connection closes or fails.
    virtual bool receive(ByteBuffer& message) = 0;

    // Interrupt a blocked receive during shutdown.
    virtual void shutdown() = 0;
};

} // namespace teleop
