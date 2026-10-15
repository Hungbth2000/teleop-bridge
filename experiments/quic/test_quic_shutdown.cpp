
#include "quic_transport.hpp"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <thread>

using namespace std::chrono_literals;

using teleop::ByteBuffer;
using teleop::DeliveryMode;
using teleop::QuicTransport;

int main() {
    constexpr int TRIALS = 5;

    for (int trial = 0; trial < TRIALS; ++trial) {
        const auto port =
            static_cast<std::uint16_t>(9100 + trial);

        std::atomic<bool> server_ok{false};
        std::atomic<bool> client_ok{false};
        std::atomic<int> send_attempts{0};
        std::atomic<int> received_count{0};

        std::thread server([&] {
            try {
                auto transport = QuicTransport::accept(
                    "127.0.0.1",
                    port,
                    "certs/quic-server.crt",
                    "certs/quic-server.key"
                );

                if (!transport) {
                    return;
                }

                server_ok.store(true);

                // Receive messages until the connection closes.
                std::thread receiver([&] {
                    ByteBuffer message;

                    while (transport->receive(message)) {
                        received_count.fetch_add(1);
                    }
                });

                std::this_thread::sleep_for(200ms);

                // Shut down while the client may still
                // be transmitting.
                transport->shutdown();

                receiver.join();
            } catch (const std::exception& e) {
                std::cerr
                    << "[server] Error: "
                    << e.what() << '\n';
            }
        });

        std::this_thread::sleep_for(300ms);

        try {
            auto transport = QuicTransport::connect(
                "127.0.0.1", port
            );

            if (transport) {
                client_ok.store(true);

                std::thread sender([&] {
                    ByteBuffer message(100, 0x42);

                    for (int i = 0; i < 500; ++i) {
                        const auto mode =
                            (i % 2 == 0)
                                ? DeliveryMode::ReliableOrdered
                                : DeliveryMode::Unreliable;

                        send_attempts.fetch_add(1);

                        if (!transport->send(message, mode)) {
                            break;
                        }

                        std::this_thread::sleep_for(1ms);
                    }
                });

                // Initiate shutdown concurrently
                // with the sender thread.
                std::this_thread::sleep_for(100ms);

                transport->shutdown();

                sender.join();
            }
        } catch (const std::exception& e) {
            std::cerr
                << "[client] Error: "
                << e.what() << '\n';
        }

        server.join();

        std::cout
            << "[trial " << trial + 1 << "] "
            << "server=" << server_ok.load()
            << " client=" << client_ok.load()
            << " send_attempts=" << send_attempts.load()
            << " received=" << received_count.load()
            << '\n';

        if (!server_ok.load() || !client_ok.load() ||
            send_attempts.load() == 0) {
            std::cerr << "[TEST] FAIL\n";
            return 1;
        }
    }

    std::cout << "[TEST] PASS\n";
    return 0;
}
