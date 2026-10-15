
#pragma once

#include "transport.hpp"
#include "msquic.h"

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <vector>
#include <cstddef>

namespace teleop {

class QuicTransport final : public ITransport {
public:
    ~QuicTransport() override;

    QuicTransport(const QuicTransport&) = delete;
    QuicTransport& operator=(const QuicTransport&) = delete;

    bool send(
        const ByteBuffer& message,
        DeliveryMode mode
    ) override;

    bool receive(ByteBuffer& message) override;

    void shutdown() override;
    void print_diagnostics() const;

    // Client: robot connects to operator.
    static std::unique_ptr<QuicTransport> connect(
        const char* address,
        std::uint16_t port
    );

    // Server: operator accepts a connection.
    static std::unique_ptr<QuicTransport> accept(
        const char* bind_address,
        std::uint16_t port,
        const char* certificate_file,
        const char* private_key_file
    );

private:
    QuicTransport() = default;

    void initialize(
        bool is_server,
        const char* certificate_file = nullptr,
        const char* private_key_file = nullptr
    );

    bool wait_connected();

    static QUIC_STATUS QUIC_API connection_callback(
        HQUIC connection,
        void* context,
        QUIC_CONNECTION_EVENT* event
    );

    static QUIC_STATUS QUIC_API stream_callback(
        HQUIC stream,
        void* context,
        QUIC_STREAM_EVENT* event
    );

    static QUIC_STATUS QUIC_API listener_callback(
        HQUIC listener,
        void* context,
        QUIC_LISTENER_EVENT* event
    );

    void handle_stream_bytes(
        const std::uint8_t* data,
        std::size_t length
    );

    void enqueue_message(
        ByteBuffer message,
        bool reliable
    );

    static constexpr std::size_t MAX_QUEUE = 256;
    static constexpr std::size_t MAX_MESSAGE_SIZE = 1024 * 1024;

    const QUIC_API_TABLE* api_ = nullptr;

    HQUIC registration_ = nullptr;
    HQUIC configuration_ = nullptr;
    HQUIC listener_ = nullptr;
    HQUIC connection_ = nullptr;
    HQUIC reliable_stream_ = nullptr;

    std::atomic<bool> running_{true};
    std::atomic<bool> connected_{false};

    std::atomic<bool> stream_ready_{false};
    std::atomic<bool> datagram_enabled_{false};
    std::atomic<std::uint16_t> max_datagram_length_{0};
    std::atomic<std::size_t> pending_sends_{0};

    static constexpr std::size_t MAX_PENDING_SENDS = 256;

    std::atomic<std::size_t> pending_datagrams_{0};
    static constexpr std::size_t MAX_PENDING_DATAGRAMS = 32;
    static constexpr std::size_t MAX_PENDING_VIDEO_DATAGRAMS = 16;

    // Diagnostic counters for QUIC DATAGRAM transmission.
    std::atomic<std::uint64_t> datagram_sent_accepted_{0};
    std::atomic<std::uint64_t> datagram_rejected_not_ready_{0};
    std::atomic<std::uint64_t> datagram_rejected_size_{0};
    std::atomic<std::uint64_t> datagram_rejected_queue_{0};
    std::atomic<std::uint64_t> datagram_rejected_api_{0};

    std::atomic<std::uint64_t> datagram_final_acked_{0};
    std::atomic<std::uint64_t> datagram_final_lost_{0};
    std::atomic<std::uint64_t> datagram_final_canceled_{0};

    std::atomic<bool> cleanup_started_{false};

    bool is_server_ = false;

    std::mutex mutex_;
    std::condition_variable cv_;

    // Protects send operations against concurrent handle closure.
    std::mutex send_mutex_;

    std::deque<ByteBuffer> reliable_queue_;
    std::deque<ByteBuffer> realtime_queue_;

    // Accumulates incomplete length-prefixed stream messages.
    ByteBuffer stream_buffer_;
};

} // namespace teleop
