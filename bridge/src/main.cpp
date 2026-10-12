#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <netinet/tcp.h>  // NEW: TCP_NODELAY
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <vector>

#include "message.hpp"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

#include "zenoh.hxx"

constexpr int TCP_PORT = 9000;
constexpr uint32_t MAX_MESSAGE_SIZE = 1024 * 1024;

constexpr const char* ROBOT_TOPIC =
    "teleop/test/robot_to_operator";

constexpr const char* OPERATOR_TOPIC =
    "teleop/test/operator_to_robot";

constexpr const char* MOTION_TOPIC =
    "teleop/commands/motion";

constexpr const char* RELIABLE_TOPIC =
    "teleop/commands/reliable";

constexpr const char* RELIABLE_ACK_TOPIC =
    "teleop/commands/reliable_ack";

// Send exactly the requested number of bytes.
bool send_all(int fd, const void* data, size_t size) {
    const char* ptr = static_cast<const char*>(data);

    while (size > 0) {
        ssize_t n = send(fd, ptr, size, MSG_NOSIGNAL);

        if (n < 0 && errno == EINTR) {
            continue;
        }
        if (n <= 0) {
            return false;
        }

        ptr += n;
        size -= static_cast<size_t>(n);
    }

    return true;
}

// Receive exactly the requested number of bytes.
bool recv_all(int fd, void* data, size_t size) {
    char* ptr = static_cast<char*>(data);

    while (size > 0) {
        ssize_t n = recv(fd, ptr, size, 0);

        if (n < 0 && errno == EINTR) {
            continue;
        }
        if (n <= 0) {
            return false;
        }

        ptr += n;
        size -= static_cast<size_t>(n);
    }

    return true;
}

// Wire format: [4-byte payload length][payload].
bool send_message(int fd, const std::string& message) {
    if (message.size() > MAX_MESSAGE_SIZE) {
        return false;
    }

    uint32_t length =
        htonl(static_cast<uint32_t>(message.size()));

    return send_all(fd, &length, sizeof(length)) &&
           send_all(fd, message.data(), message.size());
}

bool recv_message(int fd, std::string& message) {
    uint32_t network_length = 0;

    if (!recv_all(fd, &network_length,
                  sizeof(network_length))) {
        return false;
    }

    uint32_t length = ntohl(network_length);

    if (length > MAX_MESSAGE_SIZE) {
        std::cerr << "Received oversized message\n";
        return false;
    }

    message.resize(length);

    return recv_all(fd, message.data(), length);
}

zenoh::Session open_zenoh(int port) {
    std::string config_json =
        "{\"mode\":\"client\","
        "\"connect\":{\"endpoints\":[\"tcp/127.0.0.1:"
        + std::to_string(port) +
        "\"]},"
        "\"scouting\":{\"multicast\":{\"enabled\":false}}}";

    auto config = zenoh::Config::from_str(config_json);
    return zenoh::Session::open(std::move(config));
}

// Disable Nagle's algorithm for low-latency messages.
void configure_low_latency_tcp(int fd) {
    int enabled = 1;

    if (setsockopt(
            fd,
            IPPROTO_TCP,
            TCP_NODELAY,
            &enabled,
            sizeof(enabled)
        ) < 0) {
        perror("TCP_NODELAY");
    }
}

int create_server() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        throw std::runtime_error("socket failed");
    }

    int reuse = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR,
               &reuse, sizeof(reuse));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(TCP_PORT);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (bind(fd, reinterpret_cast<sockaddr*>(&addr),
             sizeof(addr)) < 0 ||
        listen(fd, 1) < 0) {
        close(fd);
        throw std::runtime_error("bind/listen failed");
    }

    return fd;
}

int connect_to_server() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(TCP_PORT);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (connect(fd, reinterpret_cast<sockaddr*>(&addr),
                sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }

    return fd;
}

// Handle one active TCP connection in both directions.
void run_connected(
    zenoh::Session& session,
    int fd,
    const std::string& role
) {
    using namespace teleop;

    const char* test_outbound =
        role == "robot" ? ROBOT_TOPIC : OPERATOR_TOPIC;

    const char* test_inbound =
        role == "robot" ? OPERATOR_TOPIC : ROBOT_TOPIC;

    const MessageType test_type =
        role == "robot"
            ? MessageType::RobotState
            : MessageType::FastCommand;

    std::mutex send_mutex;
    std::atomic<std::uint64_t> next_sequence{1};

    // Shared forwarding function for local zenoh publications.
    auto forward = [&](const zenoh::Sample& sample,
                       MessageType type,
                       std::uint8_t stream_id) {
        try {
            Message msg{};

            msg.type = type;
            msg.stream_id = stream_id;
            msg.sequence = next_sequence.fetch_add(1);
            msg.timestamp_ns = now_ns();
            msg.payload = sample.get_payload().as_vector();

            auto encoded = serialize(msg);
            std::string wire(encoded.begin(), encoded.end());

            std::lock_guard<std::mutex> lock(send_mutex);

            if (!send_message(fd, wire)) {
                std::cerr
                    << "[" << role << "] Send failed\n";
                shutdown(fd, SHUT_RDWR);
                return;
            }

            // Avoid printing all 100 movement commands/second.
            if (type != MessageType::FastCommand ||
                msg.sequence % 100 == 0) {
                std::cout
                    << "[" << role << "] TX"
                    << " type=" << static_cast<int>(type)
                    << " seq=" << msg.sequence
                    << " bytes=" << msg.payload.size()
                    << std::endl;
            }

        } catch (const std::exception& e) {
            std::cerr
                << "[" << role << "] TX error: "
                << e.what() << '\n';
        }
    };

    {
        // Preserve the two existing test topics.
        auto test_sub = session.declare_subscriber(
            zenoh::KeyExpr(test_outbound),
            [&](const zenoh::Sample& sample) {
                forward(sample, test_type, 0);
            },
            zenoh::closures::none
        );

        // Only the operator bridge forwards local
        // movement commands. The robot callback does nothing,
        // preventing a forwarding loop.
        auto motion_sub = session.declare_subscriber(
            zenoh::KeyExpr(MOTION_TOPIC),
            [&](const zenoh::Sample& sample) {
                if (role == "operator") {
                    forward(
                        sample,
                        MessageType::FastCommand,
                        1
                    );
                }
            },
            zenoh::closures::none
        );
  
        auto reliable_sub = session.declare_subscriber(
            zenoh::KeyExpr(RELIABLE_TOPIC),
            [&](const zenoh::Sample& sample) {
                if (role == "operator") {
                    forward(
                        sample,
                        MessageType::ReliableCommand,
                        2
                    );
                }
            },
            zenoh::closures::none
        );

        auto ack_sub = session.declare_subscriber(
            zenoh::KeyExpr(RELIABLE_ACK_TOPIC),
            [&](const zenoh::Sample& sample) {
                if (role == "robot") {
                    forward(
                        sample,
                        MessageType::ExecutionAck,
                        3
                    );
                }
            },
            zenoh::closures::none
        );

        std::cout
            << "[" << role << "] Test TX: "
            << test_outbound << '\n'
            << "[" << role << "] Test RX: "
            << test_inbound << '\n';

        if (role == "operator") {
            std::cout
                << "[operator] Motion TX: "
                << MOTION_TOPIC << '\n';
        } else {
            std::cout
                << "[robot] Motion RX: "
                << MOTION_TOPIC << '\n';
        }

        // Network -> local zenoh.
        std::string wire;

        while (recv_message(fd, wire)) {
            try {
                std::vector<std::uint8_t> encoded(
                    wire.begin(), wire.end()
                );

                Message msg = deserialize(encoded);
                
                const bool is_motion =
                    role == "robot" &&
                    msg.type == MessageType::FastCommand &&
                    msg.stream_id == 1;

                const bool is_reliable =
                    role == "robot" &&
                    msg.type == MessageType::ReliableCommand &&
                    msg.stream_id == 2;

                const bool is_ack =
                    role == "operator" &&
                    msg.type == MessageType::ExecutionAck &&
                    msg.stream_id == 3;

                const bool valid_test =
                    msg.stream_id == 0 &&
                    msg.type == (
                        role == "robot"
                            ? MessageType::FastCommand
                            : MessageType::RobotState
                    );

                const char* destination = nullptr;

                if (is_motion) {
                    destination = MOTION_TOPIC;
                } else if (is_reliable) {
                    destination = RELIABLE_TOPIC;
                } else if (is_ack) {
                    destination = RELIABLE_ACK_TOPIC;
                } else if (valid_test) {
                    destination = test_inbound;
                } else {
                    std::cerr
                        << "[" << role
                        << "] Unexpected message type/stream\n";
                    continue;
                }

                // Publish the original binary payload.
                session.put(
                    zenoh::KeyExpr(destination),
                    zenoh::Bytes(msg.payload)
                );

                if (!is_motion) {
                    std::cout
                        << "[" << role << "] RX"
                        << " seq=" << msg.sequence
                        << " bytes=" << msg.payload.size()
                        << '\n';
                }

            } catch (const std::exception& e) {
                std::cerr
                    << "[" << role << "] RX error: "
                    << e.what() << '\n';
                break;
            }
        }
    }

    // Subscribers are destroyed before closing the socket.
    close(fd);

    std::cout
        << "[" << role << "] Connection closed\n";
}


void run_operator() {
    auto session = open_zenoh(7447);
    int server = create_server();

    std::cout
        << "[operator] Connected to zenoh router 7447\n"
        << "[operator] Listening on TCP port 9000\n";

    while (true) {
        int client = accept(server, nullptr, nullptr);

        if (client < 0) {
            if (errno == EINTR) continue;
            continue;
        }

        // NEW: Disable Nagle on the connected socket.
        configure_low_latency_tcp(client);

        std::cout
            << "[operator] Robot bridge connected\n";

        run_connected(session, client, "operator");
    }
}

void run_robot() {
    auto session = open_zenoh(7448);

    std::cout
        << "[robot] Connected to zenoh router 7448\n";

    while (true) {
        int fd = connect_to_server();

        if (fd >= 0) {

            // NEW: Disable Nagle on the connected socket.
            configure_low_latency_tcp(fd);
            
            std::cout
                << "[robot] Connected to operator bridge\n";

            run_connected(session, fd, "robot");
        } else {
            std::cout
                << "[robot] Waiting for operator bridge...\n";
        }

        std::this_thread::sleep_for(
            std::chrono::milliseconds(500)
        );
    }
}

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr
            << "Usage: teleop_bridge <operator|robot>\n";
        return 1;
    }

    try {
        std::string role = argv[1];

        if (role == "operator") {
            run_operator();
        } else if (role == "robot") {
            run_robot();
        } else {
            std::cerr << "Invalid role\n";
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n';
        return 1;
    }
}
