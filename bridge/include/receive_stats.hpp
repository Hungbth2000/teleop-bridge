
#pragma once

#include "scheduler.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace teleop {

struct ReceiveSnapshot {
    // Received message counts.
    std::array<std::uint64_t, TRAFFIC_KIND_COUNT>
        by_kind{};

    // NEW: received serialized bytes per category.
    std::array<std::uint64_t, TRAFFIC_KIND_COUNT>
        bytes_by_kind{};

    std::uint64_t total = 0;
    std::uint64_t total_bytes = 0;
    std::uint64_t invalid = 0;
};

class ReceiveStats {
public:
    void record_received(
        TrafficKind kind,
        std::size_t bytes
    ) {
        const auto index = static_cast<std::size_t>(kind);

        if (index >= TRAFFIC_KIND_COUNT) {
            record_invalid();
            return;
        }

        std::lock_guard<std::mutex> lock(mutex_);

        ++data_.by_kind[index];
        data_.bytes_by_kind[index] += bytes;

        ++data_.total;
        data_.total_bytes += bytes;
    }

    void record_invalid() {
        std::lock_guard<std::mutex> lock(mutex_);
        ++data_.invalid;
    }

    ReceiveSnapshot snapshot() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return data_;
    }

private:
    mutable std::mutex mutex_;
    ReceiveSnapshot data_;
};

} // namespace teleop
