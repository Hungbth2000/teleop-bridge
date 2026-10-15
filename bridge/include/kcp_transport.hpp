#pragma once

#include "transport.hpp"

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

struct IKCPCB;

namespace teleop {

class KcpTransport final : public ITransport {
public:
    static std::unique_ptr<KcpTransport> accept(
        const std::string& local_address,
        const std::string& peer_address,
        std::uint16_t port = 9003
    );

    static std::unique_ptr<KcpTransport> connect(
        const std::string& local_address,
        const std::string& peer_address,
        std::uint16_t port = 9003
    );

    ~KcpTransport() override;

    KcpTransport(const KcpTransport&) = delete;
    KcpTransport& operator=(const KcpTransport&) = delete;

    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override;

    bool receive(ByteBuffer& message) override;

    void shutdown() override;

private:
    KcpTransport(
        int socket_fd,
        std::uint32_t conversation_id,
        bool server_side
    );

    static int output_callback(
        const char* data,
        int length,
        IKCPCB* kcp,
        void* user
    );

    void io_loop();

    int socket_fd_ = -1;
    IKCPCB* kcp_ = nullptr;
    bool server_side_ = false;

    std::atomic<bool> running_{true};

    std::thread io_thread_;

    std::mutex kcp_mutex_;

    std::mutex receive_mutex_;
    std::condition_variable receive_cv_;
    std::deque<ByteBuffer> receive_queue_;
};

} // namespace teleop
