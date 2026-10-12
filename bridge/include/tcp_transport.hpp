
#pragma once

#include "transport.hpp"

#include <memory>

namespace teleop {

class TcpTransport final : public ITransport {
public:
    explicit TcpTransport(int fd);
    ~TcpTransport() override;

    TcpTransport(const TcpTransport&) = delete;
    TcpTransport& operator=(const TcpTransport&) = delete;

    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override;

    bool receive(ByteBuffer& message) override;

    void shutdown() override;

    // Operator-side TCP listener.
    static int create_server(int port);

    // Accept one robot bridge connection.
    static std::unique_ptr<TcpTransport> accept_client(
        int server_fd
    );

    // Robot-side outbound connection.
    static std::unique_ptr<TcpTransport> connect_to(
        const char* address,
        int port
    );

private:
    int fd_;

    static bool send_all(
        int fd, const void* data, std::size_t size
    );

    static bool recv_all(
        int fd, void* data, std::size_t size
    );

    static void configure_low_latency(int fd);
};

} // namespace teleop
