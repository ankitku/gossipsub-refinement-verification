import numpy as np
from meshsub import MeshSubComplete

# Test churn=0 specifically
print("Testing churn=0 case...")
sim = MeshSubComplete(
    num_peers=200,
    D=8,
    D_lazy=20,
    gossip_fraction=0.5,
    churny_fraction=0.0,  # NO CHURN
    validators_per_node=1
)

# Run
sim.run(n_ticks=10000, warmup_ticks=2000, verbose=True)

# Check mesh sizes
eager_sizes = [len(p.mesh_eager) for p in sim.peers.values()]
lazy_sizes = [len(p.mesh_lazy) for p in sim.peers.values()]

print(f"\nMesh diagnostics:")
print(f"  Eager: mean={np.mean(eager_sizes):.1f}, min={min(eager_sizes)}, max={max(eager_sizes)}")
print(f"  Lazy: mean={np.mean(lazy_sizes):.1f}, min={min(lazy_sizes)}, max={max(lazy_sizes)}")

# Check message production
stats = sim.get_stats()
print(f"\nMessage production:")
print(f"  Published: {stats['total_origin']}")
print(f"  Expected: ~130 (200 peers × 0.002604 msgs/sec × 1000 sec)")

# Check delivery per message
for mid in list(sim.produced_messages.keys())[:5]:
    seen = sum(1 for p in sim.peers.values() if mid in p.seen)
    targets = len(sim.produced_targets[mid])
    print(f"  Message {mid}: {seen}/{targets} = {seen/targets:.1%}")

sim.print_report()