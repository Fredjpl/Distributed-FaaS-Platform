import time
import requests
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import subprocess
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import serialize, deserialize
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import seaborn as sns

class PerformanceEvaluator:
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url
        self.results = {}
        
        # Create a session with connection pooling and retry logic
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Configure connection pooling
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=50,
            max_retries=retry_strategy
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
    def __del__(self):
        """Clean up session when object is destroyed"""
        if hasattr(self, 'session'):
            self.session.close()
    
    def register_function(self, name, func):
        """Register a function with the FaaS platform"""
        response = self.session.post(
            f"{self.base_url}/register_function",
            json={"name": name, "payload": serialize(func)},
            timeout=30
        )
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to register function: {response.text}")
        return response.json()["function_id"]
    
    def execute_function(self, function_id, args=()):
        """Execute a function and return task_id"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    f"{self.base_url}/execute_function",
                    json={"function_id": function_id, "payload": serialize((args, {}))},
                    timeout=30
                )
                if response.status_code not in [200, 201]:
                    raise Exception(f"Failed to execute function: {response.text}")
                return response.json()["task_id"]
            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    print(f"Connection error, retrying in {2**attempt} seconds...")
                    time.sleep(2**attempt)
                else:
                    raise
    
    def wait_for_task(self, task_id, timeout=120):
        """Wait for a task to complete and measure latency"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = self.session.get(
                    f"{self.base_url}/result/{task_id}",
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    if data["status"] == "COMPLETED":
                        latency = time.time() - start_time
                        return deserialize(data["result"]), latency
                    elif data["status"] == "FAILED":
                        raise Exception(f"Task failed: {deserialize(data['result'])}")
            except requests.exceptions.ConnectionError:
                pass
            
            time.sleep(0.1)
        
        raise Exception(f"Task {task_id} timed out")
    
    def run_tasks_batch(self, function_id, num_tasks, task_args, batch_size=5):
        """Submit and wait for a batch of tasks with proper rate limiting"""
        print(f"    Submitting {num_tasks} tasks...")
        
        # Record timings
        submit_start = time.time()
        task_timings = []
        
        # Submit tasks in smaller batches
        task_ids = []
        for i in range(0, num_tasks, batch_size):
            batch_end = min(i + batch_size, num_tasks)
            
            # Submit batch
            for j in range(i, batch_end):
                task_start = time.time()
                task_id = self.execute_function(function_id, task_args)
                task_ids.append((task_id, task_start))
            
            # Delay between batches
            if batch_end < num_tasks:
                time.sleep(0.2)
        
        submit_end = time.time()
        submission_time = submit_end - submit_start
        print(f"    All tasks submitted in {submission_time:.2f}s")
        
        # Wait for all tasks to complete
        print(f"    Waiting for tasks to complete...")
        latencies = []
        completed = 0
        failed = 0
        
        # Use ThreadPoolExecutor with limited concurrency
        max_concurrent = min(20, num_tasks)
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_task = {
                executor.submit(self.wait_for_task, task_id[0]): (task_id[0], task_id[1])
                for task_id in task_ids
            }
            
            for future in as_completed(future_to_task):
                task_id, task_start = future_to_task[future]
                try:
                    result, latency = future.result()
                    latencies.append(latency)
                    completed += 1
                    
                    # Progress indicator
                    if completed % max(1, num_tasks // 10) == 0:
                        print(f"      {completed}/{num_tasks} tasks completed")
                        
                except Exception as e:
                    print(f"      Task {task_id} error: {e}")
                    failed += 1
        
        # Calculate metrics
        completion_time = time.time() - submit_start
        
        if latencies:
            metrics = {
                'num_tasks': num_tasks,
                'submission_time': submission_time,
                'completion_time': completion_time,
                'throughput': completed / completion_time,
                'avg_latency': np.mean(latencies),
                'min_latency': np.min(latencies),
                'max_latency': np.max(latencies),
                'median_latency': np.median(latencies),
                'p95_latency': np.percentile(latencies, 95),
                'p99_latency': np.percentile(latencies, 99),
                'success_rate': completed / num_tasks,
                'failed_tasks': failed,
                'latencies': latencies
            }
        else:
            metrics = {
                'num_tasks': num_tasks,
                'submission_time': submission_time,
                'completion_time': completion_time,
                'throughput': 0,
                'avg_latency': 0,
                'min_latency': 0,
                'max_latency': 0,
                'median_latency': 0,
                'p95_latency': 0,
                'p99_latency': 0,
                'success_rate': 0,
                'failed_tasks': failed,
                'latencies': []
            }
        
        return metrics
    
    def weak_scaling_study(self, mode, worker_configs, tasks_per_worker=5):
        """Perform weak scaling study for a given mode"""
        print(f"\n{'='*60}")
        print(f"Weak Scaling Study - {mode.upper()} Mode")
        print(f"{'='*60}\n")
        
        # Define test functions
        def noop_task():
            """No-op task that returns immediately"""
            return "done"
        
        def cpu_task(n=1000):
            """CPU-intensive task"""
            result = 0
            for i in range(n):
                result += i ** 2
            return result
        
        def sleep_task(duration=0.1):
            """I/O-bound task that sleeps"""
            import time
            time.sleep(duration)
            return f"slept {duration}s"
        
        # Register functions
        print("Registering test functions...")
        noop_id = self.register_function(f"noop_{mode}", noop_task)
        cpu_id = self.register_function(f"cpu_{mode}", cpu_task)
        sleep_id = self.register_function(f"sleep_{mode}", sleep_task)
        
        results = {
            'noop': [],
            'cpu': [],
            'sleep': []
        }
        
        for config in worker_configs:
            if mode == 'local':
                num_processes = config
                num_tasks = min(num_processes * tasks_per_worker, 50)  # Limit tasks
                print(f"\nTesting with {num_processes} local processes, {num_tasks} tasks...")
                config_str = f"{num_processes} processes"
            else:
                num_workers, processes_per_worker = config
                num_tasks = min(num_workers * tasks_per_worker, 50)  # Limit tasks
                print(f"\nTesting with {num_workers} workers ({processes_per_worker} processes each), {num_tasks} tasks...")
                config_str = f"{num_workers}x{processes_per_worker}"
            
            # Test no-op tasks
            print(f"  Running no-op tasks...")
            try:
                metrics = self.run_tasks_batch(noop_id, num_tasks, (), batch_size=5)
                metrics['config'] = config_str
                metrics['num_workers'] = num_processes if mode == 'local' else num_workers
                results['noop'].append(metrics)
                print(f"    Throughput: {metrics['throughput']:.2f} tasks/s")
                print(f"    Completion Time: {metrics['completion_time']:.3f}s")
                print(f"    Avg Latency: {metrics['avg_latency']:.3f}s")
                print(f"    Success Rate: {metrics['success_rate']*100:.1f}%")
            except Exception as e:
                print(f"    Error: {e}")
            
            time.sleep(2)
            
            # Test CPU-intensive tasks
            print(f"  Running CPU-intensive tasks...")
            try:
                metrics = self.run_tasks_batch(cpu_id, num_tasks, (1000,), batch_size=5)
                metrics['config'] = config_str
                metrics['num_workers'] = num_processes if mode == 'local' else num_workers
                results['cpu'].append(metrics)
                print(f"    Throughput: {metrics['throughput']:.2f} tasks/s")
                print(f"    Completion Time: {metrics['completion_time']:.3f}s")
                print(f"    Avg Latency: {metrics['avg_latency']:.3f}s")
                print(f"    Success Rate: {metrics['success_rate']*100:.1f}%")
            except Exception as e:
                print(f"    Error: {e}")
            
            time.sleep(2)
            
            # Test I/O-bound tasks
            print(f"  Running I/O-bound tasks (0.1s sleep)...")
            try:
                metrics = self.run_tasks_batch(sleep_id, num_tasks, (0.1,), batch_size=5)
                metrics['config'] = config_str
                metrics['num_workers'] = num_processes if mode == 'local' else num_workers
                results['sleep'].append(metrics)
                print(f"    Throughput: {metrics['throughput']:.2f} tasks/s")
                print(f"    Completion Time: {metrics['completion_time']:.3f}s")
                print(f"    Avg Latency: {metrics['avg_latency']:.3f}s")
                print(f"    Success Rate: {metrics['success_rate']*100:.1f}%")
            except Exception as e:
                print(f"    Error: {e}")
            
            time.sleep(3)
        
        return results
    
    def run_complete_evaluation(self):
        """Run complete performance evaluation"""
        all_results = {}
        
        # Test local mode
        print("\n" + "="*70)
        print("STARTING LOCAL MODE EVALUATION")
        print("="*70)
        
        dispatcher = subprocess.Popen([
            sys.executable, "task_dispatcher.py", "-m", "local", "-w", "8"
        ])
        
        time.sleep(3)
        
        try:
            local_configs = [1, 2, 4, 8]
            all_results['local'] = self.weak_scaling_study('local', local_configs, tasks_per_worker=5)
        finally:
            dispatcher.terminate()
            dispatcher.wait()
            time.sleep(2)
        
        # Test pull mode
        print("\n" + "="*70)
        print("STARTING PULL MODE EVALUATION")
        print("="*70)
        
        dispatcher = subprocess.Popen([
            sys.executable, "task_dispatcher.py", "-m", "pull", "-p", "5556"
        ])
        
        time.sleep(3)
        
        try:
            pull_results = {'noop': [], 'cpu': [], 'sleep': []}
            worker_configs = [(1, 5), (2, 5), (4, 5), (8, 5)]
            
            for num_workers, processes_per_worker in worker_configs:
                # Start workers
                workers = []
                for i in range(num_workers):
                    worker = subprocess.Popen([
                        sys.executable, "pull_worker.py",
                        str(processes_per_worker),
                        "tcp://localhost:5556"
                    ])
                    workers.append(worker)
                
                time.sleep(5)
                
                # Run tests
                results = self.weak_scaling_study('pull', [(num_workers, processes_per_worker)], tasks_per_worker=5)
                
                for task_type in ['noop', 'cpu', 'sleep']:
                    if results[task_type]:
                        pull_results[task_type].extend(results[task_type])
                
                # Stop workers
                for w in workers:
                    w.terminate()
                    w.wait()
                
                time.sleep(2)
            
            all_results['pull'] = pull_results
            
        finally:
            dispatcher.terminate()
            dispatcher.wait()
            time.sleep(2)
        
        # Test push mode
        print("\n" + "="*70)
        print("STARTING PUSH MODE EVALUATION")
        print("="*70)
        
        dispatcher = subprocess.Popen([
            sys.executable, "task_dispatcher.py", "-m", "push", "-p", "5557"
        ])
        
        time.sleep(3)
        
        try:
            push_results = {'noop': [], 'cpu': [], 'sleep': []}
            worker_configs = [(1, 5), (2, 5), (4, 5), (8, 5)]
            
            for num_workers, processes_per_worker in worker_configs:
                # Start workers
                workers = []
                for i in range(num_workers):
                    worker = subprocess.Popen([
                        sys.executable, "push_worker.py",
                        str(processes_per_worker),
                        "tcp://localhost:5557"
                    ])
                    workers.append(worker)
                
                time.sleep(5)
                
                # Run tests
                results = self.weak_scaling_study('push', [(num_workers, processes_per_worker)], tasks_per_worker=5)
                
                for task_type in ['noop', 'cpu', 'sleep']:
                    if results[task_type]:
                        push_results[task_type].extend(results[task_type])
                
                # Stop workers
                for w in workers:
                    w.terminate()
                    w.wait()
                
                time.sleep(2)
            
            all_results['push'] = push_results
            
        finally:
            dispatcher.terminate()
            dispatcher.wait()
            time.sleep(2)
        
        return all_results
    
    def plot_comprehensive_results(self, results):
        """Create comprehensive performance visualization plots"""
        # Set style
        plt.style.use('seaborn-v0_8-darkgrid')
        colors = {'local': '#2ecc71', 'pull': '#3498db', 'push': '#e74c3c'}
        
        # Create figure with multiple subplots
        fig = plt.figure(figsize=(20, 16))
        gs = gridspec.GridSpec(4, 3, height_ratios=[1, 1, 1, 1.2], hspace=0.3, wspace=0.3)
        
        # Title
        fig.suptitle('MPCSFaaS Comprehensive Performance Evaluation', fontsize=20, fontweight='bold')
        
        # Plot 1: Throughput comparison across task types
        ax1 = plt.subplot(gs[0, :])
        task_types = ['noop', 'cpu', 'sleep']
        x = np.arange(len(task_types))
        width = 0.25
        
        for i, mode in enumerate(['local', 'pull', 'push']):
            throughputs = []
            errors = []
            for task_type in task_types:
                if mode in results and task_type in results[mode] and results[mode][task_type]:
                    data = [d['throughput'] for d in results[mode][task_type]]
                    throughputs.append(np.mean(data))
                    errors.append(np.std(data))
                else:
                    throughputs.append(0)
                    errors.append(0)
            
            ax1.bar(x + (i-1)*width, throughputs, width, label=mode.capitalize(),
                   color=colors[mode], yerr=errors, capsize=5, alpha=0.8)
        
        ax1.set_xlabel('Task Type', fontsize=12)
        ax1.set_ylabel('Average Throughput (tasks/s)', fontsize=12)
        ax1.set_title('Throughput Comparison by Task Type', fontsize=14, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(['No-op', 'CPU-intensive', 'I/O-bound'])
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Plots 2-4: Weak scaling for each task type (MODIFIED TO SHOW COMPLETION TIME)
        for idx, task_type in enumerate(['noop', 'cpu', 'sleep']):
            ax = plt.subplot(gs[1, idx])
            
            for mode in ['local', 'pull', 'push']:
                if mode in results and task_type in results[mode] and results[mode][task_type]:
                    data = results[mode][task_type]
                    processes = [d['num_workers'] for d in data]
                    completion_times = [d['completion_time'] for d in data]
                    
                    ax.plot(processes, completion_times, 'o-', label=mode.capitalize(),
                           color=colors[mode], linewidth=2, markersize=8)
            
            ax.set_xlabel('Number of Workers', fontsize=10)
            ax.set_ylabel('Completion Time (seconds)', fontsize=10)
            ax.set_title(f'Weak Scaling - {task_type.capitalize()} Tasks', fontsize=12)
            ax.legend()
            ax.grid(True, alpha=0.3)
            ax.set_xscale('log', base=2)
            # Optionally set y-axis to log scale if the range is large
            # ax.set_yscale('log')
        
        # Plots 5-7: Latency distribution for each mode
        for idx, mode in enumerate(['local', 'pull', 'push']):
            ax = plt.subplot(gs[2, idx])
            
            if mode in results:
                for task_type, color in zip(['noop', 'cpu', 'sleep'], ['blue', 'green', 'red']):
                    if task_type in results[mode]:
                        all_latencies = []
                        for d in results[mode][task_type]:
                            if 'latencies' in d and d['latencies']:
                                all_latencies.extend([l*1000 for l in d['latencies']])  # Convert to ms
                        
                        if all_latencies:
                            ax.hist(all_latencies, bins=30, alpha=0.5, label=task_type.capitalize(),
                                   color=color, density=True)
            
            ax.set_xlabel('Latency (ms)', fontsize=10)
            ax.set_ylabel('Density', fontsize=10)
            ax.set_title(f'Latency Distribution - {mode.capitalize()} Mode', fontsize=12)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Set reasonable x-axis limits
            if mode == 'local':
                ax.set_xlim(0, 50)
            else:
                ax.set_xlim(0, 200)
        
        # Plot 8: Scaling efficiency comparison (MODIFIED TO USE COMPLETION TIME)
        ax8 = plt.subplot(gs[3, 0])
        
        for mode in ['local', 'pull', 'push']:
            if mode in results and 'noop' in results[mode] and len(results[mode]['noop']) > 1:
                data = results[mode]['noop']
                processes = np.array([d['num_workers'] for d in data])
                completion_times = np.array([d['completion_time'] for d in data])
                num_tasks = np.array([d['num_tasks'] for d in data])
                
                # Calculate scaling efficiency based on completion time
                # In weak scaling, ideal completion time should remain constant
                baseline_time = completion_times[0]
                efficiency = (baseline_time / completion_times) * 100
                
                ax8.plot(processes, efficiency, 's-', label=mode.capitalize(),
                        color=colors[mode], linewidth=2, markersize=8)
        
        ax8.axhline(y=100, color='black', linestyle='--', alpha=0.5, label='Perfect Scaling')
        ax8.set_xlabel('Number of Workers', fontsize=12)
        ax8.set_ylabel('Scaling Efficiency (%)', fontsize=12)
        ax8.set_title('Weak Scaling Efficiency Comparison', fontsize=14, fontweight='bold')
        ax8.legend()
        ax8.grid(True, alpha=0.3)
        ax8.set_xscale('log', base=2)
        ax8.set_ylim(0, 120)
        
        # Plot 9: Success rate comparison
        ax9 = plt.subplot(gs[3, 1])
        
        task_types = ['noop', 'cpu', 'sleep']
        x = np.arange(len(task_types))
        width = 0.25
        
        for i, mode in enumerate(['local', 'pull', 'push']):
            success_rates = []
            for task_type in task_types:
                if mode in results and task_type in results[mode] and results[mode][task_type]:
                    data = [d['success_rate'] * 100 for d in results[mode][task_type]]
                    success_rates.append(np.mean(data))
                else:
                    success_rates.append(0)
            
            ax9.bar(x + (i-1)*width, success_rates, width, label=mode.capitalize(),
                   color=colors[mode], alpha=0.8)
        
        ax9.set_xlabel('Task Type', fontsize=12)
        ax9.set_ylabel('Success Rate (%)', fontsize=12)
        ax9.set_title('Task Success Rates', fontsize=14, fontweight='bold')
        ax9.set_xticks(x)
        ax9.set_xticklabels(['No-op', 'CPU-intensive', 'I/O-bound'])
        ax9.legend()
        ax9.grid(True, alpha=0.3)
        ax9.set_ylim(0, 105)
        
        # Plot 10: Percentile latencies
        ax10 = plt.subplot(gs[3, 2])
        
        percentiles = ['avg', 'p95', 'p99']
        x = np.arange(len(percentiles))
        width = 0.25
        
        for i, mode in enumerate(['local', 'pull', 'push']):
            values = []
            if mode in results and 'noop' in results[mode] and results[mode]['noop']:
                data = results[mode]['noop']
                values = [
                    np.mean([d['avg_latency']*1000 for d in data]),
                    np.mean([d['p95_latency']*1000 for d in data]),
                    np.mean([d['p99_latency']*1000 for d in data])
                ]
            else:
                values = [0, 0, 0]
            
            ax10.bar(x + (i-1)*width, values, width, label=mode.capitalize(),
                    color=colors[mode], alpha=0.8)
        
        ax10.set_xlabel('Percentile', fontsize=12)
        ax10.set_ylabel('Latency (ms)', fontsize=12)
        ax10.set_title('Latency Percentiles - No-op Tasks', fontsize=14, fontweight='bold')
        ax10.set_xticks(x)
        ax10.set_xticklabels(['Average', '95th', '99th'])
        ax10.legend()
        ax10.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('comprehensive_performance_results.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        return fig
    
    def generate_detailed_report(self, results):
        """Generate a detailed performance report"""
        report = []
        report.append("="*80)
        report.append("MPCSFaaS COMPREHENSIVE PERFORMANCE EVALUATION REPORT")
        report.append("="*80)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Executive Summary
        report.append("EXECUTIVE SUMMARY")
        report.append("-"*50)
        report.append("This report presents a comprehensive evaluation of the MPCSFaaS platform")
        report.append("comparing three execution modes (Local, Pull, Push) across different")
        report.append("workload types (No-op, CPU-intensive, I/O-bound).\n")
        
        # Key Findings
        report.append("KEY FINDINGS")
        report.append("-"*50)
        
        # Find best mode for each task type (based on throughput)
        best_throughput = {'noop': (0, ''), 'cpu': (0, ''), 'sleep': (0, '')}
        
        # Find best mode for completion time
        best_completion = {'noop': (float('inf'), ''), 'cpu': (float('inf'), ''), 'sleep': (float('inf'), '')}
        
        for mode in ['local', 'pull', 'push']:
            if mode in results:
                for task_type in ['noop', 'cpu', 'sleep']:
                    if task_type in results[mode] and results[mode][task_type]:
                        avg_throughput = np.mean([d['throughput'] for d in results[mode][task_type]])
                        avg_completion = np.mean([d['completion_time'] for d in results[mode][task_type]])
                        
                        if avg_throughput > best_throughput[task_type][0]:
                            best_throughput[task_type] = (avg_throughput, mode)
                        
                        if avg_completion < best_completion[task_type][0]:
                            best_completion[task_type] = (avg_completion, mode)
        
        report.append(f"1. Best mode for no-op tasks: {best_throughput['noop'][1].capitalize()} "
                     f"({best_throughput['noop'][0]:.2f} tasks/s, "
                     f"{best_completion['noop'][0]:.2f}s completion time)")
        report.append(f"2. Best mode for CPU tasks: {best_throughput['cpu'][1].capitalize()} "
                     f"({best_throughput['cpu'][0]:.2f} tasks/s, "
                     f"{best_completion['cpu'][0]:.2f}s completion time)")
        report.append(f"3. Best mode for I/O tasks: {best_throughput['sleep'][1].capitalize()} "
                     f"({best_throughput['sleep'][0]:.2f} tasks/s, "
                     f"{best_completion['sleep'][0]:.2f}s completion time)\n")
        
        # Detailed Results
        for mode in ['local', 'pull', 'push']:
            if mode in results:
                report.append(f"\n{mode.upper()} MODE DETAILED RESULTS")
                report.append("="*50)
                
                for task_type in ['noop', 'cpu', 'sleep']:
                    if task_type in results[mode] and results[mode][task_type]:
                        report.append(f"\n{task_type.capitalize()} Tasks:")
                        report.append("-"*30)
                        
                        # Create table
                        report.append(f"{'Config':<15} {'Tasks':<8} {'Completion':<12} {'Throughput':<12} "
                                     f"{'Avg Latency':<12} {'P95 Latency':<12} {'Success':<10}")
                        report.append("-"*89)
                        
                        for d in results[mode][task_type]:
                            report.append(
                                f"{d['config']:<15} {d['num_tasks']:<8} "
                                f"{d['completion_time']:<12.2f} {d['throughput']:<12.2f} "
                                f"{d['avg_latency']*1000:<12.1f} {d['p95_latency']*1000:<12.1f} "
                                f"{d['success_rate']*100:<10.1f}%"
                            )
                        
                        # Summary statistics
                        completion_times = [d['completion_time'] for d in results[mode][task_type]]
                        throughputs = [d['throughput'] for d in results[mode][task_type]]
                        latencies = [d['avg_latency'] for d in results[mode][task_type]]
                        
                        report.append(f"\nSummary:")
                        report.append(f"  Average completion time: {np.mean(completion_times):.2f} s")
                        report.append(f"  Average throughput: {np.mean(throughputs):.2f} tasks/s")
                        report.append(f"  Average latency: {np.mean(latencies)*1000:.1f} ms")
                        report.append(f"  Completion time std dev: {np.std(completion_times):.2f}")
        
        # Scaling Analysis (Modified for completion time)
        report.append("\n\nSCALING ANALYSIS")
        report.append("="*50)
        
        for mode in ['local', 'pull', 'push']:
            if mode in results and 'noop' in results[mode] and len(results[mode]['noop']) > 1:
                data = results[mode]['noop']
                processes = [d['num_workers'] for d in data]
                completion_times = [d['completion_time'] for d in data]
                
                # In weak scaling, ideal completion time should remain constant
                baseline_time = completion_times[0]
                efficiency_scores = [baseline_time / ct for ct in completion_times]
                avg_efficiency = np.mean(efficiency_scores) * 100
                
                report.append(f"\n{mode.capitalize()} Mode:")
                report.append(f"  Baseline completion time: {baseline_time:.3f}s")
                report.append(f"  Average scaling efficiency: {avg_efficiency:.1f}%")
                report.append(f"  Interpretation: {'Good' if avg_efficiency > 80 else 'Moderate' if avg_efficiency > 50 else 'Poor'} weak scaling")
        
        # Communication Overhead Analysis
        report.append("\n\nCOMMUNICATION OVERHEAD ANALYSIS")
        report.append("="*50)
        
        overheads = {}
        for mode in ['local', 'pull', 'push']:
            if mode in results and 'noop' in results[mode] and results[mode]['noop']:
                avg_latency = np.mean([d['avg_latency'] for d in results[mode]['noop']])
                overheads[mode] = avg_latency * 1000  # Convert to ms
        
        if 'local' in overheads:
            baseline = overheads['local']
            report.append(f"\nUsing Local mode as baseline ({baseline:.2f} ms)")
            
            for mode in ['pull', 'push']:
                if mode in overheads:
                    overhead = overheads[mode] - baseline
                    percentage = (overhead / baseline) * 100
                    report.append(f"{mode.capitalize()} mode overhead: {overhead:.2f} ms ({percentage:.1f}% increase)")
        
        # Recommendations
        report.append("\n\nRECOMMENDATIONS")
        report.append("="*50)
        report.append("\n1. For CPU-bound workloads:")
        report.append("   - Use Local mode when network overhead must be minimized")
        report.append("   - Consider Pull/Push modes for better fault tolerance")
        
        report.append("\n2. For I/O-bound workloads:")
        report.append("   - All modes perform similarly due to I/O dominance")
        report.append("   - Choose based on operational requirements")
        
        report.append("\n3. For mixed workloads:")
        report.append("   - Pull mode offers good load balancing")
        report.append("   - Push mode may provide lower latency for uniform workloads")
        
        report.append("\n4. Scaling considerations:")
        report.append("   - All modes show reasonable weak scaling")
        report.append("   - Network modes (Pull/Push) have higher base overhead")
        report.append("   - Consider task granularity vs communication overhead")
        
        # Technical Details
        report.append("\n\nTECHNICAL NOTES")
        report.append("="*50)
        report.append("- Task submission was rate-limited to avoid socket exhaustion")
        report.append("- Connection pooling was used for HTTP requests")
        report.append("- Tests were run with limited concurrency for stability")
        report.append("- Results may vary based on system specifications")
        
        # Save report
        report_text = "\n".join(report)
        
        # Save as markdown
        with open("performance_analysis.md", "w") as f:
            f.write(report_text)
        
        # Save raw results as JSON
        import json
        with open("performance_results.json", "w") as f:
            # Convert numpy arrays to lists for JSON serialization
            json_results = {}
            for mode, mode_results in results.items():
                json_results[mode] = {}
                for task_type, task_results in mode_results.items():
                    json_results[mode][task_type] = []
                    for result in task_results:
                        result_copy = result.copy()
                        # Remove latencies array to keep file size reasonable
                        if 'latencies' in result_copy:
                            del result_copy['latencies']
                        json_results[mode][task_type].append(result_copy)
            
            json.dump(json_results, f, indent=2)
        
        print("\n" + report_text)
        return report_text


def main():
    """Main function to run the performance evaluation"""
    print("MPCSFaaS Comprehensive Performance Evaluation")
    print("=" * 50)
    print()
    
    # Check if FastAPI server is running
    try:
        response = requests.get("http://127.0.0.1:8000/")
        if response.status_code != 200:
            print("ERROR: FastAPI server is not responding correctly!")
            print("Please ensure the server is running with: uvicorn main:app --reload")
            return
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to FastAPI server!")
        print("Please ensure the server is running with: uvicorn main:app --reload")
        return
    
    # Check if Redis is running
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
    except:
        print("ERROR: Cannot connect to Redis!")
        print("Please ensure Redis is running with: redis-server")
        return
    
    # Create evaluator and run tests
    evaluator = PerformanceEvaluator()
    
    print("Starting comprehensive performance evaluation...")
    print("This will take approximately 10-15 minutes to complete.")
    print("Progress will be displayed throughout the evaluation.\n")
    
    try:
        # Run the evaluation
        results = evaluator.run_complete_evaluation()
        
        # Generate comprehensive plots
        print("\nGenerating comprehensive performance visualizations...")
        evaluator.plot_comprehensive_results(results)
        
        # Generate detailed report
        print("\nGenerating detailed performance report...")
        evaluator.generate_detailed_report(results)
        
        print("\nPerformance evaluation complete!")
        print("\nGenerated files:")
        print("  - comprehensive_performance_results.png : Multi-panel performance visualization")
        print("  - performance_analysis.md : Detailed performance analysis report")
        print("  - performance_results.json : Raw performance data for further analysis")
        
    except KeyboardInterrupt:
        print("\nEvaluation interrupted by user.")
    except Exception as e:
        print(f"\nError during evaluation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure session is closed
        if hasattr(evaluator, 'session'):
            evaluator.session.close()
        
        # Kill any lingering processes
        print("\nCleaning up any remaining processes...")
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('task_dispatcher.py' in str(arg) or 
                                     'pull_worker.py' in str(arg) or 
                                     'push_worker.py' in str(arg) for arg in cmdline):
                        print(f"  Terminating {proc.info['name']} (PID: {proc.info['pid']})")
                        proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


if __name__ == "__main__":
    main()