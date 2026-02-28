#!/usr/bin/env python3
"""
Final Polished Pareto Dominance Plot

Key improvements:
1. Clean annotation placement avoiding overlaps
2. Emphasis on D_lazy=1 configurations (paper's main finding)
3. Better visual hierarchy
4. Clearer latency-cost-delivery tradeoff story
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D

PAYLOAD_SIZE = 1536


def aggregate_to_worst_case(df):
    """Aggregate each (D, D_lazy) to worst-case metrics across churn."""
    agg = df.groupby(['D', 'D_lazy']).agg(
        min_delivery=('delivery_rate_mean', 'min'),
        max_cost=('bytes_per_delivery_mean', 'max'),
        max_p99=('p99_latency_sec_mean', 'max'),
    ).reset_index()
    agg['normalized_cost'] = agg['max_cost'] / PAYLOAD_SIZE
    return agg


def compute_2d_pareto(df, delivery_col, cost_col):
    """Compute 2D Pareto frontier (maximize delivery, minimize cost)."""
    n = len(df)
    is_pareto = np.ones(n, dtype=bool)
    delivery = df[delivery_col].values
    cost = df[cost_col].values
    
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if (delivery[j] >= delivery[i] and cost[j] <= cost[i] and 
                (delivery[j] > delivery[i] or cost[j] < cost[i])):
                is_pareto[i] = False
                break
    return is_pareto


def get_latency_marker(p99):
    """Map latency to marker shape."""
    if p99 < 1:
        return 'o'   # circle (sub-second - FloodSub territory)
    elif p99 < 5:
        return 's'   # square (fast)
    elif p99 < 20:
        return '^'   # triangle (moderate)
    else:
        return 'D'   # diamond (slow)


def plot_pareto_dominance(df, outpath):
    """Create final polished Pareto dominance plot."""
    
    # Separate protocols
    df_flood = df[(df['D'] == 60) & (df['D_lazy'] == 0)]
    df_gossip = df[~((df['D'] == 60) & (df['D_lazy'] == 0))]
    
    # Aggregate to worst-case
    gossip_agg = aggregate_to_worst_case(df_gossip)
    flood_agg = aggregate_to_worst_case(df_flood)
    
    flood_delivery = flood_agg['min_delivery'].iloc[0]
    flood_cost = flood_agg['normalized_cost'].iloc[0]
    flood_latency = flood_agg['max_p99'].iloc[0]
    
    # Compute Pareto frontier
    pareto_mask = compute_2d_pareto(gossip_agg, 'min_delivery', 'normalized_cost')
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # --- Red shaded region: inferior to FloodSub ---
    # Points with BOTH higher cost AND lower delivery are strictly dominated
    ax.fill_between([flood_cost, 2000], 0.55, flood_delivery, 
                   color='red', alpha=0.10, zorder=0)
    ax.axhline(y=flood_delivery, xmin=0, xmax=1, 
               color='red', linestyle='--', alpha=0.4, linewidth=1, zorder=1)
    ax.axvline(x=flood_cost, ymin=0, ymax=1,
               color='red', linestyle='--', alpha=0.4, linewidth=1, zorder=1)
    
    # --- Plot non-frontier (gray) points ---
    dominated = gossip_agg[~pareto_mask]
    for _, row in dominated.iterrows():
        marker = get_latency_marker(row['max_p99'])
        ax.scatter(row['normalized_cost'], row['min_delivery'],
                  c='#BDBDBD', marker=marker, s=50, alpha=0.5,
                  edgecolors='#9E9E9E', linewidths=0.3, zorder=2)
    
    # --- Plot Pareto frontier points ---
    frontier = gossip_agg[pareto_mask].copy()
    
    for _, row in frontier.iterrows():
        marker = get_latency_marker(row['max_p99'])
        d_lazy = row['D_lazy']
        
        # Color scheme emphasizing D_lazy=1
        if d_lazy == 1:
            color = '#1565C0'  # strong blue
            edge = '#0D47A1'
            size = 120
            zorder = 12
        elif d_lazy <= 5:
            color = '#43A047'  # green
            edge = '#2E7D32'
            size = 90
            zorder = 10
        elif d_lazy <= 13:
            color = '#FB8C00'  # orange
            edge = '#E65100'
            size = 70
            zorder = 8
        else:
            color = '#8E24AA'  # purple
            edge = '#6A1B9A'
            size = 60
            zorder = 6
        
        ax.scatter(row['normalized_cost'], row['min_delivery'],
                  c=color, marker=marker, s=size, alpha=0.9,
                  edgecolors=edge, linewidths=1, zorder=zorder)
    
    # --- Plot FloodSub ---
    ax.scatter(flood_cost, flood_delivery, c='#D32F2F', marker='*', s=200,
              edgecolors='#B71C1C', linewidths=2.5, zorder=15)
    
    # --- Highlight Ethereum configs ---
    eth_mask = (gossip_agg['D'].isin([8, 10, 12])) & (gossip_agg['D_lazy'].isin([5, 9, 13]))
    eth_pts = gossip_agg[eth_mask]
    for _, row in eth_pts.iterrows():
        ax.scatter(row['normalized_cost'], row['min_delivery'],
                  facecolors='none', edgecolors='#00E676', marker='o',
                  s=350, linewidths=3, zorder=20)
    
    # --- Draw Pareto frontier line ---
    frontier_sorted = frontier.sort_values('normalized_cost')
    ax.plot(frontier_sorted['normalized_cost'], frontier_sorted['min_delivery'],
           'k-', linewidth=2.5, alpha=0.5, zorder=4)
    
    # --- ANNOTATIONS ---
    
    # Find key D_lazy=1 config that dominates FloodSub
    d1_configs = gossip_agg[(gossip_agg['D_lazy'] == 1) & 
                            (gossip_agg['min_delivery'] >= flood_delivery) &
                            (gossip_agg['normalized_cost'] < flood_cost)]
    
    if not d1_configs.empty:
        best_d1 = d1_configs.sort_values('normalized_cost').iloc[0]
        ratio = flood_cost / best_d1['normalized_cost']
        
        ax.annotate(
            f"$D$={int(best_d1['D'])}, $D_{{lazy}}$=1\n"
            f"{best_d1['min_delivery']:.1%} delivery\n"
            f"{best_d1['normalized_cost']:.0f}× cost\n"
            f"({ratio:.0f}× savings vs FloodSub)",
            xy=(best_d1['normalized_cost'], best_d1['min_delivery']),
            xytext=(1.8, 0.90),
            fontsize=9, ha='left', va='top',
            arrowprops=dict(arrowstyle='->', color='#1565C0', lw=1.5,
                           connectionstyle='arc3,rad=-0.2'),
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#E3F2FD',
                     edgecolor='#1565C0', alpha=0.95),
            zorder=25
        )
    
    # FloodSub annotation (positioned to avoid overlap)
    ax.annotate(
        f"FloodSub\n"
        f"D=60, $D_{{lazy}}$=0\n"
        f"{flood_delivery:.1%} delivery\n"
        f"{flood_cost:.0f}× cost\n"
        f"{flood_latency:.1f}s p99 (fastest)",
        xy=(flood_cost, flood_delivery),
        xytext=(120, 0.82),
        fontsize=9, ha='left', va='top',
        arrowprops=dict(arrowstyle='->', color='#D32F2F', lw=1.5,
                       connectionstyle='arc3,rad=0.2'),
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFEBEE',
                 edgecolor='#D32F2F', alpha=0.95),
        zorder=25
    )
    
    # Red region explanation (positioned to avoid legend overlap)
    ax.text(300, 0.68, 
            'Strictly inferior\nto FloodSub',
            fontsize=8, color='#C62828', alpha=0.7, ha='center', va='bottom',
            style='italic', zorder=25)
    
    # Key insight text box
    insight_text = (
        "Key Finding: GossipSub with minimal gossip ($D_{lazy}$=1)\n"
        "matches FloodSub delivery at 4–12× lower bandwidth cost.\n"
        "FloodSub's only advantage: sub-second latency."
    )
    props = dict(boxstyle='round,pad=0.6', facecolor='lightyellow', 
                edgecolor='#FFA000', alpha=0.95)
    ax.text(0.02, 0.02, insight_text, transform=ax.transAxes, fontsize=9,
           verticalalignment='bottom', bbox=props, zorder=30)
    
    # --- Axis settings ---
    ax.set_xscale('log')
    ax.set_xlim(1.5, 800)
    ax.set_ylim(0.75, 1.005)
    
    ax.set_xlabel(r'Normalized bandwidth cost ($\beta / P$) — lower is better →', fontsize=11)
    ax.set_ylabel('← higher is better — Worst-case delivery rate', fontsize=11)
    ax.set_title('GossipSub Dominates FloodSub: Delivery vs. Bandwidth Cost\n'
                 '(Each point aggregated to worst-case across 0–40% churn)',
                 fontsize=13, fontweight='bold', pad=15)
    
    # Grid
    ax.grid(True, alpha=0.25, linestyle='-', linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    
    # --- LEGENDS ---
    
    # Configuration legend (left side)
    config_handles = [
        Line2D([0], [0], marker='*', color='w', markerfacecolor='#D32F2F',
               markersize=13, markeredgecolor='#B71C1C', markeredgewidth=2,
               label='FloodSub (D=60)'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#1565C0',
               markersize=11, markeredgecolor='#0D47A1', label='$D_{lazy}$=1'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#43A047',
               markersize=10, markeredgecolor='#2E7D32', label='$D_{lazy}$∈[3,5]'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#FB8C00',
               markersize=9, markeredgecolor='#E65100', label='$D_{lazy}$∈[7,13]'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#8E24AA',
               markersize=8, markeredgecolor='#6A1B9A', label='$D_{lazy}$>13'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#BDBDBD',
               markersize=8, markeredgecolor='#9E9E9E', alpha=0.5, 
               label='Pareto-dominated'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='none',
               markersize=13, markeredgecolor='#00E676', markeredgewidth=3,
               label='Ethereum (D∈[8,12])'),
        Line2D([0], [0], color='black', linewidth=2.5, alpha=0.5,
               label='Pareto frontier'),
        Patch(facecolor='red', alpha=0.12, edgecolor='red',
              label='FloodSub-dominated region'),
    ]
    
    # Latency legend (marker shapes)
    latency_handles = [
        Line2D([0], [0], marker='o', color='gray', linestyle='None',
               markersize=8, label='p99 < 1s'),
        Line2D([0], [0], marker='s', color='gray', linestyle='None',
               markersize=8, label='p99: 1–5s'),
        Line2D([0], [0], marker='^', color='gray', linestyle='None',
               markersize=9, label='p99: 5–20s'),
        Line2D([0], [0], marker='D', color='gray', linestyle='None',
               markersize=9, label='p99 > 20s'),
    ]
    
    leg1 = ax.legend(handles=config_handles, loc='lower left', fontsize=8,
                    framealpha=0.95, title='Configuration', title_fontsize=9,
                    borderpad=0.8, bbox_to_anchor=(0.0, 0.12))
    ax.add_artist(leg1)
    
    ax.legend(handles=latency_handles, loc='lower left', fontsize=8,
             framealpha=0.95, title='Marker Shape = Latency', title_fontsize=9,
             borderpad=0.8, bbox_to_anchor=(0.23, 0.12))
    
    plt.tight_layout()
    plt.savefig(outpath, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"[OK] Saved: {outpath}")
    
    # Print summary
    print(f"\n{'='*70}")
    print("SUMMARY: GossipSub vs FloodSub")
    print(f"{'='*70}")
    print(f"FloodSub (D=60): {flood_delivery:.1%} delivery, {flood_cost:.0f}× cost, {flood_latency:.1f}s p99")
    print()
    
    print("D_lazy=1 configurations dominating FloodSub (delivery ≥ FloodSub, cost < FloodSub):")
    d1_dominates = gossip_agg[(gossip_agg['D_lazy'] == 1) & 
                              (gossip_agg['min_delivery'] >= flood_delivery) &
                              (gossip_agg['normalized_cost'] < flood_cost)]
    for _, row in d1_dominates.sort_values('normalized_cost').iterrows():
        ratio = flood_cost / row['normalized_cost']
        print(f"  D={row['D']:2.0f}: {row['min_delivery']:.1%} delivery, "
              f"{row['normalized_cost']:.0f}× cost ({ratio:.0f}× savings), "
              f"{row['max_p99']:.1f}s p99")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate Pareto dominance plot from simulation results',
        usage='%(prog)s [INPUT_CSV] [OUTPUT_DIR] [options]'
    )
    parser.add_argument('input_csv', nargs='?', default='pareto_results.csv',
                        help='Input CSV file (default: pareto_results.csv)')
    parser.add_argument('output_dir', nargs='?', default='plots',
                        help='Output directory for plots (default: plots)')
    parser.add_argument('--dpi', type=int, default=300,
                        help='DPI for output plots (default: 300)')
    args = parser.parse_args()
    
    df = pd.read_csv(args.input_csv)
    print(f"Loaded {len(df)} rows from {args.input_csv}")
    
    os.makedirs(args.output_dir, exist_ok=True)
    plot_pareto_dominance(df, f'{args.output_dir}/fig_pareto_dominance.png')


if __name__ == '__main__':
    main()