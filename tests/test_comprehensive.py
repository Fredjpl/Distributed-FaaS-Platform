import pytest
import time
import json
import requests
from .serialize import serialize, deserialize
import uuid

base_url = "http://127.0.0.1:8000/"

def test_redis_connection(clean_redis):
    """Test Redis connection"""
    assert clean_redis.ping()

def test_server_health(fastapi_server):
    """Test server is running"""
    response = requests.get(fastapi_server + "/")
    assert response.status_code == 200
    assert "MPCSFaaS" in response.json()["message"]

def test_function_registration_success(fastapi_server, clean_redis, task_dispatcher):
    """Test successful function registration"""
    def add_numbers(a, b):
        return a + b
    
    serialized_fn = serialize(add_numbers)
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "add_numbers", "payload": serialized_fn}
    )
    
    assert response.status_code in [200, 201]
    data = response.json()
    assert "function_id" in data
    
    # Verify function is stored in Redis
    function_id = data["function_id"]
    stored_data = clean_redis.get(f"function:{function_id}")
    assert stored_data is not None
    
    stored_function = json.loads(stored_data)
    assert stored_function["name"] == "add_numbers"

def test_function_registration_invalid_payload(fastapi_server):
    """Test function registration with invalid payload"""
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "invalid", "payload": "not_a_function"}
    )
    
    assert response.status_code in [400, 500]

def test_function_execution_not_found(fastapi_server):
    """Test executing non-existent function"""
    fake_id = str(uuid.uuid4())
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": fake_id, "payload": serialize(((1, 2), {}))}
    )
    
    assert response.status_code == 404

def test_task_status_not_found(fastapi_server):
    """Test getting status of non-existent task"""
    fake_id = str(uuid.uuid4())
    response = requests.get(fastapi_server + f"/status/{fake_id}")
    
    assert response.status_code == 404

def test_task_result_not_found(fastapi_server):
    """Test getting result of non-existent task"""
    fake_id = str(uuid.uuid4())
    response = requests.get(fastapi_server + f"/result/{fake_id}")
    
    assert response.status_code == 404

def test_redis_error_handling(fastapi_server, clean_redis, task_dispatcher):
        """Test system behavior when Redis operations fail"""
        # This test simulates Redis errors by using invalid data
        
        # Test getting status of malformed task data
        malformed_task_id = "malformed-task-id"
        clean_redis.set(f"task:{malformed_task_id}", "invalid json data")
        
        response = requests.get(fastapi_server + f"/status/{malformed_task_id}")
        assert response.status_code == 422  # Should handle the error gracefully

def test_function_execution_error_handling(fastapi_server, clean_redis, task_dispatcher):
    """Test handling of function execution errors"""
    def error_function():
        raise ValueError("Intentional error for testing")
    
    def division_by_zero(a, b):
        return a / b
    
    def runtime_error():
        undefined_variable.some_method()  # This will cause NameError
    
    # Test ValueError
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "error_function", "payload": serialize(error_function)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Wait for task to fail
    for _ in range(30):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        if response.json()["status"] == "FAILED":
            error_msg = deserialize(response.json()["result"])
            assert "Intentional error for testing" in error_msg
            break
        time.sleep(0.1)
    else:
        pytest.fail("Task should have failed but didn't")

    # Test division by zero
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "division_by_zero", "payload": serialize(division_by_zero)}
    )
    function_id = response.json()["function_id"]
    
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((10, 0), {}))}
    )
    task_id = response.json()["task_id"]
    
    for _ in range(30):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        if response.json()["status"] == "FAILED":
            break
        time.sleep(0.1)
    else:
        pytest.fail("Division by zero should have failed")

    # Test runtime error
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "runtime_error", "payload": serialize(runtime_error)}
    )
    function_id = response.json()["function_id"]
    
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((), {}))}
    )
    task_id = response.json()["task_id"]
    
    for _ in range(30):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        if response.json()["status"] == "FAILED":
            break
        time.sleep(0.1)
    else:
        pytest.fail("Runtime error should have failed")

def test_invalid_parameter_handling(fastapi_server, clean_redis, task_dispatcher):
    """Test handling of invalid parameters during execution"""
    def simple_add(a, b):
        return a + b
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "simple_add", "payload": serialize(simple_add)}
    )
    function_id = response.json()["function_id"]
    
    # Test with invalid parameter payload
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": "invalid_params"}
    )
    assert response.status_code in [400, 500]  # Bad request

def test_complex_function_execution(fastapi_server, clean_redis, task_dispatcher):
    """Test execution of a more complex function"""
    def fibonacci(n):
        if n <= 1:
            return n
        return fibonacci(n-1) + fibonacci(n-2)
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "fibonacci", "payload": serialize(fibonacci)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Execute function
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((7,), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Wait for completion and get result
    for _ in range(50):  # Wait up to 5 seconds
        response = requests.get(fastapi_server + f"/result/{task_id}")
        assert response.status_code == 200
        
        if response.json()["status"] in ["COMPLETED", "FAILED"]:
            result = deserialize(response.json()["result"])
            assert result == 13  # fibonacci(7) = 13
            break
        time.sleep(0.1)
    else:
        pytest.fail("Task did not complete in time")

def test_function_with_exception(fastapi_server, clean_redis, task_dispatcher):
    """Test function that raises an exception"""
    def failing_function():
        raise ValueError("This function always fails")
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "failing_function", "payload": serialize(failing_function)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Execute function
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Wait for completion and check it failed
    for _ in range(30):
        response = requests.get(fastapi_server + f"/result/{task_id}")
        assert response.status_code == 200
        
        if response.json()["status"] == "FAILED":
            error_message = deserialize(response.json()["result"])
            assert "This function always fails" in error_message
            break
        elif response.json()["status"] == "COMPLETED":
            pytest.fail("Expected task to fail but it completed")
        time.sleep(0.1)
    else:
        pytest.fail("Task did not complete in time")

def test_multiple_concurrent_tasks(fastapi_server, clean_redis, task_dispatcher):
    """Test multiple tasks executing concurrently"""
    def slow_function(n, sleep_time=0.1):
        import time
        time.sleep(sleep_time)
        return n * 2
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "slow_function", "payload": serialize(slow_function)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Submit multiple tasks
    task_ids = []
    for i in range(5):
        response = requests.post(
            fastapi_server + "/execute_function",
            json={"function_id": function_id, "payload": serialize(((i,), {"sleep_time": 0.1}))}
        )
        assert response.status_code in [200, 201]
        task_ids.append(response.json()["task_id"])
    
    # Wait for all tasks to complete
    completed_tasks = 0
    for _ in range(100):  # Wait up to 10 seconds
        for task_id in task_ids:
            response = requests.get(fastapi_server + f"/status/{task_id}")
            if response.json()["status"] in ["COMPLETED", "FAILED"]:
                completed_tasks += 1
        
        if completed_tasks >= len(task_ids):
            break
        completed_tasks = 0  # Reset for next iteration
        time.sleep(0.1)
    
    assert completed_tasks >= len(task_ids), "Not all tasks completed in time"

def test_task_lifecycle_status_progression(fastapi_server, clean_redis, task_dispatcher):
    """Test that task progresses through correct status lifecycle"""
    def simple_function(x):
        import time
        time.sleep(3)  
        return x + 1
    
    # Register function
    response = requests.post(
        fastapi_server + "/register_function",
        json={"name": "simple_function", "payload": serialize(simple_function)}
    )
    assert response.status_code in [200, 201]
    function_id = response.json()["function_id"]
    
    # Execute function
    response = requests.post(
        fastapi_server + "/execute_function",
        json={"function_id": function_id, "payload": serialize(((5,), {}))}
    )
    assert response.status_code in [200, 201]
    task_id = response.json()["task_id"]
    
    # Check initial status should be QUEUED
    response = requests.get(fastapi_server + f"/status/{task_id}")
    assert response.status_code == 200
    initial_status = response.json()["status"]
    assert initial_status in ["QUEUED", "RUNNING"], f"Expected QUEUED or RUNNING, got {initial_status}"
    
    # Wait for completion
    final_status = None
    for _ in range(30):
        response = requests.get(fastapi_server + f"/status/{task_id}")
        status = response.json()["status"]
        if status in ["COMPLETED", "FAILED"]:
            final_status = status
            break
        time.sleep(0.1)
    
    assert final_status == "COMPLETED", f"Expected COMPLETED, got {final_status}"
    
    # Verify result
    response = requests.get(fastapi_server + f"/result/{task_id}")
    result = deserialize(response.json()["result"])
    assert result == 6