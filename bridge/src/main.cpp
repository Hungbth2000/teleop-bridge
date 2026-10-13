#include <memory>
#include <iomanip>

#include "scheduler.hpp"
#include "transport.hpp"
#include "receive_stats.hpp"
#include "tcp_transport.hpp"
#include "rate_limiter.hpp"
#include "csv_telemetry.hpp"

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
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <condition_variable>

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

constexpr const char* VIDEO_LOAD_TOPIC =
    "teleop/test/video_load";

constexpr const char* HEAD_VIDEO_TX_TOPIC =
    "teleop/video/head/tx";

constexpr const char* HEAD_VIDEO_RX_TOPIC =
    "teleop/video/head/rx";

constexpr const char* WRIST_LEFT_VIDEO_TX_TOPIC =
    "teleop/video/wrist_left/tx";

constexpr const char* WRIST_LEFT_VIDEO_RX_TOPIC =
    "teleop/video/wrist_left/rx";

constexpr const char* WRIST_RIGHT_VIDEO_TX_TOPIC =
    "teleop/video/wrist_right/tx";

constexpr const char* WRIST_RIGHT_VIDEO_RX_TOPIC =
    "teleop/video/wrist_right/rx";

constexpr const char* BANDWIDTH_TOPIC =
    "teleop/bridge/bandwidth";

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

teleop::TrafficKind classify_received_message(
    const teleop::Message& msg
) {
    using namespace teleop;

    // Stream 0 contains the original test messages.
    if (msg.stream_id == 0) {
        return TrafficKind::Test;
    }

    switch (msg.type) {
        case MessageType::FastCommand:
            return TrafficKind::Motion;

        case MessageType::ReliableCommand:
            // Reliable command: !QBQ
            // 8 bytes ID + 1 byte opcode + 8 bytes timestamp.
            if (msg.payload.size() != 17) {
                return TrafficKind::ReliableOther;
            }

            if (msg.payload[8] == 1) {
                return TrafficKind::EStop;
            }

            if (msg.payload[8] == 2) {
                return TrafficKind::Reset;
            }

            return TrafficKind::ReliableOther;

        case MessageType::ExecutionAck:
            return TrafficKind::ExecutionAck;

        case MessageType::RobotState:
            return TrafficKind::RobotState;

        case MessageType::Video:
            return TrafficKind::Video;

        case MessageType::Query:
            return TrafficKind::Query;

        case MessageType::Reply:
            return TrafficKind::Reply;
    }

    return TrafficKind::Test;
}


void print_scheduler_stats(
    const teleop::SchedulerStats& stats,
    const teleop::ReceiveSnapshot& received,
    const std::string& role
) {
    using namespace teleop;

    std::cout
        << "\n[" << role << "] Live bridge statistics\n";

    std::cout
        << std::left
        << std::setw(18) << "Type"
        << std::right
        << std::setw(11) << "Enqueued"
        << std::setw(10) << "Sent"
        << std::setw(11) << "Received"
        << std::setw(10) << "Dropped"
        << std::setw(10) << "Expired"
        << std::setw(11) << "Rejected"
        << std::setw(13) << "Send failed"
        << '\n';

    for (std::size_t i = 0;
         i < TRAFFIC_KIND_COUNT;
         ++i) {

        const auto& c = stats.by_kind[i];
        const auto rx = received.by_kind[i];

        // Display only categories that have activity.
        if (c.enqueued == 0 &&
            c.sent == 0 &&
            rx == 0 &&
            c.dropped == 0 &&
            c.expired == 0 &&
            c.rejected == 0 &&
            c.send_failed == 0) {
            continue;
        }

        std::cout
            << std::left
            << std::setw(18) << TRAFFIC_KIND_NAMES[i]
            << std::right
            << std::setw(11) << c.enqueued
            << std::setw(10) << c.sent
            << std::setw(11) << rx
            << std::setw(10) << c.dropped
            << std::setw(10) << c.expired
            << std::setw(11) << c.rejected
            << std::setw(13) << c.send_failed
            << '\n';
    }

    std::cout
        << "Total received: " << received.total
        << " | Invalid: " << received.invalid
        << '\n'
        << std::flush;
}

void print_bandwidth_stats(
    const teleop::SchedulerStats& current_tx,
    const teleop::SchedulerStats& previous_tx,
    const teleop::ReceiveSnapshot& current_rx,
    const teleop::ReceiveSnapshot& previous_rx,
    double elapsed_seconds,
    const std::string& role
) {
    using namespace teleop;

    if (elapsed_seconds <= 0.0) {
        return;
    }

    std::cout
        << "\n[" << role << "] Bandwidth statistics"
        << " (last " << std::fixed
        << std::setprecision(2)
        << elapsed_seconds << " s)\n";

    std::cout
        << std::left
        << std::setw(18) << "Type"
        << std::right
        << std::setw(16) << "TX bytes total"
        << std::setw(16) << "RX bytes total"
        << std::setw(14) << "TX Mbit/s"
        << std::setw(14) << "RX Mbit/s"
        << '\n';

    std::uint64_t total_tx = 0;
    std::uint64_t total_rx = 0;

    double total_tx_mbps = 0.0;
    double total_rx_mbps = 0.0;

    for (std::size_t i = 0;
         i < TRAFFIC_KIND_COUNT;
         ++i) {

        const auto tx_bytes =
            current_tx.by_kind[i].sent_bytes;

        const auto rx_bytes =
            current_rx.bytes_by_kind[i];

        if (tx_bytes == 0 && rx_bytes == 0) {
            continue;
        }

        const auto previous_tx_bytes =
            previous_tx.by_kind[i].sent_bytes;

        const auto previous_rx_bytes =
            previous_rx.bytes_by_kind[i];

        // Counters are cumulative within one session.
        const auto tx_delta =
            tx_bytes >= previous_tx_bytes
                ? tx_bytes - previous_tx_bytes
                : 0;

        const auto rx_delta =
            rx_bytes >= previous_rx_bytes
                ? rx_bytes - previous_rx_bytes
                : 0;

        const double tx_mbps =
            (static_cast<double>(tx_delta) * 8.0) /
            (elapsed_seconds * 1'000'000.0);

        const double rx_mbps =
            (static_cast<double>(rx_delta) * 8.0) /
            (elapsed_seconds * 1'000'000.0);

        total_tx += tx_bytes;
        total_rx += rx_bytes;

        total_tx_mbps += tx_mbps;
        total_rx_mbps += rx_mbps;

        std::cout
            << std::left
            << std::setw(18) << TRAFFIC_KIND_NAMES[i]
            << std::right
            << std::setw(16) << tx_bytes
            << std::setw(16) << rx_bytes
            << std::setw(14) << std::fixed
            << std::setprecision(4) << tx_mbps
            << std::setw(14) << rx_mbps
            << '\n';
    }

    std::cout
        << std::left
        << std::setw(18) << "TOTAL"
        << std::right
        << std::setw(16) << total_tx
        << std::setw(16) << total_rx
        << std::setw(14) << std::fixed
        << std::setprecision(4) << total_tx_mbps
        << std::setw(14) << total_rx_mbps
        << '\n'
        << std::flush;
}

void run_connected(
    zenoh::Session& session,
    std::unique_ptr<teleop::ITransport> transport,
    const std::string& role
) {
    using namespace teleop;
    using Clock = std::chrono::steady_clock;

    const char* test_outbound =
        role == "robot" ? ROBOT_TOPIC : OPERATOR_TOPIC;

    const char* test_inbound =
        role == "robot" ? OPERATOR_TOPIC : ROBOT_TOPIC;

    const MessageType test_type =
        role == "robot"
            ? MessageType::RobotState
            : MessageType::FastCommand;

    PriorityScheduler scheduler;
    ReceiveStats receive_stats;

    // One limiter per connected session.
    // Only robot outbound traffic is limited.
    teleop::RateLimiter outbound_limiter;

    // One CSV writer per connected bridge session.
    // Appends to the role-specific file.
    teleop::CsvTelemetry csv_telemetry(role, "tcp");

    std::atomic<std::uint64_t> next_sequence{1};
    
    std::mutex reporter_mutex;
    std::condition_variable reporter_cv;
    bool reporter_running = true;

    
    std::mutex bandwidth_mutex;
    std::condition_variable bandwidth_cv;
    bool bandwidth_running = true;

    std::thread bandwidth_publisher([&] {
        using namespace std::chrono_literals;

        std::unique_lock<std::mutex> lock(
            bandwidth_mutex
        );

        while (bandwidth_running) {
            lock.unlock();

            if (role == "robot") {
                const auto now = Clock::now();

                const auto budget_bps =
                    static_cast<std::uint64_t>(
                        outbound_limiter.current_rate_bps(
                            now
                        )
                    );

                const std::string phase =
                    budget_bps <= 2'000'000
                        ? "degraded"
                        : "normal";

                const std::string payload =
                    "{\"budget_bps\":" +
                    std::to_string(budget_bps) +
                    ",\"phase\":\"" +
                    phase + "\"}";

                try {
                    session.put(
                        BANDWIDTH_TOPIC,
                        payload
                    );
                } catch (const std::exception& e) {
                    std::cerr
                        << "[robot] Bandwidth publish error: "
                        << e.what() << '\n';
                }
            }

            lock.lock();

            bandwidth_cv.wait_for(
                lock,
                100ms,
                [&] { return !bandwidth_running; }
            );
        }
    });

    std::thread reporter([&] {
        using namespace std::chrono_literals;
        using Clock = std::chrono::steady_clock;

        // Initial snapshots for calculating interval rates.
        auto previous_tx = scheduler.stats();
        auto previous_rx = receive_stats.snapshot();
        auto previous_time = Clock::now();

        std::unique_lock<std::mutex> lock(reporter_mutex);

        while (reporter_running) {
            if (reporter_cv.wait_for(
                    lock,
                    5s,
                    [&] { return !reporter_running; }
                )) {
                break;
            }

            lock.unlock();

            // Capture current statistics and elapsed time.
            auto current_tx = scheduler.stats();
            auto current_rx = receive_stats.snapshot();
            auto current_time = Clock::now();

            const double elapsed_seconds =
                std::chrono::duration<double>(
                    current_time - previous_time
                ).count();

            // Existing message count table.
            print_scheduler_stats(
                current_tx,
                current_rx,
                role
            );

            // NEW: bandwidth statistics.
            print_bandwidth_stats(
                current_tx,
                previous_tx,
                current_rx,
                previous_rx,
                elapsed_seconds,
                role
            );

            // The assignment limits robot outbound traffic.
            // The operator has no robot-outbound budget.
            const double configured_budget_mbps =
                role == "robot"
                    ? outbound_limiter.current_rate_mbps(
                        current_time
                    )
                    : 0.0;
       
            if (role == "robot") {
                const auto budget_bps =
                    static_cast<std::uint64_t>(
                        outbound_limiter.current_rate_bps(
                            current_time
                        )
                    );

                const char* phase =
                    budget_bps <= 2'000'000
                        ? "degraded"
                        : "normal";

                const std::string payload =
                    "{\"budget_bps\":" +
                    std::to_string(budget_bps) +
                    ",\"phase\":\"" +
                    std::string(phase) +
                    "\"}";

                try {
                    session.put(BANDWIDTH_TOPIC, payload);
                } catch (const std::exception& e) {
                    std::cerr
                        << "[robot] Bandwidth publication error: "
                        << e.what() << '\n';
                }
            }

            // NEW: Persist this reporting interval.
            try {
                csv_telemetry.write_sample(
                    current_tx,
                    previous_tx,
                    current_rx,
                    previous_rx,
                    elapsed_seconds,
                    configured_budget_mbps
                );
            } catch (const std::exception& e) {
                std::cerr
                    << "[" << role
                    << "] CSV telemetry error: "
                    << e.what()
                    << std::endl;
            }

            if (role == "robot") {
                const double budget =
                    outbound_limiter.current_rate_mbps();

                std::cout
                    << "[robot] Configured outbound budget: "
                    << budget << " Mbit/s\n";
            }

            // Save snapshots for the next interval.
            previous_tx = current_tx;
            previous_rx = current_rx;
            previous_time = current_time;

            lock.lock();
        }
    });

    // Dedicated sender. Only this thread calls transport->send().
    std::thread sender([&] {
        ScheduledMessage item;

        while (
            role == "robot"
                ? scheduler.pop_limited(
                    item, outbound_limiter
                )
                : scheduler.pop(item)
        ) {
            // This checks time spent in our scheduler only.
            // B3 separately checks A1's original timestamp.
            if (item.type == MessageType::FastCommand) {
                const auto wait_ms =
                    std::chrono::duration_cast<
                        std::chrono::milliseconds
                    >(Clock::now() - item.queued_at);

                if (wait_ms >=
                    std::chrono::milliseconds(100)) {
                    scheduler.record_expired(item.kind);
                    continue;
                }
            }

            if (!transport->send(
                    item.bytes,
                    item.delivery
                )) {
                scheduler.record_send_failed(item.kind);

                std::cerr
                    << "[" << role
                    << "] Transport send failed\n";

                scheduler.close();
                transport->shutdown();
                break;
            }

            scheduler.record_sent(
                item.kind,
                item.bytes.size()
            );
        }
    });

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

            if (type == MessageType::ReliableCommand ||
                type == MessageType::ExecutionAck) {
                std::cout
                    << "[" << role << "] ZENOH CALLBACK"
                    << " type=" << static_cast<int>(type)
                    << " bridge_seq=" << msg.sequence
                    << " bytes=" << msg.payload.size()
                    << std::endl;
            }

            // Determine the specific traffic category.
            TrafficKind kind = TrafficKind::Test;

            if (stream_id == 0) {
                kind = TrafficKind::Test;
            } else {
                switch (type) {
                    case MessageType::FastCommand:
                        kind = TrafficKind::Motion;
                        break;

                    case MessageType::ReliableCommand:
                        kind = TrafficKind::ReliableOther;

                        // Reliable command payload:
                        // uint64 command_id (8 bytes)
                        // uint8  opcode     (1 byte)
                        // uint64 created_ns (8 bytes)
                        //
                        // Opcode is at byte index 8.
                        if (msg.payload.size() == 17) {
                            const auto opcode = msg.payload[8];

                            if (opcode == 1) {
                                kind = TrafficKind::EStop;
                            } else if (opcode == 2) {
                                kind = TrafficKind::Reset;
                            }
                        }
                        break;

                    case MessageType::ExecutionAck:
                        kind = TrafficKind::ExecutionAck;
                        break;

                    case MessageType::RobotState:
                        kind = TrafficKind::RobotState;
                        break;

                    case MessageType::Video:
                        kind = TrafficKind::Video;
                        break;

                    case MessageType::Query:
                        kind = TrafficKind::Query;
                        break;

                    case MessageType::Reply:
                        kind = TrafficKind::Reply;
                        break;
                }
            }

            const DeliveryMode delivery =
                (type == MessageType::ReliableCommand ||
                 type == MessageType::ExecutionAck ||
                 type == MessageType::Query ||
                 type == MessageType::Reply)
                    ? DeliveryMode::ReliableOrdered
                    : DeliveryMode::Unreliable;

            auto result = scheduler.enqueue(
                serialize(msg),
                type,
                delivery,
                kind
            );

            if (result == EnqueueResult::Rejected) {
                std::cerr
                    << "[" << role
                    << "] Queue rejected message"
                    << " type=" << static_cast<int>(type)
                    << '\n';

                // Critical traffic must not be silently lost.
                // Abort this temporary transport session.
                // A1's retry logic handles unconfirmed commands.
                if (delivery ==
                    DeliveryMode::ReliableOrdered) {
                    transport->shutdown();
                }
            }

        } catch (const std::exception& e) {
            std::cerr
                << "[" << role
                << "] Enqueue error: "
                << e.what() << '\n';
        }
    };

    {
        auto test_sub = session.declare_subscriber(
            zenoh::KeyExpr(test_outbound),
            [&](const zenoh::Sample& sample) {
                forward(sample, test_type, 0);
            },
            zenoh::closures::none
        );

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

        auto video_load_sub = session.declare_subscriber(
            zenoh::KeyExpr(VIDEO_LOAD_TOPIC),
            [&](const zenoh::Sample& sample) {
                // Synthetic robot-to-operator video traffic.
                if (role == "robot") {
                    forward(
                        sample,
                        MessageType::Video,
                        4
                    );
                }
            },
            zenoh::closures::none
        );

        auto head_video_sub = session.declare_subscriber(
            zenoh::KeyExpr(HEAD_VIDEO_TX_TOPIC),

            // Called when a video fragment arrives.
            [&](const zenoh::Sample& sample) {
                if (role == "robot") {
                    forward(sample, MessageType::Video, 1);
                }
            },

            // Called when the subscriber is dropped.
            []() {}
        );

        auto wrist_left_video_sub =
            session.declare_subscriber(
                zenoh::KeyExpr(WRIST_LEFT_VIDEO_TX_TOPIC),
                [&](const zenoh::Sample& sample) {
                    if (role == "robot") {
                        forward(
                            sample,
                            MessageType::Video,
                            2
                        );
                    }
                },
                []() {}
            );

        auto wrist_right_video_sub =
            session.declare_subscriber(
                zenoh::KeyExpr(WRIST_RIGHT_VIDEO_TX_TOPIC),
                [&](const zenoh::Sample& sample) {
                    if (role == "robot") {
                        forward(
                            sample,
                            MessageType::Video,
                            3
                        );
                    }
                },
                []() {}
            );

        std::cout
            << "[" << role
            << "] Scheduler active; sender thread started\n";

        ByteBuffer encoded;

        // Receive on the main connection thread.
        while (transport->receive(encoded)) {
            try {
                Message msg = deserialize(encoded);

                if (msg.type == MessageType::ReliableCommand ||
                    msg.type == MessageType::ExecutionAck) {
                    std::cout
                        << "[" << role << "] TCP RECEIVED"
                        << " type=" << static_cast<int>(msg.type)
                        << " bridge_seq=" << msg.sequence
                        << " bytes=" << msg.payload.size()
                        << std::endl;
                }

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

                const bool is_video_load =
                    role == "operator" &&
                    msg.type == MessageType::Video &&
                    msg.stream_id == 4;

                const bool is_head_video =
                    role == "operator" &&
                    msg.type == MessageType::Video &&
                    msg.stream_id == 1;     
                
                const bool is_left_wrist_video =
                    role == "operator" &&
                    msg.type == MessageType::Video &&
                    msg.stream_id == 2;

                const bool is_right_wrist_video =
                    role == "operator" &&
                    msg.type == MessageType::Video &&
                    msg.stream_id == 3;

                const char* destination = nullptr;

                if (is_motion) {
                    destination = MOTION_TOPIC;
                } else if (is_reliable) {
                    destination = RELIABLE_TOPIC;
                } else if (is_ack) {
                    destination = RELIABLE_ACK_TOPIC;
                } else if (is_video_load) {
                    destination = VIDEO_LOAD_TOPIC;
                } else if (is_head_video) {
                    destination = HEAD_VIDEO_RX_TOPIC;
                } else if (is_left_wrist_video) {
                    destination = WRIST_LEFT_VIDEO_RX_TOPIC;
                } else if (is_right_wrist_video) {
                    destination = WRIST_RIGHT_VIDEO_RX_TOPIC;
                } else if (valid_test) {
                    destination = test_inbound;
                } else {
                    // Received a message with an unsupported type
                    // or direction.
                    receive_stats.record_invalid();

                    std::cerr
                        << "[" << role
                        << "] Unexpected message type\n";
                    continue;
                }

                // NEW: Count this valid, routed incoming message.
                receive_stats.record_received(
                    classify_received_message(msg),
                    encoded.size()
                );

                session.put(
                    zenoh::KeyExpr(destination),
                    zenoh::Bytes(msg.payload)
                );

            } catch (const std::exception& e) {
                receive_stats.record_invalid();

                std::cerr
                    << "[" << role
                    << "] Receive error: "
                    << e.what() << '\n';
                break;
            }
        }

        // Stop accepting new outbound messages by allowing
        // the subscriber objects to leave this scope.
    }

    // Stop the TCP transport and scheduler.
    transport->shutdown();
    scheduler.close();

    // Wait for the sender thread to finish.
    if (sender.joinable()) {
        sender.join();
    }

    // NEW: Stop the live statistics reporter.
    {
        std::lock_guard<std::mutex> lock(reporter_mutex);
        reporter_running = false;
    }

    // Wake up the reporter immediately instead of
    // waiting for its 5-second interval.
    reporter_cv.notify_one();

    // Wait for the reporter thread to finish.
    if (reporter.joinable()) {
        reporter.join();
    }

    {
        std::lock_guard<std::mutex> lock(
            bandwidth_mutex
        );
        bandwidth_running = false;
    }

    bandwidth_cv.notify_one();

    if (bandwidth_publisher.joinable()) {
        bandwidth_publisher.join();
    }

    // Print final statistics.
    auto stats = scheduler.stats();

    std::cout
        << "\n[" << role << "] Session finished\n"
        << "  Enqueued:    " << stats.accepted << '\n'
        << "  Sent:        " << stats.sent << '\n'
        << "  Dropped:     " << stats.dropped << '\n'
        << "  Expired:     " << stats.expired << '\n'
        << "  Rejected:    " << stats.rejected << '\n'
        << "  Send failed: " << stats.send_failed
        << "\n";

    print_scheduler_stats(
        scheduler.stats(),
        receive_stats.snapshot(),
        role
    );
}


void run_operator() {
    auto session = open_zenoh(7447);

    int server = teleop::TcpTransport::create_server(9000);

    std::cout
        << "[operator] Connected to zenoh router 7447\n"
        << "[operator] TCP listening on 127.0.0.1:9000\n";

    while (true) {
        auto transport =
            teleop::TcpTransport::accept_client(server);

        if (!transport) {
            std::cerr << "[operator] TCP accept failed\n";
            continue;
        }

        std::cout
            << "[operator] Robot bridge connected\n";

        run_connected(
            session, std::move(transport), "operator"
        );
    }
}

void run_robot() {
    auto session = open_zenoh(7448);

    std::cout
        << "[robot] Connected to zenoh router 7448\n";

    while (true) {
        auto transport =
            teleop::TcpTransport::connect_to(
                "127.0.0.1", 9000
            );

        if (transport) {
            std::cout
                << "[robot] Connected to operator bridge\n";

            run_connected(
                session, std::move(transport), "robot"
            );
        } else {
            std::cout
                << "[robot] Waiting for operator bridge\n";
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
