
#pragma once

#include "transport.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <atomic>

namespace teleop {

class UdpTransport final : public ITransport {
public:
    static constexpr std::size_t MAX_DATAGRAM = 1200;

    // Bind a local UDP endpoint and connect to a fixed peer.
    static std::unique_ptr<UdpTransport> create(
        const std::string& local_address,
        std::uint16_t local_port,
        const std::string& peer_address,
        std::uint16_t peer_port
    );

    ~UdpTransport() override;

    UdpTransport(const UdpTransport&) = delete;
    UdpTransport& operator=(const UdpTransport&) = delete;

    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override;

    bool receive(ByteBuffer& message) override;

    void shutdown() override;

private:

    std::atomic<bool> running_{true};

    explicit UdpTransport(int fd);

    int fd_;
};

} // namespace teleop
