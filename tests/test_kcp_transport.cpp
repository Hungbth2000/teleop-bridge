#include "kcp_transport.hpp"

#include <cassert>
#include <chrono>
#include <future>
#include <iostream>
#include <memory>
#include <thread>

using namespace teleop;
using namespace std::chrono_literals;

int main() {
    // Both addresses are loopback, but distinct, allowing
    // each endpoint to bind the same UDP port.
    auto server_future = std::async(
        std::launch::async,
        [] {
            return KcpTransport::accept(
                "127.0.0.1", "127.0.0.2", 19003
            );
        }
    );

    std::this_thread::sleep_for(100ms);

    auto client = KcpTransport::connect(
        "127.0.0.2", "127.0.0.1", 19003
    );

    assert(client && "KCP client handshake failed");

    auto server = server_future.get();
    assert(server && "KCP server handshake failed");

    const ByteBuffer client_message{'H', 'e', 'l', 'l', 'o'};
    const ByteBuffer server_message{'W', 'o', 'r', 'l', 'd'};

    assert(client->send(
        client_message, DeliveryMode::ReliableOrdered
    ));

    ByteBuffer received;
    assert(server->receive(received));
    assert(received == client_message);

    assert(server->send(
        server_message, DeliveryMode::ReliableOrdered
    ));

    received.clear();
    assert(client->receive(received));
    assert(received == server_message);

    client->shutdown();
    server->shutdown();

    std::cout << "KCP bidirectional exchange passed\n";
    return 0;
}
