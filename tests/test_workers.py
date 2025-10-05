import pytest
import time
import subprocess
import sys
import requests
import signal
import os
from .serialize import serialize, deserialize

base_url = "http://127.0.0.1:8000/"

@pytest.fixture(scope="function")
def pull_dispatcher():
    """Start task dispatcher in pull mode"""
    proc = subprocess.Popen([
        sys.executable, "task_dispatcher.py", "-m", "pull", "-p", "5556"
    ])
    time.sleep(2)  # Give time to start
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

@pytest.fixture(scope="function")
def push_dispatcher():
    """Start task dispatcher in push mode"""
    proc = subprocess.Popen([
        sys.executable, "task_dispatcher.py", "-m", "push", "-p", "5557"
    ])
    time.sleep(2)  # Give time to start
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

@pytest.fixture(scope="function")
def pull_worker():
    """Start a pull worker"""
    proc = subprocess.Popen([
        sys.executable, "pull_worker.py", "2", "tcp://localhost:5556"
    ])
    time.sleep(2)  # Give time to start and register
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

@pytest.fixture(scope="function")
def push_worker():
    """Start a push worker"""
    proc = subprocess.Popen([
        sys.executable, "push_worker.py", "2", "tcp://localhost:5557"
    ])
    time.sleep(2)  # Give time to start and register
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

def test_pull_worker_integration(fastapi_server, clean_redis, pull_dispatcher, pull_worker):
    """Test integration with pull workers"""
    def multiply(a, b):
        return a * b
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "multiply", "payload": serialize(multiply)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Execute function
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((6, 7), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Wait for completion
    for _ in range(50):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        assert response.status_code == 200
        
        if response.json()["status"] == "COMPLETED":
            result = deserialize(response.json()["result"])
            assert result == 42
            break
        elif response.json()["status"] == "FAILED":
            pytest.fail(f"Task failed: {response.json()['result']}")
        time.sleep(0.2)
    else:
        pytest.fail("Task did not complete in time")

def test_push_worker_integration(fastapi_server, clean_redis, push_dispatcher, push_worker):
    """Test integration with push workers"""
    def power(base, exp):
        return base ** exp
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "power", "payload": serialize(power)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Execute function
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((2, 8), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Wait for completion
    for _ in range(50):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        assert response.status_code == 200
        
        if response.json()["status"] == "COMPLETED":
            result = deserialize(response.json()["result"])
            assert result == 256
            break
        elif response.json()["status"] == "FAILED":
            pytest.fail(f"Task failed: {response.json()['result']}")
        time.sleep(0.2)
    else:
        pytest.fail("Task did not complete in time")

def test_multiple_pull_workers(fastapi_server, clean_redis, pull_dispatcher):
    """Test with multiple pull workers"""
    # Start multiple workers
    workers = []
    for i in range(3):
        proc = subprocess.Popen([
            sys.executable, "pull_worker.py", "2", "tcp://localhost:5556"
        ])
        workers.append(proc)
    
    time.sleep(3)  # Give time for workers to register
    
    try:
        def slow_task(n):
            import time
            time.sleep(0.2)  # Simulate work
            return n * 2
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "slow_task", "payload": serialize(slow_task)}
        )
        assert response.status_code in [200, 201]
        function_id = response.json()["function_id"]
        
        # Submit multiple tasks
        task_ids = []
        for i in range(8):  # More tasks than workers
            response = requests.post(
                fastapi_server + "/execute_function",
                json={"function_id": function_id, "payload": serialize(((i,), {}))}
            )
            assert response.status_code in [200, 201]
            task_ids.append(response.json()["task_id"])
        
        # Wait for all tasks to complete
        completed = 0
        for _ in range(100):  # 10 seconds max
            for task_id in task_ids:
                response = requests.get(fastapi_server + f"/status/{task_id}")
                if response.json()["status"] in ["COMPLETED", "FAILED"]:
                    completed += 1
            
            if completed >= len(task_ids):
                break
            completed = 0
            time.sleep(0.1)
        
        assert completed >= len(task_ids), "Not all tasks completed"
        
        # Verify results
        for i, task_id in enumerate(task_ids):
            response = requests.get(fastapi_server + f"/result/{task_id}")
            if response.json()["status"] == "COMPLETED":
                result = deserialize(response.json()["result"])
                assert result == i * 2
    
    finally:
        # Cleanup workers
        for worker in workers:
            try:
                worker.terminate()
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()

def test_multiple_push_workers(fastapi_server, clean_redis, push_dispatcher):
    """Test with multiple push workers"""
    # Start multiple workers
    workers = []
    for i in range(3):
        proc = subprocess.Popen([
            sys.executable, "push_worker.py", "2", "tcp://localhost:5557"
        ])
        workers.append(proc)
    
    time.sleep(3)  # Give time for workers to register
    
    try:
        def slow_task(n):
            import time
            time.sleep(0.2)  # Simulate work
            return n * 3
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "slow_task", "payload": serialize(slow_task)}
        )
        assert response.status_code in [200, 201]
        function_id = response.json()["function_id"]
        
        # Submit multiple tasks
        task_ids = []
        for i in range(8):  # More tasks than workers
            response = requests.post(
                fastapi_server + "/execute_function",
                json={"function_id": function_id, "payload": serialize(((i,), {}))}
            )
            assert response.status_code in [200, 201]
            task_ids.append(response.json()["task_id"])
        
        # Wait for all tasks to complete
        completed = 0
        for _ in range(100):  # 10 seconds max
            for task_id in task_ids:
                response = requests.get(fastapi_server + f"/status/{task_id}")
                if response.json()["status"] in ["COMPLETED", "FAILED"]:
                    completed += 1
            
            if completed >= len(task_ids):
                break
            completed = 0
            time.sleep(0.1)
        
        assert completed >= len(task_ids), "Not all tasks completed"
        
        # Verify results
        for i, task_id in enumerate(task_ids):
            response = requests.get(fastapi_server + f"/result/{task_id}")
            if response.json()["status"] == "COMPLETED":
                result = deserialize(response.json()["result"])
                assert result == i * 3
    
    finally:
        # Cleanup workers
        for worker in workers:
            try:
                worker.terminate()
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()