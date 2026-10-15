
#include "quic_transport.hpp"
#include "message.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>

#include <algorithm>
#include <cstdint>

#include <arpa/inet.h>

namespace teleop {

namespace {

constexpr char ALPN[] = "teleop-quic";

void check(QUIC_STATUS status, const char* operation) {
    if (QUIC_FAILED(status)) {
        throw std::runtime_error(
            std::string(operation) +
            " failed: " + std::to_string(status)
        );
    }
}

QUIC_BUFFER alpn_buffer() {
    return {
        static_cast<uint32_t>(sizeof(ALPN) - 1),
        reinterpret_cast<uint8_t*>(
            const_cast<char*>(ALPN)
        )
    };
}

struct StreamSendContext {
    QUIC_BUFFER buffer{};
    ByteBuffer bytes;

    explicit StreamSendContext(const ByteBuffer& message) {
        bytes.resize(4 + message.size());

        const auto length =
            static_cast<std::uint32_t>(message.size());

        bytes[0] = static_cast<std::uint8_t>(length >> 24);
        bytes[1] = static_cast<std::uint8_t>(length >> 16);
        bytes[2] = static_cast<std::uint8_t>(length >> 8);
        bytes[3] = static_cast<std::uint8_t>(length);

        std::copy(
            message.begin(),
            message.end(),
            bytes.begin() + 4
        );

        buffer.Length =
            static_cast<std::uint32_t>(bytes.size());
        buffer.Buffer = bytes.data();
    }
};

struct DatagramSendContext {
    QUIC_BUFFER buffer{};
    ByteBuffer bytes;

    explicit DatagramSendContext(const ByteBuffer& message)
        : bytes(message) {
        buffer.Length =
            static_cast<std::uint32_t>(bytes.size());
        buffer.Buffer = bytes.data();
    }
};

} // namespace

void QuicTransport::initialize(
    bool is_server,
    const char* certificate_file,
    const char* private_key_file
) {

    is_server_ = is_server;

    check(MsQuicOpen2(&api_), "MsQuicOpen2");

    const QUIC_REGISTRATION_CONFIG registration_config = {
        "teleop-bridge",
        QUIC_EXECUTION_PROFILE_LOW_LATENCY
    };

    check(
        api_->RegistrationOpen(
            &registration_config,
            &registration_
        ),
        "RegistrationOpen"
    );

    QUIC_SETTINGS settings{};

    settings.IsSet.IdleTimeoutMs = TRUE;
    settings.IdleTimeoutMs = 30000;

    settings.IsSet.PeerBidiStreamCount = TRUE;
    settings.PeerBidiStreamCount = 1;

    settings.IsSet.DatagramReceiveEnabled = TRUE;
    settings.DatagramReceiveEnabled = TRUE;

    QUIC_BUFFER alpn = alpn_buffer();

    check(
        api_->ConfigurationOpen(
            registration_,
            &alpn,
            1,
            &settings,
            sizeof(settings),
            nullptr,
            &configuration_
        ),
        "ConfigurationOpen"
    );

    QUIC_CREDENTIAL_CONFIG credentials{};

    QUIC_CERTIFICATE_FILE certificate{};

    if (is_server) {
        if (!certificate_file || !private_key_file) {
            throw std::runtime_error(
                "QUIC server requires certificate and key"
            );
        }

        certificate.PrivateKeyFile = private_key_file;
        certificate.CertificateFile = certificate_file;

        credentials.Type =
            QUIC_CREDENTIAL_TYPE_CERTIFICATE_FILE;

        credentials.CertificateFile = &certificate;
    } else {
        credentials.Type = QUIC_CREDENTIAL_TYPE_NONE;

        // LOCAL DEVELOPMENT ONLY.
        // Replace with certificate validation before
        // deployment on untrusted networks.
        credentials.Flags = static_cast<
            QUIC_CREDENTIAL_FLAGS
        >(
            QUIC_CREDENTIAL_FLAG_CLIENT |
            QUIC_CREDENTIAL_FLAG_NO_CERTIFICATE_VALIDATION
        );
    }

    check(
        api_->ConfigurationLoadCredential(
            configuration_,
            &credentials
        ),
        "ConfigurationLoadCredential"
    );
}

bool QuicTransport::wait_connected() {
    std::unique_lock<std::mutex> lock(mutex_);

    bool ready = cv_.wait_for(
        lock,
        std::chrono::seconds(10),
        [this] {
            return connected_.load() ||
                   !running_.load();
        }
    );

    return ready && connected_.load();
}

QUIC_STATUS QUIC_API QuicTransport::listener_callback(
    HQUIC,
    void* context,
    QUIC_LISTENER_EVENT* event
) {
    auto* self = static_cast<QuicTransport*>(context);

    if (event->Type != QUIC_LISTENER_EVENT_NEW_CONNECTION) {
        return QUIC_STATUS_SUCCESS;
    }

    HQUIC connection = event->NEW_CONNECTION.Connection;

    {
        std::lock_guard<std::mutex> lock(self->mutex_);

        if (!self->running_.load() ||
            self->connection_ != nullptr) {
            return QUIC_STATUS_NOT_SUPPORTED;
        }

        self->connection_ = connection;
    }

    self->api_->SetCallbackHandler(
        connection,
        reinterpret_cast<void*>(
            QuicTransport::connection_callback
        ),
        self
    );

    QUIC_STATUS status =
        self->api_->ConnectionSetConfiguration(
            connection,
            self->configuration_
        );

    if (QUIC_FAILED(status)) {
        std::lock_guard<std::mutex> lock(self->mutex_);
        self->connection_ = nullptr;
        self->running_.store(false);
        self->cv_.notify_all();
    }

    return status;
}

QUIC_STATUS QUIC_API QuicTransport::connection_callback(
    HQUIC,
    void* context,
    QUIC_CONNECTION_EVENT* event
) {
    auto* self = static_cast<QuicTransport*>(context);

    switch (event->Type) {
    case QUIC_CONNECTION_EVENT_CONNECTED: {
        std::cout << "[quic] Connected\n";

        if (!self->is_server_) {
            QUIC_STATUS status = self->api_->StreamOpen(
                self->connection_,
                QUIC_STREAM_OPEN_FLAG_NONE,
                QuicTransport::stream_callback,
                self,
                &self->reliable_stream_
            );

            if (QUIC_FAILED(status)) {
                std::cerr << "[quic] StreamOpen failed\n";
                self->api_->ConnectionShutdown(
                    self->connection_,
                    QUIC_CONNECTION_SHUTDOWN_FLAG_NONE,
                    1
                );
                break;
            }

            status = self->api_->StreamStart(
                self->reliable_stream_,
                QUIC_STREAM_START_FLAG_IMMEDIATE
            );

            if (QUIC_FAILED(status)) {
                std::cerr << "[quic] StreamStart failed\n";
                self->api_->ConnectionShutdown(
                    self->connection_,
                    QUIC_CONNECTION_SHUTDOWN_FLAG_NONE,
                    1
                );
                break;
            }
        }

        self->connected_.store(true);
        self->cv_.notify_all();
        break;
    }

    case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_TRANSPORT:
    case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_PEER:
    case QUIC_CONNECTION_EVENT_SHUTDOWN_COMPLETE:
        self->running_.store(false);
        self->connected_.store(false);
        self->cv_.notify_all();
        break;

    case QUIC_CONNECTION_EVENT_PEER_STREAM_STARTED: {
        HQUIC stream = event->PEER_STREAM_STARTED.Stream;

        {
            std::lock_guard<std::mutex> lock(self->mutex_);

            if (self->reliable_stream_ != nullptr) {
                return QUIC_STATUS_NOT_SUPPORTED;
            }

            self->reliable_stream_ = stream;
        }

        self->api_->SetCallbackHandler(
            stream,
            reinterpret_cast<void*>(
                QuicTransport::stream_callback
            ),
            self
        );

        self->stream_ready_.store(true);
        self->cv_.notify_all();

        std::cout << "[quic] Peer reliable stream opened\n";
        break;
    }

    case QUIC_CONNECTION_EVENT_DATAGRAM_STATE_CHANGED: {
        const bool enabled =
            event->DATAGRAM_STATE_CHANGED.SendEnabled;

        const std::uint16_t max_length =
            event->DATAGRAM_STATE_CHANGED.MaxSendLength;

        self->datagram_enabled_.store(enabled);
        self->max_datagram_length_.store(
            enabled ? max_length : 0
        );

        std::cout
            << "[quic] DATAGRAM enabled: "
            << enabled
            << ", max payload: "
            << max_length
            << " bytes\n";

        self->cv_.notify_all();
        break;
    }

    case QUIC_CONNECTION_EVENT_DATAGRAM_RECEIVED: {
        const QUIC_BUFFER* buffer =
            event->DATAGRAM_RECEIVED.Buffer;

        if (!buffer || !self->running_.load()) {
            break;
        }

        try {
            ByteBuffer message(
                buffer->Buffer,
                buffer->Buffer + buffer->Length
            );

            self->enqueue_message(
                std::move(message),
                false
            );
        } catch (const std::exception& e) {
            std::cerr
                << "[quic] Datagram receive error: "
                << e.what() << '\n';
        }

        break;
    }

    case QUIC_CONNECTION_EVENT_DATAGRAM_SEND_STATE_CHANGED: {
        const auto state =
            event->DATAGRAM_SEND_STATE_CHANGED.State;

        if (QUIC_DATAGRAM_SEND_STATE_IS_FINAL(state)) {
            switch (state) {
            case QUIC_DATAGRAM_SEND_ACKNOWLEDGED:
            case QUIC_DATAGRAM_SEND_ACKNOWLEDGED_SPURIOUS:
                self->datagram_final_acked_.fetch_add(1);
                break;

            case QUIC_DATAGRAM_SEND_LOST_DISCARDED:
                self->datagram_final_lost_.fetch_add(1);
                break;

            case QUIC_DATAGRAM_SEND_CANCELED:
                self->datagram_final_canceled_.fetch_add(1);
                break;

            default:
                break;
            }

            auto* context =
                static_cast<DatagramSendContext*>(
                    event->DATAGRAM_SEND_STATE_CHANGED.ClientContext
                );

            if (context) {
                delete context;
                self->pending_datagrams_.fetch_sub(1);
            }
        }
        break;
    }

    default:
        break;
    }

    return QUIC_STATUS_SUCCESS;
}

QUIC_STATUS QUIC_API QuicTransport::stream_callback(
    HQUIC,
    void* context,
    QUIC_STREAM_EVENT* event
) {
    auto* self = static_cast<QuicTransport*>(context);

    switch (event->Type) {
    case QUIC_STREAM_EVENT_START_COMPLETE:
        if (QUIC_SUCCEEDED(event->START_COMPLETE.Status)) {
            self->stream_ready_.store(true);
            self->cv_.notify_all();

            std::cout << "[quic] Reliable stream started\n";
        } else {
            std::cerr << "[quic] Reliable stream start failed\n";

            self->running_.store(false);
            self->cv_.notify_all();
        }
        break;

    case QUIC_STREAM_EVENT_SEND_COMPLETE: {
        auto* send_context =
            static_cast<StreamSendContext*>(
                event->SEND_COMPLETE.ClientContext
            );

        delete send_context;
        self->pending_sends_.fetch_sub(1);
        break;
    }

    case QUIC_STREAM_EVENT_RECEIVE:
        try {
            for (std::uint32_t i = 0;
                i < event->RECEIVE.BufferCount;
                ++i) {

                const QUIC_BUFFER& buffer =
                    event->RECEIVE.Buffers[i];

                self->handle_stream_bytes(
                    buffer.Buffer,
                    buffer.Length
                );
            }
        } catch (const std::exception& e) {
            std::cerr
                << "[quic] Receive error: "
                << e.what() << '\n';

            self->running_.store(false);
            self->cv_.notify_all();
        }
        break;

    case QUIC_STREAM_EVENT_PEER_SEND_SHUTDOWN:
        std::cout << "[quic] Peer closed stream sending\n";
        break;

    case QUIC_STREAM_EVENT_PEER_SEND_ABORTED:
        self->running_.store(false);
        self->cv_.notify_all();
        break;

    default:
        break;
    }

    return QUIC_STATUS_SUCCESS;
}

void QuicTransport::handle_stream_bytes(
    const std::uint8_t* data,
    std::size_t length
) {
    std::lock_guard<std::mutex> lock(mutex_);

    stream_buffer_.insert(
        stream_buffer_.end(),
        data,
        data + length
    );

    std::size_t consumed = 0;

    while (stream_buffer_.size() - consumed >= 4) {
        const auto* p = stream_buffer_.data() + consumed;

        const std::uint32_t message_length =
            (static_cast<std::uint32_t>(p[0]) << 24) |
            (static_cast<std::uint32_t>(p[1]) << 16) |
            (static_cast<std::uint32_t>(p[2]) << 8) |
            static_cast<std::uint32_t>(p[3]);

        if (message_length == 0 ||
            message_length > MAX_MESSAGE_SIZE) {
            running_.store(false);
            cv_.notify_all();
            return;
        }

        const std::size_t frame_length =
            4 + static_cast<std::size_t>(message_length);

        if (stream_buffer_.size() - consumed <
            frame_length) {
            break;
        }

        if (reliable_queue_.size() >= MAX_QUEUE) {
            // Never silently discard reliable control messages.
            running_.store(false);
            cv_.notify_all();
            return;
        }

        ByteBuffer message(
            stream_buffer_.begin() + consumed + 4,
            stream_buffer_.begin() + consumed + frame_length
        );

        reliable_queue_.push_back(std::move(message));

        consumed += frame_length;
    }

    if (consumed > 0) {
        stream_buffer_.erase(
            stream_buffer_.begin(),
            stream_buffer_.begin() + consumed
        );
    }

    cv_.notify_all();
}

void QuicTransport::enqueue_message(
    ByteBuffer message,
    bool reliable
) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (!running_.load()) {
        return;
    }

    if (reliable) {
        if (reliable_queue_.size() >= MAX_QUEUE) {
            running_.store(false);
            cv_.notify_all();
            return;
        }

        reliable_queue_.push_back(
            std::move(message)
        );
    } else {
        if (realtime_queue_.size() >= MAX_QUEUE) {
            // Prefer recent motion/video/state updates.
            realtime_queue_.pop_front();
        }

        realtime_queue_.push_back(
            std::move(message)
        );
    }

    cv_.notify_all();
}

bool QuicTransport::send(
    const ByteBuffer& message,
    DeliveryMode mode
) {

    std::lock_guard<std::mutex> send_lock(send_mutex_);

    if (mode == DeliveryMode::Unreliable) {
        if (message.empty() ||
            !running_.load() ||
            !connected_.load() ||
            !datagram_enabled_.load()) {
            datagram_rejected_not_ready_.fetch_add(1);
            return false;
        }

        const auto max_length =
            max_datagram_length_.load();

        if (max_length == 0 ||
            message.size() > max_length) {
            datagram_rejected_size_.fetch_add(1);
            return false;
        }
          
        // The serialized TEL1 message stores MessageType at byte 4.
        // Validate the header before inspecting it.
        if (message.size() < HEADER_SIZE ||
            message[0] != 'T' ||
            message[1] != 'E' ||
            message[2] != 'L' ||
            message[3] != '1') {
            datagram_rejected_not_ready_.fetch_add(1);
            return false;
        }

        const auto type =
            static_cast<MessageType>(message[4]);

        const bool is_video =
            type == MessageType::Video;

        // Reserve outstanding-send capacity for motion and robot state.
        // Reliable control uses the separate reliable stream.
        const std::size_t pending_limit =
            is_video
                ? MAX_PENDING_VIDEO_DATAGRAMS
                : MAX_PENDING_DATAGRAMS;

        const auto previous =
            pending_datagrams_.fetch_add(1);

        if (previous >= pending_limit) {
            pending_datagrams_.fetch_sub(1);
            datagram_rejected_queue_.fetch_add(1);
            return false;
        }

        auto* context = new DatagramSendContext(message);

        const QUIC_STATUS status = api_->DatagramSend(
            connection_,
            &context->buffer,
            1,
            QUIC_SEND_FLAG_NONE,
            context
        );

        if (QUIC_FAILED(status)) {
            delete context;
            pending_datagrams_.fetch_sub(1);
            datagram_rejected_api_.fetch_add(1);
            return false;
        }

        datagram_sent_accepted_.fetch_add(1);
        return true;
    }

    if (message.empty() ||
        message.size() > MAX_MESSAGE_SIZE) {
        return false;
    }

    {
        std::unique_lock<std::mutex> lock(mutex_);

        const bool ready = cv_.wait_for(
            lock,
            std::chrono::seconds(2),
            [this] {
                return stream_ready_.load() ||
                       !running_.load();
            }
        );

        if (!ready ||
            !running_.load() ||
            !connected_.load() ||
            !stream_ready_.load()) {
            return false;
        }
    }

    // Bound the number of outstanding asynchronous sends.
    const auto previous =
        pending_sends_.fetch_add(1);

    if (previous >= MAX_PENDING_SENDS) {
        pending_sends_.fetch_sub(1);
        return false;
    }

    auto* context = new StreamSendContext(message);

    const QUIC_STATUS status = api_->StreamSend(
        reliable_stream_,
        &context->buffer,
        1,
        QUIC_SEND_FLAG_NONE,
        context
    );

    if (QUIC_FAILED(status)) {
        delete context;
        pending_sends_.fetch_sub(1);
        return false;
    }

    return true;
}

bool QuicTransport::receive(ByteBuffer& message) {
    std::unique_lock<std::mutex> lock(mutex_);

    cv_.wait(lock, [this] {
        return !reliable_queue_.empty() ||
               !realtime_queue_.empty() ||
               !running_.load();
    });

    if (!running_.load()) {
        return false;
    }

    if (!reliable_queue_.empty()) {
        message = std::move(
            reliable_queue_.front()
        );

        reliable_queue_.pop_front();
        return true;
    }

    if (!realtime_queue_.empty()) {
        message = std::move(
            realtime_queue_.front()
        );

        realtime_queue_.pop_front();
        return true;
    }

    return false;
}

void QuicTransport::print_diagnostics() const {
    std::cerr
        << "[quic] DATAGRAM statistics:"
        << " accepted=" << datagram_sent_accepted_.load()
        << " not_ready=" << datagram_rejected_not_ready_.load()
        << " oversized=" << datagram_rejected_size_.load()
        << " queue_full=" << datagram_rejected_queue_.load()
        << " api_failed=" << datagram_rejected_api_.load()
        << " pending=" << pending_datagrams_.load()
        << " acked=" << datagram_final_acked_.load()
        << " lost=" << datagram_final_lost_.load()
        << " canceled=" << datagram_final_canceled_.load()
        << '\n';
}

void QuicTransport::shutdown() {
    if (cleanup_started_.exchange(true)) {
        return;
    }

    std::cerr << "[quic] Shutdown started\n";

    print_diagnostics();

    running_.store(false);
    connected_.store(false);
    cv_.notify_all();

    std::lock_guard<std::mutex> send_lock(send_mutex_);

    if (!api_) {
        return;
    }

    if (connection_) {
        std::cerr << "[quic] ConnectionShutdown...\n";

        api_->ConnectionShutdown(
            connection_,
            QUIC_CONNECTION_SHUTDOWN_FLAG_NONE,
            0
        );
    }

    if (reliable_stream_) {
        std::cerr << "[quic] StreamClose...\n";

        api_->StreamClose(reliable_stream_);
        reliable_stream_ = nullptr;

        std::cerr << "[quic] StreamClose done\n";
    }

    if (connection_) {
        std::cerr << "[quic] ConnectionClose...\n";

        api_->ConnectionClose(connection_);
        connection_ = nullptr;

        std::cerr << "[quic] ConnectionClose done\n";
    }

    if (listener_) {
        std::cerr << "[quic] ListenerClose...\n";

        api_->ListenerClose(listener_);
        listener_ = nullptr;

        std::cerr << "[quic] ListenerClose done\n";
    }

    std::cerr << "[quic] Shutdown completed\n";
}

QuicTransport::~QuicTransport() {
    std::cerr << "[quic] Destructor started\n";

    shutdown();

    if (configuration_) {
        std::cerr << "[quic] ConfigurationClose...\n";
        api_->ConfigurationClose(configuration_);
        configuration_ = nullptr;
    }

    if (registration_) {
        std::cerr << "[quic] RegistrationClose...\n";
        api_->RegistrationClose(registration_);
        registration_ = nullptr;
    }

    if (api_) {
        std::cerr << "[quic] MsQuicClose...\n";
        MsQuicClose(api_);
        api_ = nullptr;
    }

    std::cerr << "[quic] Destructor completed\n";
}

std::unique_ptr<QuicTransport> QuicTransport::connect(
    const char* address,
    std::uint16_t port
) {
    auto transport = std::unique_ptr<QuicTransport>(
        new QuicTransport()
    );

    transport->initialize(false);

    check(
        transport->api_->ConnectionOpen(
            transport->registration_,
            connection_callback,
            transport.get(),
            &transport->connection_
        ),
        "ConnectionOpen"
    );

    check(
        transport->api_->ConnectionStart(
            transport->connection_,
            transport->configuration_,
            QUIC_ADDRESS_FAMILY_UNSPEC,
            address,
            port
        ),
        "ConnectionStart"
    );

    if (!transport->wait_connected()) {
        return nullptr;
    }

    return transport;
}

std::unique_ptr<QuicTransport> QuicTransport::accept(
    const char* bind_address,
    std::uint16_t port,
    const char* certificate_file,
    const char* private_key_file
) {
    auto transport = std::unique_ptr<QuicTransport>(
        new QuicTransport()
    );

    transport->initialize(
        true,
        certificate_file,
        private_key_file
    );

    check(
        transport->api_->ListenerOpen(
            transport->registration_,
            listener_callback,
            transport.get(),
            &transport->listener_
        ),
        "ListenerOpen"
    );

    QUIC_ADDR address{};

    QuicAddrSetFamily(
        &address,
        QUIC_ADDRESS_FAMILY_INET
    );

    QuicAddrSetPort(&address, port);

    if (inet_pton(
            AF_INET,
            bind_address,
            &address.Ipv4.sin_addr
        ) != 1) {
        throw std::runtime_error(
            "Invalid QUIC bind address"
        );
    }

    QUIC_BUFFER alpn = alpn_buffer();

    check(
        transport->api_->ListenerStart(
            transport->listener_,
            &alpn,
            1,
            &address
        ),
        "ListenerStart"
    );

    std::cout
        << "[quic] Listening on "
        << bind_address << ":" << port << '\n';

    {
        std::unique_lock<std::mutex> lock(transport->mutex_);

        transport->cv_.wait(lock, [&] {
            return transport->connected_.load() ||
                !transport->running_.load();
        });
    }

    if (!transport->connected_.load()) {
        return nullptr;
    }

    return transport;
}

} // namespace teleop
