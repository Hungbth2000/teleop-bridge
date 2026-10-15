
#include "quic_transport.hpp"

#include <chrono>
#include <exception>
#include <iostream>
#include <string>
#include <thread>

using teleop::ByteBuffer;
using teleop::DeliveryMode;
using teleop::QuicTransport;

ByteBuffer make_bytes(const std::string& text) {
    return ByteBuffer(text.begin(), text.end());
}

std::string to_text(const ByteBuffer& data) {
    return std::string(data.begin(), data.end());
}

bool send_datagram(
    QuicTransport& transport,
    const std::string& text
) {
    // Allow time for DATAGRAM negotiation.
    for (int attempt = 0; attempt < 100; ++attempt) {
        if (transport.send(
                make_bytes(text),
                DeliveryMode::Unreliable
            )) {
            return true;
        }

        std::this_thread::sleep_for(
            std::chrono::milliseconds(20)
        );
    }

    return false;
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

            ByteBuffer received;

            if (!transport->receive(received)) {
                std::cerr << "[server] Receive failed\n";
                return;
            }

            std::cout
                << "[server] Received: "
                << to_text(received) << '\n';

            if (to_text(received) != "robot-motion-123") {
                return;
            }

            server_ok = send_datagram(
                *transport,
                "operator-datagram-reply"
            );

            // Allow the asynchronous send to progress.
            std::this_thread::sleep_for(
                std::chrono::milliseconds(500)
            );
        } catch (const std::exception& e) {
            std::cerr
                << "[server] Error: "
                << e.what() << '\n';
        }
    });

    std::this_thread::sleep_for(
        std::chrono::milliseconds(500)
    );

    try {
        auto transport = QuicTransport::connect(
            "127.0.0.1",
            9002
        );

        if (transport) {
            const bool sent = send_datagram(
                *transport,
                "robot-motion-123"
            );

            std::cout
                << "[client] DATAGRAM send accepted: "
                << sent << '\n';

            ByteBuffer response;

            if (sent && transport->receive(response)) {
                std::cout
                    << "[client] Received: "
                    << to_text(response) << '\n';

                client_ok =
                    to_text(response) ==
                    "operator-datagram-reply";
            }
        }
    } catch (const std::exception& e) {
        std::cerr
            << "[client] Error: "
            << e.what() << '\n';
    }

    server.join();

    if (server_ok && client_ok) {
        std::cout << "[TEST] PASS\n";
        return 0;
    }

    std::cerr << "[TEST] FAIL\n";
    return 1;
}
