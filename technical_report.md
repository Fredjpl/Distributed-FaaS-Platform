# Technical Report - MPCSFaaS Implementation

## Executive Summary

This report details the implementation of MPCSFaaS, a Function-as-a-Service platform built with Python, FastAPI, Redis, and ZMQ. The system supports three execution modes (Local, Pull, Push) and provides a complete serverless computing environment with fault tolerance capabilities.

## Architecture Overview

### Core Components

1. **FastAPI Web Service (main.py)**
   - REST API endpoints for function registration, execution, status checking, and result retrieval
   - Stateless design with all persistence delegated to Redis
   - UUID-based identification for functions and tasks
   - Comprehensive error handling with appropriate HTTP status codes

2. **Redis Integration**
   - Dual-purpose usage: key-value store and message broker
   - Function storage with metadata
   - Task lifecycle management (QUEUED → RUNNING → COMPLETED/FAILED)
   - Pub/Sub mechanism for task distribution

3. **Task Dispatcher (task_dispatcher.py)**
   - Central coordinator for task distribution
   - Three execution modes implemented:
     - **Local**: Direct multiprocessing pool execution
     - **Pull**: Workers request tasks (ZMQ REQ/REP)
     - **Push**: Dispatcher sends tasks to workers (ZMQ DEALER/ROUTER)
   - Worker registration and heartbeat monitoring
   - Fault detection and task recovery mechanisms

4. **Worker Implementation**
   - **Pull Workers**: Active task fetching with request-based model
   - **Push Workers**: Passive task reception with event-driven model
   - Multiprocessing pools for concurrent task execution
   - Automatic registration and heartbeat maintenance

## Implementation Details

### Function Registration and Storage

Functions are serialized using `dill` (enhanced pickle) and base64-encoded for storage:
- Validation ensures payload contains callable Python functions
- UUID generation provides unique identifiers
- Metadata stored alongside function payload in Redis

### Task Execution Pipeline

1. **Task Creation**:
   - Validate function existence and parameter format
   - Generate unique task UUID
   - Store task with initial QUEUED status
   - Publish task ID to Redis channel

2. **Task Distribution**:
   - Dispatcher subscribes to Redis "tasks" channel
   - Mode-specific distribution logic:
     - Local: Direct pool execution
     - Pull: Queue tasks for worker requests
     - Push: Load-balanced distribution to registered workers

3. **Result Handling**:
   - Workers execute functions in isolated processes
   - Results/exceptions serialized and returned
   - Task status updated atomically in Redis

### Communication Patterns

**Pull Mode (REQ/REP)**:
- Workers initiate communication
- Natural load balancing (workers request when ready)
- Higher latency due to polling overhead
- Resilient to worker failures

**Push Mode (DEALER/ROUTER)**:
- Dispatcher initiates communication
- Lower latency for well-distributed workloads
- Requires active load balancing implementation
- More complex failure handling

### Fault Tolerance Mechanisms

1. **Heartbeat System**:
   - Workers send periodic heartbeats (1-second intervals)
   - 3-second timeout for failure detection
   - Graceful handling of worker disconnections

2. **Task Recovery**:
   - Failed worker tasks automatically requeued
   - Task status reverted from RUNNING to QUEUED
   - Reassignment to healthy workers
   - Maintains at-least-once execution semantics

3. **Error Handling**:
   - Function execution exceptions captured and stored
   - Serialization errors handled gracefully
   - Network failures trigger reconnection logic
   - HTTP request retries with exponential backoff

## Performance Optimizations

1. **Connection Pooling**: HTTP session reuse in client
2. **Batch Processing**: Rate-limited task submission
3. **Concurrent Result Fetching**: ThreadPoolExecutor for parallel polling
4. **Process Pool Reuse**: Persistent worker pools across tasks
5. **Efficient Serialization**: Binary protocol with base64 encoding

## Limitations and Trade-offs

### Architectural Limitations

1. **Single Redis Instance**: 
   - Single point of failure
   - Memory constraints for large functions/results
   - No persistence guarantees (in-memory store)

2. **No Task Prioritization**:
   - FIFO processing only
   - No support for priority queues
   - Limited scheduling capabilities

3. **Network Overhead**:
   - Serialization/deserialization costs
   - ZMQ communication latency
   - Redis pub/sub delays

### Scalability Constraints

1. **Task Dispatcher Bottleneck**:
   - Single dispatcher limits horizontal scaling
   - All tasks flow through one coordinator
   - Potential congestion at high loads

2. **Worker Registration**:
   - In-memory worker tracking
   - Lost on dispatcher restart
   - No persistent worker state

3. **Result Storage**:
   - Results remain in Redis indefinitely
   - Manual cleanup required
   - Memory exhaustion risk

### Reliability Considerations

1. **At-Least-Once Semantics**:
   - Tasks may execute multiple times on failures
   - Non-idempotent functions problematic
   - No exactly-once guarantees

2. **Heartbeat Granularity**:
   - 3-second detection window
   - Tasks blocked during detection period
   - Trade-off between overhead and responsiveness

3. **Partial Failures**:
   - Network partitions not handled
   - Split-brain scenarios possible
   - No consensus mechanism

## Design Decisions and Rationale

1. **FastAPI Choice**:
   - Modern async framework
   - Automatic validation and documentation
   - High performance with minimal overhead

2. **ZMQ for Worker Communication**:
   - Low-latency messaging
   - Multiple communication patterns
   - Language-agnostic protocol

3. **Redis for State Management**:
   - Fast in-memory operations
   - Built-in pub/sub support
   - Simple deployment model

4. **Process-Based Isolation**:
   - True parallelism (GIL avoidance)
   - Fault isolation between tasks
   - Memory protection

## Future Improvements

1. **High Availability**:
   - Redis Sentinel/Cluster support
   - Multiple dispatcher instances
   - Consistent hashing for distribution

2. **Enhanced Monitoring**:
   - Metrics collection (Prometheus)
   - Distributed tracing
   - Performance profiling

3. **Advanced Features**:
   - Task dependencies
   - Workflow orchestration
   - Resource limits/quotas
   - Authentication/authorization

4. **Operational Enhancements**:
   - Automatic result expiration
   - Task deduplication
   - Circuit breakers
   - Backpressure handling
