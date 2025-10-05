import json
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec

def load_results(filename='performance_results.json'):
    """Load performance results from JSON file"""
    with open(filename, 'r') as f:
        return json.load(f)

def create_overhead_analysis_plot(results):
    """Create a detailed overhead analysis plot"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Communication Overhead Analysis', fontsize=16, fontweight='bold')
    
    # Extract latency data
    modes = ['local', 'pull', 'push']
    task_types = ['noop', 'cpu', 'sleep']
    colors = {'noop': '#3498db', 'cpu': '#2ecc71', 'sleep': '#e74c3c'}
    
    # Plot 1: Latency comparison by mode
    for task_idx, task_type in enumerate(task_types):
        latencies_by_mode = []
        for mode in modes:
            if mode in results and task_type in results[mode]:
                avg_latencies = [d['avg_latency'] * 1000 for d in results[mode][task_type]]
                latencies_by_mode.append(np.mean(avg_latencies) if avg_latencies else 0)
            else:
                latencies_by_mode.append(0)
        
        x = np.arange(len(modes)) + task_idx * 0.25
        ax1.bar(x, latencies_by_mode, 0.25, label=task_type.capitalize(), 
                color=colors[task_type], alpha=0.8)
    
    ax1.set_xlabel('Execution Mode', fontsize=12)
    ax1.set_ylabel('Average Latency (ms)', fontsize=12)
    ax1.set_title('Average Latency by Mode and Task Type', fontsize=14)
    ax1.set_xticks(np.arange(len(modes)) + 0.25)
    ax1.set_xticklabels(modes)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Overhead breakdown
    if 'local' in results and 'noop' in results['local']:
        baseline_latency = np.mean([d['avg_latency'] * 1000 for d in results['local']['noop']])
        
        overheads = {'pull': [], 'push': []}
        labels = []
        
        for task_type in task_types:
            for mode in ['pull', 'push']:
                if mode in results and task_type in results[mode]:
                    avg_latency = np.mean([d['avg_latency'] * 1000 for d in results[mode][task_type]])
                    overhead = avg_latency - baseline_latency
                    overheads[mode].append(max(0, overhead))
                else:
                    overheads[mode].append(0)
            labels.append(task_type.capitalize())
        
        x = np.arange(len(labels))
        width = 0.35
        
        ax2.bar(x - width/2, overheads['pull'], width, label='Pull Mode', color='#3498db', alpha=0.8)
        ax2.bar(x + width/2, overheads['push'], width, label='Push Mode', color='#e74c3c', alpha=0.8)
        
        ax2.set_xlabel('Task Type', fontsize=12)
        ax2.set_ylabel('Communication Overhead (ms)', fontsize=12)
        ax2.set_title('Communication Overhead vs Local Mode', fontsize=14)
        ax2.set_xticks(x)
        ax2.set_xticklabels(labels)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('overhead_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

def create_scaling_efficiency_plot(results):
    """Create detailed scaling efficiency analysis"""
    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.3)
    
    fig.suptitle('Scaling Efficiency Analysis', fontsize=16, fontweight='bold')
    
    # Plot 1: Throughput scaling
    ax1 = fig.add_subplot(gs[0, :])
    
    for mode in ['local', 'pull', 'push']:
        if mode in results and 'noop' in results[mode]:
            data = results[mode]['noop']
            processes = [d['num_workers'] for d in data]
            throughputs = [d['throughput'] for d in data]
            
            if len(processes) > 1:
                # Fit power law: throughput = a * processes^b
                log_processes = np.log(processes)
                log_throughputs = np.log(throughputs)
                coeffs = np.polyfit(log_processes, log_throughputs, 1)
                
                # Generate fitted line
                x_fit = np.linspace(min(processes), max(processes), 100)
                y_fit = np.exp(coeffs[1]) * x_fit ** coeffs[0]
                
                ax1.scatter(processes, throughputs, s=100, label=f'{mode.capitalize()} (scaling: {coeffs[0]:.2f})')
                ax1.plot(x_fit, y_fit, '--', alpha=0.5)

    ax1.set_xlabel('Number of Workers', fontsize=12)
    ax1.set_ylabel('Throughput (tasks/s)', fontsize=12)
    ax1.set_title('Throughput Scaling with Fitted Power Laws', fontsize=14)
    ax1.set_xscale('log')
    ax1.set_yscale('log')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Efficiency heatmap
    ax2 = fig.add_subplot(gs[1, 0])
    
    efficiency_data = []
    row_labels = []
    col_labels = ['No-op', 'CPU', 'I/O']
    
    for mode in ['local', 'pull', 'push']:
        row_data = []
        for task_type in ['noop', 'cpu', 'sleep']:
            if mode in results and task_type in results[mode] and len(results[mode][task_type]) > 1:
                data = results[mode][task_type]
                # Calculate efficiency as ratio of last to first throughput per process
                first = data[0]['throughput'] / data[0]['num_workers']
                last = data[-1]['throughput'] / data[-1]['num_workers']
                efficiency = (last / first) * 100
                row_data.append(efficiency)
            else:
                row_data.append(0)
        efficiency_data.append(row_data)
        row_labels.append(mode.capitalize())
    
    sns.heatmap(efficiency_data, annot=True, fmt='.1f', cmap='RdYlGn', 
                xticklabels=col_labels, yticklabels=row_labels, 
                cbar_kws={'label': 'Efficiency (%)'}, ax=ax2, center=100)
    ax2.set_title('Scaling Efficiency by Mode and Task Type', fontsize=14)
    
    # Plot 3: Cost efficiency
    ax3 = fig.add_subplot(gs[1, 1])
    
    # Calculate throughput per process (cost efficiency)
    modes_list = []
    efficiencies = []
    task_types_list = []
    
    for mode in ['local', 'pull', 'push']:
        for task_type in ['noop', 'cpu', 'sleep']:
            if mode in results and task_type in results[mode]:
                for d in results[mode][task_type]:
                    modes_list.append(mode.capitalize())
                    task_types_list.append(task_type.capitalize())
                    efficiencies.append(d['throughput'] / d['num_workers'])
    
    # Create violin plot
    import pandas as pd
    df = pd.DataFrame({
        'Mode': modes_list,
        'Task Type': task_types_list,
        'Efficiency': efficiencies
    })
    
    sns.violinplot(data=df, x='Mode', y='Efficiency', hue='Task Type', ax=ax3)
    ax3.set_ylabel('Throughput per Process', fontsize=12)
    ax3.set_title('Cost Efficiency Distribution', fontsize=14)
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('scaling_efficiency_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

def create_latency_percentile_plot(results):
    """Create latency percentile comparison"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('Latency Percentile Analysis', fontsize=16, fontweight='bold')
    
    percentiles = ['avg_latency', 'p95_latency', 'p99_latency']
    percentile_labels = ['Average', '95th Percentile', '99th Percentile']
    
    for idx, (ax, percentile, label) in enumerate(zip(axes, percentiles, percentile_labels)):
        data_by_mode = {'local': [], 'pull': [], 'push': []}
        
        for mode in ['local', 'pull', 'push']:
            if mode in results:
                for task_type in ['noop', 'cpu', 'sleep']:
                    if task_type in results[mode]:
                        for d in results[mode][task_type]:
                            if percentile in d:
                                data_by_mode[mode].append(d[percentile] * 1000)  # Convert to ms
        
        # Create box plots
        box_data = [data_by_mode[mode] for mode in ['local', 'pull', 'push']]
        positions = [1, 2, 3]
        
        bp = ax.boxplot(box_data, positions=positions, widths=0.6, 
                        patch_artist=True, showfliers=True)
        
        # Customize box plots
        colors = ['#2ecc71', '#3498db', '#e74c3c']
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax.set_xlabel('Execution Mode', fontsize=10)
        ax.set_ylabel('Latency (ms)', fontsize=10)
        ax.set_title(f'{label} Latency', fontsize=12)
        ax.set_xticklabels(['Local', 'Pull', 'Push'])
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('latency_percentiles.png', dpi=300, bbox_inches='tight')
    plt.show()

def create_workload_comparison_plot(results):
    """Create workload-specific performance comparison"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Workload-Specific Performance Analysis', fontsize=16, fontweight='bold')
    
    # Define metrics to compare
    metrics = {
        'throughput': 'Throughput (tasks/s)',
        'avg_latency': 'Average Latency (ms)',
        'success_rate': 'Success Rate (%)',
        'p99_latency': '99th Percentile Latency (ms)'
    }
    
    axes = [ax1, ax2, ax3, ax4]
    
    for ax, (metric, label) in zip(axes, metrics.items()):
        # Prepare data
        x = np.arange(3)  # Three task types
        width = 0.25
        
        for i, mode in enumerate(['local', 'pull', 'push']):
            values = []
            errors = []
            
            for task_type in ['noop', 'cpu', 'sleep']:
                if mode in results and task_type in results[mode]:
                    data = results[mode][task_type]
                    if metric == 'avg_latency' or metric == 'p99_latency':
                        vals = [d[metric] * 1000 for d in data if metric in d]
                    elif metric == 'success_rate':
                        vals = [d[metric] * 100 for d in data if metric in d]
                    else:
                        vals = [d[metric] for d in data if metric in d]
                    
                    values.append(np.mean(vals) if vals else 0)
                    errors.append(np.std(vals) if vals else 0)
                else:
                    values.append(0)
                    errors.append(0)
            
            ax.bar(x + (i-1)*width, values, width, label=mode.capitalize(),
                   yerr=errors, capsize=5, alpha=0.8)
        
        ax.set_xlabel('Task Type', fontsize=10)
        ax.set_ylabel(label, fontsize=10)
        ax.set_title(f'{label} by Task Type', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(['No-op', 'CPU', 'I/O'])
        ax.legend()
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('workload_comparison.png', dpi=300, bbox_inches='tight')
    plt.show()

def main():
    """Generate all additional performance visualizations"""
    print("Performance Results Visualizer")
    print("=" * 40)
    
    try:
        # Load results
        print("Loading performance results...")
        results = load_results()
        
        # Generate plots
        print("\nGenerating overhead analysis plot...")
        create_overhead_analysis_plot(results)
        
        print("Generating scaling efficiency plot...")
        create_scaling_efficiency_plot(results)
        
        print("Generating latency percentile plot...")
        create_latency_percentile_plot(results)
        
        print("Generating workload comparison plot...")
        create_workload_comparison_plot(results)
        
        print("\nAll visualizations generated successfully!")
        print("\nGenerated files:")
        print("  - overhead_analysis.png")
        print("  - scaling_efficiency_analysis.png")
        print("  - latency_percentiles.png")
        print("  - workload_comparison.png")
        
    except FileNotFoundError:
        print("ERROR: performance_results.json not found!")
        print("Please run the performance evaluation client first.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()