#!/usr/bin/env python3
"""
Quick test of latency measurement in MeshSub
"""

from meshsub import MeshSubComplete

print("Testing MeshSub latency measurement...")

# Quick test with small network
sim = MeshSubComplete(
    num_peers=20,
    tick_sec=0.1,
    heartbeat_interval_sec=1.0,
    D=4,
    D_lazy=3,
    validators_per_node=1,
    global_bandwidth_bps=25_000_000,
    msg_size_default=1536,
    churny_fraction=0.0
)

# Run short simulation
sim.run(n_ticks=1000, warmup_ticks=200, verbose=False)

# Check latency stats
latency = sim.get_latency_statistics()
if latency:
    print("✓ Latency measurement successful!")
    print(f"  99th percentile latency: {latency['p99_latency_sec']:.3f}s ({latency['p99_latency_ticks']:.1f} ticks)")
    print(f"  Total deliveries tracked: {latency['total_deliveries']}")
    print(f"  Messages tracked: {latency['total_messages']}")
else:
    print("✗ No latency data collected")

# Print brief report
sim.print_report()
