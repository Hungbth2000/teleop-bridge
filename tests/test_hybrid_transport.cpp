
#include "hybrid_transport.hpp"
#include <atomic>
#include <functional>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>

using namespace teleop;

namespace teleop {

struct HybridTransportTestAccess {
    static void enqueue_both(
        HybridTransport& hybrid,
        ByteBuffer reliable,
        ByteBuffer realtime
    ) {
        std::lock_guard<std::mutex> lock(hybrid.mutex_);

        hybrid.reliable_queue_.push_back(
            std::move(reliable)
        );

        hybrid.realtime_queue_.push_back(
            std::move(realtime)
        );

        hybrid.cv_.notify_all();
    }
};

} // namespace teleop

class MockTransport final : public ITransport {
public:
    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override {
        std::lock_guard<std::mutex> lock(mutex_);

        if (stopped_) {
            return false;
        }

        sent_.push_back(message);
        last_mode_ = mode;
        return true;
    }

    void set_receive_callback(std::function<void()> callback) {
        std::lock_guard<std::mutex> lock(mutex_);
        receive_callback_ = std::move(callback);
    }

    bool receive(ByteBuffer& message) override {
        std::unique_lock<std::mutex> lock(mutex_);

        cv_.wait(lock, [&] {
            return stopped_ || !incoming_.empty();
        });

        if (stopped_) {
            return false;
        }

        message = std::move(incoming_.front());
        incoming_.pop_front();
        return true;
    }

    void shutdown() override {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stopped_ = true;
        }
        cv_.notify_all();
    }

    void inject(ByteBuffer message) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            incoming_.push_back(std::move(message));
        }
        cv_.notify_one();
    }

    std::size_t sent_count() {
        std::lock_guard<std::mutex> lock(mutex_);
        return sent_.size();
    }

    DeliveryMode last_mode() {
        std::lock_guard<std::mutex> lock(mutex_);
        return last_mode_;
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    std::function<void()> receive_callback_;

    bool stopped_ = false;

    std::deque<ByteBuffer> incoming_;
    std::deque<ByteBuffer> sent_;

    DeliveryMode last_mode_ = DeliveryMode::Unreliable;
};

int main() {
    auto reliable = std::make_unique<MockTransport>();
    auto realtime = std::make_unique<MockTransport>();

    auto* reliable_ptr = reliable.get();
    auto* realtime_ptr = realtime.get();

    HybridTransport hybrid(
        std::move(reliable),
        std::move(realtime)
    );

    ByteBuffer reliable_message{1, 2, 3};
    ByteBuffer realtime_message{4, 5, 6};

    // Reliable messages should use the reliable lane.
    assert(hybrid.send(
        reliable_message,
        DeliveryMode::ReliableOrdered
    ));

    assert(reliable_ptr->sent_count() == 1);
    assert(realtime_ptr->sent_count() == 0);
    assert(
        reliable_ptr->last_mode() ==
        DeliveryMode::ReliableOrdered
    );

    // Unreliable messages should use the real-time lane.
    assert(hybrid.send(
        realtime_message,
        DeliveryMode::Unreliable
    ));

    assert(reliable_ptr->sent_count() == 1);
    assert(realtime_ptr->sent_count() == 1);

    // Verify reception from the real-time lane.
    std::cerr << "[TEST] Injecting realtime message\n";
    realtime_ptr->inject(realtime_message);

    ByteBuffer received;

    std::cerr << "[TEST] Waiting for realtime receive\n";
    assert(hybrid.receive(received));

    std::cerr << "[TEST] Realtime received\n";
    assert(received == realtime_message);

    // Verify reception from the reliable lane.
    std::cerr << "[TEST] Injecting reliable message\n";
    reliable_ptr->inject(reliable_message);

    std::cerr << "[TEST] Waiting for reliable receive\n";
    assert(hybrid.receive(received));

    std::cerr << "[TEST] Reliable received\n";
    assert(received == reliable_message);

    // Both messages are queued before receive() is called.
    std::cerr << "[TEST] Checking reliable priority\n";

    ByteBuffer priority_reliable{10, 11, 12};
    ByteBuffer priority_realtime{20, 21, 22};

    HybridTransportTestAccess::enqueue_both(
        hybrid,
        priority_reliable,
        priority_realtime
    );

assert(hybrid.receive(received));
assert(received == priority_reliable);

assert(hybrid.receive(received));
assert(received == priority_realtime);

std::cerr << "[TEST] Reliable priority passed\n";

    // Verify shutdown.
    std::cerr << "[TEST] Shutting down\n";
    hybrid.shutdown();

    std::cerr << "[TEST] Shutdown called\n";

    std::cerr << "[TEST] Checking send after shutdown\n";
    assert(!hybrid.send(
        realtime_message,
        DeliveryMode::Unreliable
    ));

    std::cerr << "[TEST] Checking receive after shutdown\n";
    assert(!hybrid.receive(received));

    std::cerr << "[TEST] All assertions passed\n";

    std::cout << "Hybrid transport tests passed\n";
}
