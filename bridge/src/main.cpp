
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
    const char* outbound_topic =
        role == "robot" ? ROBOT_TOPIC : OPERATOR_TOPIC;

    const char* inbound_topic =
        role == "robot" ? OPERATOR_TOPIC : ROBOT_TOPIC;

    std::mutex send_mutex;

    {
        // Local zenoh -> TCP.
        // Subscriber is destroyed before the socket is closed.
        auto subscriber = session.declare_subscriber(
            zenoh::KeyExpr(outbound_topic),

            [&](const zenoh::Sample& sample) {
                std::string message =
                    sample.get_payload().as_string();

                std::lock_guard<std::mutex> lock(send_mutex);

                if (!send_message(fd, message)) {
                    std::cerr
                        << "[" << role << "] Send failed\n";

                    // Wake the receiving loop so it can exit.
                    shutdown(fd, SHUT_RDWR);
                    return;
                }

                std::cout
                    << "[" << role << "] Sent: "
                    << message << std::endl;
            },

            zenoh::closures::none
        );

        std::cout
            << "[" << role << "] TX subscription: "
            << outbound_topic << '\n'
            << "[" << role << "] RX publication: "
            << inbound_topic << std::endl;

        // TCP -> local zenoh.
        std::string message;

        while (recv_message(fd, message)) {
            std::cout
                << "[" << role << "] Received: "
                << message << std::endl;

            session.put(
                zenoh::KeyExpr(inbound_topic),
                zenoh::Bytes(message)
            );
        }
    }

    // Subscriber has been destroyed; no callback uses fd now.
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
