
#include <cassert>
#include <iostream>

#include "scheduler.hpp"

using namespace teleop;

ByteBuffer data(std::uint8_t value) {
    return {value};
}

int main() {
    PriorityScheduler scheduler;

    // Robot state update.
    scheduler.enqueue(
        data(10),
        MessageType::RobotState,
        DeliveryMode::Unreliable,
        TrafficKind::RobotState
    );

    // Newer movement replaces older unsent movement.
    scheduler.enqueue(
        data(20),
        MessageType::FastCommand,
        DeliveryMode::Unreliable,
        TrafficKind::Motion
    );

    scheduler.enqueue(
        data(21),
        MessageType::FastCommand,
        DeliveryMode::Unreliable,
        TrafficKind::Motion
    );

    // Two critical commands.
    scheduler.enqueue(
        data(30),
        MessageType::ReliableCommand,
        DeliveryMode::ReliableOrdered,
        TrafficKind::EStop
    );

    scheduler.enqueue(
        data(31),
        MessageType::ReliableCommand,
        DeliveryMode::ReliableOrdered,
        TrafficKind::Reset
    );

    ScheduledMessage item;

    // Critical messages first, in their enqueue order.
    assert(scheduler.pop(item));
    assert(item.bytes == data(30));
    assert(item.kind == TrafficKind::EStop);
    scheduler.record_sent(item.kind, item.bytes.size());

    assert(scheduler.pop(item));
    assert(item.bytes == data(31));
    assert(item.kind == TrafficKind::Reset);
    scheduler.record_sent(item.kind, item.bytes.size());

    // Then the newest movement command.
    assert(scheduler.pop(item));
    assert(item.bytes == data(21));
    assert(item.kind == TrafficKind::Motion);
    scheduler.record_sent(item.kind, item.bytes.size());

    // Robot state is lower priority.
    assert(scheduler.pop(item));
    assert(item.bytes == data(10));
    assert(item.kind == TrafficKind::RobotState);
    scheduler.record_sent(item.kind, item.bytes.size());

    const auto stats = scheduler.stats();

    assert(stats.accepted == 5);
    assert(stats.sent == 4);
    assert(stats.dropped == 1);

    const auto& motion =
        stats.by_kind[
            static_cast<std::size_t>(TrafficKind::Motion)
        ];

    assert(motion.enqueued == 2);
    assert(motion.sent == 1);
    assert(motion.dropped == 1);

    assert(motion.enqueued_bytes == 2);
    assert(motion.sent_bytes == 1);

    const auto& estop =
        stats.by_kind[
            static_cast<std::size_t>(TrafficKind::EStop)
        ];

    assert(estop.enqueued == 1);
    assert(estop.sent == 1);

    assert(estop.enqueued_bytes == 1);
    assert(estop.sent_bytes == 1);

    const auto& reset =
        stats.by_kind[
            static_cast<std::size_t>(TrafficKind::Reset)
        ];

    assert(reset.enqueued == 1);
    assert(reset.sent == 1);

    scheduler.close();

    std::cout << "Scheduler tests passed!\n";
    std::cout << "Accepted: " << stats.accepted << '\n';
    std::cout << "Sent: " << stats.sent << '\n';
    std::cout << "Dropped: " << stats.dropped << '\n';

    return 0;
}