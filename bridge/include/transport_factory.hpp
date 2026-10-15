
#pragma once

#include "transport.hpp"

#include <cstdint>
#include <memory>
#include <string>

namespace teleop {

class TransportFactory {
public:
    // Existing TCP-only methods.
    static int create_server(
        int port,
        const char* bind_address
    );

    static std::unique_ptr<ITransport> accept_client(
        int server_fd
    );

    static std::unique_ptr<ITransport> connect_to(
        const char* address,
        int port
    );

    // Hybrid: TCP for reliable messages,
    // UDP for best-effort messages.
    static std::unique_ptr<ITransport> accept_hybrid(
        int server_fd,
        const std::string& local_udp_address,
        const std::string& peer_udp_address,
        std::uint16_t udp_port = 9001
    );

    static std::unique_ptr<ITransport> connect_hybrid(
        const char* tcp_address,
        int tcp_port,
        const std::string& local_udp_address,
        const std::string& peer_udp_address,
        std::uint16_t udp_port = 9001
    );

    // KCP: reliable message delivery over UDP.
    static std::unique_ptr<ITransport> accept_kcp(
        const std::string& local_address,
        const std::string& peer_address,
        std::uint16_t port = 9003
    );

    static std::unique_ptr<ITransport> connect_kcp(
        const std::string& local_address,
        const std::string& peer_address,
        std::uint16_t port = 9003
    );

    // QUIC: reliable streams and unreliable datagrams.
    static std::unique_ptr<ITransport> accept_quic(
        const char* bind_address,
        std::uint16_t port,
        const char* certificate_file,
        const char* private_key_file
    );

    static std::unique_ptr<ITransport> connect_quic(
        const char* server_address,
        std::uint16_t port
    );

    // Hybrid QUIC/UDP.
    static std::unique_ptr<ITransport> accept_hybrid_quic(
        const std::string& local_udp_address,
        const std::string& peer_udp_address,
        const char* certificate_file,
        const char* private_key_file
    );

    static std::unique_ptr<ITransport> connect_hybrid_quic(
        const std::string& local_udp_address,
        const std::string& peer_udp_address
    );

    // Hybrid KCP/UDP.
    static std::unique_ptr<ITransport> accept_hybrid_kcp(
        const std::string& local_udp_address,
        const std::string& peer_udp_address
    );

    static std::unique_ptr<ITransport> connect_hybrid_kcp(
        const std::string& local_udp_address,
        const std::string& peer_udp_address
    );
};

} // namespace teleop
