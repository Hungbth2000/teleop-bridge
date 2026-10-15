
#pragma once

#include "transport.hpp"

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>

namespace teleop {

class HybridTransport final : public ITransport {
public:
    HybridTransport(
        std::unique_ptr<ITransport> reliable,
        std::unique_ptr<ITransport> realtime
    );

    ~HybridTransport() override;

    HybridTransport(const HybridTransport&) = delete;
    HybridTransport& operator=(const HybridTransport&) = delete;

    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override;

    bool receive(ByteBuffer& message) override;

    void shutdown() override;

private:
    friend struct HybridTransportTestAccess;
    static constexpr std::size_t MAX_REALTIME_QUEUE = 256;
    static constexpr std::size_t MAX_RELIABLE_QUEUE = 256;

    std::unique_ptr<ITransport> reliable_;
    std::unique_ptr<ITransport> realtime_;

    std::atomic<bool> running_{true};

    std::thread reliable_receiver_;
    std::thread realtime_receiver_;

    std::mutex mutex_;
    std::condition_variable cv_;

    // Keep reliable and best-effort messages separate.
    std::deque<ByteBuffer> reliable_queue_;
    std::deque<ByteBuffer> realtime_queue_;

    void receive_loop(
        ITransport& transport,
        bool reliable_lane
    );
};

} // namespace teleop
