# Lean Gossip: Simulation Framework

This repository contains the simulation framework for studying Gossipsub protocol parameter optimization under churn, as presented in the paper "Lean Gossip: Big Gains From Small Talk."

## Overview

The framework consists of three main components:
1. **meshsub.py** - Core Gossipsub protocol simulator
2. **pareto_sweep.py** - Parameter sweep for generating experimental data
3. **churn_regime_plots.py** & **dominance_plots.py** - Visualization and analysis tools

---

## meshsub.py: Core Simulator

### Description

`meshsub.py` implements a complete discrete-event simulator for the Gossipsub v1.0 protocol with Ethereum-realistic parameters. It models:

- **Eager-push mesh overlay** with configurable degree D
- **Lazy-pull gossip** with configurable degree D_lazy
- **Bimodal churn model** (stable + churny peers, based on Kiffer et al.)
- **Geographic regions** with realistic inter-region latencies
- **Token-bucket bandwidth constraints** (25 Mbps default per peer)
- **Message production** following Ethereum's attestation workload
- **IHAVE/IWANT protocol** for gossip-based recovery
- **Mesh maintenance** (GRAFT/PRUNE) via periodic heartbeats

### Key Features

- **Fine-grained timing**: 100ms tick resolution (configurable)
- **Heartbeat interval**: 1 second (10 ticks at default resolution)
- **Message cache (mcache)**: Maintains last 3 heartbeat rounds for gossip
- **Persistent delivery tracking**: Accurately measures delivery even when peers rejoin
- **Comprehensive metrics**: Delivery rate, latency (p50/p90/p99), bandwidth breakdown

### Usage Example

```python
from meshsub import MeshSubComplete

# Create simulator with Ethereum defaults
sim = MeshSubComplete(
    num_peers=1000,              # Network size
    tick_sec=0.1,                # 100ms ticks
    heartbeat_interval_sec=1.0,  # Heartbeat every 1 second
    peer_table_min=40,           # Min peer connections
    peer_table_max=80,           # Max peer connections
    D=8,                         # Eager mesh degree
    D_lazy=6,                    # Gossip degree
    validators_per_node=1,       # Validators per peer
    global_bandwidth_bps=25_000_000,  # 25 Mbps per peer
    msg_size_default=1536,       # 1.5 KiB message size
    churny_fraction=0.2,         # 20% churny peers
    churny_leave_rate=0.01,      # Leave probability per tick
    churny_rejoin_rate=0.05,     # Rejoin probability per tick
)

# Run simulation: 10,000 ticks measurement + 2,000 ticks warmup
sim.run(n_ticks=10000, warmup_ticks=2000, verbose=True)

# Print comprehensive report
sim.print_report()

# Get detailed statistics
stats = sim.get_stats()
print(f"Delivery rate: {stats['delivery_mean']:.1%}")
print(f"Total bandwidth: {stats['total_bytes']/1024/1024:.2f} MB")

# Get latency statistics
latency = sim.get_latency_statistics()
print(f"p99 latency: {latency['p99_latency_sec']:.2f}s")
```

### Configuration Parameters

#### Network Topology
- `num_peers`: Total network size (default: 200)
- `peer_table_min/max`: Peer connection bounds (40-80, Kiffer et al.)
- `D`: Target eager mesh degree (default: 8, Ethereum)
- `D_lazy`: Gossip degree for lazy pull (default: 6)

#### Timing
- `tick_sec`: Simulation tick duration (default: 0.1s = 100ms)
- `heartbeat_interval_sec`: Gossip heartbeat interval (default: 1.0s)

#### Workload
- `validators_per_node`: Validators per peer (default: 1)
  - Determines message production rate: 1 attestation per 384 seconds per validator
- `msg_size_default`: Message payload size (default: 1536 bytes)

#### Bandwidth
- `global_bandwidth_bps`: Per-peer upload capacity (default: 25 Mbps)

#### Churn Model
- `churny_fraction`: Fraction of churny peers (default: 0.2 = 20%)
- `stable_leave_rate`: Leave probability for stable peers (default: 0.0)
- `churny_leave_rate`: Leave probability per tick for churny peers (default: 0.01)
- `churny_rejoin_rate`: Rejoin probability per tick (default: 0.05)

#### Geographic Regions
- `region_names`: List of region labels (default: ['EU', 'US', 'Asia'])
- `region_fractions`: Distribution across regions (default: [0.3, 0.4, 0.3])

### Output Metrics

The simulator tracks:

1. **Delivery Rate**: Fraction of online peers who received each message
2. **Latency Statistics**: p50, p90, p99 message propagation delay
3. **Bandwidth Breakdown**:
   - Payload traffic (application messages)
   - Control traffic (IHAVE/IWANT/GRAFT/PRUNE)
   - Mesh maintenance vs. gossip overhead
4. **Churn Events**: Leaves and joins by peer type
5. **Drop Statistics**: Messages dropped due to bandwidth limits or offline peers

---

## pareto_sweep.py: Parameter Sweep

### Description

`pareto_sweep.py` performs exhaustive parameter sweeps over D (mesh degree) and D_lazy (gossip degree) across multiple churn regimes. It runs multiple random seeds per configuration to ensure statistical confidence.

### Usage

#### Basic Execution

```bash
# Full parameter sweep (default: 525 configurations × 3 seeds = 1,575 runs)
python pareto_sweep.py --output pareto_results.csv --workers 8
```

#### Quick Test Mode

```bash
# Reduced parameter space for testing
python pareto_sweep.py --quick --output test_results.csv
```

#### Custom Configuration

```bash
# Custom number of seeds and parallel workers
python pareto_sweep.py --seeds 5 --workers 12 --output results.csv
```

### Command-Line Arguments

- `--quick`: Use reduced parameter space (faster testing)
- `--seeds N`: Number of random seeds per configuration (default: 3)
- `--output FILE`: Output CSV filename (default: pareto_results.csv)
- `--workers N`: Number of parallel workers (default: 3)

### Parameter Ranges

#### Default (Full Sweep)
- **D**: [2, 4, 6, 8, 10, 12, 14] (7 values)
- **D_lazy**: [3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 33] (15 values)
- **Churn**: [0.0, 0.1, 0.2, 0.3, 0.4] (5 values)
- **Total**: 7 × 15 × 5 = **525 configurations**

#### Quick Mode
- **D**: [6, 8, 10]
- **D_lazy**: [6, 12]
- **Churn**: [0.0, 0.2]
- **Total**: 3 × 2 × 2 = **12 configurations**

### Output Format

The sweep generates a CSV file (`pareto_results.csv`) with columns:

#### Configuration Parameters
- `D`, `D_lazy`, `churny_fraction`, `num_seeds`

#### Primary Metrics (mean ± std across seeds)
- `delivery_rate_mean/std`: Fraction of messages delivered
- `p99_latency_sec_mean/std`: 99th percentile latency
- `bytes_per_delivery_mean/std`: Total bandwidth cost per successful delivery

#### Secondary Metrics
- `p50_latency_sec_mean/std`, `p90_latency_sec_mean/std`: Additional latency percentiles
- `payload_bytes_MB_mean/std`: Application payload traffic
- `control_bytes_MB_mean/std`: Protocol overhead (IHAVE/IWANT/GRAFT/PRUNE)
- `meshmnt_bytes_MB_mean/std`: Mesh maintenance traffic
- `gossip_bytes_MB_mean/std`: Gossip traffic
- `drops_peer_mean/std`: Drops due to bandwidth limits
- `drops_offline_mean/std`: Drops due to offline peers

### Resume Support

The script supports **resuming interrupted sweeps**:
- If `pareto_results.csv` exists, it reads completed configurations
- Skips already-completed (D, D_lazy, churn) tuples
- Appends new results to the existing file

```bash
# Initial run (interrupted after 100 configs)
python pareto_sweep.py --output pareto_results.csv --workers 8

# Resume from where it left off
python pareto_sweep.py --output pareto_results.csv --workers 8
# Will skip the 100 completed configs and continue
```

### Performance Notes

- **Single config runtime**: ~30-60 seconds (1000 peers, 10,000 ticks)
- **Full sweep**: ~4-8 hours with 8 workers
- **Memory**: ~500 MB per worker
- **Recommended workers**: Number of CPU cores - 1

---

## churn_regime_plots.py: Performance Analysis

### Description

`churn_regime_plots.py` generates performance plots showing how mesh degree (D) and gossip degree (D_lazy) affect delivery, bandwidth cost, and latency across different churn regimes.

### Usage

```bash
# Generate all plots from pareto_results.csv
python churn_regime_plots.py

# Use custom input/output paths
INPUT_CSV=my_results.csv OUTPUT_DIR=figures python churn_regime_plots.py
```

### Generated Figures

#### 1. Effect of D by Churn Regime (`fig_D_by_churn.png`)

Three subplots showing D (x-axis) vs. metrics (y-axis), with separate lines per churn level:
- **(a) Delivery Rate**: Shows diminishing returns of increasing D
- **(b) Normalized Cost**: Bandwidth cost (β/P) vs. D, log-scale y-axis
- **(c) Tail Latency (p99)**: Latency decreases with higher D

**Error bars**: Show range (min/max) across all D_lazy values at each D

**FloodSub reference**: If D=60, D_lazy=0 data exists, shown as separate reference point with visual break

#### 2. Effect of D_lazy by Churn Regime (`fig_Dlazy_by_churn.png`)

Three subplots showing D_lazy (x-axis) vs. metrics:
- **(a) Delivery Rate**: Gossip improves delivery under churn
- **(b) Normalized Cost**: Cost increases sharply with D_lazy
- **(c) Tail Latency (p99)**: Modest latency reduction with more gossip

**Error bars**: Show range across all D values at each D_lazy

#### 3. Effect of D for Fixed D_lazy (`fig_D_fixed_Dlazy9.png`)

Shows D sweep for a single D_lazy value (default: 9, Ethereum-like):
- Cleaner view without aggregation across D_lazy
- Ethernet's D=8 marked with vertical dashed line

#### 4. Effect of D_lazy for Fixed D (`fig_Dlazy_fixed_D8.png`)

Shows D_lazy sweep for a single D value (default: 8, Ethereum):
- Illustrates gossip's effectiveness at a realistic mesh degree

### Features

- **Dynamic axis limits**: Automatically adjusts y-axis ranges based on data
- **Delivery rate formatting**: Y-axis capped at 1.00 even if visual padding extends beyond
- **Log-scale axes**: Cost and latency use log scale for clarity
- **Churn color scheme**: Consistent colors across all plots
  - 0% churn: Green
  - 10%: Blue
  - 20%: Orange
  - 30%: Red
  - 40%: Purple
- **Graceful handling of incomplete data**: Skips plots if insufficient data available

### Customization

Environment variables:
```bash
# Custom input CSV
INPUT_CSV=custom_results.csv python churn_regime_plots.py

# Custom output directory
OUTPUT_DIR=my_figures python churn_regime_plots.py

# Both
INPUT_CSV=data.csv OUTPUT_DIR=plots python churn_regime_plots.py
```

---

## dominance_plots.py: Pareto Frontier Analysis

### Description

`dominance_plots.py` generates the Pareto dominance visualization showing that Gossipsub dominates Floodsub across delivery-cost tradeoffs.

### Usage

```bash
# Generate Pareto dominance plot
python dominance_plots.py
```

### Generated Figure

**`fig_pareto_dominance.png`**: Scatter plot showing:
- **X-axis**: Bytes per delivery (log scale)
- **Y-axis**: Delivery rate
- **Marker size**: Scaled by D_lazy (smaller = less gossip)
- **Marker opacity**: D_lazy ≤ 1 shown at full opacity, higher values de-emphasized

**Key elements**:
1. **GossipSub Pareto frontier**: Black line connecting non-dominated configurations
2. **FloodSub feasible region**: Red vertical band at D=60, D_lazy=0
3. **Annotations**: 
   - "Minimal gossip suffices" pointing to D_lazy=1 threshold
   - FloodSub characteristics (low latency, high cost, lower delivery)

### Interpretation

The plot demonstrates:
- **GossipSub (D=2, D_lazy=1)** achieves equivalent delivery to FloodSub at **29× lower cost**
- **Pareto frontier** shows configurations that are not dominated on both delivery and cost
- **Minimal gossip (D_lazy=1)** captures most reliability benefits
- **FloodSub** lies outside the efficient frontier despite maximal connectivity

### Output

Saved to `figs/fig_pareto_dominance.png` (directory created automatically)

---

## Complete Workflow Example

### 1. Run Parameter Sweep

```bash
# Full experimental sweep (takes 4-8 hours with 8 workers)
python pareto_sweep.py --seeds 3 --workers 8 --output pareto_results.csv
```

### 2. Generate Analysis Plots

```bash
# Generate churn regime analysis
python churn_regime_plots.py

# Generate Pareto dominance plot
python dominance_plots.py
```

### 3. Results

After execution, you'll have:
- `pareto_results.csv`: Raw experimental data (645 rows for full sweep)
- `plots/fig_D_by_churn.png`: D impact analysis
- `plots/fig_Dlazy_by_churn.png`: D_lazy impact analysis
- `plots/fig_D_fixed_Dlazy9.png`: D sweep for Ethereum's D_lazy
- `plots/fig_Dlazy_fixed_D8.png`: D_lazy sweep for Ethereum's D
- `figs/fig_pareto_dominance.png`: Pareto frontier visualization

---

## Dependencies

```bash
pip install numpy pandas matplotlib
```

### Required Python Packages
- `numpy`: Numerical operations and random sampling
- `pandas`: Data manipulation and CSV I/O
- `matplotlib`: Plotting and visualization

### Python Version
- Requires Python 3.7+ (uses dataclasses, type hints)

---
## Troubleshooting

### Issue: "No convergence" warnings during sweep
- **Cause**: Some configurations may not stabilize within 10,000 ticks
- **Solution**: Increase `n_ticks` in `pareto_sweep.py` (line 23) or warmup period

### Issue: Out of memory during parallel sweep
- **Cause**: Too many workers for available RAM
- **Solution**: Reduce `--workers` argument (each worker uses ~500 MB)

### Issue: Missing plots for certain D or D_lazy values
- **Cause**: Incomplete experimental data for those parameters
- **Solution**: Scripts gracefully skip missing data; check CSV for available configurations

### Issue: FloodSub reference not appearing in plots
- **Cause**: No D=60, D_lazy=0 configuration in results
- **Solution**: Add FloodSub to parameter sweep by including D=60, D_lazy=0 in ranges

---

## License

This simulation framework is released as open-source software accompanying the "Lean Gossip" paper. See repository for license details.

## Contact

For questions or issues, please open an issue on the GitHub repository or contact the authors.
