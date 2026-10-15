
#include "udp_transport.hpp"
#include "message.hpp"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <thread>

#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

int main() {
    using namespace teleop;

    // Two UDP endpoints on localhost.
    auto operator_transport = UdpTransport::create(
        "127.0.0.1", 19001,
        "127.0.0.1", 19002
    );

    auto robot_transport = UdpTransport::create(
        "127.0.0.1", 19002,
        "127.0.0.1", 19001
    );

    Message motion{
        MessageType::FastCommand,
        0,
        42,
        now_ns(),
        std::vector<std::uint8_t>(100, 0xAB)
    };

    const auto encoded = serialize(motion);

    assert(
        operator_transport->send(
            encoded,
            DeliveryMode::Unreliable
        )
    );

    ByteBuffer received;

    assert(robot_transport->receive(received));

    const auto decoded = deserialize(received);

    assert(decoded.type == MessageType::FastCommand);
    assert(decoded.sequence == 42);
    assert(decoded.payload == motion.payload);

    // Test reverse direction.
    Message state{
        MessageType::RobotState,
        0,
        43,
        now_ns(),
        std::vector<std::uint8_t>(80, 0xCD)
    };

    assert(
        robot_transport->send(
            serialize(state),
            DeliveryMode::Unreliable
        )
    );

    assert(operator_transport->receive(received));

    const auto decoded_state = deserialize(received);

    assert(decoded_state.type == MessageType::RobotState);
    assert(decoded_state.sequence == 43);

    // Reliable messages must be rejected by UDP.
    assert(
        !operator_transport->send(
            encoded,
            DeliveryMode::ReliableOrdered
        )
    );

    // Oversized outgoing datagrams must be rejected.
    ByteBuffer oversized(
        UdpTransport::MAX_DATAGRAM + 1,
        0xFF
    );

    assert(
        !operator_transport->send(
            oversized,
            DeliveryMode::Unreliable
        )
    );

    // Send an oversized raw UDP datagram to the robot.
    // The robot transport should discard it and continue.
    int raw_fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    assert(raw_fd >= 0);

    sockaddr_in destination{};
    destination.sin_family = AF_INET;
    destination.sin_port = htons(19002);

    assert(
        ::inet_pton(
            AF_INET,
            "127.0.0.1",
            &destination.sin_addr
        ) == 1
    );

    std::vector<std::uint8_t> oversized_incoming(1500, 0xEE);

    assert(
        ::sendto(
            raw_fd,
            oversized_incoming.data(),
            oversized_incoming.size(),
            0,
            reinterpret_cast<sockaddr*>(&destination),
            sizeof(destination)
        ) == static_cast<ssize_t>(oversized_incoming.size())
    );

    ::close(raw_fd);

    // A valid message following the oversized datagram
    // should still be received successfully.
    assert(
        operator_transport->send(
            encoded,
            DeliveryMode::Unreliable
        )
    );

    assert(robot_transport->receive(received));
    assert(deserialize(received).sequence == 42);

    // Verify that shutdown interrupts a blocked receive.
    auto shutdown_transport = UdpTransport::create(
        "127.0.0.1", 19003,
        "127.0.0.1", 19004
    );

    std::atomic<bool> receive_finished{false};
    std::atomic<bool> receive_result{true};

    std::thread receiver([&] {
        ByteBuffer buffer;

        receive_result.store(
            shutdown_transport->receive(buffer)
        );

        receive_finished.store(true);
    });

    // Give the receiver time to enter recv().
    std::this_thread::sleep_for(
        std::chrono::milliseconds(100)
    );

    shutdown_transport->shutdown();

    receiver.join();

    assert(receive_finished.load());
    assert(!receive_result.load());

    std::cout << "UDP transport tests passed\n";
    return 0;
}
