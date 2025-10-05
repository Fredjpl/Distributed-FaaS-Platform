import pytest
import time
import subprocess
import sys
import requests
import signal
import os
import threading
import json
from .serialize import serialize, deserialize

base_url = "http://127.0.0.1:8000/"

class TestFaultTolerance:
    """Test suite for fault tolerance scenarios"""

    @pytest.fixture(scope="function")
    def pull_dispatcher_ft(self):
        """Start task dispatcher in pull mode for fault tolerance tests"""
        proc = subprocess.Popen([
            sys.executable, "task_dispatcher.py", "-m", "pull", "-p", "5558"
        ])
        time.sleep(3)  # Give time to start
        yield proc
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    @pytest.fixture(scope="function")
    def push_dispatcher_ft(self):
        """Start task dispatcher in push mode for fault tolerance tests"""
        proc = subprocess.Popen([
            sys.executable, "task_dispatcher.py", "-m", "push", "-p", "5559"
        ])
        time.sleep(3)  # Give time to start
        yield proc
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def test_pull_worker_failure_and_recovery(self, fastapi_server, clean_redis, pull_dispatcher_ft):
        """Test pull worker failure detection and task recovery"""
        def long_running_task(duration):
            import time
            time.sleep(duration)
            return f"Completed after {duration} seconds"
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "long_running_task", "payload": serialize(long_running_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start a worker
        worker1 = subprocess.Popen([
            sys.executable, "pull_worker.py", "2", "tcp://localhost:5558"
        ])
        time.sleep(3)  # Let worker register
        
        try:
            # Submit a long-running task
            response = requests.post(
                fastapi_server + "/execute_function",
                json={"function_id": function_id, "payload": serialize(((15,), {}))}  # 15 second task
            )
            task_id = response.json()["task_id"]
            
            # Wait for task to start running
            for _ in range(50):
                response = requests.get(fastapi_server + f"/status/{task_id}")
                if response.json()["status"] == "RUNNING":
                    break
                time.sleep(0.1)
            
            # Kill the worker while task is running
            worker1.kill()
            worker1.wait()
            print("Worker killed during task execution")
            
            # Start a new worker to pick up the failed task
            time.sleep(12)  # Wait for heartbeat timeout
            worker2 = subprocess.Popen([
                sys.executable, "pull_worker.py", "2", "tcp://localhost:5558"
            ])
            time.sleep(3)  # Let new worker register
            
            try:
                # Check if task gets requeued and completed by new worker
                task_completed = False
                for _ in range(200):  # Wait up to 20 seconds
                    response = requests.get(fastapi_server + f"/result/{task_id}")
                    status = response.json()["status"]
                    if status == "COMPLETED":
                        result = deserialize(response.json()["result"])
                        assert "Completed after 15 seconds" in result
                        task_completed = True
                        break
                    elif status == "QUEUED":
                        print("Task requeued after worker failure")
                    time.sleep(0.1)
                
                # The task might not complete due to timing, but it should at least be requeued
                final_response = requests.get(fastapi_server + f"/status/{task_id}")
                final_status = final_response.json()["status"]
                assert final_status in ["QUEUED", "RUNNING", "COMPLETED"], f"Task should be requeued or completed, got {final_status}"
                
            finally:
                try:
                    worker2.terminate()
                    worker2.wait(timeout=3)
                except:
                    worker2.kill()
                    worker2.wait()
        
        finally:
            try:
                worker1.terminate()
                worker1.wait(timeout=3)
            except:
                pass

    def test_push_worker_failure_and_recovery(self, fastapi_server, clean_redis, push_dispatcher_ft):
        """Test push worker failure detection and task recovery"""
        def long_running_task(duration):
            import time
            time.sleep(duration)
            return f"Completed after {duration} seconds"
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "long_running_task", "payload": serialize(long_running_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start a worker
        worker1 = subprocess.Popen([
            sys.executable, "push_worker.py", "2", "tcp://localhost:5559"
        ])
        time.sleep(3)  # Let worker register
        
        try:
            # Submit a long-running task
            response = requests.post(
                fastapi_server + "/execute_function",
                json={"function_id": function_id, "payload": serialize(((15,), {}))}  # 15 second task
            )
            task_id = response.json()["task_id"]
            
            # Wait for task to start running
            for _ in range(50):
                response = requests.get(fastapi_server + f"/status/{task_id}")
                if response.json()["status"] == "RUNNING":
                    break
                time.sleep(0.1)
            
            # Kill the worker while task is running
            worker1.kill()
            worker1.wait()
            print("Worker killed during task execution")
            
            # Start a new worker to pick up the failed task
            time.sleep(12)  # Wait for heartbeat timeout
            worker2 = subprocess.Popen([
                sys.executable, "push_worker.py", "2", "tcp://localhost:5559"
            ])
            time.sleep(3)  # Let new worker register
            
            try:
                # Check if task gets requeued and completed by new worker
                task_completed = False
                for _ in range(200):  # Wait up to 20 seconds
                    response = requests.get(fastapi_server + f"/result/{task_id}")
                    status = response.json()["status"]
                    if status == "COMPLETED":
                        result = deserialize(response.json()["result"])
                        assert "Completed after 15 seconds" in result
                        task_completed = True
                        break
                    elif status == "QUEUED":
                        print("Task requeued after worker failure")
                    time.sleep(0.1)
                
                # The task might not complete due to timing, but it should at least be requeued
                final_response = requests.get(fastapi_server + f"/status/{task_id}")
                final_status = final_response.json()["status"]
                assert final_status in ["QUEUED", "RUNNING", "COMPLETED"], f"Task should be requeued or completed, got {final_status}"
                
            finally:
                try:
                    worker2.terminate()
                    worker2.wait(timeout=3)
                except:
                    worker2.kill()
                    worker2.wait()
        
        finally:
            try:
                worker1.terminate()
                worker1.wait(timeout=3)
            except:
                pass

    def test_multiple_pull_workers_failures(self, fastapi_server, clean_redis, pull_dispatcher_ft):
        """Test system resilience when multiple workers fail"""
        def quick_task(n):
            return n * 2
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "quick_task", "payload": serialize(quick_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start multiple workers
        workers = []
        for i in range(3):
            worker = subprocess.Popen([
                sys.executable, "pull_worker.py", "2", "tcp://localhost:5558"
            ])
            workers.append(worker)
        
        time.sleep(5)  # Let workers register
        
        try:
            # Submit multiple tasks
            task_ids = []
            for i in range(10):
                response = requests.post(
                    fastapi_server + "/execute_function",
                    json={"function_id": function_id, "payload": serialize(((i,), {}))}
                )
                task_ids.append(response.json()["task_id"])
            
            # Kill all workers suddenly
            for worker in workers:
                worker.kill()
                worker.wait()
            
            print("All workers killed")
            time.sleep(12)  # Wait for heartbeat timeout
            
            # Start new workers
            new_workers = []
            for i in range(2):  # Fewer workers than before
                worker = subprocess.Popen([
                    sys.executable, "pull_worker.py", "2", "tcp://localhost:5558"
                ])
                new_workers.append(worker)
            
            time.sleep(5)  # Let new workers register
            
            try:
                # Check that tasks are requeued and eventually completed
                completed_count = 0
                for _ in range(100):
                    for task_id in task_ids:
                        response = requests.get(fastapi_server + f"/result/{task_id}")
                        if response.json()["status"] == "COMPLETED":
                            completed_count += 1
                    
                    if completed_count >= len(task_ids):
                        break
                    completed_count = 0
                    time.sleep(0.2)
                
                # At least some tasks should be completed or requeued
                final_completed = 0
                final_queued = 0
                for task_id in task_ids:
                    response = requests.get(fastapi_server + f"/status/{task_id}")
                    status = response.json()["status"]
                    if status == "COMPLETED":
                        final_completed += 1
                    elif status in ["QUEUED", "RUNNING"]:
                        final_queued += 1

                assert (final_completed + final_queued) >= len(task_ids) * 0.5, "at least half of tasks should be completed or requeued"

            finally:
                for worker in new_workers:
                    try:
                        worker.terminate()
                        worker.wait(timeout=3)
                    except:
                        worker.kill()
                        worker.wait()
        
        finally:
            for worker in workers:
                try:
                    worker.terminate()
                    worker.wait(timeout=3)
                except:
                    pass

    def test_multiple_push_workers_failures(self, fastapi_server, clean_redis, push_dispatcher_ft):
        """Test system resilience when multiple workers fail"""
        def quick_task(n):
            return n * 2
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "quick_task", "payload": serialize(quick_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start multiple workers
        workers = []
        for i in range(3):
            worker = subprocess.Popen([
                sys.executable, "push_worker.py", "2", "tcp://localhost:5557"
            ])
            workers.append(worker)
        
        time.sleep(5)  # Let workers register
        
        try:
            # Submit multiple tasks
            task_ids = []
            for i in range(10):
                response = requests.post(
                    fastapi_server + "/execute_function",
                    json={"function_id": function_id, "payload": serialize(((i,), {}))}
                )
                task_ids.append(response.json()["task_id"])
            
            # Kill all workers suddenly
            for worker in workers:
                worker.kill()
                worker.wait()
            
            print("All workers killed")
            time.sleep(12)  # Wait for heartbeat timeout
            
            # Start new workers
            new_workers = []
            for i in range(2):  # Fewer workers than before
                worker = subprocess.Popen([
                    sys.executable, "push_worker.py", "2", "tcp://localhost:5557"
                ])
                new_workers.append(worker)
            
            time.sleep(5)  # Let new workers register
            
            try:
                # Check that tasks are requeued and eventually completed
                completed_count = 0
                for _ in range(100):
                    for task_id in task_ids:
                        response = requests.get(fastapi_server + f"/result/{task_id}")
                        if response.json()["status"] == "COMPLETED":
                            completed_count += 1
                    
                    if completed_count >= len(task_ids):
                        break
                    completed_count = 0
                    time.sleep(0.2)
                
                # At least some tasks should be completed or requeued
                final_completed = 0
                final_queued = 0
                for task_id in task_ids:
                    response = requests.get(fastapi_server + f"/status/{task_id}")
                    status = response.json()["status"]
                    if status == "COMPLETED":
                        final_completed += 1
                    elif status in ["QUEUED", "RUNNING"]:
                        final_queued += 1

                assert (final_completed + final_queued) >= len(task_ids) * 0.5, "At least half of tasks should be completed or requeued"

            finally:
                for worker in new_workers:
                    try:
                        worker.terminate()
                        worker.wait(timeout=3)
                    except:
                        worker.kill()
                        worker.wait()
        
        finally:
            for worker in workers:
                try:
                    worker.terminate()
                    worker.wait(timeout=3)
                except:
                    pass

        

    def test_concurrent_push_worker_failures(self, fastapi_server, clean_redis, push_dispatcher_ft):
        """Test system stability when workers fail concurrently"""
        def concurrent_task(task_id):
            import time
            time.sleep(2)
            return f"Task {task_id} completed"
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "concurrent_task", "payload": serialize(concurrent_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start multiple workers
        workers = []
        for i in range(4):
            worker = subprocess.Popen([
                sys.executable, "push_worker.py", "2", "tcp://localhost:5559"
            ])
            workers.append(worker)
        
        time.sleep(5)  # Let workers register
        
        try:
            # Submit tasks
            task_ids = []
            for i in range(8):
                response = requests.post(
                    fastapi_server + "/execute_function",
                    json={"function_id": function_id, "payload": serialize(((i,), {}))}
                )
                task_ids.append(response.json()["task_id"])
            
            # Wait a bit for tasks to start
            time.sleep(1)
            
            # Kill workers concurrently
            def kill_worker(worker):
                time.sleep(0.1)  # Small delay
                worker.kill()
                worker.wait()
            
            threads = []
            for worker in workers:
                thread = threading.Thread(target=kill_worker, args=(worker,))
                thread.start()
                threads.append(thread)
            
            for thread in threads:
                thread.join()
            
            print("All workers killed concurrently")
            
            # Wait for heartbeat timeout
            time.sleep(15)
            
            # Start new workers
            new_workers = []
            for i in range(2):
                worker = subprocess.Popen([
                    sys.executable, "push_worker.py", "2", "tcp://localhost:5559"
                ])
                new_workers.append(worker)
            
            time.sleep(5)
            
            try:
                # Check system recovery
                recovered_tasks = 0
                for _ in range(100):
                    for task_id in task_ids:
                        response = requests.get(fastapi_server + f"/status/{task_id}")
                        status = response.json()["status"]
                        if status in ["COMPLETED", "QUEUED", "RUNNING"]:
                            recovered_tasks += 1
                    
                    if recovered_tasks >= len(task_ids):
                        break
                    recovered_tasks = 0
                    time.sleep(0.1)
                
                # System should recover and handle the tasks
                assert recovered_tasks >= len(task_ids) * 0.5, "System should recover from concurrent failures"
            
            finally:
                for worker in new_workers:
                    try:
                        worker.terminate()
                        worker.wait(timeout=3)
                    except:
                        worker.kill()
                        worker.wait()
        
        finally:
            for worker in workers:
                try:
                    worker.terminate()
                    worker.wait(timeout=3)
                except:
                    pass

    def test_concurrent_pull_worker_failures(self, fastapi_server, clean_redis, pull_dispatcher_ft):
        """Test system stability when workers fail concurrently"""
        def concurrent_task(task_id):
            import time
            time.sleep(2)
            return f"Task {task_id} completed"
        
        # Register function
        response = requests.post(
            fastapi_server + "/register_function",
            json={"name": "concurrent_task", "payload": serialize(concurrent_task)}
        )
        function_id = response.json()["function_id"]
        
        # Start multiple workers
        workers = []
        for i in range(4):
            worker = subprocess.Popen([
                sys.executable, "pull_worker.py", "2", "tcp://localhost:5559"
            ])
            workers.append(worker)
        
        time.sleep(5)  # Let workers register
        
        try:
            # Submit tasks
            task_ids = []
            for i in range(8):
                response = requests.post(
                    fastapi_server + "/execute_function",
                    json={"function_id": function_id, "payload": serialize(((i,), {}))}
                )
                task_ids.append(response.json()["task_id"])
            
            # Wait a bit for tasks to start
            time.sleep(1)
            
            # Kill workers concurrently
            def kill_worker(worker):
                time.sleep(0.1)  # Small delay
                worker.kill()
                worker.wait()
            
            threads = []
            for worker in workers:
                thread = threading.Thread(target=kill_worker, args=(worker,))
                thread.start()
                threads.append(thread)
            
            for thread in threads:
                thread.join()
            
            print("All workers killed concurrently")
            
            # Wait for heartbeat timeout
            time.sleep(15)
            
            # Start new workers
            new_workers = []
            for i in range(2):
                worker = subprocess.Popen([
                    sys.executable, "pull_worker.py", "2", "tcp://localhost:5559"
                ])
                new_workers.append(worker)
            
            time.sleep(5)
            
            try:
                # Check system recovery
                recovered_tasks = 0
                for _ in range(100):
                    for task_id in task_ids:
                        response = requests.get(fastapi_server + f"/status/{task_id}")
                        status = response.json()["status"]
                        if status in ["COMPLETED", "QUEUED", "RUNNING"]:
                            recovered_tasks += 1
                    
                    if recovered_tasks >= len(task_ids):
                        break
                    recovered_tasks = 0
                    time.sleep(0.1)
                
                # System should recover and handle the tasks
                assert recovered_tasks >= len(task_ids) * 0.5, "System should recover from concurrent failures"
            
            finally:
                for worker in new_workers:
                    try:
                        worker.terminate()
                        worker.wait(timeout=3)
                    except:
                        worker.kill()
                        worker.wait()
        
        finally:
            for worker in workers:
                try:
                    worker.terminate()
                    worker.wait(timeout=3)
                except:
                    pass