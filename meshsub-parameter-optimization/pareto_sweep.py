#!/usr/bin/env python3
"""
pareto_sweep.py

Parameter sweep for MeshSub to generate data for Pareto analysis.

Objectives:
1. Maximize delivery rate
2. Minimize p99 latency
3. Minimize bytes per delivery

Sweeps:
- D (eager mesh degree)
- D_lazy (lazy mesh degree)
- churny_fraction (churn intensity)

Outputs:
- pareto_results.csv: All configurations with metrics
"""

import sys
import csv
import itertools
import random
import numpy as np
import os
import concurrent.futures
import threading
from meshsub import MeshSubComplete


def run_single_config(D, D_lazy, churny_fraction, seed=42):
    """
    Run single configuration with specified seed.
    Returns dict with metrics.
    """
    # Set seeds for reproducibility
    random.seed(seed)
    np.random.seed(seed)
    
    # Create simulator (suppress output)
    import io
    import contextlib
    
    with contextlib.redirect_stdout(io.StringIO()):
        sim = MeshSubComplete(
            num_peers=1000,
            tick_sec=0.1,
            heartbeat_interval_sec=1.0,
            peer_table_min=40,
            peer_table_max=80,
            D=D,
            D_lazy=D_lazy,
            validators_per_node=1,
            global_bandwidth_bps=25_000_000,
            msg_size_default=1536,
            mcache_gossip=3,
            churny_fraction=churny_fraction,
            churny_leave_rate=0.01,
            churny_rejoin_rate=0.05,
            region_names=[],      # Disable regions (uniform delays)
            region_fractions=[],  # Disable regions (uniform delays)
        )
        
        # Run with warmup
        sim.run(n_ticks=10000, warmup_ticks=2000, verbose=False)
    
    # Get statistics
    stats = sim.get_stats()
    latency = sim.get_latency_statistics()
    
    # Compute derived metrics
    num_peers = 1000
    num_messages = stats['total_origin']
    delivery_rate = stats['delivery_mean']  # = mean(|R_m| / |V|) over all messages
    total_bytes = stats['total_bytes']
    
    # Bytes per successful delivery: β = B_total / sum_m |R_m|
    # Since delivery_rate = mean(|R_m|/|V|), we have sum_m |R_m| ≈ num_messages * |V| * delivery_rate
    total_deliveries = num_messages * num_peers * delivery_rate
    bytes_per_delivery = total_bytes / total_deliveries if total_deliveries > 0 else float('inf')
    
    result = {
        'D': D,
        'D_lazy': D_lazy,
        'churny_fraction': churny_fraction,
        'seed': seed,
        # Primary objectives
        'delivery_rate': delivery_rate,
        'p99_latency_sec': latency['p99_latency_sec'] if latency else None,
        'bytes_per_delivery': bytes_per_delivery,
        # Secondary metrics
        'p50_latency_sec': latency['p50_latency_sec'] if latency else None,
        'p90_latency_sec': latency['p90_latency_sec'] if latency else None,
        'avg_latency_sec': latency['avg_latency_sec'] if latency else None,
        # Bandwidth breakdown
        'payload_bytes_MB': stats['payload_bytes'] / (1024 * 1024),
        'control_bytes_MB': stats['control_bytes'] / (1024 * 1024),
        'meshmnt_bytes_MB': stats['meshmnt_bytes'] / (1024 * 1024),
        'gossip_bytes_MB': stats['gossip_bytes'] / (1024 * 1024),
        'total_bytes_MB': stats['total_bytes'] / (1024 * 1024),
        'payload_pct': stats['payload_pct'],
        # Other stats
        'messages_published': num_messages,
        'total_deliveries': latency['total_deliveries'] if latency else 0,
        'drops_peer': stats['drops_peer'],
        'drops_offline': stats['drops_offline'],
        'online_rate': stats['online_total'] / num_peers,
    }
    
    return result


def run_multi_seed(D, D_lazy, churny_fraction, num_seeds=5):
    """
    Run configuration with multiple seeds and aggregate results.
    Returns dict with mean and std for each metric.
    """
    results = []
    
    for seed in range(num_seeds):
        result = run_single_config(D, D_lazy, churny_fraction, seed=seed + 42)
        results.append(result)
    
    # Metrics to aggregate
    metrics = [
        'delivery_rate', 'p99_latency_sec', 'bytes_per_delivery',
        'p50_latency_sec', 'p90_latency_sec', 'avg_latency_sec',
        'payload_bytes_MB', 'control_bytes_MB', 'meshmnt_bytes_MB',
        'gossip_bytes_MB', 'total_bytes_MB', 'payload_pct',
        'messages_published', 'total_deliveries',
        'drops_peer', 'drops_offline', 'online_rate'
    ]
    
    aggregated = {
        'D': D,
        'D_lazy': D_lazy,
        'churny_fraction': churny_fraction,
        'num_seeds': num_seeds,
    }
    
    for metric in metrics:
        values = [r[metric] for r in results if r[metric] is not None]
        if values:
            aggregated[f'{metric}_mean'] = np.mean(values)
            aggregated[f'{metric}_std'] = np.std(values)
        else:
            aggregated[f'{metric}_mean'] = None
            aggregated[f'{metric}_std'] = None
    
    return aggregated


def run_config(D, D_lazy, churny_frac, num_seeds):
    """
    Worker function to run a single config and return the result.
    """
    try:
        result = run_multi_seed(D, D_lazy, churny_frac, num_seeds=num_seeds)
        return result
    except Exception as e:
        print(f"ERROR for D={D}, D_lazy={D_lazy}, churn={churny_frac}: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='MeshSub parameter sweep for Pareto analysis')
    parser.add_argument('--quick', action='store_true',
                        help='Quick test with reduced parameter space')
    parser.add_argument('--seeds', type=int, default=3,
                        help='Number of random seeds per config (default: 3)')
    parser.add_argument('--output', type=str, default='pareto_results.csv',
                        help='Output CSV file (default: pareto_results.csv)')
    parser.add_argument('--workers', type=int, default=3,
                        help='Number of parallel workers (default: 3)')

    args = parser.parse_args()

    # Define parameter ranges
    if args.quick:
        D_values = [6, 8, 10]
        D_lazy_values = [6, 12]
        churny_values = [0.0, 0.2]
    else:
        D_values = [2,4,6,8,10,12,14]
        D_lazy_values = [1,3,5,7,9,11,13,15,17,19,21,23]
        churny_values = [0, 0.1, 0.2, 0.3, 0.4]

    configs = list(itertools.product(D_values, D_lazy_values, churny_values))
    
    # Add Floodsub reference configurations: D=60, D_lazy=0 across all churn levels
    floodsub_configs = [(60, 0, churn) for churn in churny_values]
    configs.extend(floodsub_configs)
    
    total_configs = len(configs)

    # Metrics to aggregate (for fieldnames)
    metrics = [
        'delivery_rate', 'p99_latency_sec', 'bytes_per_delivery',
        'p50_latency_sec', 'p90_latency_sec', 'avg_latency_sec',
        'payload_bytes_MB', 'control_bytes_MB', 'meshmnt_bytes_MB',
        'gossip_bytes_MB', 'total_bytes_MB', 'payload_pct',
        'messages_published', 'total_deliveries',
        'drops_peer', 'drops_offline', 'online_rate'
    ]
    
    # Build metric fieldnames interleaved (_mean, _std for each metric)
    # to match the order they're added in run_multi_seed()
    metric_fields = []
    for m in metrics:
        metric_fields.extend([f'{m}_mean', f'{m}_std'])

    output_file = args.output
    completed_configs = set()
    file_mode = 'w'

    if os.path.exists(output_file):
        file_mode = 'a'
        try:
            with open(output_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    completed_configs.add((int(row['D']), int(row['D_lazy']), float(row['churny_fraction'])))
        except Exception as e:
            print(f"Warning: Could not read existing file {output_file}: {e}. Starting fresh.")
            file_mode = 'w'
            completed_configs = set()

    remaining_configs = total_configs - len(completed_configs)
    args.workers = min(args.workers, remaining_configs) if remaining_configs > 0 else 1

    print("=" * 70)
    print("MESHSUB PARETO SWEEP")
    print("=" * 70)
    print(f"Parameters:")
    print(f"  D:       {D_values}")
    print(f"  D_lazy:  {D_lazy_values}")
    print(f"  churn:   {churny_values}")
    print(f"\nTotal: {total_configs} configs × {args.seeds} seeds = {total_configs * args.seeds} runs")
    print(f"Output: {args.output}")
    print(f"Workers: {args.workers}")
    if completed_configs:
        print(f"Resuming: {len(completed_configs)} configurations already completed")
    print("=" * 70)
    print()

    # Run sweep
    fieldnames = ['D', 'D_lazy', 'churny_fraction', 'num_seeds'] + metric_fields

    with open(output_file, file_mode, newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if file_mode == 'w':
            writer.writeheader()
            f.flush()

        lock = threading.Lock()
        completed_count = len(completed_configs)

        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for D, D_lazy, churny_frac in configs:
                if (D, D_lazy, churny_frac) in completed_configs:
                    continue
                future = executor.submit(run_config, D, D_lazy, churny_frac, args.seeds)
                futures[future] = (D, D_lazy, churny_frac)

            # Wait for all to complete
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    D, D_lazy, churny_frac = futures[future]
                    with lock:
                        writer.writerow(result)
                        f.flush()
                    print(f"D={D:2d}, D_lazy={D_lazy:2d}, churn={churny_frac:.1f}: "
                          f"delivery={result['delivery_rate_mean']:.1%}, "
                          f"p99={result['p99_latency_sec_mean']:.2f}s, "
                          f"ctrl={result['control_bytes_MB_mean']:.1f}MB")

    # Summary
    print()
    print("=" * 70)
    print(f"Completed {total_configs - completed_count}/{total_configs} configurations ({completed_count} skipped)")
    print(f"Saved: {args.output}")
    print("=" * 70)


if __name__ == "__main__":
    main()