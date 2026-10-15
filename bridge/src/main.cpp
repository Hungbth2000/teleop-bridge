#include <memory>
#include <iomanip>

#include "scheduler.hpp"
#include "transport.hpp"
#include "transport_factory.hpp"
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
#include <cstdlib>
#include <condition_variable>

#include <unordered_map>
#include <optional>

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

constexpr const char* ROBOT_STATE_TOPIC =
    "teleop/robot/state";

constexpr const char* CONFIG_QUERY_TOPIC =
    "teleop/robot/config";

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

bool use_hybrid_transport();

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
    CsvTelemetry csv_telemetry(
        role,
        use_hybrid_transport() ? "hybrid" : "tcp"
    );

    std::atomic<std::uint64_t> next_sequence{1};

    // Native Zenoh queries awaiting replies from B3.
    //
    // Query::clone() allows us to retain the original
    // A3 query after its queryable callback returns.
    std::mutex pending_queries_mutex;

    struct PendingQuery {
        zenoh::Query query;
        Clock::time_point deadline;
    };

    std::unordered_map<
        std::uint64_t,
        PendingQuery
    > pending_queries;

    // A query expires after three seconds.
    constexpr auto QUERY_TIMEOUT =
        std::chrono::milliseconds(3000);

    std::atomic<bool> timeout_running{true};

    std::thread timeout_worker([&] {
        using namespace std::chrono_literals;

        while (timeout_running.load()) {
            std::this_thread::sleep_for(100ms);

            std::vector<zenoh::Query> expired;
            std::vector<std::uint64_t> expired_ids;

            {
                std::lock_guard<std::mutex> guard(
                    pending_queries_mutex
                );

                const auto now = Clock::now();

                for (auto it = pending_queries.begin();
                    it != pending_queries.end();) {

                    if (now >= it->second.deadline) {
                        expired_ids.push_back(it->first);

                        expired.push_back(
                            std::move(it->second.query)
                        );

                        it = pending_queries.erase(it);
                    } else {
                        ++it;
                    }
                }
            }

            // Release cloned Zenoh queries outside the mutex.
            // This completes unanswered queries without
            // manufacturing a successful response.
            expired.clear();

            for (const auto id : expired_ids) {
                std::cerr
                    << "[operator] CONFIG QUERY EXPIRED"
                    << " id=" << id
                    << '\n';
            }
        }
    });

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

        auto robot_state_sub = session.declare_subscriber(
            zenoh::KeyExpr(ROBOT_STATE_TOPIC),
            [&](const zenoh::Sample& sample) {
                if (role == "robot") {
                    forward(
                        sample,
                        MessageType::RobotState,
                        5
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

        std::optional<zenoh::Queryable<void>> config_queryable;

        // A3 sends a native Zenoh query to this proxy.
        // Only the operator bridge should forward it.
        if (role == "operator") {
            config_queryable.emplace(
                session.declare_queryable(
                    zenoh::KeyExpr(CONFIG_QUERY_TOPIC),

                    [&](zenoh::Query& query) {

                        const std::uint64_t request_id =
                            next_sequence.fetch_add(1);

                        // Retain the query beyond this callback.
                        {
                            std::lock_guard<std::mutex> guard(
                                pending_queries_mutex
                            );

                            pending_queries.emplace(
                                request_id,
                                PendingQuery{
                                    query.clone(),
                                    Clock::now() + QUERY_TIMEOUT
                                }
                            );
                        }

                        // Build a bridge message for the robot side.
                        Message msg{};
                        msg.type = MessageType::Query;
                        msg.stream_id = 6;
                        msg.sequence = request_id;
                        msg.timestamp_ns = now_ns();

                        // This first implementation supports only
                        // the fixed teleop/robot/config query.
                        msg.payload = {};

                        try {
                            const auto result = scheduler.enqueue(
                                serialize(msg),
                                MessageType::Query,
                                DeliveryMode::ReliableOrdered,
                                TrafficKind::Query
                            );

                            if (result == EnqueueResult::Rejected) {
                                {
                                    std::lock_guard<std::mutex> guard(
                                        pending_queries_mutex
                                    );

                                    pending_queries.erase(request_id);
                                }

                                std::cerr
                                    << "[operator] CONFIG QUERY REJECTED"
                                    << " id=" << request_id
                                    << '\n';

                                return;
                            }

                            std::cout
                                << "[operator] CONFIG QUERY QUEUED"
                                << " id=" << request_id
                                << '\n';

                        } catch (const std::exception& e) {
                            {
                                std::lock_guard<std::mutex> guard(
                                    pending_queries_mutex
                                );

                                pending_queries.erase(request_id);
                            }

                            std::cerr
                                << "[operator] Query enqueue error: "
                                << e.what() << '\n';
                        }
                    },

                    zenoh::closures::none
                )
            );
        }

        std::cout
            << "[" << role
            << "] Scheduler active; sender thread started\n";

        ByteBuffer encoded;

        // Keep query workers alive until this TCP session ends.
        struct QueryWorker {
            std::thread thread;
            std::shared_ptr<std::atomic<bool>> finished;
        };

        std::vector<QueryWorker> query_workers;

        // Maximum number of queries being processed concurrently.
        constexpr unsigned MAX_ACTIVE_QUERIES = 8;

        std::atomic<unsigned> active_queries{0};

        query_workers.reserve(MAX_ACTIVE_QUERIES);

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

                const bool is_robot_state =
                    role == "operator" &&
                    msg.type == MessageType::RobotState &&
                    msg.stream_id == 5;

                const bool is_config_query =
                    role == "robot" &&
                    msg.type == MessageType::Query &&
                    msg.stream_id == 6;

                const bool is_config_reply =
                    role == "operator" &&
                    msg.type == MessageType::Reply &&
                    msg.stream_id == 6;

                if (is_config_query) {
                    receive_stats.record_received(
                        classify_received_message(msg),
                        encoded.size()
                    );

                    const std::uint64_t request_id = msg.sequence;

                    // Reclaim workers that completed earlier.
                    // Only the TCP receive thread modifies this vector.
                    query_workers.erase(
                        std::remove_if(
                            query_workers.begin(),
                            query_workers.end(),
                            [](QueryWorker& worker) {
                                if (!worker.finished->load()) {
                                    return false;
                                }

                                if (worker.thread.joinable()) {
                                    worker.thread.join();
                                }

                                return true;
                            }
                        ),
                        query_workers.end()
                    );

                    const unsigned previous =
                        active_queries.fetch_add(1);

                    if (previous >= MAX_ACTIVE_QUERIES) {
                        active_queries.fetch_sub(1);

                        std::cerr
                            << "[robot] CONFIG QUERY OVERLOAD"
                            << " id=" << request_id
                            << " active=" << previous
                            << '\n';

                        // No successful reply is manufactured.
                        // A3 will observe query failure/timeout.
                        continue;
                    }

                    std::cout
                        << "[robot] TCP CONFIG QUERY RECEIVED"
                        << " id=" << request_id
                        << '\n';

                    bool worker_slot_added = false;

                    try {
                        // Create a flag shared between the worker
                        // and the TCP receive thread.
                        auto finished =
                            std::make_shared<std::atomic<bool>>(false);

                        // Create the worker thread.
                        // Store an empty thread before starting it.
                        query_workers.push_back(
                            QueryWorker{
                                std::thread{},
                                finished
                            }
                        );

                        worker_slot_added = true;

                        // Start the thread in its already-owned slot.
                        query_workers.back().thread =
                            std::thread([&, request_id, finished] {

                                // Set the flag when this worker exits.
                                struct FinishedGuard {
                                    std::shared_ptr<std::atomic<bool>> flag;

                                    ~FinishedGuard() {
                                        flag->store(true);
                                    }
                                };

                                FinishedGuard finished_guard{finished};

                                // Automatically release the active-query slot,
                                // including when a query times out or throws.
                                struct ActiveQueryGuard {
                                    std::atomic<unsigned>& counter;

                                    ~ActiveQueryGuard() {
                                        counter.fetch_sub(1);
                                    }
                                };

                                ActiveQueryGuard active_guard{active_queries};

                                // Test-only delay to verify the concurrency limit.
                                if (const char* value =
                                        std::getenv("TELEOP_QUERY_DELAY_MS")) {

                                    try {
                                        const int delay_ms = std::stoi(value);

                                        if (delay_ms > 0 && delay_ms <= 2000) {
                                            std::this_thread::sleep_for(
                                                std::chrono::milliseconds(delay_ms)
                                            );
                                        }

                                    } catch (const std::exception&) {
                                        std::cerr
                                            << "[robot] Invalid TELEOP_QUERY_DELAY_MS\n";
                                    }
                                }

                                struct QueryState {
                                    std::mutex mutex;
                                    std::condition_variable cv;
                                    bool complete = false;
                                    std::optional<std::vector<std::uint8_t>> payload;
                                };

                                auto state = std::make_shared<QueryState>();

                                try {
                                    auto options =
                                        zenoh::Session::GetOptions::create_default();

                                    options.timeout_ms = 3000;

                                    session.get(
                                        zenoh::KeyExpr(CONFIG_QUERY_TOPIC),
                                        "",

                                        [state](zenoh::Reply& reply) {
                                            if (!reply.is_ok()) {
                                                return;
                                            }

                                            auto data =
                                                reply.get_ok().get_payload().as_vector();

                                            std::lock_guard<std::mutex> guard(
                                                state->mutex
                                            );

                                            // Accept the first successful reply only.
                                            if (!state->payload.has_value()) {
                                                state->payload = std::move(data);
                                            }
                                        },

                                        [state]() {
                                            {
                                                std::lock_guard<std::mutex> guard(
                                                    state->mutex
                                                );

                                                state->complete = true;
                                            }

                                            state->cv.notify_one();
                                        },

                                        std::move(options)
                                    );

                                    std::optional<std::vector<std::uint8_t>> payload;

                                    {
                                        std::unique_lock<std::mutex> lock(
                                            state->mutex
                                        );

                                        // Give Zenoh slightly longer than its own
                                        // 3000 ms timeout to finish the query.
                                        const bool completed = state->cv.wait_for(
                                            lock,
                                            std::chrono::milliseconds(3500),
                                            [&] { return state->complete; }
                                        );

                                        if (completed && state->payload.has_value()) {
                                            payload = std::move(state->payload);
                                        }
                                    }

                                    if (!payload.has_value()) {
                                        std::cerr
                                            << "[robot] CONFIG QUERY TIMEOUT/NO REPLY"
                                            << " id=" << request_id
                                            << '\n';

                                        return;
                                    }

                                    Message response{};
                                    response.type = MessageType::Reply;
                                    response.stream_id = 6;
                                    response.sequence = request_id;
                                    response.timestamp_ns = now_ns();
                                    response.payload = std::move(*payload);

                                    const auto result = scheduler.enqueue(
                                        serialize(response),
                                        MessageType::Reply,
                                        DeliveryMode::ReliableOrdered,
                                        TrafficKind::Reply
                                    );

                                    if (result == EnqueueResult::Rejected) {
                                        std::cerr
                                            << "[robot] CONFIG REPLY QUEUE REJECTED"
                                            << " id=" << request_id
                                            << '\n';

                                        return;
                                    }

                                    std::cout
                                        << "[robot] CONFIG REPLY QUEUED"
                                        << " id=" << request_id
                                        << '\n';

                                } catch (const std::exception& e) {
                                    std::cerr
                                        << "[robot] CONFIG QUERY ERROR"
                                        << " id=" << request_id
                                        << " error=" << e.what()
                                        << '\n';
                                }
                        });

                    } catch (const std::exception& e) {
                        // No thread started successfully.
                        // Remove its empty slot if one was added.
                        if (worker_slot_added) {
                            query_workers.pop_back();
                        }

                        active_queries.fetch_sub(1);

                        std::cerr
                            << "[robot] Failed to start query worker"
                            << " id=" << request_id
                            << " error=" << e.what()
                            << '\n';
                    }

                    continue;
                }

                if (is_config_reply) {
                    receive_stats.record_received(
                        classify_received_message(msg),
                        encoded.size()
                    );

                    std::optional<zenoh::Query> pending;

                    {
                        std::lock_guard<std::mutex> guard(
                            pending_queries_mutex
                        );

                        auto it = pending_queries.find(msg.sequence);

                        if (it != pending_queries.end()) {
                            if (Clock::now() < it->second.deadline) {
                                pending.emplace(std::move(it->second.query));
                            }

                            pending_queries.erase(it);
                        }
                    }

                    if (!pending.has_value()) {
                        std::cerr
                            << "[operator] UNKNOWN/DUPLICATE CONFIG REPLY"
                            << " id=" << msg.sequence
                            << '\n';

                        continue;
                    }

                    try {
                        pending->reply(
                            zenoh::KeyExpr(CONFIG_QUERY_TOPIC),
                            zenoh::Bytes(msg.payload)
                        );

                        std::cout
                            << "[operator] NATIVE CONFIG REPLY SENT"
                            << " id=" << msg.sequence
                            << " bytes=" << msg.payload.size()
                            << '\n';

                    } catch (const std::exception& e) {
                        std::cerr
                            << "[operator] CONFIG REPLY ERROR"
                            << " id=" << msg.sequence
                            << " error=" << e.what()
                            << '\n';
                    }

                    continue;
                }

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
                } else if (is_robot_state) {
                    destination = ROBOT_STATE_TOPIC;
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

        // Wait for any remaining query workers to finish.
        for (auto& worker : query_workers) {
            if (worker.thread.joinable()) {
                worker.thread.join();
            }
        }

        query_workers.clear();

        // Stop accepting new outbound messages by allowing
        // the subscriber objects to leave this scope.
    }

    timeout_running.store(false);

    if (timeout_worker.joinable()) {
        timeout_worker.join();
    }

    {
        std::lock_guard<std::mutex> guard(
            pending_queries_mutex
        );

        pending_queries.clear();
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

const char* env_address(
    const char* name,
    const char* fallback = "127.0.0.1"
) {
    const char* value = std::getenv(name);

    return (value != nullptr && value[0] != '\0')
        ? value
        : fallback;
}

bool use_hybrid_transport() {
    const std::string mode =
        env_address("TELEOP_TRANSPORT", "tcp");

    if (mode != "tcp" && mode != "hybrid") {
        throw std::runtime_error(
            "TELEOP_TRANSPORT must be tcp or hybrid"
        );
    }

    return mode == "hybrid";
}

void run_operator() {

    std::cout
        << "[bridge] Transport mode: "
        << (use_hybrid_transport() ? "hybrid" : "tcp")
        << '\n';

    auto session = open_zenoh(7447);

    const char* bind_address =
        env_address("TELEOP_TCP_BIND");

    int server = teleop::TransportFactory::create_server(
        9000, bind_address
    );

    std::cout
        << "[operator] Connected to zenoh router 7447\n"
        << "[operator] TCP listening on "
        << bind_address << ":9000\n";

    while (true) {
        std::unique_ptr<teleop::ITransport> transport;

        if (use_hybrid_transport()) {
            transport = teleop::TransportFactory::accept_hybrid(
                server,
                env_address("TELEOP_UDP_LOCAL"),
                env_address("TELEOP_UDP_PEER")
            );
        } else {
            transport =
                teleop::TransportFactory::accept_client(server);
        }

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

    std::cout
        << "[bridge] Transport mode: "
        << (use_hybrid_transport() ? "hybrid" : "tcp")
        << '\n';

    auto session = open_zenoh(7448);

    const char* operator_address =
        env_address("TELEOP_TCP_HOST");

    std::cout
        << "[robot] Connected to zenoh router 7448\n";

    while (true) {
        std::unique_ptr<teleop::ITransport> transport;

        if (use_hybrid_transport()) {
            transport = teleop::TransportFactory::connect_hybrid(
                operator_address,
                9000,
                env_address("TELEOP_UDP_LOCAL"),
                env_address("TELEOP_UDP_PEER")
            );
        } else {
            transport =
                teleop::TransportFactory::connect_to(
                    operator_address, 9000
                );
        }

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
