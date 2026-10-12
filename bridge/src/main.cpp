#include <cerrno>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

#include "zenoh.hxx"

constexpr int TCP_PORT = 9000;
constexpr uint32_t MAX_MESSAGE_SIZE = 1024 * 1024;
constexpr const char* TOPIC = "teleop/test/message";

bool send_all(int fd, const void* data, size_t size) {
    const auto* ptr = static_cast<const char*>(data);

    while (size > 0) {
        ssize_t n = send(fd, ptr, size, MSG_NOSIGNAL);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            return false;
        }
        ptr += n;
        size -= static_cast<size_t>(n);
    }
    return true;
}

bool recv_all(int fd, void* data, size_t size) {
    auto* ptr = static_cast<char*>(data);

    while (size > 0) {
        ssize_t n = recv(fd, ptr, size, 0);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            return false;
        }
        ptr += n;
        size -= static_cast<size_t>(n);
    }
    return true;
}

bool send_message(int fd, const std::string& msg) {
    if (msg.size() > MAX_MESSAGE_SIZE) return false;

    uint32_t length = htonl(
        static_cast<uint32_t>(msg.size())
    );

    return send_all(fd, &length, sizeof(length)) &&
           send_all(fd, msg.data(), msg.size());
}

bool recv_message(int fd, std::string& msg) {
    uint32_t network_length = 0;

    if (!recv_all(fd, &network_length,
                  sizeof(network_length))) {
        return false;
    }

    uint32_t length = ntohl(network_length);
    if (length > MAX_MESSAGE_SIZE) return false;

    msg.resize(length);
    return recv_all(fd, msg.data(), msg.size());
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

int make_server() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) throw std::runtime_error("socket failed");

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

int connect_to_operator() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

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

void run_operator() {
    auto session = open_zenoh(7447);
    int server = make_server();

    std::cout << "[operator] zenoh connected on 7447\n";
    std::cout << "[operator] TCP listening on 9000\n";

    while (true) {
        int client = accept(server, nullptr, nullptr);
        if (client < 0) continue;

        std::cout << "[operator] Robot bridge connected\n";

        std::string msg;
        while (recv_message(client, msg)) {
            std::cout << "[operator] Received: "
                      << msg << std::endl;

            session.put(
                zenoh::KeyExpr(TOPIC),
                zenoh::Bytes(msg)
            );
        }

        close(client);
        std::cout << "[operator] Connection lost\n";
    }
}

void run_robot() {
    auto session = open_zenoh(7448);

    std::mutex socket_mutex;
    int connection = -1;

    auto subscriber = session.declare_subscriber(
        zenoh::KeyExpr(TOPIC),
        [&](const zenoh::Sample& sample) {
            std::string msg =
                sample.get_payload().as_string();

            std::lock_guard<std::mutex> lock(socket_mutex);

            if (connection < 0) return;

            if (!send_message(connection, msg)) {
                close(connection);
                connection = -1;
            } else {
                std::cout << "[robot] Forwarded: "
                          << msg << std::endl;
            }
        },
        zenoh::closures::none
    );

    std::cout << "[robot] zenoh connected on 7448\n";

    while (true) {
        {
            std::lock_guard<std::mutex> lock(socket_mutex);
            if (connection < 0) {
                connection = connect_to_operator();
                if (connection >= 0) {
                    std::cout
                        << "[robot] Connected to operator\n";
                }
            }
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
