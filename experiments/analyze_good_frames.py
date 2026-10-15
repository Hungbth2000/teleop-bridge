#!/usr/bin/env python3
"""Summarize encoded-access-unit delivery from existing teleop video frame CSVs.

This is NOT proof that frames were successfully decoded and displayed.
Each camera's latest complete TX run is selected, and RX records are matched
only by (run_id, stream_id, frame_id).
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

STREAMS = {
    'head': ('video_frames_tx.csv', 'video_frames_rx.csv'),
    'left': ('video_frames_tx_wrist_left.csv', 'video_frames_rx_wrist_left.csv'),
    'right': ('video_frames_tx_wrist_right.csv', 'video_frames_rx_wrist_right.csv'),
}
REQUIRED = {'run_id', 'stream_id', 'frame_id', 'frame_number', 'capture_ns', 'event_ns', 'latency_ms'}


def load(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        absent = REQUIRED - set(reader.fieldnames or [])
        if absent:
            raise ValueError(f'{path}: missing columns {sorted(absent)}')
        return list(reader)


def run_summary(name, tx_rows, rx_rows, requested_run=None):
    runs = defaultdict(list)
    for row in tx_rows:
        if row['run_id'] and row['frame_id']:
            runs[(row['run_id'], row['stream_id'])].append(row)
    if not runs:
        raise ValueError(f'{name}: no TX runs')
    if requested_run:
        candidates = [(key, rows) for key, rows in runs.items() if key[0] == requested_run]
        if not candidates:
            raise ValueError(f'{name}: run {requested_run} not found in TX')
        key, chosen = max(candidates, key=lambda kv: max(int(r['capture_ns']) for r in kv[1]))
    else:
        key, chosen = max(runs.items(), key=lambda kv: max(int(r['capture_ns']) for r in kv[1]))
    run_id, stream_id = key
    tx_by_id = {}
    for r in chosen:
        tx_by_id.setdefault(r['frame_id'], r)
    rx_by_id = defaultdict(list)
    for r in rx_rows:
        if (r['run_id'], r['stream_id']) == key:
            rx_by_id[r['frame_id']].append(r)
    stats = Counter()
    details = []
    for frame_id, tx in sorted(tx_by_id.items(), key=lambda x: int(x[1]['frame_number'])):
        seen = rx_by_id.get(frame_id, [])
        if not seen:
            state, latency = 'missing', None
        else:
            valid = []
            for r in seen:
                try:
                    latency_ms = (int(r['event_ns']) - int(tx['capture_ns'])) / 1e6
                except (ValueError, TypeError):
                    continue
                # Reject impossible negative latencies (clock mismatch, invalid data)
                if latency_ms >= 0:
                    valid.append(latency_ms)
            if not valid:
                state, latency = 'invalid_timestamp', None
            else:
                latency = min(valid)
                state = 'good_transport' if latency <= 200.0 else 'late'
        stats[state] += 1
        stats['duplicate_rx_rows'] += max(0, len(seen) - 1)
        details.append({'camera': name, 'run_id': run_id, 'stream_id': stream_id,
                        'frame_id': frame_id, 'frame_number': tx['frame_number'],
                        'capture_ns': tx['capture_ns'], 'latency_ms': round(latency, 6) if latency is not None else '',
                        'classification': state, 'rx_records': len(seen)})
    total = len(tx_by_id)
    good = stats['good_transport']
    summary = {'camera': name, 'run_id': run_id, 'stream_id': stream_id,
               'captured_frames': total, 'good_transport_frames': good,
               'good_transport_pct': round(100 * good / total, 3) if total else None,
               'late_frames': stats['late'], 'missing_frames': stats['missing'],
               'invalid_timestamp_frames': stats['invalid_timestamp'],
               'duplicate_rx_rows': stats['duplicate_rx_rows'],
               'measurement_scope': 'complete reassembled H264 access units received <=200ms; not decoded/displayed',
               'two_mbps_result': 'NOT MEASURED: requires aligned budget phase data'}
    return summary, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results'))
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--run-head', help='Optional explicit head run ID')
    parser.add_argument('--run-left', help='Optional explicit left wrist run ID')
    parser.add_argument('--run-right', help='Optional explicit right wrist run ID')
    args = parser.parse_args()
    out = args.output or args.results / 'task2' / 'good_frames_tcp_udp' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=True)
    results, frames = [], []
    for name, (tx_file, rx_file) in STREAMS.items():
        tx, rx = load(args.results / tx_file), load(args.results / rx_file)
        summary, details = run_summary(name, tx, rx, getattr(args, f'run_{name}'))
        results.append(summary)
        frames.extend(details)
        print(f"{name:5} run={summary['run_id']} captured={summary['captured_frames']} "
              f"transport_good={summary['good_transport_frames']} "
              f"({summary['good_transport_pct']}%) late={summary['late_frames']} "
              f"missing={summary['missing_frames']}")
    with (out / 'frames_classified.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(frames[0]))
        writer.writeheader()
        writer.writerows(frames)
    with (out / 'summary.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    (out / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    report = ['# Task 2 — Preliminary camera transport-frame results', '',
              'These are **reassembled encoded-frame** outcomes, not decoded/displayed frame results.',
              'Integrity depends on FrameReassembler checks and the existing receiver logging.',
              'The 2 Mbit/s head-frame acceptance requirement is **not assessed** without bridge-phase alignment.', '',
              '| Camera | Run ID | Captured | <=200 ms (encoded) | Rate | Late | Missing |',
              '|---|---|---:|---:|---:|---:|---:|']
    for r in results:
        report.append(f"| {r['camera']} | {r['run_id']} | {r['captured_frames']} | {r['good_transport_frames']} | {r['good_transport_pct']}% | {r['late_frames']} | {r['missing_frames']} |")
    report += ['', 'Missing TX/RX frames are included in the denominator. Only frame IDs with the selected run ID and stream ID are matched.',
               'Each camera selects its latest TX run independently. Confirm that the selected three runs came from the same concurrent experiment.',
               'Do not label the result PASS for Task 2 until decoded-display verification and degraded-phase classification are implemented.', '']
    (out / 'report.md').write_text('\n'.join(report))
    print(f'Saved report: {out}')


if __name__ == '__main__':
    main()
