import pytest
import time
import subprocess
import sys
import redis
import requests


@pytest.fixture(scope="session")
def redis_server():
    """Ensure Redis is running for tests"""
    try:
        # Try to connect to Redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("Redis is already running")
        yield r
    except redis.ConnectionError:
        pytest.skip("Redis server is not running. Please start Redis with 'redis-server'")

@pytest.fixture(scope="session")
def fastapi_server(redis_server):
    """Start FastAPI server for testing"""
    # Start the FastAPI server
    proc = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "main:app", 
        "--host", "127.0.0.1", "--port", "8000"
    ])
    
    # Wait for server to start
    for _ in range(30):  # Wait up to 30 seconds
        try:
            response = requests.get("http://127.0.0.1:8000/")
            if response.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(1)
    else:
        proc.terminate()
        pytest.fail("FastAPI server failed to start")
    
    yield "http://127.0.0.1:8000"
    
    # Cleanup
    proc.terminate()
    proc.wait()

@pytest.fixture(scope="session")
def task_dispatcher():
    """Start task dispatcher in local mode for testing"""
    proc = subprocess.Popen([
        sys.executable, "task_dispatcher.py", "-m", "local", "-w", "2"
    ])
    
    # Give dispatcher time to start
    time.sleep(2)
    
    yield proc
    
    # Cleanup
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

@pytest.fixture
def clean_redis(redis_server):
    """Clean Redis before each test"""
    # Clear all keys that might be left from previous tests
    for key in redis_server.scan_iter("function:*"):
        redis_server.delete(key)
    for key in redis_server.scan_iter("task:*"):
        redis_server.delete(key)
    yield redis_server