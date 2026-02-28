#!/usr/bin/env python3
"""
validation_metrics.py

Simple script to extract validation metrics from your MeshSub simulation
for comparison with Protocol Labs Gossipsub v1.1 Evaluation Report.

Usage:
    python validation_metrics.py

Make sure meshsub.py is in the same directory.
"""

import sys

import numpy as np
from meshsub import MeshSubComplete

# Protocol Labs reference values
PROTOCOL_LABS = {
    'p99_latency_sec': 0.165,      # 165 ms baseline
    'max_latency_sec': 0.350,      # ~350 ms baseline
    'delivery_rate': 1.0,          # 100%
    'p99_under_attack': 1.6,       # Never exceeded 1.6s even under attack
    'eth2_propagation': 3.0,       # ETH2 requirement: ~3 seconds
}


def run_single_config(D, D_lazy, churny_fraction, num_peers=200, 
                      n_ticks=5000, warmup_ticks=1000, tick_sec=0.1):
    """Run simulation and return key metrics.
    
    Args:
        D: Eager mesh degree
        D_lazy: Lazy mesh degree  
        churny_fraction: Fraction of churny peers
        num_peers: Number of peers in network
        n_ticks: Total simulation ticks
        warmup_ticks: Warmup ticks before measurement
        tick_sec: Tick duration in seconds (0.1 = 100ms, 0.01 = 10ms)
    """
    
    sim = MeshSubComplete(
        num_peers=num_peers,
        tick_sec=tick_sec,
        heartbeat_interval_sec=1.0,
        peer_table_min=40,
        peer_table_max=80,
        D=D,
        D_lazy=D_lazy,
        validators_per_node=1,
        global_bandwidth_bps=25_000_000,
        msg_size_default=1536,
        churny_fraction=churny_fraction,
        churny_leave_rate=0.01,
        churny_rejoin_rate=0.05,
    )
    
    sim.run(n_ticks=n_ticks, warmup_ticks=warmup_ticks, verbose=False)
    
    stats = sim.get_stats()
    latency = sim.get_latency_statistics()
    
    return {
        'delivery_rate': stats['delivery_mean'],
        'p50_latency_sec': latency['p50_latency_sec'] if latency else None,
        'p90_latency_sec': latency['p90_latency_sec'] if latency else None,
        'p99_latency_sec': latency['p99_latency_sec'] if latency else None,
        'max_latency_sec': latency['max_latency_ticks'] * sim.tick_sec if latency else None,
        'avg_latency_sec': latency['avg_latency_sec'] if latency else None,
        'total_messages': latency['total_messages'] if latency else 0,
        'total_deliveries': latency['total_deliveries'] if latency else 0,
        'tick_sec': tick_sec,
    }


def main():
    print("\n" + "="*70)
    print("VALIDATION METRICS FOR PROTOCOL LABS COMPARISON")
    print("="*70)
    
    # =========================================================================
    # Test 1: Baseline (D=8, D_lazy=8, no churn) with 10ms ticks for accuracy
    # This is the primary validation target
    # =========================================================================
    print("\n[1] Running baseline (D=8, D_lazy=8, churn=0%, 1000 nodes, 10ms ticks)...")
    print("    (This may take a while due to fine tick resolution...)")
    
    # Use 10ms ticks for validation - need 10x more ticks for same wall-clock time
    # 20000 ticks * 0.01s = 200s simulated time
    # 5000 warmup ticks * 0.01s = 50s warmup
    baseline = run_single_config(
        D=8, 
        D_lazy=8, 
        churny_fraction=0.0, 
        num_peers=1000,
        tick_sec=0.01,      # 10ms ticks for accurate latency
        n_ticks=20000,      # 200s simulated time
        warmup_ticks=5000   # 50s warmup
    )
    
    print("\n" + "-"*70)
    print("BASELINE RESULTS (D=8, D_lazy=8, c=0, 1000 nodes, 10ms ticks)")
    print("-"*70)
    print(f"{'Metric':<25} {'Your Simulation':<20} {'Protocol Labs':<20}")
    print("-"*70)
    print(f"{'Delivery rate':<25} {baseline['delivery_rate']:.4f} ({baseline['delivery_rate']*100:.2f}%){'':<3} {PROTOCOL_LABS['delivery_rate']:.2f} (100%)")
    print(f"{'p50 (median) latency':<25} {baseline['p50_latency_sec']:.4f} s{'':<12} ~0.100 s")
    print(f"{'p99 latency':<25} {baseline['p99_latency_sec']:.4f} s{'':<12} {PROTOCOL_LABS['p99_latency_sec']:.3f} s")
    print(f"{'Maximum latency':<25} {baseline['max_latency_sec']:.4f} s{'':<12} {PROTOCOL_LABS['max_latency_sec']:.3f} s")
    print(f"{'Messages published':<25} {baseline['total_messages']}")
    print(f"{'Total deliveries':<25} {baseline['total_deliveries']:,}")
    
    # =========================================================================
    # Test 2: Same config with 100ms ticks (to show tick resolution effect)
    # =========================================================================
    print("\n[2] Running same config with 100ms ticks (for comparison)...")
    baseline_100ms = run_single_config(
        D=8, 
        D_lazy=8, 
        churny_fraction=0.0, 
        num_peers=1000,
        tick_sec=0.1,       # 100ms ticks (coarser)
        n_ticks=2000,       # 200s simulated time
        warmup_ticks=500    # 50s warmup
    )
    
    print("\n" + "-"*70)
    print("TICK RESOLUTION COMPARISON (D=8, D_lazy=8, c=0, 1000 nodes)")
    print("-"*70)
    print(f"{'Metric':<25} {'10ms ticks':<20} {'100ms ticks':<20}")
    print("-"*70)
    print(f"{'Delivery rate':<25} {baseline['delivery_rate']:.4f}{'':<15} {baseline_100ms['delivery_rate']:.4f}")
    print(f"{'p50 latency':<25} {baseline['p50_latency_sec']:.4f} s{'':<13} {baseline_100ms['p50_latency_sec']:.4f} s")
    print(f"{'p99 latency':<25} {baseline['p99_latency_sec']:.4f} s{'':<13} {baseline_100ms['p99_latency_sec']:.4f} s")
    print(f"{'Max latency':<25} {baseline['max_latency_sec']:.4f} s{'':<13} {baseline_100ms['max_latency_sec']:.4f} s")
    
    # =========================================================================
    # Test 3: Churn sweep (with 100ms ticks for efficiency)
    # =========================================================================
    print("\n[3] Running churn sweep (100ms ticks for efficiency)...")
    churn_results = {}
    for churn in [0.0, 0.1, 0.2, 0.3, 0.4]:
        print(f"    churn={churn:.0%}...", end=" ", flush=True)
        result = run_single_config(
            D=8, 
            D_lazy=8, 
            churny_fraction=churn, 
            num_peers=1000,
            tick_sec=0.1,
            n_ticks=2000, 
            warmup_ticks=500
        )
        churn_results[churn] = result
        print(f"delivery={result['delivery_rate']:.3f}, p99={result['p99_latency_sec']:.3f}s")
    
    print("\n" + "-"*70)
    print("CHURN SENSITIVITY (D=8, D_lazy=8, 1000 nodes)")
    print("-"*70)
    print(f"{'Churn':<10} {'Delivery':<15} {'p99 (s)':<15} {'Max (s)':<15}")
    print("-"*70)
    for churn, r in churn_results.items():
        print(f"{churn:.0%}{'':<7} {r['delivery_rate']:.4f}{'':<10} {r['p99_latency_sec']:.4f}{'':<10} {r['max_latency_sec']:.4f}")
    
    # =========================================================================
    # Summary for paper
    # =========================================================================
    print("\n" + "="*70)
    print("VALUES TO USE IN YOUR PAPER (validation_section.tex)")
    print("="*70)
    
    print(f"""
For the Ethereum-like configuration ($D=8$, $D_{{\\text{{lazy}}}}=8$, $c=0$), 
our simulation with 10ms tick resolution produces:

\\begin{{itemize}}
    \\item Median (p50) latency: {baseline['p50_latency_sec']:.3f} seconds
    \\item p99 latency: {baseline['p99_latency_sec']:.3f} seconds
    \\item Maximum (p100) latency: {baseline['max_latency_sec']:.3f} seconds
    \\item Delivery rate: {baseline['delivery_rate']*100:.1f}\\%
\\end{{itemize}}

Protocol Labs reports p99 latency of 165 ms (0.165 s) for a 1000-node network.
Your p99 of {baseline['p99_latency_sec']:.3f} s is {"consistent with" if baseline['p99_latency_sec'] < 0.5 else "higher than"} their baseline.

Note on tick resolution:
- 10ms ticks: p99 = {baseline['p99_latency_sec']:.3f}s (accurate, used for validation)
- 100ms ticks: p99 = {baseline_100ms['p99_latency_sec']:.3f}s (conservative upper bound, used for parameter sweep)

ETH2 Requirement: Full propagation in ~3 seconds
Your maximum latency: {baseline['max_latency_sec']:.3f} s → {"✓ MEETS REQUIREMENT" if baseline['max_latency_sec'] < 3.0 else "✗ EXCEEDS"}
""")
    
    print("="*70)
    
    return {
        'baseline_10ms': baseline,
        'baseline_100ms': baseline_100ms,
        'churn_sweep': churn_results,
    }


if __name__ == "__main__":
    results = main()