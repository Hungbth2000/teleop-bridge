#include <stdexcept>

#include "hybrid_transport.hpp"

#include <utility>

namespace teleop {

HybridTransport::HybridTransport(
    std::unique_ptr<ITransport> reliable,
    std::unique_ptr<ITransport> realtime
)
    : reliable_(std::move(reliable)),
      realtime_(std::move(realtime)) {

    if (!reliable_ || !realtime_) {
        throw std::invalid_argument(
            "HybridTransport requires both lanes"
        );
    }

    reliable_receiver_ = std::thread([this] {
        receive_loop(*reliable_, true);
    });

    realtime_receiver_ = std::thread([this] {
        receive_loop(*realtime_, false);
    });
}

HybridTransport::~HybridTransport() {
    shutdown();

    if (reliable_receiver_.joinable()) {
        reliable_receiver_.join();
    }

    if (realtime_receiver_.joinable()) {
        realtime_receiver_.join();
    }
}

bool HybridTransport::send(
    const ByteBuffer& message,
    DeliveryMode mode
) {
    if (!running_.load()) {
        return false;
    }

    if (mode == DeliveryMode::ReliableOrdered) {
        return reliable_->send(message, mode);
    }

    return realtime_->send(message, mode);
}

bool HybridTransport::receive(ByteBuffer& message) {
    std::unique_lock<std::mutex> lock(mutex_);

    // Wait for a message or shutdown.
    cv_.wait(lock, [&] {
        return !running_.load() ||
               !reliable_queue_.empty() ||
               !realtime_queue_.empty();
    });

    // Never deliver queued messages after shutdown.
    if (!running_.load()) {
        return false;
    }

    // Reliable traffic has priority.
    if (!reliable_queue_.empty()) {
        message = std::move(reliable_queue_.front());
        reliable_queue_.pop_front();
        return true;
    }

    // Otherwise deliver real-time traffic.
    if (!realtime_queue_.empty()) {
        message = std::move(realtime_queue_.front());
        realtime_queue_.pop_front();
        return true;
    }

    return false;
}

void HybridTransport::receive_loop(
    ITransport& transport,
    bool reliable_lane
) {
    ByteBuffer message;

    while (running_.load()) {
        if (!transport.receive(message)) {
            if (reliable_lane && running_.load()) {
                shutdown();
            }
            break;
        }

        bool reliable_overflow = false;

        {
            std::lock_guard<std::mutex> lock(mutex_);

            if (!running_.load()) {
                break;
            }

            if (reliable_lane) {
                if (reliable_queue_.size() >= MAX_RELIABLE_QUEUE) {
                    reliable_overflow = true;
                } else {
                    reliable_queue_.push_back(std::move(message));
                }
            } else {
                if (realtime_queue_.size() >= MAX_REALTIME_QUEUE) {
                    realtime_queue_.pop_front();
                }

                realtime_queue_.push_back(std::move(message));
            }
        }

        if (reliable_overflow) {
            shutdown();
            break;
        }

        cv_.notify_one();
        message.clear();
    }
}

void HybridTransport::shutdown() {
    if (!running_.exchange(false)) {
        return;
    }

    reliable_->shutdown();
    realtime_->shutdown();

    cv_.notify_all();
}

} // namespace teleop
