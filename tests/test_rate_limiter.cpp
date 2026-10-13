
#include <cassert>
#include <chrono>
#include <cmath>
#include <iostream>

#include "rate_limiter.hpp"

using namespace teleop;
using namespace std::chrono_literals;

int main() {
    using Clock = RateLimiter::Clock;

    const auto t0 = Clock::time_point{};
    RateLimiter limiter(t0);

    // Test 1: initial normal rate.
    assert(
        limiter.current_rate_mbps(t0) == 8.0
    );

    // Test 2: normal mode during first 45 seconds.
    assert(
        limiter.current_rate_mbps(t0 + 30s) == 8.0
    );

    // Test 3: degraded at second 45.
    assert(
        limiter.current_rate_mbps(t0 + 45s) == 2.0
    );

    assert(
        limiter.current_rate_mbps(t0 + 59s) == 2.0
    );

    // Test 4: normal again at second 60.
    assert(
        limiter.current_rate_mbps(t0 + 60s) == 8.0
    );

    assert(
        limiter.current_rate_mbps(t0 + 75s) == 8.0
    );

    // Test 5: burst capacity.
    assert(
        limiter.try_consume(4096, t0)
    );

    // No remaining tokens at the same instant.
    assert(
        !limiter.try_consume(1, t0)
    );

    // Test 6: normal rate replenishment.
    // 8 Mbit/s = 1,000 bytes per millisecond.
    assert(
        limiter.try_consume(1000, t0 + 1ms)
    );

    // Test 7: reject a message larger than burst cap.
    assert(
        !limiter.try_consume(5000, t0 + 2ms)
    );

    // Test 8: depleted bucket during degraded mode.
    RateLimiter degraded(t0);

    assert(
        degraded.try_consume(4096, t0 + 45s)
    );

    assert(
        !degraded.try_consume(1000, t0 + 45s)
    );

    // 2 Mbit/s = 250 bytes per millisecond.
    assert(
        degraded.try_consume(1000, t0 + 45s + 4ms)
    );

    // Test 9: zero tokens remain immediately afterward.
    assert(
        !degraded.try_consume(
            1, t0 + 45s + 4ms
        )
    );

    std::cout
        << "Rate limiter tests passed!\n"
        << "Normal budget: 8 Mbit/s\n"
        << "Degraded budget: 2 Mbit/s\n"
        << "Degraded interval: [45s, 60s)\n"
        << "Burst capacity: 4096 bytes\n";

    return 0;
}
