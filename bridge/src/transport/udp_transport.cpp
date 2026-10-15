
#include "udp_transport.hpp"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <stdexcept>
#include <string>

namespace teleop {

UdpTransport::UdpTransport(int fd) : fd_(fd) {
    timeval timeout{};
    timeout.tv_sec = 0;
    timeout.tv_usec = 100000; // 100 ms

    if (::setsockopt(
            fd_,
            SOL_SOCKET,
            SO_RCVTIMEO,
            &timeout,
            sizeof(timeout)
        ) < 0) {
        throw std::runtime_error(
            "Failed to configure UDP receive timeout"
        );
    }
}

UdpTransport::~UdpTransport() {
    if (fd_ >= 0) {
        ::close(fd_);
    }
}

std::unique_ptr<UdpTransport> UdpTransport::create(
    const std::string& local_address,
    std::uint16_t local_port,
    const std::string& peer_address,
    std::uint16_t peer_port
) {
    int fd = ::socket(AF_INET, SOCK_DGRAM, 0);

    if (fd < 0) {
        throw std::runtime_error("UDP socket creation failed");
    }

    sockaddr_in local{};
    local.sin_family = AF_INET;
    local.sin_port = htons(local_port);

    sockaddr_in peer{};
    peer.sin_family = AF_INET;
    peer.sin_port = htons(peer_port);

    if (
        ::inet_pton(
            AF_INET, local_address.c_str(), &local.sin_addr
        ) != 1 ||
        ::inet_pton(
            AF_INET, peer_address.c_str(), &peer.sin_addr
        ) != 1
    ) {
        ::close(fd);
        throw std::runtime_error("Invalid UDP address");
    }

    if (::bind(
            fd,
            reinterpret_cast<sockaddr*>(&local),
            sizeof(local)
        ) < 0) {
        ::close(fd);
        throw std::runtime_error("UDP bind failed");
    }

    if (::connect(
            fd,
            reinterpret_cast<sockaddr*>(&peer),
            sizeof(peer)
        ) < 0) {
        ::close(fd);
        throw std::runtime_error("UDP connect failed");
    }

    return std::unique_ptr<UdpTransport>(
        new UdpTransport(fd)
    );
}

bool UdpTransport::send(
    const ByteBuffer& message,
    DeliveryMode mode
) {
    if (mode != DeliveryMode::Unreliable) {
        return false;
    }

    if (message.empty() || message.size() > MAX_DATAGRAM) {
        return false;
    }

    const ssize_t sent = ::send(
        fd_,
        message.data(),
        message.size(),
        MSG_NOSIGNAL
    );

    return sent == static_cast<ssize_t>(message.size());
}

bool UdpTransport::receive(ByteBuffer& message) {
    std::uint8_t buffer[MAX_DATAGRAM];

    while (running_.load()) {
        const ssize_t received = ::recv(
            fd_,
            buffer,
            sizeof(buffer),
            MSG_TRUNC
        );

        if (received < 0) {
            if (errno == EINTR ||
                errno == EAGAIN ||
                errno == EWOULDBLOCK) {
                continue;
            }

            return false;
        }

        if (
            received == 0 ||
            received > static_cast<ssize_t>(MAX_DATAGRAM)
        ) {
            continue;
        }

        if (!running_.load()) {
            return false;
        }

        message.assign(buffer, buffer + received);
        return true;
    }

    return false;
}

void UdpTransport::shutdown() {
    running_.store(false);
}

} // namespace teleop
