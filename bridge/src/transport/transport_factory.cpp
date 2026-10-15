#include "transport_factory.hpp"
#include "hybrid_transport.hpp"
#include "tcp_transport.hpp"
#include "udp_transport.hpp"
#include "quic_transport.hpp"
#include "kcp_transport.hpp"

namespace teleop {

int TransportFactory::create_server(
    int port,
    const char* bind_address
) {
    return TcpTransport::create_server(
        port,
        bind_address
    );
}

std::unique_ptr<ITransport>
TransportFactory::accept_client(int server_fd) {
    return TcpTransport::accept_client(server_fd);
}

std::unique_ptr<ITransport>
TransportFactory::connect_to(
    const char* address,
    int port
) {
    return TcpTransport::connect_to(
        address,
        port
    );
}


std::unique_ptr<ITransport>
TransportFactory::accept_hybrid(
    int server_fd,
    const std::string& local_udp_address,
    const std::string& peer_udp_address,
    std::uint16_t udp_port
) {
    // Preserve the existing TCP acceptance behavior.
    auto tcp = TcpTransport::accept_client(server_fd);

    if (!tcp) {
        return nullptr;
    }

    // Create the independent best-effort lane.
    // If UDP initialization fails, the TCP transport
    // is destroyed automatically.
    auto udp = UdpTransport::create(
        local_udp_address,
        udp_port,
        peer_udp_address,
        udp_port
    );

    return std::make_unique<HybridTransport>(
        std::move(tcp),
        std::move(udp)
    );
}

std::unique_ptr<ITransport>
TransportFactory::connect_hybrid(
    const char* tcp_address,
    int tcp_port,
    const std::string& local_udp_address,
    const std::string& peer_udp_address,
    std::uint16_t udp_port
) {
    auto tcp = TcpTransport::connect_to(
        tcp_address,
        tcp_port
    );

    if (!tcp) {
        return nullptr;
    }

    auto udp = UdpTransport::create(
        local_udp_address,
        udp_port,
        peer_udp_address,
        udp_port
    );

    return std::make_unique<HybridTransport>(
        std::move(tcp),
        std::move(udp)
    );
}

std::unique_ptr<ITransport>
TransportFactory::accept_kcp(
    const std::string& local_address,
    const std::string& peer_address,
    std::uint16_t port
) {
    return KcpTransport::accept(
        local_address, peer_address, port
    );
}

std::unique_ptr<ITransport>
TransportFactory::connect_kcp(
    const std::string& local_address,
    const std::string& peer_address,
    std::uint16_t port
) {
    return KcpTransport::connect(
        local_address, peer_address, port
    );
}

std::unique_ptr<ITransport>
TransportFactory::accept_quic(
    const char* bind_address,
    std::uint16_t port,
    const char* certificate_file,
    const char* private_key_file
) {
    return QuicTransport::accept(
        bind_address,
        port,
        certificate_file,
        private_key_file
    );
}

std::unique_ptr<ITransport>
TransportFactory::connect_quic(
    const char* server_address,
    std::uint16_t port
) {
    return QuicTransport::connect(
        server_address,
        port
    );
}

std::unique_ptr<ITransport>
TransportFactory::accept_hybrid_quic(
    const std::string& local,
    const std::string& peer,
    const char* certificate_file,
    const char* private_key_file
) {
    auto reliable = QuicTransport::accept(
        local.c_str(), 9002,
        certificate_file, private_key_file
    );

    if (!reliable) {
        return nullptr;
    }

    auto realtime = UdpTransport::create(
        local, 9001, peer, 9001
    );

    if (!realtime) {
        return nullptr;
    }

    return std::make_unique<HybridTransport>(
        std::move(reliable),
        std::move(realtime)
    );
}

std::unique_ptr<ITransport>
TransportFactory::connect_hybrid_quic(
    const std::string& local,
    const std::string& peer
) {
    auto reliable = QuicTransport::connect(
        peer.c_str(), 9002
    );

    if (!reliable) {
        return nullptr;
    }

    auto realtime = UdpTransport::create(
        local, 9001, peer, 9001
    );

    if (!realtime) {
        return nullptr;
    }

    return std::make_unique<HybridTransport>(
        std::move(reliable),
        std::move(realtime)
    );
}

std::unique_ptr<ITransport>
TransportFactory::accept_hybrid_kcp(
    const std::string& local,
    const std::string& peer
) {
    auto reliable = KcpTransport::accept(
        local, peer, 9003
    );

    if (!reliable) {
        return nullptr;
    }

    auto realtime = UdpTransport::create(
        local, 9001, peer, 9001
    );

    if (!realtime) {
        return nullptr;
    }

    return std::make_unique<HybridTransport>(
        std::move(reliable),
        std::move(realtime)
    );
}

std::unique_ptr<ITransport>
TransportFactory::connect_hybrid_kcp(
    const std::string& local,
    const std::string& peer
) {
    auto reliable = KcpTransport::connect(
        local, peer, 9003
    );

    if (!reliable) {
        return nullptr;
    }

    auto realtime = UdpTransport::create(
        local, 9001, peer, 9001
    );

    if (!realtime) {
        return nullptr;
    }

    return std::make_unique<HybridTransport>(
        std::move(reliable),
        std::move(realtime)
    );
}

} // namespace teleop