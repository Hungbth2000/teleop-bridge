
#include "quic_transport.hpp"

#include <chrono>
#include <exception>
#include <iostream>
#include <thread>

int main() {
    bool server_connected = false;
    bool client_connected = false;

    std::thread server([&] {
        try {
            auto transport = teleop::QuicTransport::accept(
                "127.0.0.1",
                9002,
                "certs/quic-server.crt",
                "certs/quic-server.key"
            );

            server_connected = (transport != nullptr);

            std::cout
                << "[TEST] Server connected: "
                << server_connected << '\n';

            if (transport) {
                std::this_thread::sleep_for(
                    std::chrono::seconds(2)
                );
            }
        } catch (const std::exception& e) {
            std::cerr
                << "[TEST] Server error: "
                << e.what() << '\n';
        }
    });

    std::this_thread::sleep_for(
        std::chrono::milliseconds(500)
    );

    try {
        auto transport = teleop::QuicTransport::connect(
            "127.0.0.1",
            9002
        );

        client_connected = (transport != nullptr);

        std::cout
            << "[TEST] Client connected: "
            << client_connected << '\n';

        if (transport) {
            std::this_thread::sleep_for(
                std::chrono::seconds(1)
            );
        }
    } catch (const std::exception& e) {
        std::cerr
            << "[TEST] Client error: "
            << e.what() << '\n';
    }

    server.join();

    if (server_connected && client_connected) {
        std::cout << "[TEST] PASS\n";
        return 0;
    }

    std::cout << "[TEST] FAIL\n";
    return 1;
}
