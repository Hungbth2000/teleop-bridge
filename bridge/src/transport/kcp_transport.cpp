#include "kcp_transport.hpp"
#include "ikcp.h"

#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <utility>

namespace teleop {
namespace {

constexpr std::size_t MAX_MESSAGE = 64 * 1024;
constexpr std::size_t MAX_RECEIVE_QUEUE = 256;
constexpr int MAX_PENDING_SEGMENTS = 256;
constexpr int UDP_BUFFER_SIZE = 2048;

std::uint32_t clock_ms() {
    using namespace std::chrono;
    return static_cast<std::uint32_t>(
        duration_cast<milliseconds>(
            steady_clock::now().time_since_epoch()
        ).count()
    );
}

int create_socket(
    const std::string& local_address,
    const std::string& peer_address,
    std::uint16_t port
) {
    int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        throw std::runtime_error("KCP socket creation failed");
    }

    sockaddr_in local{};
    local.sin_family = AF_INET;
    local.sin_port = htons(port);

    sockaddr_in peer{};
    peer.sin_family = AF_INET;
    peer.sin_port = htons(port);

    if (::inet_pton(AF_INET, local_address.c_str(),
                    &local.sin_addr) != 1 ||
        ::inet_pton(AF_INET, peer_address.c_str(),
                    &peer.sin_addr) != 1) {
        ::close(fd);
        throw std::runtime_error("Invalid KCP IP address");
    }

    if (::bind(fd, reinterpret_cast<sockaddr*>(&local),
               sizeof(local)) != 0 ||
        ::connect(fd, reinterpret_cast<sockaddr*>(&peer),
                  sizeof(peer)) != 0) {
        ::close(fd);
        throw std::runtime_error("KCP bind/connect failed");
    }

    return fd;
}

// Laboratory-only session handshake, not authentication.
void make_handshake(
    char* output,
    const char* marker,
    std::uint32_t conversation
) {
    std::memcpy(output, marker, 4);
    const std::uint32_t network_id = htonl(conversation);
    std::memcpy(output + 4, &network_id, 4);
}

bool parse_handshake(
    const char* data,
    int length,
    const char* marker,
    std::uint32_t& conversation
) {
    if (length != 8 || std::memcmp(data, marker, 4) != 0) {
        return false;
    }

    std::uint32_t network_id = 0;
    std::memcpy(&network_id, data + 4, 4);
    conversation = ntohl(network_id);
    return conversation != 0;
}

bool wait_readable(int fd, int timeout_ms) {
    pollfd descriptor{};
    descriptor.fd = fd;
    descriptor.events = POLLIN;

    const int result = ::poll(&descriptor, 1, timeout_ms);
    return result > 0 && (descriptor.revents & POLLIN);
}

} // namespace

std::unique_ptr<KcpTransport> KcpTransport::accept(
    const std::string& local_address,
    const std::string& peer_address,
    std::uint16_t port
) {
    const int fd = create_socket(local_address, peer_address, port);
    std::array<char, UDP_BUFFER_SIZE> buffer{};

    std::cout << "[kcp] Waiting for robot handshake\n";

    while (true) {
        if (!wait_readable(fd, 100)) {
            continue;
        }

        const ssize_t received =
            ::recv(fd, buffer.data(), buffer.size(), 0);

        std::uint32_t conversation = 0;

        if (!parse_handshake(
                buffer.data(),
                static_cast<int>(received),
                "KCPH",
                conversation)) {
            continue;
        }

        char acknowledgement[8];
        make_handshake(acknowledgement, "KCPA", conversation);

        if (::send(fd, acknowledgement, sizeof(acknowledgement),
                   MSG_NOSIGNAL) != sizeof(acknowledgement)) {
            continue;
        }

        std::cout << "[kcp] Session accepted\n";
        auto transport = std::unique_ptr<KcpTransport>(
            new KcpTransport(fd, conversation, true)
        );

        return transport;
    }
}

std::unique_ptr<KcpTransport> KcpTransport::connect(
    const std::string& local_address,
    const std::string& peer_address,
    std::uint16_t port
) {
    const int fd = create_socket(local_address, peer_address, port);

    std::random_device random;
    std::uint32_t conversation = 0;

    while (conversation == 0) {
        conversation =
            (static_cast<std::uint32_t>(random()) << 16) ^
            static_cast<std::uint32_t>(random());
    }

    char hello[8];
    make_handshake(hello, "KCPH", conversation);

    std::array<char, UDP_BUFFER_SIZE> buffer{};

    // Retry for up to five seconds.
    for (int attempt = 0; attempt < 25; ++attempt) {
        ::send(fd, hello, sizeof(hello), MSG_NOSIGNAL);

        if (!wait_readable(fd, 200)) {
            continue;
        }

        const ssize_t received =
            ::recv(fd, buffer.data(), buffer.size(), 0);

        std::uint32_t acknowledged = 0;

        if (parse_handshake(
                buffer.data(),
                static_cast<int>(received),
                "KCPA",
                acknowledged) &&
            acknowledged == conversation) {
            std::cout << "[kcp] Session established\n";

            return std::unique_ptr<KcpTransport>(
                new KcpTransport(fd, conversation, false)
            );
        }
    }

    ::close(fd);
    return nullptr;
}

KcpTransport::KcpTransport(
    int socket_fd,
    std::uint32_t conversation_id,
    bool server_side
)
    : socket_fd_(socket_fd),
      server_side_(server_side) {

    kcp_ = ikcp_create(conversation_id, this);

    if (!kcp_) {
        ::close(socket_fd_);
        socket_fd_ = -1;
        throw std::runtime_error("ikcp_create failed");
    }

    ikcp_setoutput(kcp_, &KcpTransport::output_callback);
    ikcp_setmtu(kcp_, 1200);
    ikcp_wndsize(kcp_, 128, 128);

    // 10 ms update, fast retransmit enabled,
    // congestion control remains enabled.
    ikcp_nodelay(kcp_, 1, 10, 2, 0);

    io_thread_ = std::thread([this] {
        io_loop();
    });
}

KcpTransport::~KcpTransport() {
    shutdown();

    if (io_thread_.joinable()) {
        io_thread_.join();
    }

    if (kcp_) {
        ikcp_release(kcp_);
    }

    if (socket_fd_ >= 0) {
        ::close(socket_fd_);
    }
}

int KcpTransport::output_callback(
    const char* data,
    int length,
    IKCPCB*,
    void* user
) {
    auto* self = static_cast<KcpTransport*>(user);

    const ssize_t sent = ::send(
        self->socket_fd_,
        data,
        static_cast<std::size_t>(length),
        MSG_NOSIGNAL
    );

    return sent == length ? length : -1;
}

bool KcpTransport::send(
    const ByteBuffer& message,
    DeliveryMode mode
) {
    // KCP always sends reliably in this experiment.
    (void)mode;

    if (!running_.load() ||
        message.empty() ||
        message.size() > MAX_MESSAGE) {
        return false;
    }

    std::lock_guard<std::mutex> lock(kcp_mutex_);

    if (!running_.load()) {
        return false;
    }

    // Avoid unbounded reliable buffering during congestion.
    const auto segments_needed =
        (message.size() + kcp_->mss - 1) / kcp_->mss;

    const auto pending =
        static_cast<std::size_t>(ikcp_waitsnd(kcp_));

    if (pending + segments_needed >
        static_cast<std::size_t>(MAX_PENDING_SEGMENTS)) {

        static std::atomic<std::uint64_t> rejected{0};

        const auto count = rejected.fetch_add(1) + 1;

        // Log the first rejection and then every 100th.
        if (count == 1 || count % 100 == 0) {
            std::cerr
                << "[kcp] SEND QUEUE FULL"
                << " rejected=" << count
                << " pending_segments=" << pending
                << " required_segments=" << segments_needed
                << '\n';
        }

        return false;
    }

    const int accepted = ikcp_send(
        kcp_,
        reinterpret_cast<const char*>(message.data()),
        static_cast<int>(message.size())
    );

    return accepted == static_cast<int>(message.size());
}

bool KcpTransport::receive(ByteBuffer& message) {
    std::unique_lock<std::mutex> lock(receive_mutex_);

    receive_cv_.wait(lock, [this] {
        return !running_.load() || !receive_queue_.empty();
    });

    if (!running_.load()) {
        return false;
    }

    message = std::move(receive_queue_.front());
    receive_queue_.pop_front();
    return true;
}

void KcpTransport::io_loop() {
    std::array<char, UDP_BUFFER_SIZE> datagram{};
    ByteBuffer complete(MAX_MESSAGE);

    while (running_.load()) {
        if (wait_readable(socket_fd_, 10)) {
            const ssize_t count = ::recv(
                socket_fd_,
                datagram.data(),
                datagram.size(),
                0
            );

            if (count > 0) {
                std::uint32_t requested_conversation = 0;

                if (parse_handshake(
                        datagram.data(),
                        static_cast<int>(count),
                        "KCPH",
                        requested_conversation)) {

                    if (server_side_ &&
                        requested_conversation == kcp_->conv) {

                        char acknowledgement[8];
                        make_handshake(
                            acknowledgement,
                            "KCPA",
                            requested_conversation
                        );

                        ::send(
                            socket_fd_,
                            acknowledgement,
                            sizeof(acknowledgement),
                            MSG_NOSIGNAL
                        );
                    }

                    continue;
                }

                std::lock_guard<std::mutex> lock(kcp_mutex_);
                ikcp_input(kcp_, datagram.data(), count);
            }
        }

        {
            std::lock_guard<std::mutex> lock(kcp_mutex_);

            ikcp_update(kcp_, clock_ms());

            while (running_.load()) {
                const int length = ikcp_peeksize(kcp_);

                if (length < 0) {
                    break;
                }

                if (length == 0 ||
                    static_cast<std::size_t>(length) > MAX_MESSAGE) {
                    std::cerr << "[kcp] Invalid message size\n";
                    shutdown();
                    break;
                }

                const int received = ikcp_recv(
                    kcp_,
                    reinterpret_cast<char*>(complete.data()),
                    static_cast<int>(complete.size())
                );

                if (received <= 0) {
                    break;
                }

                {
                    std::lock_guard<std::mutex> queue_lock(
                        receive_mutex_
                    );

                    if (receive_queue_.size() >= MAX_RECEIVE_QUEUE) {
                        std::cerr
                            << "[kcp] Receive queue overflow\n";
                        shutdown();
                        break;
                    }

                    receive_queue_.emplace_back(
                        complete.begin(),
                        complete.begin() + received
                    );
                }

                receive_cv_.notify_one();
            }
        }
    }

    receive_cv_.notify_all();
}

void KcpTransport::shutdown() {
    running_.store(false);
    receive_cv_.notify_all();
}

} // namespace teleop
