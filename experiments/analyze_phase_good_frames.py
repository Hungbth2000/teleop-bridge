#!/usr/bin/env python3
"""Analyze per-camera capture-to-decode good frames by bridge budget phase.

Reads archived Task 2 evidence; does not run nodes or modify raw CSVs.
"""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

CAMERAS = {
    'head': ('video_frames_tx.csv', 'decoded_frames_head.csv', 1),
    'left': ('video_frames_tx_wrist_left.csv', 'decoded_frames_left.csv', 2),
    'right': ('video_frames_tx_wrist_right.csv', 'decoded_frames_right.csv', 3),
}

def read_csv(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))

def percentile(numbers, q):
    if not numbers:
        return None
    numbers = sorted(numbers)
    pos = (len(numbers) - 1) * q / 100
    low = math.floor(pos)
    high = math.ceil(pos)
    return round(numbers[low] + (numbers[high] - numbers[low]) * (pos - low), 3)

def analyse(evidence, report):
    report.mkdir(parents=True, exist_ok=True)
    records = []
    summaries = []
    origins = set()
    for camera, (sender_file, decoded_file, stream_id) in CAMERAS.items():
        sends = read_csv(evidence / sender_file)
        decodes = read_csv(evidence / decoded_file)
        if not sends:
            raise ValueError(f'{camera}: no captured frames')
        # Sender CSV is append-only; analyze its last run only.
        run_id = sends[-1]['run_id']
        sends = [r for r in sends if r['run_id'] == run_id]
        captures = {}
        for row in sends:
            frame_id = row['frame_id']
            if frame_id in captures:
                raise ValueError(f'{camera}: duplicate captured frame_id {frame_id}')
            if int(row['stream_id']) != stream_id:
                raise ValueError(f'{camera}: unexpected stream_id in TX')
            if not row.get('cycle_start_ns') or not row.get('capture_ns'):
                raise ValueError(f'{camera}: cycle_start_ns/capture_ns missing in TX')
            origin = int(row['cycle_start_ns'])
            origins.add(origin)
            captures[frame_id] = row
        if len({int(r['cycle_start_ns']) for r in sends}) != 1:
            raise ValueError(f'{camera}: cycle_start_ns varies within a run')
        decoded_by_id = {}
        duplicate_decodes = 0
        for row in decodes:
            frame_id = row['frame_id']
            if frame_id not in captures:
                continue
            if int(row['stream_id']) != stream_id:
                raise ValueError(f'{camera}: wrong stream_id in decoder CSV')
            if frame_id in decoded_by_id:
                duplicate_decodes += 1
            else:
                decoded_by_id[frame_id] = row
        if duplicate_decodes:
            raise ValueError(f'{camera}: {duplicate_decodes} duplicate decoded-frame IDs')
        for frame_id, row in captures.items():
            capture_ns = int(row['capture_ns'])
            origin = int(row['cycle_start_ns'])
            elapsed = (capture_ns - origin) / 1e9
            if elapsed < 0:
                raise ValueError(f'{camera}: capture predates bandwidth limiter start')
            phase_seconds = elapsed % 60
            budget = 2 if 45 <= phase_seconds < 60 else 8
            decoded = decoded_by_id.get(frame_id)
            decode_ms = None
            status = 'missing_or_not_decoded'
            if decoded:
                # Recompute from timestamps rather than trusting the saved latency field.
                decoded_ns = int(decoded['decoded_ns'])
                if int(decoded['capture_ns']) != capture_ns:
                    raise ValueError(f'{camera}: capture timestamp mismatch for {frame_id}')
                decode_ms = (decoded_ns - capture_ns) / 1e6
                if decode_ms < 0:
                    raise ValueError(f'{camera}: negative decode latency for {frame_id}')
                status = 'good' if decode_ms <= 200 else 'late'
            records.append({
                'camera': camera, 'run_id': run_id, 'frame_id': frame_id,
                'frame_number': row['frame_number'], 'capture_ns': capture_ns,
                'cycle_start_ns': origin, 'cycle_phase_s': f'{phase_seconds:.6f}',
                'budget_mbps': budget, 'advertised_budget_bps': row.get('budget_bps', ''),
                'decoded_ns': decoded['decoded_ns'] if decoded else '',
                'capture_to_decode_ms': f'{decode_ms:.6f}' if decode_ms is not None else '',
                'status': status,
            })
        for phase in (8, 2, 'all'):
            subset = [r for r in records if r['camera'] == camera and
                      (phase == 'all' or r['budget_mbps'] == phase)]
            n = len(subset)
            good = sum(r['status'] == 'good' for r in subset)
            late = sum(r['status'] == 'late' for r in subset)
            missing = n - good - late
            times = [float(r['capture_to_decode_ms']) for r in subset
                     if r['capture_to_decode_ms'] != '']
            summaries.append({
                'camera': camera, 'run_id': run_id, 'budget_mbps': phase,
                'captured': n, 'decoded_on_time': good, 'late': late,
                'missing_or_not_decoded': missing,
                'good_percent': round(100 * good / n, 3) if n else None,
                'p50_decode_ms': percentile(times, 50),
                'p95_decode_ms': percentile(times, 95),
                'p99_decode_ms': percentile(times, 99),
                'max_decode_ms': round(max(times), 3) if times else None,
                'head_2mbps_acceptance': (
                    'PASS' if n and good / n >= 0.8 else 'FAIL' if n else 'NOT MEASURED'
                ) if camera == 'head' and phase == 2 else '',
            })
    if len(origins) != 1:
        raise ValueError(f'Camera TX logs have different bridge cycle origins: {origins}')
    def write_csv(name, rows):
        with (report / name).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write_csv('frame_classification.csv', records)
    write_csv('summary.csv', summaries)
    (report / 'summary.json').write_text(json.dumps({
        'measurement': 'capture_to_decoded_frame_ready',
        'notes': [
            'A headless viewer counts decoder output, not physical screen display.',
            'CRC32 validates encoded access-unit payload; pixel-reference equality is not tested.',
            'Bandwidth grouping uses exact limiter cycle origin and camera capture monotonic times.',
            'Reported bandwidth is configured budget; bridge telemetry does not include all wire overhead.',
        ], 'cycle_start_ns': next(iter(origins)), 'results': summaries,
    }, indent=2) + '\n', encoding='utf-8')
    lines = ['# Task 2.1 — Camera good-frame results', '',
             'Successful frame = decoder output within 200 ms of capture; denominator = all captured frames.', '',
             '| Camera | Budget | Captured | Good | Late | Missing/not decoded | Good % | p95 (ms) | Max (ms) |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        def fmt(val): return '—' if val is None else str(val)
        lines.append('| ' + ' | '.join(map(str, [r['camera'], r['budget_mbps'],
            r['captured'], r['decoded_on_time'], r['late'], r['missing_or_not_decoded'],
            fmt(r['good_percent']), fmt(r['p95_decode_ms']), fmt(r['max_decode_ms'])])) + ' |')
    head2 = next(r for r in summaries if r['camera'] == 'head' and r['budget_mbps'] == 2)
    lines += ['', f"**Head at 2 Mbit/s:** {head2['head_2mbps_acceptance']} "
              f"({head2['decoded_on_time']}/{head2['captured']} good).", '',
              'Limitations: decoder output readiness is not physical display; CRC32 + decode '
              'do not prove pixel-perfect equality with a deterministic reference. '
              'Budget compliance including wire overhead requires separate network-byte measurement.', '']
    (report / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    for row in summaries:
        print(f"{row['camera']:>5} {str(row['budget_mbps']):>3}Mbps "
              f"captured={row['captured']:4} good={row['decoded_on_time']:4} "
              f"good%={row['good_percent']} p95={row['p95_decode_ms']}ms "
              f"{row['head_2mbps_acceptance']}")
    print(f'Written: {report}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path,
        default=Path('results/task2/good_frames_tcp_udp/good_frame_evidence'))
    parser.add_argument('--report', type=Path,
        default=Path('results/task2/good_frames_tcp_udp/good_frame_report'))
    args = parser.parse_args()
    analyse(args.evidence, args.report)
