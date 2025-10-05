# Distributed Function-as-a-Service Platform

A distributed Function-as-a-Service (FaaS) platform implementation using Python, FastAPI, Redis, and ZMQ. This project provides serverless function execution with three execution modes: Local, Pull, and Push.

## Features

- **Multiple Execution Modes**: Local (multiprocessing), Pull (worker-initiated), and Push (dispatcher-initiated)
- **Fault Tolerance**: Automatic worker failure detection and task recovery
- **RESTful API**: FastAPI-based service for function management
- **Distributed Architecture**: ZMQ-based communication between components
- **Performance Monitoring**: Comprehensive benchmarking and visualization tools
- **Serialization Support**: Dill-based function serialization for Python objects

## Architecture

![image](https://github.com/user-attachments/assets/7aeb2479-d1c3-4e5b-8115-b7075d77328f)

## Prerequisites

- Python 3.12 or higher
- Redis server (6.x or higher)
- Conda installed
- Unix-like OS (Linux/macOS) or WSL2 for Windows

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/mpcs-52040/mpcsfaas-project-peili.git
cd mpcsfaas
```

### 2. Create Conda Environment

```bash
# Create a new conda environment with Python 3.12
conda create -n mpcsfaas python=3.12
conda activate mpcsfaas
```

### 3. Install Dependencies

```bash
# Install all required packages
pip install -r requirements.txt
```

### 4. Install Redis (if not already installed)

**macOS:**
```bash
brew install redis
brew services start redis
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis-server
```

**Using Conda:**
```bash
conda install -c conda-forge redis
```

## Quick Start

### 1. Start Redis Server

```bash
# Check if Redis is running
redis-cli ping

# If not running, start it:
redis-server
```

### 2. Start the FastAPI Service

```bash
uvicorn main:app --reload 
```

### 3. Start the Task Dispatcher (choose one mode)

**Local Mode:**
```bash
python task_dispatcher.py -m local -w 5
```

**Pull Mode:**
```bash
python task_dispatcher.py -m pull -p 5555
```

**Push Mode:**
```bash
python task_dispatcher.py -m push -p 5555
```

### 4. Start Workers (for Pull/Push modes only)

**Pull Workers:**
```bash
# Terminal 1
python pull_worker.py 2 tcp://localhost:5555

# Terminal 2 (optional, for multiple workers)
python pull_worker.py 2 tcp://localhost:5555
```

**Push Workers:**
```bash
# Terminal 1
python push_worker.py 2 tcp://localhost:5555

# Terminal 2 (optional, for multiple workers)
python push_worker.py 2 tcp://localhost:5555
```

## Running the System

### Basic Function Registration and Execution

```python
import requests
from utils import serialize, deserialize

# Define a function
def hello(name):
    return f"Hello, {name}!"

# Register the function
response = requests.post(
    "http://127.0.0.1:8000/register_function",
    json={"name": "hello", "payload": serialize(hello)}
)
function_id = response.json()["function_id"]

# Execute the function
response = requests.post(
    "http://127.0.0.1:8000/execute_function",
    json={"function_id": function_id, "payload": serialize((("World",), {}))}
)
task_id = response.json()["task_id"]

# Get the result
response = requests.get(f"http://127.0.0.1:8000/result/{task_id}")
result = deserialize(response.json()["result"])
print(result)  # Output: Hello, World!
```

### API Endpoints

- `POST /register_function` - Register a new function
- `POST /execute_function` - Execute a registered function
- `GET /status/{task_id}` - Get task status
- `GET /result/{task_id}` - Get task result

## Running Tests

### 1. Basic Test Suite

```bash
# Run all tests
pytest tests/

# Run specific test files
pytest tests/test_webservice.py
pytest tests/test_comprehensive.py
pytest tests/test_workers.py
pytest tests/test_fault_tolerance.py

# Run with verbose output
pytest -v tests/

# Run with coverage
pytest --cov=. tests/
```

### 2. Test Categories

**Unit Tests:**
```bash
pytest tests/test_webservice.py -v
```

**Integration Tests:**
```bash
# Start services first (Redis, FastAPI, Dispatcher)
pytest tests/test_comprehensive.py -v
```

**Worker Tests:**
```bash
# Test pull workers
pytest tests/test_workers.py::test_pull_worker_integration -v

# Test push workers
pytest tests/test_workers.py::test_push_worker_integration -v
```

**Fault Tolerance Tests:**
```bash
pytest tests/test_fault_tolerance.py -v
```

## Performance Evaluation

### 1. Run Complete Performance Evaluation

```bash
# Ensure FastAPI and Redis are running first
python client.py
```

This will:
- Run weak scaling studies for all modes
- Test different workload types (no-op, CPU, I/O)
- Generate performance visualizations
- Create detailed reports

### 2. Generated Output Files

- `comprehensive_performance_results.png` - Multi-panel performance visualization
- `performance_analysis.md` - Detailed performance analysis
- `performance_results.json` - Raw performance data

### 3. Generate Additional Performance Visualizations

After running the performance evaluation, you can generate more detailed plots:

```bash
# Generate additional performance analysis plots
python plot.py
```

This will create four additional visualization files:
- `overhead_analysis.png` - Detailed communication overhead analysis
- `scaling_efficiency_analysis.png` - Scaling efficiency with power law fitting
- `latency_percentiles.png` - Box plots of latency distributions
- `workload_comparison.png` - Side-by-side workload performance metrics

### 4. Understanding the Visualization Results

**Overhead Analysis**: Shows the additional latency introduced by network communication compared to local execution.

**Scaling Efficiency**: Demonstrates how well the system scales with additional workers, including power law fitting to quantify scaling behavior.

**Latency Percentiles**: Box plots showing the distribution of latencies, helping identify outliers and performance consistency.

**Workload Comparison**: Direct comparison of different metrics (throughput, latency, success rate) across all modes and task types.

### 5. Custom Performance Tests

```python
from client import PerformanceEvaluator

# Create evaluator
evaluator = PerformanceEvaluator()

# Run specific tests
results = evaluator.weak_scaling_study('local', [1, 2, 4, 8], tasks_per_worker=5)

# Generate plots
evaluator.plot_comprehensive_results(results)
```

## Project Structure

```
mpcsfaas/
├── main.py                 # FastAPI web service
├── task_dispatcher.py      # Task distribution logic
├── pull_worker.py          # Pull mode worker implementation
├── push_worker.py          # Push mode worker implementation
├── utils.py                # Serialization utilities
├── client.py               # Performance evaluation client
├── plot.py                 # Additional performance visualizations
├── requirements.txt        # Python dependencies
├── tests/                  # Test suite
│   ├── conftest.py        # Test fixtures
│   ├── serialize.py       # Test utilities
│   ├── test_webservice.py # API tests
│   ├── test_comprehensive.py # Integration tests
│   ├── test_workers.py    # Worker tests
│   └── test_fault_tolerance.py # Fault tolerance tests
└── reports/               # Generated reports
    ├── technical_report.md
    ├── testing_report.md
    └── performance_report.md
```

## Troubleshooting

### Common Issues

**1. Redis Connection Error:**
```bash
# Check if Redis is running
redis-cli ping

# Start Redis if needed
redis-server
```

**2. Port Already in Use:**
```bash
# Find process using port
lsof -i :8000  # For FastAPI
lsof -i :5555  # For ZMQ

# Kill process if needed
kill -9 <PID>
```

**3. Worker Registration Failed:**
- Ensure dispatcher is running before starting workers
- Check ZMQ URL format: `tcp://localhost:5555`
- Verify firewall settings

**4. Test Failures:**
- Clean Redis before tests: `redis-cli FLUSHALL`
- Ensure no services running from previous tests
- Check for zombie processes: `ps aux | grep python`

**5. Performance Test Hanging:**
- Reduce number of tasks or workers
- Check system resources (CPU, memory)
- Kill stuck processes and restart

### Debug Mode

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Clean Shutdown

```bash
# Stop all services in order:
# 1. Stop workers (Ctrl+C)
# 2. Stop dispatcher (Ctrl+C)
# 3. Stop FastAPI (Ctrl+C)
# 4. Stop Redis (if needed)
redis-cli shutdown
```

## Development Tips

1. **Virtual Environment Alternative:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   venv\Scripts\activate     # Windows
   pip install -r requirements.txt
   ```

2. **Running Multiple Workers:**
   Use screen or tmux for managing multiple terminal sessions

3. **Monitoring:**
   - Redis: `redis-cli MONITOR`
   - FastAPI: Check http://127.0.0.1:8000/docs
   - System: `htop` or `top`

4. **Custom Functions:**
   - Ensure functions are serializable
   - Avoid global dependencies
   - Return serializable results

## License

This project is part of MPCS 52040 Distributed Systems coursework.

