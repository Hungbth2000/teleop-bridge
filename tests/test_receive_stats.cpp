
#include <cassert>
#include <iostream>

#include "receive_stats.hpp"

using namespace teleop;

int main() {
    ReceiveStats receiver;

    receiver.record_received(TrafficKind::Motion, 126);
    receiver.record_received(TrafficKind::Motion, 126);
    receiver.record_received(TrafficKind::EStop, 43);
    receiver.record_invalid();

    const auto stats = receiver.snapshot();

    const auto motion =
        static_cast<std::size_t>(TrafficKind::Motion);

    const auto estop =
        static_cast<std::size_t>(TrafficKind::EStop);

    assert(stats.by_kind[motion] == 2);
    assert(stats.bytes_by_kind[motion] == 252);

    assert(stats.by_kind[estop] == 1);
    assert(stats.bytes_by_kind[estop] == 43);

    assert(stats.total == 3);
    assert(stats.total_bytes == 295);
    assert(stats.invalid == 1);

    std::cout << "Receive statistics tests passed!\n";
    return 0;
}
