
#include "tcp_transport.hpp"

#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <iostream>
#include <stdexcept>

namespace teleop {

namespace {

// 26-byte application header + up to 1 MiB payload.
constexpr std::uint32_t MAX_WIRE_SIZE =
    26 + 1024 * 1024;

} // namespace

TcpTransport::TcpTransport(int fd) : fd_(fd) {
    configure_low_latency(fd_);
}

TcpTransport::~TcpTransport() {
    if (fd_ >= 0) {
        ::close(fd_);
    }
}

void TcpTransport::configure_low_latency(int fd) {
    int enabled = 1;

    if (::setsockopt(
            fd, IPPROTO_TCP, TCP_NODELAY,
            &enabled, sizeof(enabled)
        ) < 0) {
        perror("TCP_NODELAY");
    }
}

bool TcpTransport::send_all(
    int fd, const void* data, std::size_t size
) {
    const auto* ptr =
        static_cast<const std::uint8_t*>(data);

    while (size > 0) {
        ssize_t n = ::send(fd, ptr, size, MSG_NOSIGNAL);

        if (n < 0 && errno == EINTR) {
            continue;
        }

        if (n <= 0) {
            return false;
        }

        ptr += n;
        size -= static_cast<std::size_t>(n);
    }

    return true;
}

bool TcpTransport::recv_all(
    int fd, void* data, std::size_t size
) {
    auto* ptr = static_cast<std::uint8_t*>(data);

    while (size > 0) {
        ssize_t n = ::recv(fd, ptr, size, 0);

        if (n < 0 && errno == EINTR) {
            continue;
        }

        if (n <= 0) {
            return false;
        }

        ptr += n;
        size -= static_cast<std::size_t>(n);
    }

    return true;
}

bool TcpTransport::send(
    const ByteBuffer& message,
    DeliveryMode mode
) {
    // TCP always provides reliable ordered bytes.
    // We retain mode for the common transport interface.
    (void)mode;

    if (message.size() > MAX_WIRE_SIZE) {
        std::cerr << "[tcp] Message too large\n";
        return false;
    }

    const auto size = static_cast<std::uint32_t>(
        message.size()
    );

    const std::uint32_t network_size = htonl(size);

    return send_all(
               fd_, &network_size, sizeof(network_size)
           ) &&
           send_all(
               fd_, message.data(), message.size()
           );
}

bool TcpTransport::receive(ByteBuffer& message) {
    std::uint32_t network_size = 0;

    if (!recv_all(
            fd_, &network_size, sizeof(network_size)
        )) {
        return false;
    }

    std::uint32_t size = ntohl(network_size);

    if (size == 0 || size > MAX_WIRE_SIZE) {
        std::cerr << "[tcp] Invalid message length\n";
        return false;
    }

    message.resize(size);

    return recv_all(fd_, message.data(), size);
}

void TcpTransport::shutdown() {
    if (fd_ >= 0) {
        ::shutdown(fd_, SHUT_RDWR);
    }
}

int TcpTransport::create_server(
    int port,
    const char* bind_address
) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);

    if (fd < 0) {
        throw std::runtime_error("TCP socket failed");
    }

    int reuse = 1;
    ::setsockopt(
        fd, SOL_SOCKET, SO_REUSEADDR,
        &reuse, sizeof(reuse)
    );

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (::inet_pton(
        AF_INET, bind_address, &addr.sin_addr
        ) != 1 ||
        ::bind(
            fd,
            reinterpret_cast<sockaddr*>(&addr),
            sizeof(addr)
        ) < 0 ||
        ::listen(fd, 1) < 0) {
        ::close(fd);
        throw std::runtime_error(
            "TCP bind/listen failed"
        );
    }

    return fd;
}

std::unique_ptr<TcpTransport>
TcpTransport::accept_client(int server_fd) {
    int fd;

    do {
        fd = ::accept(server_fd, nullptr, nullptr);
    } while (fd < 0 && errno == EINTR);

    if (fd < 0) {
        return nullptr;
    }

    return std::make_unique<TcpTransport>(fd);
}

std::unique_ptr<TcpTransport>
TcpTransport::connect_to(
    const char* address,
    int port
) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);

    if (fd < 0) {
        return nullptr;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (::inet_pton(
            AF_INET, address, &addr.sin_addr
        ) != 1 ||
        ::connect(
            fd,
            reinterpret_cast<sockaddr*>(&addr),
            sizeof(addr)
        ) < 0) {
        ::close(fd);
        return nullptr;
    }

    return std::make_unique<TcpTransport>(fd);
}

} // namespace teleop
