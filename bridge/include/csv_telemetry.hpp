
#pragma once

#include "scheduler.hpp"
#include "receive_stats.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <stdexcept>
#include <string>

namespace teleop {

class CsvTelemetry {
public:
    using Clock = std::chrono::steady_clock;

    CsvTelemetry(
        const std::string& role,
        const std::string& protocol = "tcp"
    )
        : role_(role),
          protocol_(protocol),
          started_at_(Clock::now()) {

        std::filesystem::create_directories("results");

        const std::string filename =
            "results/telemetry_" + role_ +
            "_" + protocol_ + ".csv";

        bool write_header = true;

        if (std::filesystem::exists(filename)) {
            write_header =
                std::filesystem::file_size(filename) == 0;
        }

        file_.open(filename, std::ios::app);

        if (!file_) {
            throw std::runtime_error(
                "Cannot open telemetry file: " + filename
            );
        }

        const auto start_ns =
            std::chrono::duration_cast<
                std::chrono::nanoseconds
            >(
                std::chrono::system_clock::now()
                    .time_since_epoch()
            ).count();

        session_id_ =
            role_ + "_" + std::to_string(start_ns);

        if (write_header) {
            file_
                << "timestamp_unix_ms,"
                << "session_id,"
                << "role,"
                << "protocol,"
                << "elapsed_s,"
                << "traffic_kind,"
                << "tx_bytes_total,"
                << "rx_bytes_total,"
                << "tx_mbps,"
                << "rx_mbps,"
                << "enqueued,"
                << "sent,"
                << "received,"
                << "dropped,"
                << "expired,"
                << "rejected,"
                << "send_failed,"
                << "configured_budget_mbps\n";

            file_.flush();
        }
    }

    void write_sample(
        const SchedulerStats& current_tx,
        const SchedulerStats& previous_tx,
        const ReceiveSnapshot& current_rx,
        const ReceiveSnapshot& previous_rx,
        double interval_seconds,
        double budget_mbps
    ) {
        if (interval_seconds <= 0.0) {
            return;
        }

        const auto now = Clock::now();

        const double elapsed_s =
            std::chrono::duration<double>(
                now - started_at_
            ).count();

        const auto unix_ms =
            std::chrono::duration_cast<
                std::chrono::milliseconds
            >(
                std::chrono::system_clock::now()
                    .time_since_epoch()
            ).count();

        for (std::size_t i = 0;
             i < TRAFFIC_KIND_COUNT;
             ++i) {

            const auto& current =
                current_tx.by_kind[i];

            const auto& previous =
                previous_tx.by_kind[i];

            const std::uint64_t tx_bytes =
                current.sent_bytes;

            const std::uint64_t rx_bytes =
                current_rx.bytes_by_kind[i];

            const std::uint64_t tx_delta =
                tx_bytes >= previous.sent_bytes
                    ? tx_bytes - previous.sent_bytes
                    : 0;

            const std::uint64_t rx_delta =
                rx_bytes >= previous_rx.bytes_by_kind[i]
                    ? rx_bytes -
                        previous_rx.bytes_by_kind[i]
                    : 0;

            const double tx_mbps =
                static_cast<double>(tx_delta) * 8.0 /
                (interval_seconds * 1'000'000.0);

            const double rx_mbps =
                static_cast<double>(rx_delta) * 8.0 /
                (interval_seconds * 1'000'000.0);

            file_
                << unix_ms << ','
                << session_id_ << ','
                << role_ << ','
                << protocol_ << ','
                << std::fixed << std::setprecision(3)
                << elapsed_s << ','
                << TRAFFIC_KIND_NAMES[i] << ','
                << tx_bytes << ','
                << rx_bytes << ','
                << std::setprecision(6)
                << tx_mbps << ','
                << rx_mbps << ','
                << current.enqueued << ','
                << current.sent << ','
                << current_rx.by_kind[i] << ','
                << current.dropped << ','
                << current.expired << ','
                << current.rejected << ','
                << current.send_failed << ','
                << std::setprecision(3)
                << budget_mbps
                << '\n';
        }

        // Make every reporting interval available
        // without waiting for the process to exit.
        file_.flush();

        if (!file_) {
            throw std::runtime_error(
                "Failed writing telemetry CSV"
            );
        }
    }

private:
    std::string role_;
    std::string protocol_;
    std::string session_id_;

    Clock::time_point started_at_;
    std::ofstream file_;
};

} // namespace teleop
