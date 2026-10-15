#include "transport_factory.hpp"
#include "hybrid_transport.hpp"
#include "tcp_transport.hpp"
#include "udp_transport.hpp"

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


} // namespace teleop