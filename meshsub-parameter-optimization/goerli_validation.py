#!/usr/bin/env python3
"""
goerli_validation.py

Validation metrics for MeshSub simulation using real Goerli network topology.
Loads the peer connection graph from Goerli_Data.csv and runs Protocol Labs
comparison metrics.

Usage:
    python goerli_validation.py
"""

import math
import random
import statistics
from collections import defaultdict, deque, namedtuple
from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional, Tuple
from enum import Enum
import time
import numpy as np

# Import base classes from meshsub
import sys
sys.path.insert(0, '/mnt/user-data/uploads')
from meshsub import (
    Message, PeerType, TokenBucket, PeerState,
    ATTESTATION_SIZE, AGGREGATE_SIZE, BEACON_BLOCK_SIZE, BLOB_SIZE,
    ID_SIZE, IHAVE_OVERHEAD, IWANT_OVERHEAD, GRAFT_PRUNE_SIZE
)

# Protocol Labs reference values
PROTOCOL_LABS = {
    'p99_latency_sec': 0.165,      # 165 ms baseline
    'max_latency_sec': 0.350,      # ~350 ms baseline
    'delivery_rate': 1.0,          # 100%
    'p99_under_attack': 1.6,       # Never exceeded 1.6s even under attack
    'eth2_propagation': 3.0,       # ETH2 requirement: ~3 seconds
}


def load_goerli_topology(filepath: str) -> Tuple[int, Dict[int, Set[int]]]:
    """
    Load Goerli network topology from CSV edge list.
    
    Returns:
        num_peers: Total number of unique peers
        adjacency: Dict mapping peer_id -> set of neighbor peer_ids
    """
    adjacency = defaultdict(set)
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if ';' in line:
                parts = line.split(';')
                if len(parts) == 2:
                    # Extract numeric IDs (e.g., "P715" -> 715)
                    a_id = int(parts[0][1:])
                    b_id = int(parts[1][1:])
                    adjacency[a_id].add(b_id)
                    adjacency[b_id].add(a_id)
    
    # Get all unique peer IDs
    all_peers = set(adjacency.keys())
    num_peers = len(all_peers)
    
    # Ensure contiguous IDs (remap if necessary)
    sorted_peers = sorted(all_peers)
    id_map = {old_id: new_id for new_id, old_id in enumerate(sorted_peers)}
    
    # Remap adjacency list
    remapped_adj = {}
    for old_id, neighbors in adjacency.items():
        new_id = id_map[old_id]
        remapped_adj[new_id] = {id_map[n] for n in neighbors}
    
    return num_peers, remapped_adj


class MeshSubGoerli:
    """
    MeshSub simulator initialized with Goerli network topology.
    
    Uses real peer connection data from Goerli testnet to initialize
    the peer table, then builds mesh overlays on top.
    """
    
    def __init__(
        self,
        # Topology from file
        adjacency: Dict[int, Set[int]],
        num_peers: int,
        
        # Timing
        tick_sec: float = 0.1,
        heartbeat_interval_sec: float = 1.0,
        
        # Mesh parameters
        D: int = 8,
        D_lazy: int = 6,
        
        # Validators
        validators_per_node: int = 1,
        
        # Bandwidth
        global_bandwidth_bps: int = 25_000_000,
        
        # Message sizes
        msg_size_default: int = AGGREGATE_SIZE,
        
        # Gossip
        mcache_gossip: int = 3,
        
        # Churn
        churny_fraction: float = 0.0,
        stable_leave_rate: float = 0.0,
        stable_rejoin_rate: float = 0.01,
        churny_leave_rate: float = 0.01,
        churny_rejoin_rate: float = 0.05,
        
        # Regions
        region_names: Optional[List[str]] = None,
        region_fractions: Optional[List[float]] = None,
    ):
        random.seed(42)
        np.random.seed(42)
        
        self.num_peers = num_peers
        self.tick_sec = float(tick_sec)
        self.heartbeat_ticks = int(heartbeat_interval_sec / tick_sec)
        self.D = D
        self.D_lazy = D_lazy
        self.validators_per_node = validators_per_node
        self.global_bandwidth_bps = global_bandwidth_bps
        self.msg_size_default = msg_size_default
        self.mcache_gossip = mcache_gossip
        self.churny_fraction = churny_fraction
        
        # Geographic regions
        self.region_names = region_names or ['EU', 'US', 'Asia']
        self.region_fractions = region_fractions or [0.3, 0.4, 0.3]
        
        # Latency table
        self.latency_table = {
            ('EU', 'EU'): (0.030, 0.009),
            ('EU', 'US'): (0.120, 0.036),
            ('EU', 'Asia'): (0.220, 0.066),
            ('US', 'EU'): (0.120, 0.036),
            ('US', 'US'): (0.030, 0.009),
            ('US', 'Asia'): (0.200, 0.060),
            ('Asia', 'EU'): (0.220, 0.066),
            ('Asia', 'US'): (0.200, 0.060),
            ('Asia', 'Asia'): (0.040, 0.012),
        }
        
        # Print configuration
        print(f"\n{'='*80}")
        print(f"MESHSUB WITH GOERLI TOPOLOGY")
        print(f"{'='*80}")
        print(f"Network: {num_peers} peers (from Goerli edge list)")
        print(f"Timing: tick={tick_sec}s, heartbeat every {heartbeat_interval_sec}s ({self.heartbeat_ticks} ticks)")
        print(f"Mesh: D={D}, D_lazy={D_lazy}")
        print(f"Validators: {validators_per_node} per node")
        print(f"Bandwidth: {global_bandwidth_bps/1_000_000:.0f} Mbps per peer")
        print(f"Churn: {churny_fraction:.0%} churny peers")
        
        # Analyze topology
        degrees = [len(neighbors) for neighbors in adjacency.values()]
        print(f"\nTopology statistics:")
        print(f"  Avg degree: {np.mean(degrees):.2f}")
        print(f"  Median degree: {np.median(degrees):.0f}")
        print(f"  Min/Max degree: {min(degrees)}/{max(degrees)}")
        print(f"{'='*80}\n")
        
        # Initialize peers
        self.peers = {}
        for i in range(num_peers):
            is_churny = random.random() < churny_fraction
            peer_type = PeerType.CHURNY if is_churny else PeerType.STABLE
            leave_rate = churny_leave_rate if is_churny else stable_leave_rate
            rejoin_rate = churny_rejoin_rate if is_churny else stable_rejoin_rate
            
            self.peers[i] = PeerState(
                pid=i,
                validators_per_node=validators_per_node,
                tick_sec=tick_sec,
                D=D,
                D_lazy=D_lazy,
                global_bandwidth_bps=global_bandwidth_bps,
                peer_type=peer_type,
                leave_rate=leave_rate,
                rejoin_rate=rejoin_rate
            )
        
        # Assign regions
        for pid in self.peers:
            region = np.random.choice(self.region_names, p=self.region_fractions)
            self.peers[pid].region = region
        
        # Use Goerli topology for peer tables
        for pid in range(num_peers):
            self.peers[pid].peer_table = adjacency.get(pid, set()).copy()
        
        # Build mesh overlays from peer tables
        peer_ids = list(range(num_peers))
        for i in peer_ids:
            p = self.peers[i]
            candidates = list(p.peer_table)
            random.shuffle(candidates)
            
            # Eager mesh: up to D peers
            eager_count = min(len(candidates), D)
            p.mesh_eager = set(candidates[:eager_count])
            
            # Lazy mesh: remaining peers up to D_lazy
            non_eager = [n for n in candidates if n not in p.mesh_eager]
            random.shuffle(non_eager)
            p.mesh_lazy = set(non_eager[:min(len(non_eager), D_lazy)])
        
        # Symmetrize eager mesh
        for i in peer_ids:
            p = self.peers[i]
            for nbr in list(p.mesh_eager):
                if i not in self.peers[nbr].mesh_eager:
                    self.peers[nbr].mesh_eager.add(i)
        
        # Event scheduling
        self.delivery_schedule = defaultdict(list)
        self.pending_iwants = defaultdict(list)
        
        # Online status
        self.online = {i: True for i in peer_ids}
        
        # Message tracking
        self.produced_messages = {}
        self.produced_targets = {}
        self.next_mid = 0
        self.tick = 0
        
        # Metrics
        self.churn_events = []
        self.warmup_complete = False
        self.latency_tracker = {}
        self.drops_peer = 0
        self.drops_offline = 0
    
    def _rand_delay_ticks(self, sender: int, dest: int):
        """Random network delay based on regions"""
        if sender not in self.peers or dest not in self.peers:
            delay_s = random.uniform(0.02, 0.2)
            return max(1, int(math.ceil(delay_s / self.tick_sec)))
        
        r_s = self.peers[sender].region
        r_d = self.peers[dest].region
        key = (r_s, r_d)
        if key not in self.latency_table:
            delay_s = random.uniform(0.02, 0.2)
        else:
            mu, sigma = self.latency_table[key]
            delay_s = np.random.normal(mu, sigma)
            delay_s = max(0.01, delay_s)
        
        return max(1, int(math.ceil(delay_s / self.tick_sec)))
    
    def _new_mid(self):
        mid = self.next_mid
        self.next_mid += 1
        return mid
    
    def produce_step(self):
        """Production phase"""
        for p in self.peers.values():
            if not self.online[p.pid]:
                continue
            
            p_prob = 1 - math.exp(-p.publish_rate * self.tick_sec)
            
            if random.random() < p_prob and p.token_bucket.consume(1):
                mid = self._new_mid()
                msg = Message(mid, p.pid, "attestation_aggr", self.msg_size_default, self.tick)
                
                self.produced_messages[mid] = msg
                self.produced_targets[mid] = {i for i, on in self.online.items() if on}
                
                self.latency_tracker[mid] = {
                    'pub_tick': self.tick,
                    'deliveries': {}
                }
                
                p.message_store[mid] = msg
                p.add_to_mcache(mid)
                p.seen.add(mid)
                
                for nbr in p.mesh_eager:
                    if self.online.get(nbr, False):
                        dt = self._rand_delay_ticks(p.pid, nbr)
                        self.delivery_schedule[self.tick + dt].append(
                            (nbr, p.pid, msg, False, msg.size_bytes)
                        )
    
    def process_delivery(self):
        """Process scheduled deliveries"""
        items = self.delivery_schedule.pop(self.tick, [])
        
        for dest, sender, payload, is_control, size in items:
            if not self.online.get(dest, False):
                continue
            
            if is_control:
                if payload.get("type") == "IHAVE":
                    missing = [mid for mid in payload["ids"] 
                              if mid not in self.peers[dest].seen]
                    if missing:
                        self.pending_iwants[self.tick + 1].append((dest, sender, missing))
                
                elif payload.get("type") == "IWANT":
                    provider = dest
                    requester = sender
                    for mid in payload["ids"]:
                        if mid in self.peers[provider].message_store:
                            msg = self.peers[provider].message_store[mid]
                            dt = self._rand_delay_ticks(provider, requester)
                            self.delivery_schedule[self.tick + dt].append(
                                (requester, provider, msg, False, msg.size_bytes)
                            )
                
                elif payload.get("type") == "GRAFT":
                    p = self.peers[dest]
                    graft_peer = payload["peer_id"]
                    if graft_peer in p.peer_table and self.online.get(graft_peer, False):
                        p.mesh_eager.add(graft_peer)
                        p.mesh_lazy.discard(graft_peer)
                
                elif payload.get("type") == "PRUNE":
                    p = self.peers[dest]
                    prune_peer = payload["peer_id"]
                    p.mesh_eager.discard(prune_peer)
            else:
                if isinstance(payload, Message):
                    p = self.peers[dest]
                    if payload.mid in p.seen:
                        continue
                    
                    p.seen.add(payload.mid)
                    p.message_store[payload.mid] = payload
                    p.add_to_mcache(payload.mid)
                    
                    if payload.mid in self.latency_tracker:
                        if dest not in self.latency_tracker[payload.mid]['deliveries']:
                            self.latency_tracker[payload.mid]['deliveries'][dest] = self.tick
                    
                    for nbr in p.mesh_eager:
                        if nbr == sender or not self.online.get(nbr, False):
                            continue
                        dt = self._rand_delay_ticks(dest, nbr)
                        self.delivery_schedule[self.tick + dt].append(
                            (nbr, dest, payload, False, payload.size_bytes)
                        )
        
        # Process pending IWANTs
        pending = self.pending_iwants.pop(self.tick, [])
        if pending:
            grouped = {}
            for requester, provider, mids in pending:
                grouped.setdefault((requester, provider), []).extend(mids)
            
            for (requester, provider), mids in grouped.items():
                size = IWANT_OVERHEAD + len(mids) * ID_SIZE
                dt = self._rand_delay_ticks(provider, requester)
                self.delivery_schedule[self.tick + dt].append(
                    (provider, requester, {"type": "IWANT", "ids": mids}, True, size)
                )
    
    def heartbeat(self):
        """Heartbeat: IHAVE emission + mesh maintenance"""
        for pid, p in self.peers.items():
            if not self.online.get(pid, False):
                continue
            
            recent = list(p.get_mcache_for_gossip(self.mcache_gossip))
            if not recent:
                continue
            
            lazy = list(p.mesh_lazy)
            if not lazy:
                continue
            
            random.shuffle(lazy)
            targets = lazy
            
            if not targets:
                continue
            
            ctrl_size = IHAVE_OVERHEAD + len(recent) * ID_SIZE
            for nbr in targets:
                if not self.online.get(nbr, False):
                    continue
                dt = self._rand_delay_ticks(pid, nbr)
                self.delivery_schedule[self.tick + dt].append(
                    (nbr, pid, {"type": "IHAVE", "ids": recent}, True, ctrl_size)
                )
        
        for p in self.peers.values():
            p.advance_mcache_round()
        
        # Mesh maintenance
        for pid, p in self.peers.items():
            if not self.online.get(pid, False):
                continue
            
            p.mesh_eager = {n for n in p.mesh_eager if self.online.get(n, False)}
            
            if len(p.mesh_eager) < p.D:
                need = p.D - len(p.mesh_eager)
                cands = list(p.peer_table - p.mesh_eager)
                cands = [c for c in cands if self.online.get(c, False)]
                random.shuffle(cands)
                for nbr in cands[:need]:
                    p.mesh_eager.add(nbr)
                    dt = self._rand_delay_ticks(pid, nbr)
                    self.delivery_schedule[self.tick + dt].append(
                        (nbr, pid, {"type": "GRAFT", "peer_id": pid}, True, GRAFT_PRUNE_SIZE)
                    )
            
            if len(p.mesh_eager) > p.D + 2:
                excess = list(p.mesh_eager)
                random.shuffle(excess)
                to_prune = excess[:2]
                for nbr in to_prune:
                    p.mesh_eager.discard(nbr)
                    dt = self._rand_delay_ticks(pid, nbr)
                    self.delivery_schedule[self.tick + dt].append(
                        (nbr, pid, {"type": "PRUNE", "peer_id": pid}, True, GRAFT_PRUNE_SIZE)
                    )
            
            rest = [n for n in p.peer_table if n not in p.mesh_eager and self.online.get(n, False)]
            p.mesh_lazy = set(rest[:min(len(rest), self.D_lazy)])
    
    def send_accounting(self):
        """Bandwidth accounting"""
        scheduled = list(self.delivery_schedule.get(self.tick + 1, []))
        new_sched = []
        
        for entry in scheduled:
            dest, sender, payload, is_control, size = entry
            
            if not self.online.get(sender, False) or not self.online.get(dest, False):
                self.drops_offline += 1
                continue
            
            sender_peer = self.peers[sender]
            
            if sender_peer.tokens >= size:
                sender_peer.tokens -= size
                
                if is_control:
                    sender_peer.bytes_sent_control += size
                    if payload.get("type") in ("IHAVE", "IWANT"):
                        sender_peer.bytes_sent_gossip += size
                    else:
                        sender_peer.bytes_sent_meshmnt += size
                else:
                    sender_peer.bytes_sent_payload += size
                
                new_sched.append(entry)
            else:
                self.drops_peer += 1
        
        self.delivery_schedule[self.tick + 1] = new_sched
    
    def process_bimodal_churn(self):
        """Process churn"""
        for pid, p in list(self.peers.items()):
            if not self.online[pid]:
                continue
            
            if random.random() < p.leave_rate:
                self.online[pid] = False
                p.num_leaves += 1
                self.churn_events.append({'tick': self.tick, 'type': p.peer_type.value, 'event': 'leave', 'pid': pid})
        
        for pid, p in list(self.peers.items()):
            if self.online[pid]:
                continue
            
            if random.random() < p.rejoin_rate:
                self.online[pid] = True
                p.num_joins += 1
                p.mesh_eager.clear()
                p.mesh_lazy.clear()
                self.churn_events.append({'tick': self.tick, 'type': p.peer_type.value, 'event': 'join', 'pid': pid})
    
    def run(self, n_ticks: int = 5000, warmup_ticks: int = 1000, verbose: bool = True):
        """Run simulation"""
        start_time = time.time()
        
        for t in range(n_ticks):
            self.tick = t
            
            if t == warmup_ticks:
                self.warmup_complete = True
                self.produced_messages.clear()
                self.produced_targets.clear()
                self.latency_tracker.clear()
                for p in self.peers.values():
                    p.bytes_sent_payload = 0
                    p.bytes_sent_control = 0
                    p.bytes_sent_meshmnt = 0
                    p.bytes_sent_gossip = 0
                self.churn_events.clear()
                self.drops_peer = 0
                self.drops_offline = 0
                if verbose:
                    print(f"  [tick {t}] Warmup complete, starting measurement")
            
            for p in self.peers.values():
                p.refill_tokens()
                p.token_bucket.refill(self.tick_sec)
            
            self.produce_step()
            self.send_accounting()
            self.process_delivery()
            
            if t % self.heartbeat_ticks == 0:
                self.heartbeat()
            
            self.process_bimodal_churn()
            
            if verbose and t > 0 and t % 1000 == 0:
                elapsed = time.time() - start_time
                pct = t / n_ticks * 100
                print(f"  [tick {t}/{n_ticks}] {pct:.0f}% complete ({elapsed:.1f}s elapsed)")
        
        if verbose:
            print(f"  Simulation complete in {time.time() - start_time:.1f}s")
    
    def get_stats(self):
        """Get simulation statistics"""
        total_origin = len(self.produced_messages)
        payload_bytes = sum(p.bytes_sent_payload for p in self.peers.values())
        meshmnt_bytes = sum(p.bytes_sent_meshmnt for p in self.peers.values())
        gossip_bytes = sum(p.bytes_sent_gossip for p in self.peers.values())
        control_bytes = meshmnt_bytes + gossip_bytes
        
        deliveries = []
        for mid, msg in self.produced_messages.items():
            targets_at_publish = self.produced_targets.get(mid, set())
            seen_count = sum(1 for peer_id in targets_at_publish 
                           if mid in self.peers[peer_id].seen)
            if len(targets_at_publish) > 0:
                deliveries.append(seen_count / len(targets_at_publish))
        
        delivery_mean = statistics.mean(deliveries) if deliveries else 0.0
        
        return {
            'total_origin': total_origin,
            'payload_bytes': payload_bytes,
            'control_bytes': control_bytes,
            'delivery_mean': delivery_mean,
            'online_total': sum(self.online.values()),
            'drops_peer': self.drops_peer,
            'drops_offline': self.drops_offline,
        }
    
    def get_latency_statistics(self):
        """Calculate latency statistics"""
        if not self.latency_tracker:
            return None
        
        all_latencies = []
        for msg_id, data in self.latency_tracker.items():
            pub_tick = data['pub_tick']
            deliveries = data['deliveries']
            if deliveries:
                msg_latencies = [tick - pub_tick for tick in deliveries.values()]
                all_latencies.extend(msg_latencies)
        
        if not all_latencies:
            return None
        
        latencies_sec = [lat * self.tick_sec for lat in all_latencies]
        
        return {
            'avg_latency_ticks': np.mean(all_latencies),
            'p50_latency_sec': np.percentile(latencies_sec, 50),
            'p90_latency_sec': np.percentile(latencies_sec, 90),
            'p99_latency_sec': np.percentile(latencies_sec, 99),
            'max_latency_ticks': np.max(all_latencies),
            'avg_latency_sec': np.mean(latencies_sec),
            'total_deliveries': len(all_latencies),
            'total_messages': len(self.latency_tracker)
        }


def run_goerli_validation(
    goerli_path: str,
    D: int = 8,
    D_lazy: int = 8,
    churny_fraction: float = 0.0,
    tick_sec: float = 0.1,
    n_ticks: int = 2000,
    warmup_ticks: int = 500,
):
    """Run validation with Goerli topology"""
    
    # Load topology
    print(f"\nLoading Goerli topology from {goerli_path}...")
    num_peers, adjacency = load_goerli_topology(goerli_path)
    print(f"Loaded {num_peers} peers")
    
    # Create simulator
    sim = MeshSubGoerli(
        adjacency=adjacency,
        num_peers=num_peers,
        tick_sec=tick_sec,
        heartbeat_interval_sec=1.0,
        D=D,
        D_lazy=D_lazy,
        validators_per_node=1,
        global_bandwidth_bps=25_000_000,
        msg_size_default=1536,
        churny_fraction=churny_fraction,
        churny_leave_rate=0.01,
        churny_rejoin_rate=0.05,
    )
    
    sim.run(n_ticks=n_ticks, warmup_ticks=warmup_ticks, verbose=True)
    
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
        'num_peers': num_peers,
    }


def main():
    goerli_path = "/mnt/user-data/uploads/Goerli_Data.csv"
    
    print("\n" + "="*70)
    print("GOERLI NETWORK VALIDATION METRICS")
    print("Protocol Labs Gossipsub v1.1 Evaluation Comparison")
    print("="*70)
    
    # =========================================================================
    # Test 1: Baseline with Goerli topology (D=8, D_lazy=8, no churn)
    # =========================================================================
    print("\n[1] Running Goerli baseline (D=8, D_lazy=8, churn=0%, 100ms ticks)...")
    
    baseline = run_goerli_validation(
        goerli_path=goerli_path,
        D=8,
        D_lazy=8,
        churny_fraction=0.0,
        tick_sec=0.1,
        n_ticks=2000,     # 200s simulated time
        warmup_ticks=500  # 50s warmup
    )
    
    print("\n" + "-"*70)
    print(f"GOERLI BASELINE RESULTS (D=8, D_lazy=8, c=0, {baseline['num_peers']} nodes)")
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
    # Test 2: Higher resolution (10ms ticks) for more accurate latency
    # =========================================================================
    print("\n[2] Running Goerli with 10ms ticks (higher latency resolution)...")
    
    baseline_10ms = run_goerli_validation(
        goerli_path=goerli_path,
        D=8,
        D_lazy=8,
        churny_fraction=0.0,
        tick_sec=0.01,    # 10ms ticks
        n_ticks=10000,    # 100s simulated time
        warmup_ticks=2500 # 25s warmup
    )
    
    print("\n" + "-"*70)
    print("TICK RESOLUTION COMPARISON (Goerli topology)")
    print("-"*70)
    print(f"{'Metric':<25} {'100ms ticks':<20} {'10ms ticks':<20}")
    print("-"*70)
    print(f"{'Delivery rate':<25} {baseline['delivery_rate']:.4f}{'':<15} {baseline_10ms['delivery_rate']:.4f}")
    print(f"{'p50 latency':<25} {baseline['p50_latency_sec']:.4f} s{'':<13} {baseline_10ms['p50_latency_sec']:.4f} s")
    print(f"{'p99 latency':<25} {baseline['p99_latency_sec']:.4f} s{'':<13} {baseline_10ms['p99_latency_sec']:.4f} s")
    print(f"{'Max latency':<25} {baseline['max_latency_sec']:.4f} s{'':<13} {baseline_10ms['max_latency_sec']:.4f} s")
    
    # =========================================================================
    # Test 3: Churn sweep
    # =========================================================================
    print("\n[3] Running churn sweep on Goerli topology...")
    churn_results = {}
    for churn in [0.0, 0.1, 0.2, 0.3, 0.4]:
        print(f"    churn={churn:.0%}...", end=" ", flush=True)
        result = run_goerli_validation(
            goerli_path=goerli_path,
            D=8,
            D_lazy=8,
            churny_fraction=churn,
            tick_sec=0.1,
            n_ticks=2000,
            warmup_ticks=500
        )
        churn_results[churn] = result
        print(f"delivery={result['delivery_rate']:.3f}, p99={result['p99_latency_sec']:.3f}s")
    
    print("\n" + "-"*70)
    print(f"CHURN SENSITIVITY (Goerli topology, {baseline['num_peers']} nodes)")
    print("-"*70)
    print(f"{'Churn':<10} {'Delivery':<15} {'p99 (s)':<15} {'Max (s)':<15}")
    print("-"*70)
    for churn, r in churn_results.items():
        print(f"{churn:.0%}{'':<7} {r['delivery_rate']:.4f}{'':<10} {r['p99_latency_sec']:.4f}{'':<10} {r['max_latency_sec']:.4f}")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "="*70)
    print("SUMMARY: GOERLI TOPOLOGY VALIDATION")
    print("="*70)
    
    print(f"""
For the Goerli network topology ({baseline['num_peers']} nodes, D=8, D_lazy=8):

Performance at 10ms tick resolution:
  - Median (p50) latency: {baseline_10ms['p50_latency_sec']:.3f} seconds
  - p99 latency: {baseline_10ms['p99_latency_sec']:.3f} seconds  
  - Maximum latency: {baseline_10ms['max_latency_sec']:.3f} seconds
  - Delivery rate: {baseline_10ms['delivery_rate']*100:.1f}%

Protocol Labs reference (1000 nodes, synthetic topology):
  - p99 latency: {PROTOCOL_LABS['p99_latency_sec']:.3f} seconds
  - Maximum latency: ~{PROTOCOL_LABS['max_latency_sec']:.3f} seconds
  - Delivery rate: 100%

ETH2 Requirement: Full propagation in ~3 seconds
Your maximum latency: {baseline_10ms['max_latency_sec']:.3f} s → {"✓ MEETS REQUIREMENT" if baseline_10ms['max_latency_sec'] < 3.0 else "✗ EXCEEDS"}
""")
    
    print("="*70)
    
    return {
        'baseline_100ms': baseline,
        'baseline_10ms': baseline_10ms,
        'churn_sweep': churn_results,
    }


if __name__ == "__main__":
    results = main()e