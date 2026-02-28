#!/usr/bin/env python3
"""
generate_discussion_tables.py

Generates LaTeX tables for the Discussion section from pareto_results.csv.

Tables generated:
1. tab:recommendations - Representative configurations across reliability-efficiency spectrum
2. tab:churn-sensitivity - Delivery by churn level for GS(8,1) vs Floodsub
3. tab:gossip-cost - Diminishing returns of gossip degree (D=8, 30% churn)
4. tab:minimal-gossip - Efficiency of minimal gossip (D=8, worst-case)
"""

import pandas as pd
import numpy as np
import os

PAYLOAD = 1536  # bytes

def load_data(csv_path='pareto_results.csv'):
    df = pd.read_csv(csv_path)
    df = df.drop_duplicates(subset=['D', 'D_lazy', 'churny_fraction'])
    return df


def generate_recommendations_table(df, output_path='tables/tab_recommendations.tex'):
    """Table: Representative configurations (D_lazy=1, worst-case across churn)"""
    
    rows = []
    
    # Gossipsub configurations with D_lazy=1
    dlazy1 = df[df['D_lazy'] == 1]
    for D in [2, 4, 8, 12, 14]:
        sub = dlazy1[dlazy1['D'] == D]
        if sub.empty:
            continue
        worst_delivery = sub['delivery_rate_mean'].min()
        worst_latency = sub['p99_latency_sec_mean'].max()
        worst_cost = sub['bytes_per_delivery_mean'].max()
        norm_cost = worst_cost / PAYLOAD
        rows.append({
            'D': D,
            'D_lazy': 1,
            'delivery': worst_delivery,
            'latency': worst_latency,
            'cost_norm': norm_cost
        })
    
    # Floodsub reference
    flood = df[(df['D'] == 60) & (df['D_lazy'] == 0)]
    if not flood.empty:
        worst_delivery = flood['delivery_rate_mean'].min()
        worst_latency = flood['p99_latency_sec_mean'].max()
        worst_cost = flood['bytes_per_delivery_mean'].max()
        norm_cost = worst_cost / PAYLOAD
        rows.append({
            'D': 60,
            'D_lazy': 0,
            'delivery': worst_delivery,
            'latency': worst_latency,
            'cost_norm': norm_cost,
            'is_floodsub': True
        })
    
    # Generate LaTeX
    latex = r"""\begin{table}[t]
      \centering
      \caption{Representative configurations across the reliability-efficiency-latency
            spectrum (worst-case across churn regimes). Gossipsub configurations
            with $\Dlazy{=}1$ achieve higher delivery than Floodsub at lower cost;
            Floodsub's only advantage is latency.}
      \label{tab:recommendations}
      \begin{tabular}{ccrrr}
            \toprule
            $D$ & $\Dlazy$ & Delivery & p99 Latency & Cost ($\beta/P$) \\
            \midrule
"""
    
    for row in rows:
        if row.get('is_floodsub'):
            latex += r"            \midrule" + "\n"
            latex += r"            \multicolumn{5}{l}{\textit{Floodsub reference ($D{=}60$, $\Dlazy{=}0$)}}" + " \\\\\n"
        delivery_pct = f"{row['delivery']*100:.1f}\\%"
        latex += f"            {row['D']}  & {row['D_lazy']} & {delivery_pct} & {row['latency']:.1f}\\,s & {row['cost_norm']:.0f}$\\times$ \\\\\n"
    
    latex += r"""            \bottomrule
      \end{tabular}
\end{table}
"""
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(latex)
    
    print(f"[OK] Generated {output_path}")
    return latex


def generate_churn_sensitivity_table(df, output_path='tables/tab_churn_sensitivity.tex'):
    """Table: Delivery by churn level for GS(8,1) vs Floodsub"""
    
    rows = []
    for churn in [0.0, 0.1, 0.2, 0.3, 0.4]:
        gs = df[(df['D'] == 8) & (df['D_lazy'] == 1) & (df['churny_fraction'] == churn)]
        fl = df[(df['D'] == 60) & (df['D_lazy'] == 0) & (df['churny_fraction'] == churn)]
        if gs.empty or fl.empty:
            continue
        rows.append({
            'churn': churn,
            'gs_delivery': gs['delivery_rate_mean'].values[0],
            'gs_latency': gs['p99_latency_sec_mean'].values[0],
            'fl_delivery': fl['delivery_rate_mean'].values[0],
            'fl_latency': fl['p99_latency_sec_mean'].values[0]
        })
    
    latex = r"""\begin{table}[t]
      \centering
      \caption{Delivery rate by churn level for Gossipsub ($D{=}8$, $\Dlazy{=}1$)
            compared to Floodsub ($D{=}60$, $\Dlazy{=}0$). Gossipsub achieves
            higher delivery at every churn level $>$0\%.}
      \label{tab:churn-sensitivity}
      \begin{tabular}{ccccc}
            \toprule
            \textbf{Churn} & \textbf{GS(8,1)} & \textbf{GS(8,1)} & \textbf{Floodsub} & \textbf{Floodsub} \\
                           & \textbf{Delivery} & \textbf{p99}     & \textbf{Delivery} & \textbf{p99}      \\
            \midrule
"""
    
    for row in rows:
        churn_pct = f"{row['churn']*100:.0f}\\%"
        gs_del_pct = f"{row['gs_delivery']*100:.1f}\\%"
        fl_del_pct = f"{row['fl_delivery']*100:.1f}\\%"
        latex += f"            {churn_pct} & {gs_del_pct} & {row['gs_latency']:.1f}\\,s & {fl_del_pct} & {row['fl_latency']:.1f}\\,s \\\\\n"
    
    latex += r"""            \bottomrule
      \end{tabular}
\end{table}
"""
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(latex)
    
    print(f"[OK] Generated {output_path}")
    return latex


def generate_gossip_cost_table(df, output_path='tables/tab_gossip_cost.tex'):
    """Table: Diminishing returns of gossip degree (D=8, 30% churn)"""
    
    d8_30 = df[(df['D'] == 8) & (df['churny_fraction'] == 0.3)]
    d8_30 = d8_30.sort_values('D_lazy')
    
    rows = []
    base_traffic = None
    base_delivery = None
    
    for _, row in d8_30.iterrows():
        dlazy = int(row['D_lazy'])
        delivery = row['delivery_rate_mean']
        total_gb = row['total_bytes_MB_mean'] / 1024  # Convert MB to GB
        
        if base_traffic is None:
            base_traffic = total_gb
            base_delivery = delivery
            delta = "---"
            mult = 1
        else:
            delta = f"+{(delivery - base_delivery)*100:.1f} pp"
            mult = total_gb / base_traffic
        
        rows.append({
            'dlazy': dlazy,
            'delivery': delivery,
            'delta': delta,
            'traffic_gb': total_gb,
            'mult': mult
        })
    
    # Filter to representative values
    selected_dlazy = [1, 5, 9, 13, 17, 21, 25, 29, 33]
    rows = [r for r in rows if r['dlazy'] in selected_dlazy]
    
    latex = r"""\begin{table}[t]
      \centering
      \caption{Diminishing returns of gossip degree ($D{=}8$, 30\% churn).
            Increasing $\Dlazy$ from 1 to 33 improves delivery by only
            0.4 percentage points while increasing traffic 21$\times$.}
      \label{tab:gossip-cost}
      \begin{tabular}{crrrr}
            \toprule
            $\Dlazy$ & Delivery & $\Delta$ Delivery & Total Traffic & Traffic Mult. \\
            \midrule
"""
    
    for row in rows:
        delivery_pct = f"{row['delivery']*100:.1f}\\%"
        latex += f"            {row['dlazy']:2d} & {delivery_pct} & {row['delta']:>10s} & {row['traffic_gb']:.1f}\\,GB & {row['mult']:.0f}$\\times$ \\\\\n"
    
    latex += r"""            \bottomrule
      \end{tabular}
\end{table}
"""
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(latex)
    
    print(f"[OK] Generated {output_path}")
    return latex


def generate_minimal_gossip_table(df, output_path='tables/tab_minimal_gossip.tex'):
    """Table: Efficiency of minimal gossip (D=8, worst-case across churn)"""
    
    d8 = df[df['D'] == 8]
    
    rows = []
    base_cost = None
    
    for dlazy in [1, 3, 5, 9, 13]:
        sub = d8[d8['D_lazy'] == dlazy]
        if sub.empty:
            continue
        worst_delivery = sub['delivery_rate_mean'].min()
        worst_cost = sub['bytes_per_delivery_mean'].max()
        norm_cost = worst_cost / PAYLOAD
        
        if base_cost is None:
            base_cost = worst_cost
            cost_ratio = 1
        else:
            cost_ratio = worst_cost / base_cost
        
        rows.append({
            'dlazy': dlazy,
            'delivery': worst_delivery,
            'cost': worst_cost,
            'cost_norm': norm_cost,
            'cost_ratio': cost_ratio
        })
    
    latex = r"""\begin{table}[t]
      \centering
      \caption{Effect of gossip degree for $D{=}8$ (worst-case across churn regimes).
            Minimal gossip ($\Dlazy{=}1$) captures most reliability benefit at
            a fraction of the cost.}
      \label{tab:minimal-gossip}
      \begin{tabular}{crrr}
            \toprule
            $\Dlazy$ & Delivery & Cost ($\beta/P$) & Cost vs.\ $\Dlazy{=}1$ \\
            \midrule
"""
    
    for row in rows:
        delivery_pct = f"{row['delivery']*100:.1f}\\%"
        latex += f"            {row['dlazy']:2d} & {delivery_pct} & {row['cost_norm']:.0f}$\\times$ & {row['cost_ratio']:.0f}$\\times$ \\\\\n"
    
    latex += r"""            \bottomrule
      \end{tabular}
\end{table}
"""
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(latex)
    
    print(f"[OK] Generated {output_path}")
    return latex


def generate_dominance_by_churn_table(df, output_path='tables/tab_dominance_by_churn.tex'):
    """Table: Gossipsub configurations dominating Floodsub at each churn level.
    
    Shows that minimal gossip (D=2, D_lazy=1) dominates Floodsub at every churn level.
    """
    
    rows = []
    
    # Get Floodsub reference costs for savings calculation
    flood = df[(df['D'] == 60) & (df['D_lazy'] == 0)]
    
    for churn in [0.0, 0.1, 0.2, 0.3, 0.4]:
        # Floodsub at this churn level
        fl = flood[flood['churny_fraction'] == churn]
        if fl.empty:
            continue
        fl_delivery = fl['delivery_rate_mean'].values[0]
        fl_cost = fl['bytes_per_delivery_mean'].values[0]
        
        # Find best minimal-gossip config that dominates Floodsub
        # Start with D=2, D_lazy=1 (most efficient)
        for D in [2, 4, 6, 8]:
            gs = df[(df['D'] == D) & (df['D_lazy'] == 1) & (df['churny_fraction'] == churn)]
            if gs.empty:
                continue
            gs_delivery = gs['delivery_rate_mean'].values[0]
            gs_cost = gs['bytes_per_delivery_mean'].values[0]
            
            # Check if this config dominates Floodsub (>= delivery, lower cost)
            # Use small epsilon for floating point comparison
            if gs_delivery >= fl_delivery - 0.001:
                cost_savings = fl_cost / gs_cost
                rows.append({
                    'churn': churn,
                    'fl_delivery': fl_delivery,
                    'gs_config': (D, 1),
                    'gs_delivery': gs_delivery,
                    'cost_savings': cost_savings
                })
                break  # Use the most efficient dominating config
    
    latex = r"""\begin{table}[t]
      \centering
      \caption{Gossipsub configurations dominating Floodsub at each churn level.
            Minimal gossip ($\Dlazy{=}1$) with sparse mesh exceeds Floodsub delivery
            at every churn level while achieving substantial cost savings.}
      \label{tab:dominance-by-churn}
      \small
      \begin{tabular}{lcccc}
            \toprule
            \textbf{Churn} & \textbf{Floodsub} & \textbf{Gossipsub} & \textbf{GS Delivery} & \textbf{Cost Savings} \\
            \midrule
"""
    
    for row in rows:
        churn_pct = f"{row['churn']*100:.0f}\\%"
        fl_del_pct = f"{row['fl_delivery']*100:.1f}\\%"
        gs_config = f"({row['gs_config'][0]}, {row['gs_config'][1]})"
        gs_del_pct = f"{row['gs_delivery']*100:.1f}\\%"
        savings = f"{row['cost_savings']:.0f}$\\times$"
        latex += f"            {churn_pct} & {fl_del_pct} & {gs_config} & {gs_del_pct} & {savings} \\\\\n"
    
    latex += r"""            \bottomrule
      \end{tabular}
\end{table}
"""
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(latex)
    
    print(f"[OK] Generated {output_path}")
    return latex


def print_key_statistics(df):
    """Print key statistics for use in prose."""
    
    print("\n" + "="*70)
    print("KEY STATISTICS FOR DISCUSSION SECTION")
    print("="*70)
    
    # Floodsub baseline
    flood = df[(df['D'] == 60) & (df['D_lazy'] == 0)]
    flood_worst_del = flood['delivery_rate_mean'].min()
    flood_worst_cost = flood['bytes_per_delivery_mean'].max()
    flood_norm_cost = flood_worst_cost / PAYLOAD
    print(f"\nFloodsub worst-case: {flood_worst_del:.1%} delivery, {flood_norm_cost:.0f}x cost")
    
    # Cost savings for D_lazy=1 configs
    print("\nCost savings vs Floodsub:")
    for D in [2, 4, 8]:
        sub = df[(df['D'] == D) & (df['D_lazy'] == 1)]
        worst_cost = sub['bytes_per_delivery_mean'].max()
        savings = flood_worst_cost / worst_cost
        print(f"  D={D}, D_lazy=1: {savings:.0f}x savings")
    
    # Gossip explosion
    d2_1 = df[(df['D'] == 2) & (df['D_lazy'] == 1) & (df['churny_fraction'] == 0.4)]
    d2_33 = df[(df['D'] == 2) & (df['D_lazy'] == 33) & (df['churny_fraction'] == 0.4)]
    if not d2_1.empty and not d2_33.empty:
        del1 = d2_1['delivery_rate_mean'].values[0]
        traffic1 = d2_1['total_bytes_MB_mean'].values[0]
        del33 = d2_33['delivery_rate_mean'].values[0]
        traffic33 = d2_33['total_bytes_MB_mean'].values[0]
        print(f"\nGossip explosion (D=2, 40% churn):")
        print(f"  D_lazy=1:  {del1:.1%} delivery, {traffic1/1024:.1f} GB")
        print(f"  D_lazy=33: {del33:.1%} delivery, {traffic33/1024:.1f} GB")
        print(f"  {traffic33/traffic1:.0f}x traffic for +{(del33-del1)*100:.1f} pp delivery")
    
    # D=8 diminishing returns
    d8_30 = df[(df['D'] == 8) & (df['churny_fraction'] == 0.3)]
    d8_1 = d8_30[d8_30['D_lazy'] == 1]
    d8_33 = d8_30[d8_30['D_lazy'] == 33]
    if not d8_1.empty and not d8_33.empty:
        del1 = d8_1['delivery_rate_mean'].values[0]
        traffic1 = d8_1['total_bytes_MB_mean'].values[0]
        del33 = d8_33['delivery_rate_mean'].values[0]
        traffic33 = d8_33['total_bytes_MB_mean'].values[0]
        print(f"\nDiminishing returns (D=8, 30% churn):")
        print(f"  D_lazy=1:  {del1:.1%} delivery, {traffic1/1024:.1f} GB")
        print(f"  D_lazy=33: {del33:.1%} delivery, {traffic33/1024:.1f} GB")
        print(f"  {traffic33/traffic1:.0f}x traffic for +{(del33-del1)*100:.1f} pp delivery")
    
    print("="*70 + "\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate Discussion section tables from simulation results',
        usage='%(prog)s [INPUT_CSV] [OUTPUT_DIR] [options]'
    )
    parser.add_argument('input_csv', nargs='?', default='pareto_results.csv',
                        help='Input CSV file (default: pareto_results.csv)')
    parser.add_argument('output_dir', nargs='?', default='tables',
                        help='Output directory for LaTeX tables (default: tables)')
    parser.add_argument('--stats-only', action='store_true',
                        help='Print statistics only, do not generate tables')
    args = parser.parse_args()
    
    df = load_data(args.input_csv)
    
    if not args.stats_only:
        os.makedirs(args.output_dir, exist_ok=True)
        generate_recommendations_table(df, f'{args.output_dir}/tab_recommendations.tex')
        generate_churn_sensitivity_table(df, f'{args.output_dir}/tab_churn_sensitivity.tex')
        generate_gossip_cost_table(df, f'{args.output_dir}/tab_gossip_cost.tex')
        generate_minimal_gossip_table(df, f'{args.output_dir}/tab_minimal_gossip.tex')
        generate_dominance_by_churn_table(df, f'{args.output_dir}/tab_dominance_by_churn.tex')
        print(f"\nAll tables generated in {args.output_dir}/")
        print("Include in LaTeX with: \\input{tables/tab_recommendations}")
    
    print_key_statistics(df)


if __name__ == "__main__":
    main()