
#pragma once

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace teleop {

class RateLimiter {
public:
    using Clock = std::chrono::steady_clock;
    using TimePoint = Clock::time_point;

    static constexpr double NORMAL_BPS = 8'000'000.0;
    static constexpr double DEGRADED_BPS = 2'000'000.0;

    static constexpr double CYCLE_SECONDS = 60.0;
    static constexpr double DEGRADED_START = 45.0;

    // Maximum accumulated burst allowance.
    // Future video messages must be fragmented to fit.
    static constexpr std::size_t BURST_BYTES = 4096;

    explicit RateLimiter(
        TimePoint start = Clock::now()
    )
        : start_(start),
          last_update_(start),
          tokens_(static_cast<double>(BURST_BYTES)) {}

    double current_rate_bps(TimePoint now) const {
        const double elapsed =
            std::max(
                0.0,
                std::chrono::duration<double>(
                    now - start_
                ).count()
            );

        const double position =
            elapsed -
            CYCLE_SECONDS *
                static_cast<std::uint64_t>(
                    elapsed / CYCLE_SECONDS
                );

        return position < DEGRADED_START
            ? NORMAL_BPS
            : DEGRADED_BPS;
    }

    // Nonblocking: returns false if insufficient tokens.
    // It never sleeps or waits for bandwidth.
    bool try_consume(
        std::size_t bytes,
        TimePoint now = Clock::now()
    ) {
        if (bytes > BURST_BYTES) {
            return false;
        }

        refill(now);

        if (tokens_ + 1e-9 <
            static_cast<double>(bytes)) {
            return false;
        }

        tokens_ -= static_cast<double>(bytes);
        return true;
    }

    double available_tokens(
        TimePoint now = Clock::now()
    ) {
        refill(now);
        return tokens_;
    }

    double current_rate_mbps(
        TimePoint now = Clock::now()
    ) const {
        return current_rate_bps(now) / 1'000'000.0;
    }

private:
    void refill(TimePoint now) {
        if (now <= last_update_) {
            return;
        }

        // Integrate the token rate across phase boundaries.
        // This handles a refill spanning 8 -> 2 -> 8 Mbps.
        auto cursor = last_update_;

        while (cursor < now) {
            const double elapsed =
                std::chrono::duration<double>(
                    cursor - start_
                ).count();

            const double cycle =
                static_cast<double>(
                    static_cast<std::uint64_t>(
                        std::max(0.0, elapsed) /
                        CYCLE_SECONDS
                    )
                );

            const double cycle_start =
                cycle * CYCLE_SECONDS;

            const double phase =
                elapsed - cycle_start;

            const double next_boundary_seconds =
                cycle_start +
                (phase < DEGRADED_START
                    ? DEGRADED_START
                    : CYCLE_SECONDS);

            const auto boundary = start_ +
                std::chrono::duration_cast<
                    Clock::duration
                >(
                    std::chrono::duration<double>(
                        next_boundary_seconds
                    )
                );

            const auto end =
                std::min(now, boundary);

            if (end <= cursor) {
                break;
            }

            const double seconds =
                std::chrono::duration<double>(
                    end - cursor
                ).count();

            const double bytes_per_second =
                current_rate_bps(cursor) / 8.0;

            tokens_ = std::min(
                static_cast<double>(BURST_BYTES),
                tokens_ + seconds * bytes_per_second
            );

            cursor = end;
        }

        last_update_ = now;
    }

    TimePoint start_;
    TimePoint last_update_;
    double tokens_;
};

} // namespace teleop
