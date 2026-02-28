#!/usr/bin/env python3
"""
Plots showing delivery, cost, and latency as a function of D and D_lazy
with separate lines for each churn regime and confidence intervals.

Confidence intervals show the spread (std) across the other parameter dimension:
- For D plots: spread across different D_lazy values
- For D_lazy plots: spread across different D values

Updated to dynamically use available D values from the results CSV,
handling incomplete experimental data gracefully.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os

# ============================================================
# Configuration
# ============================================================

# Default DPI (can be overridden by command line)
DPI = 300

# Message payload size in bytes (aggregated attestation)
PAYLOAD_SIZE_BYTES = 1536

# FloodSub reference configuration
FLOODSUB_D = 60
FLOODSUB_D_LAZY = 0

# Churn regime colors (will be dynamically extended if needed)
CHURN_COLORS_BASE = {
    0.0: "#2ecc71",   # green
    0.1: "#3498db",   # blue  
    0.2: "#f39c12",   # orange
    0.3: "#e74c3c",   # red
    0.4: "#9b59b6",   # purple
    0.5: "#1abc9c",   # teal
    0.6: "#e67e22",   # dark orange
    0.7: "#c0392b",   # dark red
    0.8: "#8e44ad",   # dark purple
    0.9: "#27ae60",   # dark green
    1.0: "#2c3e50",   # navy
}


def get_churn_color(churn_val):
    """Get color for a churn value, with fallback for unexpected values."""
    if churn_val in CHURN_COLORS_BASE:
        return CHURN_COLORS_BASE[churn_val]
    # Generate a color based on the value
    cmap = plt.cm.viridis
    return cmap(churn_val)


def get_churn_label(churn_val):
    """Generate label for a churn value."""
    return f"{int(churn_val * 100)}% churn"


def compute_axis_limits(data_min, data_max, padding_frac=0.1, log_scale=False):
    """
    Compute axis limits with padding based on data range.
    
    Args:
        data_min: Minimum value in data
        data_max: Maximum value in data
        padding_frac: Fraction of range to add as padding (default 10%)
        log_scale: Whether the axis uses log scale
    
    Returns:
        (y_min, y_max) tuple
    """
    if log_scale:
        # For log scale, use multiplicative padding
        if data_min <= 0:
            data_min = data_max / 100  # Fallback for zero/negative values
        log_min = np.log10(data_min)
        log_max = np.log10(data_max)
        log_range = log_max - log_min
        padding = log_range * padding_frac
        return 10 ** (log_min - padding), 10 ** (log_max + padding)
    else:
        # For linear scale, use additive padding
        data_range = data_max - data_min
        if data_range == 0:
            data_range = abs(data_max) * 0.1 if data_max != 0 else 0.1
        padding = data_range * padding_frac
        return data_min - padding, data_max + padding


def compute_delivery_limits(all_delivery_values, padding_frac=0.05):
    """
    Compute delivery rate axis limits with padding for visibility.
    
    Allows y_max slightly above 1.00 for visual padding (so points at 1.0 are visible),
    but tick labels should be capped at 1.00 (handled separately in plotting code).
    
    Args:
        all_delivery_values: List/array of all delivery rate values
        padding_frac: Fraction of range to add as padding
    
    Returns:
        (y_min, y_max) tuple
    """
    data_min = np.min(all_delivery_values)
    data_max = np.max(all_delivery_values)
    
    y_min, y_max = compute_axis_limits(data_min, data_max, padding_frac, log_scale=False)
    
    # Cap minimum at 0
    y_min = max(0, y_min)
    
    # Allow visual padding above 1.0, but cap at 1.02 for aesthetics
    # (tick labels will be filtered to not show values > 1.0)
    y_max = min(1.02, max(y_max, data_max + 0.01))
    
    # Ensure we show at least some range
    if y_max - y_min < 0.05:
        y_min = max(0, data_min - 0.025)
        y_max = min(1.02, data_max + 0.02)
    
    return y_min, y_max


def set_delivery_axis(ax, ylim):
    """
    Set delivery rate axis with proper limits and tick labels capped at 1.00.
    
    Args:
        ax: matplotlib axis
        ylim: (y_min, y_max) tuple from compute_delivery_limits
    """
    ax.set_ylim(ylim)
    
    # Get current ticks and filter to show only values <= 1.0
    ax.set_ylabel("Delivery Rate")
    
    # Generate nice tick locations within the visible range, but exclude any > 1.0
    import matplotlib.ticker as ticker
    
    # Use automatic tick locator but filter labels
    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins='auto', steps=[1, 2, 2.5, 5, 10]))
    
    # Get the ticks and filter
    ax.figure.canvas.draw()
    ticks = [t for t in ax.get_yticks() if ylim[0] <= t <= 1.0]
    
    # Make sure 1.0 is included if data goes that high
    if ylim[1] >= 1.0 and 1.0 not in ticks:
        ticks.append(1.0)
    
    ticks = sorted(set(ticks))
    ax.set_yticks(ticks)
    ax.set_yticklabels([f'{t:.2f}' if t < 1 else '1.00' for t in ticks])


# ============================================================
# Load and validate data
# ============================================================

def load_data(csv_path):
    """Load data and provide summary of available configurations."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Results file not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    
    # Get unique values
    d_values = sorted(df["D"].unique())
    d_lazy_values = sorted(df["D_lazy"].unique())
    churn_values = sorted(df["churny_fraction"].unique())
    
    print(f"[INFO] Loaded {len(df)} configurations from {csv_path}")
    print(f"       D values: {d_values}")
    print(f"       D_lazy values: {d_lazy_values}")
    print(f"       Churn values: {churn_values}")
    
    # Check for FloodSub reference
    df_flood = df[(df["D"] == FLOODSUB_D) & (df["D_lazy"] == FLOODSUB_D_LAZY)]
    if df_flood.empty:
        print(f"[WARN] No FloodSub reference data (D={FLOODSUB_D}, D_lazy={FLOODSUB_D_LAZY})")
    else:
        print(f"       FloodSub reference: {len(df_flood)} configs")
    
    return df


def get_complete_configs(df, group_col, other_col, min_other_count=1):
    """
    Find configurations that have sufficient data across the other dimension.
    
    Args:
        df: DataFrame
        group_col: Column to group by (e.g., 'D')
        other_col: Other parameter column (e.g., 'D_lazy')
        min_other_count: Minimum number of unique other values required
    
    Returns:
        List of values in group_col that have sufficient data
    """
    counts = df.groupby(group_col)[other_col].nunique()
    return sorted(counts[counts >= min_other_count].index.tolist())


# ============================================================
# Figure 1: Effect of D by churn regime
# ============================================================

def plot_D_by_churn(df, outpath):
    """Plot delivery, cost, latency vs D with separate lines per churn regime.
    
    Confidence intervals show spread across D_lazy values.
    FloodSub reference (D=60) shown separately with visual break if available.
    """
    
    # Identify FloodSub vs GossipSub data
    df_flood = df[(df["D"] == FLOODSUB_D) & (df["D_lazy"] == FLOODSUB_D_LAZY)]
    df_main = df[~((df["D"] == FLOODSUB_D) & (df["D_lazy"] == FLOODSUB_D_LAZY))]
    
    # Get available D values (excluding FloodSub)
    available_D = sorted(df_main["D"].unique())
    churns = sorted(df["churny_fraction"].unique())
    
    if not available_D:
        print(f"[WARN] No GossipSub data available, skipping {outpath}")
        return
    
    print(f"[INFO] Plotting D by churn with D values: {available_D}")
    
    # Aggregate over D_lazy for each (D, churn) combination
    g_main = (
        df_main.groupby(["D", "churny_fraction"])
          .agg(
              delivery_mean=("delivery_rate_mean", "mean"),
              delivery_std=("delivery_rate_mean", "std"),
              delivery_min=("delivery_rate_mean", "min"),
              delivery_max=("delivery_rate_mean", "max"),
              latency_mean=("p99_latency_sec_mean", "mean"),
              latency_std=("p99_latency_sec_mean", "std"),
              latency_min=("p99_latency_sec_mean", "min"),
              latency_max=("p99_latency_sec_mean", "max"),
              bytes_mean=("bytes_per_delivery_mean", "mean"),
              bytes_std=("bytes_per_delivery_mean", "std"),
              bytes_min=("bytes_per_delivery_mean", "min"),
              bytes_max=("bytes_per_delivery_mean", "max"),
              config_count=("D", "count"),  # Track how many configs per point
          )
          .reset_index()
    )
    
    # FloodSub reference
    g_flood = None
    if not df_flood.empty:
        g_flood = (
            df_flood.groupby(["D", "churny_fraction"])
              .agg(
                  delivery_mean=("delivery_rate_mean", "mean"),
                  latency_mean=("p99_latency_sec_mean", "mean"),
                  bytes_mean=("bytes_per_delivery_mean", "mean"),
              )
              .reset_index()
        )
    
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=False)
    
    # Collect all data values for dynamic axis limits
    all_delivery = []
    all_cost = []
    all_latency = []
    
    # Determine x-axis layout
    max_D = max(available_D)
    has_floodsub = g_flood is not None and not g_flood.empty
    x_flood = -3 if has_floodsub else None  # Position for FloodSub reference
    
    for churn in churns:
        sub = g_main[g_main["churny_fraction"] == churn].sort_values("D")
        if sub.empty:
            continue
        
        # Collect data for axis limits
        all_delivery.extend(sub["delivery_min"].tolist())
        all_delivery.extend(sub["delivery_max"].tolist())
        all_cost.extend((sub["bytes_min"] / PAYLOAD_SIZE_BYTES).tolist())
        all_cost.extend((sub["bytes_max"] / PAYLOAD_SIZE_BYTES).tolist())
        all_latency.extend(sub["latency_min"].tolist())
        all_latency.extend(sub["latency_max"].tolist())
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                all_delivery.extend(sub_flood["delivery_mean"].tolist())
                all_cost.extend((sub_flood["bytes_mean"] / PAYLOAD_SIZE_BYTES).tolist())
                all_latency.extend(sub_flood["latency_mean"].tolist())
            
        color = get_churn_color(churn)
        label = get_churn_label(churn)
        
        Ds = sub["D"].values
        
        # (a) Delivery - error bars showing min/max across D_lazy choices
        y = sub["delivery_mean"].values
        y_lo = sub["delivery_min"].values
        y_hi = sub["delivery_max"].values
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[0].errorbar(Ds, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label, 
                        markersize=4, capsize=3, capthick=1)
        
        # FloodSub reference point
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[0].scatter([x_flood], sub_flood["delivery_mean"].values, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
        
        # (b) Normalized cost
        y = sub["bytes_mean"].values / PAYLOAD_SIZE_BYTES
        y_lo = sub["bytes_min"].values / PAYLOAD_SIZE_BYTES
        y_hi = sub["bytes_max"].values / PAYLOAD_SIZE_BYTES
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[1].errorbar(Ds, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label,
                        markersize=4, capsize=3, capthick=1)
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[1].scatter([x_flood], sub_flood["bytes_mean"].values / PAYLOAD_SIZE_BYTES, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
        
        # (c) p99 Latency
        y = sub["latency_mean"].values
        y_lo = sub["latency_min"].values
        y_hi = sub["latency_max"].values
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[2].errorbar(Ds, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label,
                        markersize=4, capsize=3, capthick=1)
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[2].scatter([x_flood], sub_flood["latency_mean"].values, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
    
    # Configure x-axis based on available data
    if has_floodsub:
        # Add visual break and FloodSub label
        for ax in axes:
            ax.axvline(-1, color='gray', linestyle=':', linewidth=1, alpha=0.5)
            ax.axvline(-0.5, color='gray', linestyle=':', linewidth=1, alpha=0.5)
        
        # Dynamic x-ticks based on available D values
        main_ticks = [d for d in available_D if d % 2 == 0 or len(available_D) <= 10]
        if not main_ticks:
            main_ticks = available_D
        
        for ax in axes:
            ax.set_xticks([x_flood] + main_ticks)
            ax.set_xticklabels([f'{FLOODSUB_D}\n(FloodSub)'] + [str(d) for d in main_ticks])
            ax.set_xlim(-5, max_D + 2)
        
        # Add FloodSub reference annotation
        axes[0].annotate(f'FloodSub\nreference\n($D$={FLOODSUB_D}, $D_{{lazy}}$={FLOODSUB_D_LAZY})',
                        xy=(x_flood, 0.75), xytext=(x_flood - 1, 0.55),
                        fontsize=8, ha='right', va='top',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow',
                                 edgecolor='gray', alpha=0.9))
    else:
        # No FloodSub, simpler x-axis
        for ax in axes:
            ax.set_xlim(min(available_D) - 1, max_D + 1)
    
    # Formatting with dynamic y-axis limits
    delivery_ylim = compute_delivery_limits(all_delivery)
    cost_ylim = compute_axis_limits(min(all_cost), max(all_cost), padding_frac=0.15, log_scale=True)
    latency_ylim = compute_axis_limits(min(all_latency), max(all_latency), padding_frac=0.15, log_scale=True)
    
    set_delivery_axis(axes[0], delivery_ylim)
    # Only show 90% threshold line if it's within the visible range
    if delivery_ylim[0] < 0.9 < delivery_ylim[1]:
        axes[0].axhline(0.9, ls="--", lw=0.8, color="gray", alpha=0.7)
    axes[0].set_title("(a) Delivery rate vs mesh degree $D$ (bars: range over $D_{lazy}$)")
    axes[0].legend(loc="lower right", fontsize=9)
    
    axes[1].set_ylabel(r"Normalized cost ($\beta / P$)")
    axes[1].set_yscale("log")
    axes[1].set_ylim(cost_ylim)
    axes[1].set_title("(b) Bandwidth cost vs mesh degree $D$")
    
    axes[2].set_ylabel("p99 Latency (s)")
    axes[2].set_xlabel("Mesh degree $D$")
    axes[2].set_yscale("log")
    axes[2].set_ylim(latency_ylim)
    axes[2].set_title("(c) Tail latency vs mesh degree $D$")
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(outpath) if os.path.dirname(outpath) else ".", exist_ok=True)
    plt.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close()
    print(f"[OK] Saved {outpath}")


# ============================================================
# Figure 2: Effect of D_lazy by churn regime
# ============================================================

def plot_Dlazy_by_churn(df, outpath):
    """Plot delivery, cost, latency vs D_lazy with separate lines per churn regime.
    
    Confidence intervals show spread across D values.
    FloodSub reference (D_lazy=0 with D=60) shown as separate reference point if available.
    """
    
    # Identify FloodSub vs GossipSub data
    df_flood = df[(df["D"] == FLOODSUB_D) & (df["D_lazy"] == FLOODSUB_D_LAZY)]
    df_main = df[~((df["D"] == FLOODSUB_D) & (df["D_lazy"] == FLOODSUB_D_LAZY))]
    
    # Filter to D_lazy >= 1 for main analysis (exclude D_lazy=0 except FloodSub)
    df_main = df_main[df_main["D_lazy"] >= 1]
    
    # Get available D_lazy values
    available_D_lazy = sorted(df_main["D_lazy"].unique())
    churns = sorted(df["churny_fraction"].unique())
    
    if not available_D_lazy:
        print(f"[WARN] No GossipSub data with D_lazy >= 1 available, skipping {outpath}")
        return
    
    print(f"[INFO] Plotting D_lazy by churn with D_lazy values: {available_D_lazy}")
    
    # Aggregate over D for each (D_lazy, churn) combination
    g_main = (
        df_main.groupby(["D_lazy", "churny_fraction"])
          .agg(
              delivery_mean=("delivery_rate_mean", "mean"),
              delivery_std=("delivery_rate_mean", "std"),
              delivery_min=("delivery_rate_mean", "min"),
              delivery_max=("delivery_rate_mean", "max"),
              latency_mean=("p99_latency_sec_mean", "mean"),
              latency_std=("p99_latency_sec_mean", "std"),
              latency_min=("p99_latency_sec_mean", "min"),
              latency_max=("p99_latency_sec_mean", "max"),
              bytes_mean=("bytes_per_delivery_mean", "mean"),
              bytes_std=("bytes_per_delivery_mean", "std"),
              bytes_min=("bytes_per_delivery_mean", "min"),
              bytes_max=("bytes_per_delivery_mean", "max"),
              config_count=("D_lazy", "count"),
          )
          .reset_index()
    )
    
    # FloodSub reference
    g_flood = None
    if not df_flood.empty:
        g_flood = (
            df_flood.groupby(["churny_fraction"])
              .agg(
                  delivery_mean=("delivery_rate_mean", "mean"),
                  latency_mean=("p99_latency_sec_mean", "mean"),
                  bytes_mean=("bytes_per_delivery_mean", "mean"),
              )
              .reset_index()
        )
    
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=False)
    
    # Collect all data values for dynamic axis limits
    all_delivery = []
    all_cost = []
    all_latency = []
    
    max_D_lazy = max(available_D_lazy)
    has_floodsub = g_flood is not None and not g_flood.empty
    x_flood = -3 if has_floodsub else None
    
    for churn in churns:
        sub = g_main[g_main["churny_fraction"] == churn].sort_values("D_lazy")
        if sub.empty:
            continue
        
        # Collect data for axis limits
        all_delivery.extend(sub["delivery_min"].tolist())
        all_delivery.extend(sub["delivery_max"].tolist())
        all_cost.extend((sub["bytes_min"] / PAYLOAD_SIZE_BYTES).tolist())
        all_cost.extend((sub["bytes_max"] / PAYLOAD_SIZE_BYTES).tolist())
        all_latency.extend(sub["latency_min"].tolist())
        all_latency.extend(sub["latency_max"].tolist())
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                all_delivery.extend(sub_flood["delivery_mean"].tolist())
                all_cost.extend((sub_flood["bytes_mean"] / PAYLOAD_SIZE_BYTES).tolist())
                all_latency.extend(sub_flood["latency_mean"].tolist())
            
        color = get_churn_color(churn)
        label = get_churn_label(churn)
        
        Dlazys = sub["D_lazy"].values
        
        # (a) Delivery - error bars showing min/max across D choices
        y = sub["delivery_mean"].values
        y_lo = sub["delivery_min"].values
        y_hi = sub["delivery_max"].values
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[0].errorbar(Dlazys, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label,
                        markersize=4, capsize=3, capthick=1)
        
        # FloodSub reference point
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[0].scatter([x_flood], sub_flood["delivery_mean"].values, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
        
        # (b) Normalized cost
        y = sub["bytes_mean"].values / PAYLOAD_SIZE_BYTES
        y_lo = sub["bytes_min"].values / PAYLOAD_SIZE_BYTES
        y_hi = sub["bytes_max"].values / PAYLOAD_SIZE_BYTES
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[1].errorbar(Dlazys, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label,
                        markersize=4, capsize=3, capthick=1)
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[1].scatter([x_flood], sub_flood["bytes_mean"].values / PAYLOAD_SIZE_BYTES, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
        
        # (c) p99 Latency
        y = sub["latency_mean"].values
        y_lo = sub["latency_min"].values
        y_hi = sub["latency_max"].values
        yerr = np.array([np.maximum(y - y_lo, 0), np.maximum(y_hi - y, 0)])
        axes[2].errorbar(Dlazys, y, yerr=yerr, fmt='o-', lw=1.5, color=color, label=label,
                        markersize=4, capsize=3, capthick=1)
        
        if has_floodsub:
            sub_flood = g_flood[g_flood["churny_fraction"] == churn]
            if not sub_flood.empty:
                axes[2].scatter([x_flood], sub_flood["latency_mean"].values, 
                              marker='*', s=120, color=color, edgecolors='black', 
                              linewidths=1.5, zorder=5)
    
    # Configure x-axis
    if has_floodsub:
        for ax in axes:
            ax.axvline(-1, color='gray', linestyle=':', linewidth=1, alpha=0.5)
            ax.axvline(-0.5, color='gray', linestyle=':', linewidth=1, alpha=0.5)
        
        # Dynamic x-ticks
        main_ticks = [d for d in available_D_lazy if d % 4 == 1 or len(available_D_lazy) <= 10]
        if not main_ticks:
            main_ticks = available_D_lazy
        
        for ax in axes:
            ax.set_xticks([x_flood] + main_ticks)
            ax.set_xticklabels(['FloodSub\n($D$=60)'] + [str(d) for d in main_ticks])
            ax.set_xlim(-5, max_D_lazy + 2)
        
        axes[0].annotate(f'FloodSub\nreference\n($D$={FLOODSUB_D}, $D_{{lazy}}$={FLOODSUB_D_LAZY})', 
                        xy=(x_flood, 0.75), xytext=(x_flood - 1, 0.55),
                        fontsize=8, ha='right', va='top',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', 
                                 edgecolor='gray', alpha=0.9))
    else:
        for ax in axes:
            ax.set_xlim(min(available_D_lazy) - 1, max_D_lazy + 1)
    
    # Formatting with dynamic y-axis limits
    delivery_ylim = compute_delivery_limits(all_delivery)
    cost_ylim = compute_axis_limits(min(all_cost), max(all_cost), padding_frac=0.15, log_scale=True)
    latency_ylim = compute_axis_limits(min(all_latency), max(all_latency), padding_frac=0.15, log_scale=True)
    
    set_delivery_axis(axes[0], delivery_ylim)
    if delivery_ylim[0] < 0.9 < delivery_ylim[1]:
        axes[0].axhline(0.9, ls="--", lw=0.8, color="gray", alpha=0.7)
    axes[0].set_title("(a) Delivery rate vs gossip degree $D_{lazy}$ (bars: range over $D$)")
    axes[0].legend(loc="lower right", fontsize=9)
    
    axes[1].set_ylabel(r"Normalized cost ($\beta / P$)")
    axes[1].set_yscale("log")
    axes[1].set_ylim(cost_ylim)
    axes[1].set_title("(b) Bandwidth cost vs gossip degree $D_{lazy}$")
    
    axes[2].set_ylabel("p99 Latency (s)")
    axes[2].set_xlabel("Gossip degree $D_{lazy}$")
    axes[2].set_yscale("log")
    axes[2].set_ylim(latency_ylim)
    axes[2].set_title("(c) Tail latency vs gossip degree $D_{lazy}$")
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(outpath) if os.path.dirname(outpath) else ".", exist_ok=True)
    plt.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close()
    print(f"[OK] Saved {outpath}")


# ============================================================
# Figure 3: Effect of D for fixed D_lazy
# ============================================================

def plot_D_fixed_Dlazy(df, dlazy_val, outpath):
    """Plot metrics vs D for a fixed D_lazy value, per churn regime.
    
    No confidence intervals since each point is a single configuration.
    Skips if insufficient data available.
    """
    
    sub_df = df[df["D_lazy"] == dlazy_val]
    
    if sub_df.empty:
        print(f"[WARN] No data available for D_lazy={dlazy_val}, skipping {outpath}")
        return
    
    available_D = sorted(sub_df["D"].unique())
    churns = sorted(sub_df["churny_fraction"].unique())
    
    print(f"[INFO] Plotting D for fixed D_lazy={dlazy_val}, D values: {available_D}")
    
    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)
    
    # Collect all data values for dynamic axis limits
    all_delivery = []
    all_cost = []
    all_latency = []
    
    for churn in churns:
        sub = sub_df[sub_df["churny_fraction"] == churn].sort_values("D")
        if sub.empty:
            continue
        
        # Collect data for axis limits
        all_delivery.extend(sub["delivery_rate_mean"].tolist())
        all_cost.extend((sub["bytes_per_delivery_mean"] / PAYLOAD_SIZE_BYTES).tolist())
        all_latency.extend(sub["p99_latency_sec_mean"].tolist())
            
        color = get_churn_color(churn)
        label = get_churn_label(churn)
        
        Ds = sub["D"].values
        
        # (a) Delivery
        y = sub["delivery_rate_mean"].values
        axes[0].plot(Ds, y, lw=2, color=color, label=label, marker='o', markersize=5)
        
        # (b) Normalized cost
        y = sub["bytes_per_delivery_mean"].values / PAYLOAD_SIZE_BYTES
        axes[1].plot(Ds, y, lw=2, color=color, label=label, marker='o', markersize=5)
        
        # (c) p99 Latency
        y = sub["p99_latency_sec_mean"].values
        axes[2].plot(Ds, y, lw=2, color=color, label=label, marker='o', markersize=5)
    
    # Formatting with dynamic y-axis limits
    delivery_ylim = compute_delivery_limits(all_delivery)
    cost_ylim = compute_axis_limits(min(all_cost), max(all_cost), padding_frac=0.15, log_scale=True)
    latency_ylim = compute_axis_limits(min(all_latency), max(all_latency), padding_frac=0.15, log_scale=True)
    
    set_delivery_axis(axes[0], delivery_ylim)
    if delivery_ylim[0] < 0.9 < delivery_ylim[1]:
        axes[0].axhline(0.9, ls="--", lw=0.8, color="gray", alpha=0.7)
    if 8 in available_D or (min(available_D) < 8 < max(available_D)):
        axes[0].axvline(8, ls=":", lw=1, color="darkred", alpha=0.7, label="Ethereum $D=8$")
    axes[0].set_title(f"(a) Delivery rate vs $D$ (fixed $D_{{lazy}}={dlazy_val}$)")
    axes[0].legend(loc="lower right", fontsize=9)
    
    axes[1].set_ylabel(r"Normalized cost ($\beta / P$)")
    axes[1].set_yscale("log")
    axes[1].set_ylim(cost_ylim)
    if 8 in available_D or (min(available_D) < 8 < max(available_D)):
        axes[1].axvline(8, ls=":", lw=1, color="darkred", alpha=0.7)
    axes[1].set_title(f"(b) Bandwidth cost vs $D$ (fixed $D_{{lazy}}={dlazy_val}$)")
    
    axes[2].set_ylabel("p99 Latency (s)")
    axes[2].set_xlabel("Mesh degree $D$")
    axes[2].set_yscale("log")
    axes[2].set_ylim(latency_ylim)
    if 8 in available_D or (min(available_D) < 8 < max(available_D)):
        axes[2].axvline(8, ls=":", lw=1, color="darkred", alpha=0.7)
    axes[2].set_title(f"(c) Tail latency vs $D$ (fixed $D_{{lazy}}={dlazy_val}$)")
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(outpath) if os.path.dirname(outpath) else ".", exist_ok=True)
    plt.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close()
    print(f"[OK] Saved {outpath}")


# ============================================================
# Figure 4: Effect of D_lazy for fixed D
# ============================================================

def plot_Dlazy_fixed_D(df, d_val, outpath):
    """Plot metrics vs D_lazy for a fixed D value, per churn regime.
    
    No confidence intervals since each point is a single configuration.
    Skips if insufficient data available.
    """
    
    sub_df = df[df["D"] == d_val]
    
    if sub_df.empty:
        print(f"[WARN] No data available for D={d_val}, skipping {outpath}")
        return
    
    available_D_lazy = sorted(sub_df["D_lazy"].unique())
    churns = sorted(sub_df["churny_fraction"].unique())
    
    print(f"[INFO] Plotting D_lazy for fixed D={d_val}, D_lazy values: {available_D_lazy}")
    
    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)
    
    # Collect all data values for dynamic axis limits
    all_delivery = []
    all_cost = []
    all_latency = []
    
    for churn in churns:
        sub = sub_df[sub_df["churny_fraction"] == churn].sort_values("D_lazy")
        if sub.empty:
            continue
        
        # Collect data for axis limits
        all_delivery.extend(sub["delivery_rate_mean"].tolist())
        all_cost.extend((sub["bytes_per_delivery_mean"] / PAYLOAD_SIZE_BYTES).tolist())
        all_latency.extend(sub["p99_latency_sec_mean"].tolist())
            
        color = get_churn_color(churn)
        label = get_churn_label(churn)
        
        Dlazys = sub["D_lazy"].values
        
        # (a) Delivery
        y = sub["delivery_rate_mean"].values
        axes[0].plot(Dlazys, y, lw=2, color=color, label=label, marker='o', markersize=5)
        
        # (b) Normalized cost
        y = sub["bytes_per_delivery_mean"].values / PAYLOAD_SIZE_BYTES
        axes[1].plot(Dlazys, y, lw=2, color=color, label=label, marker='o', markersize=5)
        
        # (c) p99 Latency
        y = sub["p99_latency_sec_mean"].values
        axes[2].plot(Dlazys, y, lw=2, color=color, label=label, marker='o', markersize=5)
    
    # Formatting with dynamic y-axis limits
    delivery_ylim = compute_delivery_limits(all_delivery)
    cost_ylim = compute_axis_limits(min(all_cost), max(all_cost), padding_frac=0.15, log_scale=True)
    latency_ylim = compute_axis_limits(min(all_latency), max(all_latency), padding_frac=0.15, log_scale=True)
    
    set_delivery_axis(axes[0], delivery_ylim)
    if delivery_ylim[0] < 0.9 < delivery_ylim[1]:
        axes[0].axhline(0.9, ls="--", lw=0.8, color="gray", alpha=0.7)
    axes[0].set_title(f"(a) Delivery rate vs $D_{{lazy}}$ (fixed $D={d_val}$)")
    axes[0].legend(loc="lower right", fontsize=9)
    
    axes[1].set_ylabel(r"Normalized cost ($\beta / P$)")
    axes[1].set_yscale("log")
    axes[1].set_ylim(cost_ylim)
    axes[1].set_title(f"(b) Bandwidth cost vs $D_{{lazy}}$ (fixed $D={d_val}$)")
    
    axes[2].set_ylabel("p99 Latency (s)")
    axes[2].set_xlabel("Gossip degree $D_{lazy}$")
    axes[2].set_yscale("log")
    axes[2].set_ylim(latency_ylim)
    axes[2].set_title(f"(c) Tail latency vs $D_{{lazy}}$ (fixed $D={d_val}$)")
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(outpath) if os.path.dirname(outpath) else ".", exist_ok=True)
    plt.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close()
    print(f"[OK] Saved {outpath}")


# ============================================================
# Main
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate churn regime plots from simulation results',
        usage='%(prog)s [INPUT_CSV] [OUTPUT_DIR] [options]'
    )
    parser.add_argument('input_csv', nargs='?', default='pareto_results.csv',
                        help='Input CSV file (default: pareto_results.csv)')
    parser.add_argument('output_dir', nargs='?', default='plots',
                        help='Output directory for plots (default: plots)')
    parser.add_argument('--dpi', type=int, default=300,
                        help='DPI for output plots (default: 300)')
    parser.add_argument('--fixed-dlazy', type=int, default=None,
                        help='Fixed D_lazy value for D sweep plot (default: auto-detect)')
    parser.add_argument('--fixed-d', type=int, default=None,
                        help='Fixed D value for D_lazy sweep plot (default: auto-detect)')
    args = parser.parse_args()
    
    # Update global DPI setting
    global DPI
    DPI = args.dpi
    
    # Load data
    df = load_data(args.input_csv)
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Get available parameter values for smart defaults
    available_D = sorted(df[df["D"] != FLOODSUB_D]["D"].unique())
    available_D_lazy = sorted(df[df["D_lazy"] != FLOODSUB_D_LAZY]["D_lazy"].unique())
    
    # General plots (aggregated across the other parameter)
    plot_D_by_churn(df, f"{args.output_dir}/fig_D_by_churn.png")
    plot_Dlazy_by_churn(df, f"{args.output_dir}/fig_Dlazy_by_churn.png")
    
    # Fixed parameter plots
    # Use command line args if provided, otherwise use smart defaults
    
    # D_lazy to fix for D sweep
    if args.fixed_dlazy is not None:
        fixed_dlazy = args.fixed_dlazy
    elif 9 in available_D_lazy:
        fixed_dlazy = 9  # Ethereum default
    elif available_D_lazy:
        # Pick the most common D_lazy value
        dlazy_counts = df[df["D_lazy"].isin(available_D_lazy)].groupby("D_lazy").size()
        fixed_dlazy = dlazy_counts.idxmax()
    else:
        fixed_dlazy = None
    
    # D to fix for D_lazy sweep
    if args.fixed_d is not None:
        fixed_d = args.fixed_d
    elif 8 in available_D:
        fixed_d = 8  # Ethereum default
    elif available_D:
        # Pick the most common D value
        d_counts = df[df["D"].isin(available_D)].groupby("D").size()
        fixed_d = d_counts.idxmax()
    else:
        fixed_d = None
    
    if fixed_dlazy is not None:
        plot_D_fixed_Dlazy(df, dlazy_val=fixed_dlazy, 
                          outpath=f"{args.output_dir}/fig_D_fixed_Dlazy{fixed_dlazy}.png")
    
    if fixed_d is not None:
        plot_Dlazy_fixed_D(df, d_val=fixed_d, 
                          outpath=f"{args.output_dir}/fig_Dlazy_fixed_D{fixed_d}.png")
    
    print(f"\n[OK] All churn regime plots generated in {args.output_dir}/")


if __name__ == "__main__":
    main()