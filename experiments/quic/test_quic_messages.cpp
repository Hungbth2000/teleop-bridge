
#include "quic_transport.hpp"

#include <chrono>
#include <exception>
#include <future>
#include <iostream>
#include <string>
#include <thread>

using teleop::ByteBuffer;
using teleop::DeliveryMode;
using teleop::QuicTransport;

ByteBuffer to_bytes(const std::string& text) {
    return ByteBuffer(text.begin(), text.end());
}

std::string to_string(const ByteBuffer& bytes) {
    return std::string(bytes.begin(), bytes.end());
}

int main() {
    std::promise<bool> server_result;
    auto server_future = server_result.get_future();

    std::thread server([&] {
        bool success = false;

        try {
            auto transport = QuicTransport::accept(
                "127.0.0.1",
                9002,
                "certs/quic-server.crt",
                "certs/quic-server.key"
            );

            if (transport) {
                ByteBuffer message;

                std::cout << "[server] Waiting for message\n";

                if (transport->receive(message)) {
                    std::cout
                        << "[server] Received: "
                        << to_string(message) << '\n';

                    const bool received_correctly =
                        to_string(message) ==
                        "hello from robot";

                    const bool reply_sent = transport->send(
                        to_bytes("hello from operator"),
                        DeliveryMode::ReliableOrdered
                    );

                    success = received_correctly && reply_sent;
                }

                // Allow the asynchronous send to progress.
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(500)
                );
            }
        } catch (const std::exception& e) {
            std::cerr << "[server] Error: " << e.what() << '\n';
        }

        server_result.set_value(success);
    });

    std::this_thread::sleep_for(
        std::chrono::milliseconds(500)
    );

    bool client_success = false;

    try {
        auto transport = QuicTransport::connect(
            "127.0.0.1",
            9002
        );

        if (transport) {
            const bool sent = transport->send(
                to_bytes("hello from robot"),
                DeliveryMode::ReliableOrdered
            );

            std::cout << "[client] Send accepted: " << sent << '\n';

            ByteBuffer response;

            if (sent && transport->receive(response)) {
                std::cout
                    << "[client] Received: "
                    << to_string(response) << '\n';

                client_success =
                    to_string(response) ==
                    "hello from operator";
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "[client] Error: " << e.what() << '\n';
    }

    server.join();

    const bool server_success = server_future.get();

    if (client_success && server_success) {
        std::cout << "[TEST] PASS\n";
        return 0;
    }

    std::cout << "[TEST] FAIL\n";
    return 1;
}
