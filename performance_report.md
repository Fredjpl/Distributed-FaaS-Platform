# Performance Report - MPCSFaaS Evaluation Results

## Executive Summary

This report presents a comprehensive performance evaluation of the MPCSFaaS platform across three execution modes (Local, Pull, Push) and three workload types (No-op, CPU-intensive, I/O-bound). The evaluation reveals that Local mode provides the best raw performance with minimal overhead, while Pull and Push modes offer distributed execution capabilities at the cost of significant communication overhead. The system demonstrates reasonable weak scaling characteristics but exhibits performance anomalies in Push mode under certain configurations.

## Methodology

### Experimental Design

**Weak Scaling Study**:
- Proportional increase in workload with resources
- 5 tasks per worker configuration
- Worker configurations: 1, 2, 4, 8 workers
- Each worker runs 5 processes (except Local mode)

**Workload Types**:
1. **No-op Tasks**: Immediate return (baseline overhead measurement)
2. **CPU-intensive Tasks**: Quadratic computation (1000 iterations)
3. **I/O-bound Tasks**: 100ms sleep (concurrency testing)

**Metrics Collected**:
- Throughput (tasks/second)
- Completion time (seconds)
- Latency distribution (avg, min, max, p95, p99)
- Success rate (%)
- Scaling efficiency (%)

### Test Environment
- Python 3.12 runtime
- FastAPI web service
- Redis 6.x (localhost:6379)
- ZMQ for worker communication
- Hardware: Results may vary based on CPU cores and memory

## Performance Results by Mode

### 1. Local Mode Performance

**Characteristics**:
- Direct process pool execution
- Minimal communication overhead
- Best absolute performance
- Limited by local CPU resources

**Key Metrics**:
- **No-op Throughput**: 58.80 tasks/s (average)
- **CPU Throughput**: 83.59 tasks/s
- **I/O Throughput**: 29.65 tasks/s
- **Average Latency**: 6.5ms (no-op), 6.4ms (CPU), 54.3ms (I/O)
- **Success Rate**: 100% across all tests

**Scaling Behavior**:
- Throughput decreases with more workers (138.69 → 25.68 tasks/s)
- Completion time increases linearly (0.04s → 1.56s)
- Scaling efficiency: 30.6% (poor weak scaling)

### 2. Pull Mode Performance

**Characteristics**:
- Worker-initiated task requests
- Natural load balancing
- Higher baseline latency
- Good fault tolerance

**Key Metrics**
- **No-op Throughput**: 20.37 tasks/s (average)
- **CPU Throughput**: 19.00 tasks/s
- **I/O Throughput**: 15.63 tasks/s
- **Average Latency**: 146.4ms (no-op), 207.5ms (CPU), 275.4ms (I/O)
- **Success Rate**: 100% across all tests

**Scaling Behavior**:
- Inconsistent throughput scaling (22.30 → 21.26 tasks/s)
- Completion time varies (0.22s → 1.88s)
- Scaling efficiency: 42.3% (moderate weak scaling)
- Communication overhead: 139.87ms (2136% over Local)

### 3. Push Mode Performance

**Characteristics**:
- Dispatcher-initiated task distribution
- Lower latency potential
- Load balancing complexity
- Performance anomalies observed

**Key Metrics**:
- **No-op Throughput**: 11.51 tasks/s (average)
- **CPU Throughput**: 24.83 tasks/s
- **I/O Throughput**: 21.98 tasks/s
- **Average Latency**: 1189.5ms (no-op), 61.5ms (CPU), 103.3ms (I/O)
- **Success Rate**: 100% across all tests

**Scaling Behavior**:
- Severe performance degradation for no-op tasks
- Better performance for CPU/I/O tasks
- Scaling efficiency: 26.2% (poor weak scaling)
- Communication overhead: 1182.95ms (18065% over Local)

## Performance Anomalies Analysis

### Push Mode No-op Task Anomaly

The push mode exhibits catastrophic performance for no-op tasks with multiple workers:
- 1 worker: 0.13s completion (normal)
- 2 workers: 7.67s completion (59x slower)
- 4 workers: 9.13s completion (70x slower)
- 8 workers: 8.25s completion (63x slower)

**Root Cause Analysis**:
1. Message queuing in DEALER/ROUTER pattern
2. Synchronization overhead in rapid task completion
3. Potential socket buffer saturation
4. Load balancing algorithm inefficiency

### Latency Distribution Patterns

**Local Mode**:
- Tight distribution (low variance)
- Predictable performance
- P99 latency within 2x average

**Pull Mode**:
- Higher variance in latencies
- Bimodal distribution for some configurations
- P99 latency up to 5x average

**Push Mode**:
- Extreme variance for no-op tasks
- Multi-second outliers
- Better stability for longer tasks

## Workload-Specific Analysis

### No-op Tasks (Overhead Measurement)
1. **Local**: 6.5ms average latency - represents baseline system overhead
2. **Pull**: 146.4ms - adds ~140ms communication overhead
3. **Push**: 1189.5ms - severe overhead due to queuing issues

### CPU-intensive Tasks
1. **Local**: Best throughput (83.59 tasks/s)
2. **Pull**: Moderate degradation (19.00 tasks/s)
3. **Push**: Comparable to Pull (24.83 tasks/s)
4. **Finding**: CPU work amortizes communication overhead

### I/O-bound Tasks
1. **Performance Convergence**: All modes show similar throughput
2. **Concurrency Benefits**: 100ms sleep dominates execution time
3. **Scaling**: Better utilization with more workers
4. **Finding**: I/O wait masks communication overhead

## Scaling Efficiency Analysis

### Weak Scaling Results
- **Ideal**: Constant completion time as workers increase
- **Actual**: Increasing completion times across all modes
- **Best**: Pull mode at 42.3% efficiency
- **Worst**: Push mode at 26.2% efficiency

### Scalability Limitations
1. **Task Granularity**: 5 tasks/worker may be insufficient
2. **Coordination Overhead**: Increases with worker count
3. **Network Saturation**: ZMQ socket limitations
4. **Redis Bottleneck**: Single pub/sub channel

## Cost Efficiency Analysis

### Throughput per Process
- **Local Mode**: Best utilization for CPU tasks
- **Pull Mode**: Consistent but lower utilization
- **Push Mode**: Highly variable utilization

### Resource Recommendations
1. **CPU-bound**: Use Local mode with process count = CPU cores
2. **I/O-bound**: Any mode with higher process count
3. **Mixed Workloads**: Pull mode for predictability
4. **Fault Tolerance Required**: Pull or Push modes

## Performance Optimization Opportunities

### 1. Push Mode Improvements
- Implement better load balancing algorithm
- Add task batching for small tasks
- Tune ZMQ socket options (HWM, buffers)
- Consider hybrid push/pull approach

### 2. Communication Optimization
- Reduce serialization overhead
- Implement connection pooling
- Use binary protocols
- Consider UDP for non-critical tasks

### 3. Scaling Enhancements
- Multiple dispatcher instances
- Hierarchical worker organization
- Task affinity and caching
- Dynamic worker scaling

## Benchmark Limitations

1. **Synthetic Workloads**: May not represent real applications
2. **Limited Scale**: Maximum 8 workers tested
3. **Single Machine**: No network latency simulation
4. **Fixed Parameters**: 5 tasks/worker ratio

## Recommendations

### For Production Deployment

1. **Workload Analysis**:
   - Profile actual function execution times
   - Measure communication/computation ratio
   - Identify performance-critical paths

2. **Mode Selection**:
   - Local: Development and low-latency requirements
   - Pull: General-purpose distributed execution
   - Push: Avoid for high-frequency small tasks

3. **Configuration Tuning**:
   - Adjust worker process counts
   - Tune heartbeat intervals
   - Optimize task batch sizes

4. **Monitoring Requirements**:
   - Track per-task latencies
   - Monitor queue depths
   - Alert on performance anomalies

