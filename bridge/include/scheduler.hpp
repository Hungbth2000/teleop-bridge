
#pragma once

#include "message.hpp"
#include "transport.hpp"
#include "rate_limiter.hpp"

#include <array>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <utility>

namespace teleop {

// More specific than MessageType:
// E-stop and reset have the same wire message type.
enum class TrafficKind : std::size_t {
    Motion,
    EStop,
    Reset,
    ReliableOther,
    ExecutionAck,
    RobotState,
    Video,
    Query,
    Reply,
    Test,
    Count
};

inline constexpr std::size_t TRAFFIC_KIND_COUNT =
    static_cast<std::size_t>(TrafficKind::Count);

inline constexpr std::array<const char*, TRAFFIC_KIND_COUNT>
TRAFFIC_KIND_NAMES = {
    "Motion",
    "E-stop",
    "Reset",
    "Reliable other",
    "Execution ACK",
    "Robot state",
    "Video",
    "Query",
    "Reply",
    "Test"
};

struct ScheduledMessage {
    ByteBuffer bytes;
    MessageType type;
    DeliveryMode delivery;
    TrafficKind kind;
    std::chrono::steady_clock::time_point queued_at;
};

enum class EnqueueResult {
    Accepted,
    ReplacedOrDroppedOld,
    Rejected
};

struct MessageCounters {
    std::uint64_t enqueued = 0;
    std::uint64_t sent = 0;
    std::uint64_t dropped = 0;
    std::uint64_t expired = 0;
    std::uint64_t rejected = 0;
    std::uint64_t send_failed = 0;

    // NEW: serialized message bytes
    std::uint64_t enqueued_bytes = 0;
    std::uint64_t sent_bytes = 0;
};

struct SchedulerStats {
    // Preserve the existing overall counters.
    std::uint64_t accepted = 0;
    std::uint64_t dropped = 0;
    std::uint64_t rejected = 0;
    std::uint64_t sent = 0;
    std::uint64_t expired = 0;
    std::uint64_t send_failed = 0;

    // NEW: counters for individual traffic categories.
    std::array<MessageCounters, TRAFFIC_KIND_COUNT> by_kind{};
};

class PriorityScheduler {
public:
    EnqueueResult enqueue(
        ByteBuffer bytes,
        MessageType type,
        DeliveryMode delivery,
        TrafficKind kind = TrafficKind::Count
    ) {
        if (kind == TrafficKind::Count) {
            kind = default_kind(type);
        }

        std::lock_guard<std::mutex> guard(mutex_);

        auto& counters = stats_.by_kind[index(kind)];

        if (closed_) {
            ++stats_.rejected;
            ++counters.rejected;
            return EnqueueResult::Rejected;
        }

        const auto priority = classify(type);
        auto& queue = queues_[priority];

        bool dropped_old = false;

        if (queue.size() >= capacities_[priority]) {
            // Do not silently evict reliable messages.
            if (priority == 0) {
                ++stats_.rejected;
                ++counters.rejected;
                return EnqueueResult::Rejected;
            }

            const auto old_kind = queue.front().kind;

            ++stats_.dropped;
            ++stats_.by_kind[index(old_kind)].dropped;

            queue.pop_front();
            dropped_old = true;
        }

        queue.push_back(ScheduledMessage{
            std::move(bytes),
            type,
            delivery,
            kind,
            std::chrono::steady_clock::now()
        });

        ++stats_.accepted;
        ++counters.enqueued;

        // NEW: count the serialized bytes accepted into this queue.
        counters.enqueued_bytes += queue.back().bytes.size();

        condition_.notify_one();

        return dropped_old
            ? EnqueueResult::ReplacedOrDroppedOld
            : EnqueueResult::Accepted;
    }

    bool pop(ScheduledMessage& result) {
        std::unique_lock<std::mutex> lock(mutex_);

        condition_.wait(lock, [&] {
            return closed_ || has_messages();
        });

        if (closed_) {
            return false;
        }

        for (auto& queue : queues_) {
            if (!queue.empty()) {
                result = std::move(queue.front());
                queue.pop_front();
                return true;
            }
        }

        return false;
    }
    
    bool pop_limited(
        ScheduledMessage& result,
        RateLimiter& limiter
    ) {
        std::unique_lock<std::mutex> lock(mutex_);

        while (!closed_) {
            bool found_message = false;

            for (auto& queue : queues_) {
                if (queue.empty()) {
                    continue;
                }

                found_message = true;

                const auto& front = queue.front();
                const auto bytes = front.bytes.size();

                // An oversized message cannot fit into
                // the configured token bucket.
                // We will fragment video before sending.
                if (bytes > RateLimiter::BURST_BYTES) {
                    ++stats_.dropped;
                    ++stats_.by_kind[
                        static_cast<std::size_t>(
                            front.kind
                        )
                    ].dropped;

                    queue.pop_front();
                    break;
                }

                if (limiter.try_consume(bytes)) {
                    result = std::move(queue.front());
                    queue.pop_front();
                    return true;
                }

                // Insufficient tokens for the highest
                // priority pending message.
                // Do not send lower-priority traffic first.
                break;
            }

            // Wait briefly, but wake immediately when
            // another callback enqueues a new message
            // or when the scheduler closes.
            if (!found_message) {
                condition_.wait(lock, [&] {
                    return closed_ || has_messages();
                });
            } else {
                condition_.wait_for(
                    lock,
                    std::chrono::milliseconds(2)
                );
            }
        }

        return false;
    }

    void record_sent(
        TrafficKind kind,
        std::size_t bytes
    ) {
        std::lock_guard<std::mutex> guard(mutex_);

        ++stats_.sent;

        auto& counters = stats_.by_kind[index(kind)];

        ++counters.sent;
        counters.sent_bytes += bytes;
    }

    void record_expired(TrafficKind kind) {
        std::lock_guard<std::mutex> guard(mutex_);
        ++stats_.expired;
        ++stats_.by_kind[index(kind)].expired;
    }

    void record_send_failed(TrafficKind kind) {
        std::lock_guard<std::mutex> guard(mutex_);
        ++stats_.send_failed;
        ++stats_.by_kind[index(kind)].send_failed;
    }

    SchedulerStats stats() const {
        std::lock_guard<std::mutex> guard(mutex_);
        return stats_;
    }

    void close() {
        {
            std::lock_guard<std::mutex> guard(mutex_);
            closed_ = true;

            // Do not replay queued messages after reconnect.
            for (auto& queue : queues_) {
                for (const auto& item : queue) {
                    ++stats_.dropped;
                    ++stats_.by_kind[index(item.kind)].dropped;
                }
                queue.clear();
            }
        }

        condition_.notify_all();
    }

private:
    static std::size_t index(TrafficKind kind) {
        return static_cast<std::size_t>(kind);
    }

    static TrafficKind default_kind(MessageType type) {
        switch (type) {
            case MessageType::FastCommand:
                return TrafficKind::Motion;

            case MessageType::ReliableCommand:
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

    static std::size_t classify(MessageType type) {
        switch (type) {
            case MessageType::ReliableCommand:
            case MessageType::ExecutionAck:
            case MessageType::Query:
            case MessageType::Reply:
                return 0;

            case MessageType::FastCommand:
                return 1;

            case MessageType::RobotState:
                return 2;

            case MessageType::Video:
                return 3;
        }

        return 3;
    }

    bool has_messages() const {
        for (const auto& queue : queues_) {
            if (!queue.empty()) {
                return true;
            }
        }
        return false;
    }

    mutable std::mutex mutex_;
    std::condition_variable condition_;

    std::array<std::deque<ScheduledMessage>, 4> queues_;

    const std::array<std::size_t, 4> capacities_{
        64, 1, 16, 64
    };

    SchedulerStats stats_;
    bool closed_ = false;
};

} // namespace teleop
