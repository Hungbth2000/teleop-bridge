
#include "quic_transport.hpp"

#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

using teleop::ByteBuffer;
using teleop::DeliveryMode;
using teleop::QuicTransport;

constexpr int MESSAGE_COUNT = 100;

ByteBuffer make_message(int index) {
    const std::string text =
        "message-" + std::to_string(index) + "-" +
        std::string(index % 97 + 1, 'x');

    return ByteBuffer(text.begin(), text.end());
}

int main() {
    bool server_ok = false;
    bool client_ok = false;

    std::thread server([&] {
        try {
            auto transport = QuicTransport::accept(
                "127.0.0.1",
                9002,
                "certs/quic-server.crt",
                "certs/quic-server.key"
            );

            if (!transport) {
                return;
            }

            server_ok = true;

            for (int i = 0; i < MESSAGE_COUNT; ++i) {
                ByteBuffer received;

                if (!transport->receive(received) ||
                    received != make_message(i)) {
                    std::cerr
                        << "[server] Mismatch at message "
                        << i << '\n';
                    server_ok = false;
                    return;
                }
            }

            std::cout
                << "[server] Received "
                << MESSAGE_COUNT
                << " messages in order\n";

            const std::string reply = "all-messages-received";

            server_ok = transport->send(
                ByteBuffer(reply.begin(), reply.end()),
                DeliveryMode::ReliableOrdered
            );

            std::this_thread::sleep_for(
                std::chrono::milliseconds(300)
            );
        } catch (const std::exception& e) {
            std::cerr << "[server] " << e.what() << '\n';
            server_ok = false;
        }
    });

    std::this_thread::sleep_for(
        std::chrono::milliseconds(500)
    );

    try {
        auto transport = QuicTransport::connect(
            "127.0.0.1", 9002
        );

        if (transport) {
            client_ok = true;

            for (int i = 0; i < MESSAGE_COUNT; ++i) {
                if (!transport->send(
                        make_message(i),
                        DeliveryMode::ReliableOrdered
                    )) {
                    std::cerr
                        << "[client] Send failed at "
                        << i << '\n';
                    client_ok = false;
                    break;
                }
            }

            if (client_ok) {
                ByteBuffer reply;

                client_ok =
                    transport->receive(reply) &&
                    std::string(reply.begin(), reply.end()) ==
                        "all-messages-received";
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "[client] " << e.what() << '\n';
        client_ok = false;
    }

    server.join();

    if (server_ok && client_ok) {
        std::cout << "[TEST] PASS\n";
        return 0;
    }

    std::cerr << "[TEST] FAIL\n";
    return 1;
}
