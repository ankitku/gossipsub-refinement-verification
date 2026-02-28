#!/usr/bin/env python3
"""
meshsub.py

Complete Ethereum-realistic MeshSub implementation integrating:
1. Fine-tick simulation (100ms ticks, tick_sec=0.1)
2. Heartbeat every 1 second (10 ticks)
3. Per-connection bandwidth (heterogeneous)
4. Per-peer global upload cap (25 Mbps default)
5. Auto-computed budgets from bandwidth_bps
6. validators_per_node → publish_rate
7. Token bucket production
8. Proper IHAVE/IWANT scheduling
9. Bimodal churn (Kiffer et al.)
10. Warmup + measurement periods
11. Geographic regions for realistic latencies (default: 30% EU, 40% US, 30% Asia)

Based on:
- Ethereum consensus specs
- Kiffer et al. (FC 2021): Bimodal churn, ~60 connections
- EIP-7870: Bandwidth requirements
- ProbeLab topology: Regional distribution

Delivery rate is computed as |R_m| / |V| where R_m is the set of peers that
received message m and V is the full network. This measures the fraction of
all peers that received each message, providing a network-wide view of
dissemination effectiveness.
"""

import math
import random
import statistics
from collections import defaultdict, deque, namedtuple
from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional
from enum import Enum
import time
import numpy as np

# Ethereum message sizes (bytes)
ATTESTATION_SIZE = 512
AGGREGATE_SIZE = 500
BEACON_BLOCK_SIZE = 131072
BLOB_SIZE = 131072
ID_SIZE = 32
IHAVE_OVERHEAD = 32
IWANT_OVERHEAD = 16
GRAFT_PRUNE_SIZE = 100

Message = namedtuple("Message", ["mid", "origin", "msg_type", "size_bytes", "t_produced"])


class PeerType(Enum):
    """Peer classification for bimodal churn"""
    STABLE = "stable"
    CHURNY = "churny"


class TokenBucket:
    """Token bucket for rate-limited production"""
    def __init__(self, rate_per_sec, burst):
        self.rate = float(rate_per_sec)
        self.burst = int(burst)
        self.tokens = float(burst)
    
    def refill(self, tick_sec: float):
        self.tokens = min(self.burst, self.tokens + self.rate * tick_sec)
    
    def consume(self, n: int = 1) -> bool:
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


@dataclass
class PeerState:
    """Complete peer state with Ethereum-realistic parameters"""
    def __init__(self, pid, validators_per_node, tick_sec, D, D_lazy,
                 global_bandwidth_bps, peer_type, leave_rate, rejoin_rate, region: str = ''):
        self.pid = pid
        self.validators_per_node = validators_per_node
        self.tick_sec = tick_sec
        self.peer_type = peer_type
        self.leave_rate = leave_rate
        self.rejoin_rate = rejoin_rate
        self.region = region  # Geographic region (e.g., 'EU', 'US', 'Asia')
        
        # Publish rate: validators per epoch (384s)
        # Each validator: 1 attestation per 384 sec
        self.publish_rate = float(validators_per_node) / 384.0
        
        # Token bucket with safety factor
        token_rate = self.publish_rate * 2.0
        token_burst = max(1, validators_per_node)
        self.token_bucket = TokenBucket(token_rate, token_burst)
        
        # Topology
        self.peer_table = set()     # All known peers (ambient discovery)
        self.mesh_eager = set()     # Eager mesh (D peers)
        self.mesh_lazy = set()      # Lazy mesh (D_lazy peers)
        
        # Message tracking
        self.seen = set()
        self.message_store = {}     # mid -> Message
        
        # mcache: Store messages from last N heartbeat rounds
        # mcache_history[round_number] = set of message IDs from that round
        # We keep last 3 rounds for gossip (mcache_gossip=3)
        self.mcache_history = deque(maxlen=5)  # Keep last 5 rounds total
        self.mcache_current_round = set()       # Messages added this round
        
        # Gossip parameters
        self.D = D
        self.D_lazy = D_lazy
        
        # Per-peer global upload cap (bytes per tick)
        self.global_bandwidth_bps = int(global_bandwidth_bps)
        self.global_bytes_per_tick = int((self.global_bandwidth_bps * self.tick_sec) / 8.0)

        # Token bucket for bandwidth
        global_bytes_per_sec = global_bandwidth_bps / 8

        self.bucket_size = global_bytes_per_sec   # maximum tokens (1 second worth)
        self.tokens = global_bytes_per_sec        # start full
        self.refill_rate = global_bytes_per_sec   # tokens added per second

        
        # Bandwidth accounting
        self.bytes_sent_payload = 0
        self.bytes_sent_control = 0
        self.bytes_sent_meshmnt = 0
        self.bytes_sent_gossip = 0
        
        # Churn tracking
        self.is_online = True
        self.num_leaves = 0
        self.num_joins = 0
    
    def add_to_mcache(self, msg_id):
        """Add message to current round's mcache"""
        self.mcache_current_round.add(msg_id)
    
    def advance_mcache_round(self):
        """
        Advance to next heartbeat round.
        Move current_round to history, start new round.
        """
        if self.mcache_current_round:
            self.mcache_history.append(self.mcache_current_round)
        self.mcache_current_round = set()
    
    def get_mcache_for_gossip(self, mcache_gossip_rounds=3):
        """
        Get message IDs from last N heartbeat rounds for gossiping.
        
        mcache_gossip_rounds: Number of recent rounds to gossip (default 3)
        Returns: set of message IDs from last N rounds
        """
        recent_rounds = list(self.mcache_history)[-mcache_gossip_rounds:]
        msg_ids = set()
        for round_msgs in recent_rounds:
            msg_ids.update(round_msgs)
        return msg_ids
    
    def refill_tokens(self):
        """Refill token bucket"""
        self.tokens = min(self.bucket_size,
                  self.tokens + self.refill_rate * self.tick_sec)



class MeshSubComplete:
    """
    Complete MeshSub simulator with Ethereum-realistic parameters.
    
    Key features:
    - Fine-grained ticks (100ms default)
    - Heartbeat every 1 second
    - Per-connection AND per-peer bandwidth limits
    - Auto-computed budgets from bandwidth_bps
    - Bimodal churn (stable + churny peers)
    - Proper IHAVE/IWANT scheduling
    - Warmup periods
    - Geographic regions for realistic inter-region latencies
    """
    
    def __init__(
        self,
        # Network size
        num_peers: int = 200,
        
        # Timing (fine-grained ticks)
        tick_sec: float = 0.01,              # 100ms ticks (Ethereum-realistic)
        heartbeat_interval_sec: float = 1.0,  # Heartbeat every 1 second
        
        # Topology
        peer_table_min: int = 40,           # Min peer table size
        peer_table_max: int = 80,           # Max peer table size (Kiffer: ~60 avg)
        D: int = 8,                         # Eager mesh degree (Ethereum)
        D_lazy: int = 6,                    # Lazy mesh degree (libp2p default)
        
        # Validators per node (affects publish_rate)
        validators_per_node: int = 1,
        
        # Bandwidth
        # Per-peer global upload cap (simplified model)
        global_bandwidth_bps: int = 25_000_000,    # 25 Mbps per peer
        
        # Message sizes
        msg_size_default: int = AGGREGATE_SIZE,    # 1.5 KiB default
        
        # Gossip parameters
        mcache_gossip: int = 3,
        
        # Bimodal churn (Kiffer et al.)
        churny_fraction: float = 0.2,
        stable_leave_rate: float = 0.0,     # 0 = stable peers never leave
        stable_rejoin_rate: float = 0.01,
        churny_leave_rate: float = 0.01,
        churny_rejoin_rate: float = 0.05,

        # Geographic regions (default: 3 regions, 30% EU, 40% US, 30% Asia)
        region_names: Optional[List[str]] = None,
        region_fractions: Optional[List[float]] = None,
    ):
        random.seed(42)
        np.random.seed(42)  # For reproducible region assignment
        
        self.num_peers = int(num_peers)
        self.tick_sec = float(tick_sec)
        self.heartbeat_ticks = int(heartbeat_interval_sec / tick_sec)  # e.g., 1.0/0.1 = 10 ticks
        self.peer_table_min = peer_table_min
        self.peer_table_max = peer_table_max
        self.D = D
        self.D_lazy = D_lazy
        self.validators_per_node = validators_per_node
        self.global_bandwidth_bps = global_bandwidth_bps
        self.msg_size_default = msg_size_default
        self.mcache_gossip = mcache_gossip
        self.churny_fraction = churny_fraction
        
        # Geographic regions setup
        self.region_names = region_names or ['EU', 'US', 'Asia']
        self.region_fractions = region_fractions or [0.3, 0.4, 0.3]
        assert len(self.region_names) == len(self.region_fractions), "Region names and fractions must match"
        assert abs(sum(self.region_fractions) - 1.0) < 1e-6, "Fractions must sum to 1.0"
        
        # Latency table: mean and std dev (seconds) between regions (one-way, symmetric)
        # Based on typical global RTT/2 with variance (30% of mean for std)
        self.latency_table = {
            ('EU', 'EU'): (0.030, 0.009),   # Intra-EU: 30ms mean, 9ms std
            ('EU', 'US'): (0.120, 0.036),   # EU-US: 120ms
            ('EU', 'Asia'): (0.220, 0.066), # EU-Asia: 220ms
            ('US', 'EU'): (0.120, 0.036),
            ('US', 'US'): (0.030, 0.009),   # Intra-US
            ('US', 'Asia'): (0.200, 0.060), # US-Asia: 200ms
            ('Asia', 'EU'): (0.220, 0.066),
            ('Asia', 'US'): (0.200, 0.060),
            ('Asia', 'Asia'): (0.040, 0.012), # Intra-Asia: 40ms
        }
        
        # Print configuration
        print(f"\n{'='*80}")
        print(f"MESHSUB COMPLETE - ETHEREUM-REALISTIC CONFIGURATION")
        print(f"{'='*80}")
        print(f"Network: {num_peers} peers")
        print(f"Timing: tick={tick_sec}s, heartbeat every {heartbeat_interval_sec}s ({self.heartbeat_ticks} ticks)")
        print(f"Topology: peer_table={peer_table_min}-{peer_table_max}, D={D}, D_lazy={D_lazy}")
        print(f"Validators: {validators_per_node} per node")
        print(f"Bandwidth: {global_bandwidth_bps/1_000_000:.0f} Mbps per peer (global cap only)")
        print(f"Message size: {msg_size_default} bytes")
        print(f"Gossip: mcache_gossip={mcache_gossip}")
        print(f"Churn: {churny_fraction:.0%} churny peers (bimodal)")
        print(f"Regions: {dict(zip(self.region_names, self.region_fractions))}")
        print(f"{'='*80}\n")
        
        # Auto-compute derived parameters
        epoch_sec = 384
        publish_rate = validators_per_node / epoch_sec
        global_bytes_per_tick = int((global_bandwidth_bps * tick_sec) / 8.0)
        
        print(f"\nAuto-computed:")
        print(f"  publish_rate = {validators_per_node}/{epoch_sec} = {publish_rate:.6f} msgs/sec")
        print(f"  global_bytes_per_tick = {global_bandwidth_bps:,} bps × {tick_sec}s / 8 = {global_bytes_per_tick:,} bytes/tick")
        print(f"  Effective send budget: {global_bytes_per_tick} bytes / {msg_size_default} bytes = {global_bytes_per_tick // msg_size_default} msgs/tick")
        print(f"{'='*80}\n")
        
        # Initialize peers with bimodal classification
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
        
        # Build peer tables (ambient peer discovery)
        peer_ids = list(range(num_peers))
        for i in peer_ids:
            table_size = random.randint(peer_table_min, peer_table_max)
            choices = set(random.sample([x for x in peer_ids if x != i], 
                                       min(table_size, len(peer_ids) - 1)))
            self.peers[i].peer_table = choices
        
        # Symmetrize peer tables
        for i in peer_ids:
            for j in list(self.peers[i].peer_table):
                if i not in self.peers[j].peer_table:
                    self.peers[j].peer_table.add(i)
        
        # Initial mesh seeding - ensure connected eager mesh overlay

        # Step 1: Randomly select all Eager (D) and Lazy (D_lazy) connections.
        # We do this first for Eager connections, then ensure symmetry.
        for i in peer_ids:
            p = self.peers[i]
            
            # Candidates for both eager and lazy mesh (all non-self peers in peer_table)
            candidates = list(p.peer_table)
            random.shuffle(candidates)
            
            # Select Eager Mesh (D)
            eager_candidates = candidates[:min(len(candidates), D)]
            p.mesh_eager = set(eager_candidates)
            
            # Select Lazy Mesh (D_lazy) from remaining peers
            non_eager = [n for n in candidates if n not in p.mesh_eager]
            random.shuffle(non_eager)
            p.mesh_lazy = set(non_eager[:min(len(non_eager), self.D_lazy)])
            
        # Step 2: Ensure Eager mesh connections are symmetrical.
        # This is CRITICAL for guaranteed eager mesh property.
        for i in peer_ids:
            p = self.peers[i]
            for nbr in list(p.mesh_eager):
                # If peer 'i' is eager with 'nbr', 'nbr' must be eager with 'i'.
                if i not in self.peers[nbr].mesh_eager:
                    self.peers[nbr].mesh_eager.add(i)
        
        
        # Event scheduling
        self.delivery_schedule = defaultdict(list)  # tick -> [(dest, sender, payload, is_control, size)]
        self.pending_iwants = defaultdict(list)     # tick -> [(requester, provider, mids)]
        
        # Online status
        self.online = {i: True for i in peer_ids}
        
        # Message tracking
        self.produced_messages = {}   # mid -> Message
        self.next_mid = 0
        self.tick = 0
        
        # Metrics
        self.churn_events = []
        self.warmup_complete = False

        # Latency tracking: msg_id -> {'pub_tick': int, 'deliveries': {peer_id: tick}}
        self.latency_tracker = {}

        # Drop counters (diagnostic)
        self.drops_peer = 0        # Dropped due to per-peer global bandwidth
        self.drops_offline = 0     # Dropped due to offline peers
        
        # PATCH: Persistent delivery tracking
        # This tracks which peers received which messages, independent of peer.seen
        # which gets cleared on rejoin. Used for accurate delivery measurement.
        self.delivered = defaultdict(set)  # mid -> set of peer_ids that received it
    
    def _rand_delay_ticks(self, sender: int, dest: int):
        """Random network delay based on regions: Normal(mu_rs, sigma_rs) clipped to >=0.01s"""
        if sender not in self.peers or dest not in self.peers:
            # Fallback to uniform if invalid
            delay_s = random.uniform(0.025, 0.025)
            return max(1, int(math.ceil(delay_s / self.tick_sec)))
        
        r_s = self.peers[sender].region
        r_d = self.peers[dest].region
        key = (r_s, r_d)
        if key not in self.latency_table:
            # Fallback
            delay_s = random.uniform(0.02, 0.2)
        else:
            mu, sigma = self.latency_table[key]
            delay_s = np.random.normal(mu, sigma)
            delay_s = max(0.01, delay_s)  # Clip to minimum realistic delay
        
        return max(1, int(math.ceil(delay_s / self.tick_sec)))
    
    def _new_mid(self):
        """Generate new message ID"""
        mid = self.next_mid
        self.next_mid += 1
        return mid
    
    def produce_step(self):
        """Production phase: Poisson-distributed message production"""
        for p in self.peers.values():
            if not self.online[p.pid]:
                continue
            
            # Poisson arrival
            p_prob = 1 - math.exp(-p.publish_rate * self.tick_sec)
            
            if random.random() < p_prob and p.token_bucket.consume(1):
                mid = self._new_mid()
                msg = Message(mid, p.pid, "attestation_aggr", self.msg_size_default, self.tick)

                self.produced_messages[mid] = msg

                # Track publication time for latency measurement
                self.latency_tracker[mid] = {
                    'pub_tick': self.tick,
                    'deliveries': {}
                }

                p.message_store[mid] = msg
                p.add_to_mcache(mid)  # Add to current round
                p.seen.add(mid)
                
                # Track delivery for the originator (R_m includes origin)
                self.delivered[mid].add(p.pid)
                
                # Eager forwarding to mesh_eager with network delay
                for nbr in p.mesh_eager:
                    if self.online.get(nbr, False):
                        dt = self._rand_delay_ticks(p.pid, nbr)
                        self.delivery_schedule[self.tick + dt].append(
                            (nbr, p.pid, msg, False, msg.size_bytes)
                        )
    
    def process_delivery(self):
        """Process scheduled deliveries arriving at current tick"""
        items = self.delivery_schedule.pop(self.tick, [])
        
        for dest, sender, payload, is_control, size in items:
            if not self.online.get(dest, False):
                continue
            
            if is_control:
                # Control message (IHAVE or IWANT)
                if payload.get("type") == "IHAVE":
                    # Receiver checks which IDs it wants
                    missing = [mid for mid in payload["ids"] 
                              if mid not in self.peers[dest].seen]
                    if missing:
                        # Schedule IWANT for next tick
                        self.pending_iwants[self.tick + 1].append((dest, sender, missing))
                
                elif payload.get("type") == "IWANT":
                    # Provider sends requested messages
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
                    # Recipient adds sender to their eager mesh
                    p = self.peers[dest]
                    graft_peer = payload["peer_id"]
                    if graft_peer in p.peer_table and self.online.get(graft_peer, False):
                        p.mesh_eager.add(graft_peer)
                        # Remove from lazy if present
                        p.mesh_lazy.discard(graft_peer)
                
                elif payload.get("type") == "PRUNE":
                    # Recipient removes sender from their eager mesh
                    p = self.peers[dest]
                    prune_peer = payload["peer_id"]
                    p.mesh_eager.discard(prune_peer)
            else:
                # Payload message
                if isinstance(payload, Message):
                    p = self.peers[dest]
                    if payload.mid in p.seen:
                        continue

                    p.seen.add(payload.mid)
                    p.message_store[payload.mid] = payload
                    p.add_to_mcache(payload.mid)  # Add to current round

                    # Track delivery persistently: R_m = {p : m delivered to p}
                    self.delivered[payload.mid].add(dest)

                    # Track latency: record first delivery time for this peer
                    if payload.mid in self.latency_tracker:
                        if dest not in self.latency_tracker[payload.mid]['deliveries']:
                            self.latency_tracker[payload.mid]['deliveries'][dest] = self.tick

                    # Forward to eager mesh (except sender)
                    for nbr in p.mesh_eager:
                        if nbr == sender or not self.online.get(nbr, False):
                            continue
                        dt = self._rand_delay_ticks(dest, nbr)
                        self.delivery_schedule[self.tick + dt].append(
                            (nbr, dest, payload, False, payload.size_bytes)
                        )
        
        # Process pending IWANTs scheduled for this tick
        pending = self.pending_iwants.pop(self.tick, [])
        if pending:
            # Group by (requester, provider) to batch
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
        """
        Heartbeat: IHAVE emission + mesh maintenance.
        
        Gossips messages from last mcache_gossip heartbeat rounds (default 3).
        After gossiping, advances to next round.
        """
        # IHAVE emission
        for pid, p in self.peers.items():
            if not self.online.get(pid, False):
                continue
            
            # Get messages from last mcache_gossip rounds (e.g., last 3 heartbeats)
            recent = list(p.get_mcache_for_gossip(self.mcache_gossip))
            if not recent:
                continue
            
            # Select gossip targets from lazy mesh
            lazy = list(p.mesh_lazy)
            if not lazy:
                continue
            
            # Apply gossip fraction
            random.shuffle(lazy)
            k = len(lazy)
            targets = lazy[:k] if k > 0 else []
            
            if not targets:
                continue
            
            # Send single IHAVE with all recent IDs to each target
            ctrl_size = IHAVE_OVERHEAD + len(recent) * ID_SIZE
            for nbr in targets:
                if not self.online.get(nbr, False):
                    continue
                dt = self._rand_delay_ticks(pid, nbr)
                self.delivery_schedule[self.tick + dt].append(
                    (nbr, pid, {"type": "IHAVE", "ids": recent}, True, ctrl_size)
                )
        
        # Advance mcache round for all peers (start new heartbeat round)
        for p in self.peers.values():
            p.advance_mcache_round()
        
        # Mesh maintenance
        for pid, p in self.peers.items():
            if not self.online.get(pid, False):
                continue
            
            # Remove offline peers from eager mesh
            p.mesh_eager = {n for n in p.mesh_eager if self.online.get(n, False)}
            
            # Replenish if below D - send GRAFT to new peers
            if len(p.mesh_eager) < p.D:
                need = p.D - len(p.mesh_eager)
                cands = list(p.peer_table - p.mesh_eager)
                cands = [c for c in cands if self.online.get(c, False)]
                random.shuffle(cands)
                for nbr in cands[:need]:
                    p.mesh_eager.add(nbr)
                    # Send GRAFT to nbr so they add us to their mesh_eager
                    dt = self._rand_delay_ticks(pid, nbr)
                    self.delivery_schedule[self.tick + dt].append(
                        (nbr, pid, {"type": "GRAFT", "peer_id": pid}, True, GRAFT_PRUNE_SIZE)
                    )
            
            # Prune if above D+2 - remove 2 random peers and send PRUNE
            if len(p.mesh_eager) > p.D + 2:
                excess = list(p.mesh_eager)
                random.shuffle(excess)
                to_prune = excess[:2]  # Remove 2 random peers
                for nbr in to_prune:
                    p.mesh_eager.discard(nbr)
                    # Send PRUNE to nbr so they remove us from their mesh_eager
                    dt = self._rand_delay_ticks(pid, nbr)
                    self.delivery_schedule[self.tick + dt].append(
                        (nbr, pid, {"type": "PRUNE", "peer_id": pid}, True, GRAFT_PRUNE_SIZE)
                    )
            
            # Recompute lazy mesh (non-eager peers)
            rest = [n for n in p.peer_table if n not in p.mesh_eager and self.online.get(n, False)]
            p.mesh_lazy = set(rest[:min(len(rest), self.D_lazy)])
    
    def send_accounting(self):

        # Check scheduled deliveries for next tick
        scheduled = list(self.delivery_schedule.get(self.tick + 1, []))
        new_sched = []
        
        for entry in scheduled:
            dest, sender, payload, is_control, size = entry
            
            # Check online status
            if not self.online.get(sender, False) or not self.online.get(dest, False):
                self.drops_offline += 1
                continue
                            
            sender_peer = self.peers[sender]

            # Token-bucket enforcement
            if sender_peer.tokens >= size:
                sender_peer.tokens -= size

                if is_control:
                    sender_peer.bytes_sent_control += size
                    # IHAVE/IWANT are gossip, GRAFT/PRUNE are mesh maintenance
                    if payload.get("type") in ("IHAVE", "IWANT"):
                        sender_peer.bytes_sent_gossip += size
                    else:
                        sender_peer.bytes_sent_meshmnt += size
                else:
                    sender_peer.bytes_sent_payload += size

                new_sched.append(entry)
            else:
                # Drop due to exhausted bandwidth tokens
                self.drops_peer += 1
        
        self.delivery_schedule[self.tick + 1] = new_sched
    
    def process_bimodal_churn(self):
        """Process bimodal churn: stable core + churny periphery"""
        # Leaves
        for pid, p in list(self.peers.items()):
            if not self.online[pid]:
                continue
            
            if random.random() < p.leave_rate:
                self.online[pid] = False
                p.num_leaves += 1
                p.is_online = False
                self.churn_events.append({
                    'tick': self.tick,
                    'peer': pid,
                    'type': p.peer_type.value,
                    'event': 'leave'
                })
                
                # Clear state
                p.mesh_eager.clear()
                p.mesh_lazy.clear()
        
        # Joins
        for pid, p in list(self.peers.items()):
            if self.online[pid]:
                continue
            
            if random.random() < p.rejoin_rate:
                self.online[pid] = True
                p.num_joins += 1
                p.is_online = True
                self.churn_events.append({
                    'tick': self.tick,
                    'peer': pid,
                    'type': p.peer_type.value,
                    'event': 'join'
                })
                
                # Clear state on rejoin
                # NOTE: p.seen is cleared here for protocol correctness (duplicate detection)
                # but self.delivered is NOT cleared, so delivery measurement remains accurate
                p.seen.clear()
                p.mcache_history.clear()
                p.mcache_current_round.clear()
                p.message_store.clear()
                p.mesh_eager.clear()
                p.mesh_lazy.clear()
    
    def step(self):
        """Execute one tick"""
        # 1. Refill tokens
        for p in self.peers.values():
            p.refill_tokens()
        
        # 2. Production
        self.produce_step()
        
        # 3. Process deliveries
        self.process_delivery()
        
        # 4. Churn
        self.process_bimodal_churn()
        
        # 5. Send accounting (enforce bandwidth limits)
        self.send_accounting()
        
        # 6. Heartbeat (every heartbeat_ticks)
        if (self.tick % self.heartbeat_ticks) == 0:
            self.heartbeat()
        
        self.tick += 1
    
    def run(self, n_ticks: int, warmup_ticks: int = 0, verbose: bool = False):
        """Run simulation with warmup period"""
        if warmup_ticks > 0:
            if verbose:
                print(f"Running warmup for {warmup_ticks} ticks...")
            for _ in range(warmup_ticks):
                self.step()
            
            # Reset metrics after warmup
            if verbose:
                print(f"Warmup complete. Resetting metrics...")
            for p in self.peers.values():
                p.bytes_sent_payload = 0
                p.bytes_sent_control = 0
                p.bytes_sent_meshmnt = 0
                p.bytes_sent_gossip = 0
            self.produced_messages = {}
            self.latency_tracker = {}
            self.churn_events = []
            self.drops_peer = 0
            self.drops_offline = 0
            self.tick = 0
            self.warmup_complete = True
            
            # Reset delivery tracker after warmup
            self.delivered = defaultdict(set)
        
        # Measurement period
        if verbose:
            print(f"Running measurement for {n_ticks} ticks...")
        
        start_time = time.time()
        for _ in range(n_ticks):
            self.step()
            
            if verbose and self.tick % 1000 == 0:
                stats = self.get_stats()
                online_count = sum(self.online.values())
                print(f"  Tick {self.tick}: "
                      f"Online={online_count}/{self.num_peers}, "
                      f"Published={stats['total_origin']}, "
                      f"Delivery={stats['delivery_mean']:.1%}")
        
        elapsed = time.time() - start_time
        if verbose:
            print(f"Completed in {elapsed:.2f}s\n")
        
        return elapsed
    
    def get_stats(self):
        """Get statistics - only count settled messages for accurate delivery"""
        total_origin = len(self.produced_messages)
        payload_bytes = sum(p.bytes_sent_payload for p in self.peers.values())
        meshmnt_bytes = sum(p.bytes_sent_meshmnt for p in self.peers.values())
        gossip_bytes = sum(p.bytes_sent_gossip for p in self.peers.values())
        control_bytes = meshmnt_bytes + gossip_bytes
        
        settled_msgs = self.produced_messages
        
        # Calculate delivery rate: |R_m| / |V|
        # R_m = set of peers that received message m (persistent delivery tracker)
        # |V| = total network size (self.num_peers)
        deliveries = []
        for mid, msg in settled_msgs.items():
            # Count peers that received this message
            delivered_to = self.delivered.get(mid, set())
            delivery_rate = len(delivered_to) / self.num_peers
            deliveries.append(delivery_rate)
        
        delivery_mean = statistics.mean(deliveries) if deliveries else 0.0
        
        # Churn breakdown
        stable_churn = sum(1 for e in self.churn_events if e['type'] == 'stable')
        churny_churn = sum(1 for e in self.churn_events if e['type'] == 'churny')
        
        # Peer status
        stable_peers = [p for p in self.peers.values() if p.peer_type == PeerType.STABLE]
        churny_peers = [p for p in self.peers.values() if p.peer_type == PeerType.CHURNY]
        stable_online = sum(1 for p in stable_peers if self.online[p.pid])
        churny_online = sum(1 for p in churny_peers if self.online[p.pid])
        
        # Region online breakdown
        region_online = {r: sum(1 for p in self.peers.values() if p.region == r and self.online[p.pid]) 
                         for r in self.region_names}
        
        return {
            'total_origin': total_origin,
            'payload_bytes': payload_bytes,
            'control_bytes': control_bytes,
            'meshmnt_bytes': meshmnt_bytes,
            'gossip_bytes': gossip_bytes,
            'total_bytes': payload_bytes + control_bytes,
            'payload_pct': (payload_bytes / (payload_bytes + control_bytes) * 100) if (payload_bytes + control_bytes) > 0 else 0,
            'control_pct': (control_bytes / (payload_bytes + control_bytes) * 100) if (payload_bytes + control_bytes) > 0 else 0,
            'delivery_mean': delivery_mean,  # Delivery of settled messages only
            'online_total': sum(self.online.values()),
            'stable_online': stable_online,
            'stable_total': len(stable_peers),
            'churny_online': churny_online,
            'churny_total': len(churny_peers),
            'region_online': region_online,
            'churn_events': len(self.churn_events),
            'stable_churn_events': stable_churn,
            'churny_churn_events': churny_churn,
            'drops_peer': self.drops_peer,
            'drops_offline': self.drops_offline,
            'drops_total': self.drops_peer + self.drops_offline,
        }

    def get_latency_statistics(self):
        """Calculate message latency statistics"""
        if not self.latency_tracker:
            return None

        all_latencies = []

        for msg_id, data in self.latency_tracker.items():
            pub_tick = data['pub_tick']
            deliveries = data['deliveries']

            if deliveries:
                # Calculate latency for each delivery (in ticks)
                msg_latencies = [tick - pub_tick for tick in deliveries.values()]
                all_latencies.extend(msg_latencies)

        if not all_latencies:
            return None

        # Convert ticks to seconds for more meaningful units
        tick_sec = self.tick_sec
        latencies_sec = [lat * tick_sec for lat in all_latencies]

        return {
            'avg_latency_ticks': np.mean(all_latencies),
            'median_latency_ticks': np.median(all_latencies),
            'min_latency_ticks': np.min(all_latencies),
            'max_latency_ticks': np.max(all_latencies),
            'p50_latency_ticks': np.percentile(all_latencies, 50),
            'p90_latency_ticks': np.percentile(all_latencies, 90),
            'p99_latency_ticks': np.percentile(all_latencies, 99),
            'std_latency_ticks': np.std(all_latencies),
            'avg_latency_sec': np.mean(latencies_sec),
            'median_latency_sec': np.median(latencies_sec),
            'p50_latency_sec': np.percentile(latencies_sec, 50),
            'p90_latency_sec': np.percentile(latencies_sec, 90),
            'p99_latency_sec': np.percentile(latencies_sec, 99),
            'total_deliveries': len(all_latencies),
            'total_messages': len(self.latency_tracker)
        }
    
    def print_report(self):
        """Print comprehensive report"""
        stats = self.get_stats()
        
        print("="*80)
        print("SIMULATION REPORT")
        print("="*80)
        
        print(f"\nNetwork Status:")
        print(f"  Online: {stats['online_total']}/{self.num_peers}")
        print(f"    Stable: {stats['stable_online']}/{stats['stable_total']} ({stats['stable_online']/stats['stable_total']*100:.1f}%)")
        print(f"  By Region: {stats['region_online']}")
        
        print(f"\nMessages:")
        print(f"  Published: {stats['total_origin']}")
        print(f"  Delivery rate: {stats['delivery_mean']:.3f} ({stats['delivery_mean']*100:.1f}%)")

        # Latency statistics
        latency = self.get_latency_statistics()
        if latency:
            print(f"\nLatency (99th percentile):")
            print(f"  99th percentile: {latency['p99_latency_sec']:.3f}s ({latency['p99_latency_ticks']:.1f} ticks)")
            print(f"  Average: {latency['avg_latency_sec']:.3f}s ({latency['avg_latency_ticks']:.1f} ticks)")
            print(f"  Median: {latency['median_latency_sec']:.3f}s ({latency['median_latency_ticks']:.1f} ticks)")
            print(f"  Total deliveries tracked: {latency['total_deliveries']:,}")
            print(f"  Messages tracked: {latency['total_messages']:,}")

        print(f"\nBandwidth:")
        print(f"  Payload: {stats['payload_bytes']/1024/1024:.2f} MB ({stats['payload_pct']:.1f}%)")
        print(f"  Control: {stats['control_bytes']/1024/1024:.2f} MB ({stats['control_pct']:.1f}%)")
        if stats['control_bytes'] > 0:
            meshmnt_pct = stats['meshmnt_bytes'] / stats['control_bytes'] * 100
            gossip_pct = stats['gossip_bytes'] / stats['control_bytes'] * 100
            print(f"    Mesh Maint: {stats['meshmnt_bytes']/1024/1024:.2f} MB ({meshmnt_pct:.1f}%)")
            print(f"    Gossip: {stats['gossip_bytes']/1024/1024:.2f} MB ({gossip_pct:.1f}%)")
        print(f"  Total: {stats['total_bytes']/1024/1024:.2f} MB")
        
        print(f"\nChurn:")
        print(f"  Total events: {stats['churn_events']}")
        print(f"  From stable: {stats['stable_churn_events']} ({stats['stable_churn_events']/stats['churn_events']*100 if stats['churn_events'] > 0 else 0:.1f}%)")
        print(f"  From churny: {stats['churny_churn_events']} ({stats['churny_churn_events']/stats['churn_events']*100 if stats['churn_events'] > 0 else 0:.1f}%)")
        
        print(f"\nDrops (Bandwidth Enforcement):")
        print(f"  Total: {stats['drops_total']:,}")
        if stats['drops_total'] > 0:
            print(f"    Per-peer global limit: {stats['drops_peer']:,} ({stats['drops_peer']/stats['drops_total']*100:.1f}%)")
            print(f"    Offline peers: {stats['drops_offline']:,} ({stats['drops_offline']/stats['drops_total']*100:.1f}%)")
            print()
            if stats['drops_peer'] > stats['drops_offline']:
                print(f"  → Per-peer global bandwidth is the bottleneck")
            elif stats['drops_offline'] > 0:
                print(f"  → Churn (offline peers) is the main issue")
        else:
            print(f"    No drops - bandwidth is sufficient")
        
        if stats['payload_pct'] > 50:
            print(f"\n✓ Payload > 50% - VALID")
        else:
            print(f"\n✗ Payload < 50% - Gossip overhead too high")
        
        print("="*80)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("ETHEREUM-REALISTIC MESHSUB COMPLETE SIMULATION")
    print("="*80)
    
    # Test 1: Home validator (25 Mbps, 1 validator)
    print("\n1. Home validator (25 Mbps, 1 validator):")
    sim = MeshSubComplete(
        num_peers=200,
        tick_sec=0.1,                    # 100ms ticks
        heartbeat_interval_sec=1.0,      # Heartbeat every 1 second
        peer_table_min=40,
        peer_table_max=80,
        D=8,
        D_lazy=6,
        validators_per_node=1,
        global_bandwidth_bps=25_000_000,  # 25 Mbps
        msg_size_default=1536,            # 1.5 KiB
        churny_fraction=0.0
    )
    
    sim.run(n_ticks=10000, warmup_ticks=2000, verbose=True)
    sim.print_report()
    
    # Test 2: Datacenter (100 Mbps, 10 validators)
    print("\n2. Datacenter (100 Mbps, 10 validators):")
    sim2 = MeshSubComplete(
        num_peers=200,
        validators_per_node=10,
        global_bandwidth_bps=100_000_000,  # 100 Mbps
        churny_fraction=0.2
    )
    
    sim2.run(n_ticks=10000, warmup_ticks=2000, verbose=True)
    sim2.print_report()