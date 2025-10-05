import json
import redis
import time
import argparse
import threading
import zmq
import signal
import sys
from multiprocessing import Pool
from datetime import datetime, timedelta
from utils import *

class TaskDispatcher:
    def __init__(self, mode: str, port: int = 5555, num_workers: int = 4):
        self.mode = mode
        self.port = port
        self.num_workers = num_workers
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
        self.context = zmq.Context()
        self.shutdown_flag = threading.Event()
        
        # Track workers and tasks
        self.registered_workers = {}  # worker_id -> {last_heartbeat, tasks: [task_ids]}
        self.task_assignments = {}    # task_id -> worker_id
        self.worker_lock = threading.Lock()
        
        # For non-local execution
        if mode != 'local':
            self.socket = None
            self.setup_socket()
            
        # For local execution
        self.pool = None
        
        # Heartbeat monitoring (only for non-local modes)
        if mode != 'local':
            self.heartbeat_thread = threading.Thread(target=self.monitor_heartbeats)
            self.heartbeat_thread.daemon = True
            self.heartbeat_thread.start()
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

        if mode == 'local':
            print(f"Task dispatcher started in local mode with {num_workers} local workers")
        else:
            print(f"Task dispatcher started in {mode} mode on port {port}")
    
    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM"""
        print("\nShutting down task dispatcher...")
        self.shutdown_flag.set()
        
        # Close pool gracefully if it exists
        if self.pool:
            try:
                print("Closing worker pool...")
                self.pool.close()
                print("Waiting for workers to finish...")
                self.pool.join(timeout=3)
                print("Worker pool closed.")
            except Exception as e:
                print(f"Error closing pool: {e}")
                try:
                    print("Force terminating worker pool...")
                    self.pool.terminate()
                    self.pool.join(timeout=2)
                except Exception as e2:
                    print(f"Error force terminating pool: {e2}")
        
        # Close ZMQ socket
        if hasattr(self, 'socket') and self.socket:
            try:
                self.socket.close()
            except:
                pass
                
        # Terminate ZMQ context
        if hasattr(self, 'context'):
            try:
                self.context.term()
            except:
                pass
        
        print("Task dispatcher shutdown complete.")
        sys.exit(0)
    
    def setup_socket(self):
        """Set up ZMQ socket based on the dispatcher mode"""
        if self.mode == 'pull':
            # REP socket for pull model (workers request tasks)
            self.socket = self.context.socket(zmq.REP)
            self.socket.bind(f"tcp://*:{self.port}")
        elif self.mode == 'push':
            # ROUTER socket for push model (dispatcher pushes tasks to workers)
            self.socket = self.context.socket(zmq.ROUTER)
            self.socket.bind(f"tcp://*:{self.port}")
    
    def monitor_heartbeats(self):
        """Monitor worker heartbeats and handle failed workers"""
        while not self.shutdown_flag.is_set():
            current_time = datetime.now()
            workers_to_remove = []
            
            with self.worker_lock:
                for worker_id, info in self.registered_workers.items():
                    if current_time - info['last_heartbeat'] > timedelta(seconds=3):  # 3 seconds timeout
                        print(f"Worker {worker_id} has missed heartbeats, marking as failed")
                        workers_to_remove.append(worker_id)
            
            # Handle failed workers
            for worker_id in workers_to_remove:
                self.handle_worker_failure(worker_id)
            
            self.shutdown_flag.wait(5)
    
    def handle_worker_failure(self, worker_id):
        """Handle worker failure by rescheduling its tasks"""
        with self.worker_lock:
            if worker_id in self.registered_workers:
                failed_tasks = self.registered_workers[worker_id]['tasks']
                print(f"Worker {worker_id} failed. Rescheduling {len(failed_tasks)} tasks")
                
                # Remove worker from registered workers
                del self.registered_workers[worker_id]
                
                # Update task status and requeue tasks
                for task_id in failed_tasks:
                    # Remove task assignment
                    if task_id in self.task_assignments:
                        del self.task_assignments[task_id]
                    
                    # Update task status in Redis if it exists
                    task_data_raw = self.redis_client.get(f"task:{task_id}")
                    if task_data_raw:
                        try:
                            task_data = json.loads(task_data_raw)
                            # Only requeue if task was running
                            if task_data["status"] == "RUNNING":
                                task_data["status"] = "QUEUED"
                                self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                                # Republish task to queue
                                self.redis_client.publish("tasks", str(task_id))
                        except Exception as e:
                            print(f"Error updating failed task {task_id}: {e}")
    
    def register_worker(self, worker_id):
        """Register a new worker"""
        with self.worker_lock:
            self.registered_workers[worker_id] = {
                'last_heartbeat': datetime.now(),
                'tasks': []
            }
            print(f"Worker {worker_id} registered successfully")
    
    def update_heartbeat(self, worker_id):
        """Update worker heartbeat"""
        with self.worker_lock:
            if worker_id in self.registered_workers:
                self.registered_workers[worker_id]['last_heartbeat'] = datetime.now()
    
    def assign_task_to_worker(self, task_id, worker_id):
        """Assign a task to a worker"""
        with self.worker_lock:
            if worker_id in self.registered_workers:
                self.registered_workers[worker_id]['tasks'].append(task_id)
                self.task_assignments[task_id] = worker_id
    
    def complete_task(self, task_id, worker_id, status, result):
        """Mark a task as complete/failed and update Redis"""
        with self.worker_lock:
            if worker_id in self.registered_workers and task_id in self.registered_workers[worker_id]['tasks']:
                # Remove task from worker's list
                self.registered_workers[worker_id]['tasks'].remove(task_id)
                
                # Remove task assignment
                if task_id in self.task_assignments:
                    del self.task_assignments[task_id]
        
        # Update task in Redis (outside the lock to avoid holding it too long)
        task_data_raw = self.redis_client.get(f"task:{task_id}")
        if task_data_raw:
            try:
                task_data = json.loads(task_data_raw)
                task_data["status"] = status
                task_data["result"] = result
                self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                print(f"Task {task_id} completed with status {status}")
            except Exception as e:
                print(f"Error updating task {task_id}: {e}")
    
    def find_available_worker(self):
        """Find available worker with the least tasks assigned (load balancing)"""
        with self.worker_lock:
            if not self.registered_workers:
                return None
            
            # Sort workers by number of assigned tasks (least first)
            workers_by_load = sorted(
                self.registered_workers.items(),
                key=lambda x: len(x[1]['tasks'])
            )
            
            # Return worker with least tasks
            return workers_by_load[0][0]
    
    def run_push_mode(self):
        """Run the task dispatcher in push mode (DEALER/ROUTER)"""
        print("Starting task dispatcher in push mode")
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe("tasks")
        
        # Thread to listen for tasks from Redis
        task_queue = []
        queue_lock = threading.Lock()
        
        def listen_for_tasks():
            for message in pubsub.listen():
                if self.shutdown_flag.is_set():
                    break
                if message["type"] == "message":
                    task_id = message["data"].decode("utf-8")
                    print(f"Received task {task_id} for push execution")
                    
                    # Get task data from Redis
                    task_data_raw = self.redis_client.get(f"task:{task_id}")
                    if task_data_raw:
                        with queue_lock:
                            task_queue.append(task_id)
        
        # Thread to push tasks to workers
        def push_tasks():
            while not self.shutdown_flag.is_set():
                try:
                    # Get a task if available
                    task_id = None
                    with queue_lock:
                        if task_queue:
                            task_id = task_queue.pop(0)
                    
                    if task_id:
                        # Get task data from Redis
                        task_data_raw = self.redis_client.get(f"task:{task_id}")
                        if task_data_raw:
                            task_data = json.loads(task_data_raw)
                            
                            # Find available worker with least tasks
                            worker_id = self.find_available_worker()
                            
                            if worker_id:
                                # Update task status
                                task_data["status"] = "RUNNING"
                                self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                                
                                # Assign task to worker
                                self.assign_task_to_worker(task_id, worker_id)
                                
                                # Send task to worker
                                task_message = {
                                    "type": "task",
                                    "task_id": task_id,
                                    "fn_payload": task_data["fn_payload"],
                                    "param_payload": task_data["param_payload"]
                                }
                                
                                # Send as multipart message
                                self.socket.send_multipart([
                                    worker_id.encode(),
                                    json.dumps(task_message).encode()
                                ])
                                
                                print(f"Sent task {task_id} to worker {worker_id}")
                            else:
                                # No available workers, put task back in queue
                                with queue_lock:
                                    task_queue.insert(0, task_id)  # Put at front
                                self.shutdown_flag.wait(0.5)
                    else:
                        # No tasks available
                        self.shutdown_flag.wait(0.1)
                
                except Exception as e:
                    if not self.shutdown_flag.is_set():
                        print(f"Error in push_tasks: {e}")
                    self.shutdown_flag.wait(0.1)
        
        # Start threads
        task_listener = threading.Thread(target=listen_for_tasks)
        task_listener.daemon = True
        task_listener.start()
        
        task_pusher = threading.Thread(target=push_tasks)
        task_pusher.daemon = True
        task_pusher.start()
        
        # Main thread handles messages from workers
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        
        try:
            while not self.shutdown_flag.is_set():
                try:
                    # Poll with timeout
                    socks = dict(poller.poll(1000))  # 1 second timeout
                    
                    if self.socket in socks:
                        # Receive multipart message
                        worker_id_bytes, message_bytes = self.socket.recv_multipart()
                        worker_id = worker_id_bytes.decode()
                        
                        try:
                            message = json.loads(message_bytes.decode())
                            message_type = message.get("type")
                            
                            if message_type == "register":
                                # Register worker
                                self.register_worker(worker_id)
                                response = {"type": "register", "status": "ok", "message": "Worker registered"}
                                self.socket.send_multipart([
                                    worker_id_bytes,
                                    json.dumps(response).encode()
                                ])
                            
                            elif message_type == "heartbeat":
                                # Update worker heartbeat
                                self.update_heartbeat(worker_id)
                                response = {"type": "heartbeat", "status": "ok", "message": "Heartbeat received"}

                                self.socket.send_multipart([
                                    worker_id_bytes,
                                    json.dumps(response).encode()
                                ])
                            
                            elif message_type == "task_result":
                                # Worker is reporting task result
                                task_id = message.get("task_id")
                                status = message.get("status")
                                result = message.get("result")
                                
                                self.complete_task(task_id, worker_id, status, result)
                                # No response needed for task result
                            
                            else:
                                print(f"Unknown message type from worker {worker_id}: {message_type}")
                                
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error from worker {worker_id}: {e}")
                        except Exception as e:
                            print(f"Error processing message from worker {worker_id}: {e}")
                
                except zmq.ZMQError as e:
                    if not self.shutdown_flag.is_set():
                        print(f"ZMQ Error: {e}")
                    time.sleep(0.1)
                except Exception as e:
                    if not self.shutdown_flag.is_set():
                        print(f"Error in main loop: {e}")
                    time.sleep(0.1)
        
        except KeyboardInterrupt:
            print("Received keyboard interrupt in push mode")
        finally:
            print("Cleaning up push mode...")
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
    
    def run_local_mode(self):
        """Run the task dispatcher in local mode"""
        print("Starting task dispatcher in local mode")
        
        # Create the pool only when we start running
        try:
            self.pool = Pool(processes=self.num_workers)
            print(f"Created process pool with {self.num_workers} workers")
        except Exception as e:
            print(f"Error creating process pool: {e}")
            return
        
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe("tasks")
        
        try:
            # Listen for new tasks
            for message in pubsub.listen():
                if self.shutdown_flag.is_set():
                    break
                    
                if message["type"] == "message":
                    task_id = message["data"].decode("utf-8")
                    print(f"Received task {task_id} for local execution")
                    
                    # Get task data from Redis
                    task_data_raw = self.redis_client.get(f"task:{task_id}")
                    if task_data_raw:
                        try:
                            task_data = json.loads(task_data_raw)
                            
                            # Update task status
                            task_data["status"] = "RUNNING"
                            self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                            
                            # Execute task in process pool (non-blocking)
                            if self.pool and not self.shutdown_flag.is_set():
                                self.pool.apply_async(
                                    execute_task,
                                    args=(task_id, task_data["fn_payload"], task_data["param_payload"]),
                                    callback=self.task_completion_callback,
                                    error_callback=self.task_error_callback
                                )
                        except Exception as e:
                            print(f"Error processing task {task_id}: {e}")
                            
                            # Update task status to FAILED
                            try:
                                task_data = json.loads(task_data_raw) if task_data_raw else {}
                                task_data["status"] = "FAILED"
                                task_data["result"] = serialize(str(e))
                                self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                            except Exception as redis_error:
                                print(f"Error updating Redis: {redis_error}")
                                
        except KeyboardInterrupt:
            print("Received keyboard interrupt")
        except Exception as e:
            print(f"Error in local mode: {e}")
        finally:
            print("Cleaning up local mode...")
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
    
    def task_completion_callback(self, result):
        """Callback function for when a task completes in the pool"""
        try:
            task_id, status, result_payload = result
            
            # Update task status in Redis
            task_data_raw = self.redis_client.get(f"task:{task_id}")
            if task_data_raw:
                task_data = json.loads(task_data_raw)
                task_data["status"] = status
                task_data["result"] = result_payload
                self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                print(f"Task {task_id} completed with status {status}")
        except Exception as e:
            print(f"Error in task completion callback: {e}")
    
    def task_error_callback(self, error):
        """Callback function for when a task errors in the pool"""
        print(f"Task execution error: {error}")
    
    def run_pull_mode(self):
        """Run the task dispatcher in pull mode (REQ/REP)"""
        print("Starting task dispatcher in pull mode")
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe("tasks")
        
        # Start a thread to listen for tasks from Redis
        task_queue = []
        queue_lock = threading.Lock()
        
        def listen_for_tasks():
            for message in pubsub.listen():
                if self.shutdown_flag.is_set():
                    break
                if message["type"] == "message":
                    task_id = message["data"].decode("utf-8")
                    print(f"Received task {task_id} for pull execution")
                    
                    # Get task data from Redis
                    task_data_raw = self.redis_client.get(f"task:{task_id}")
                    if task_data_raw:
                        with queue_lock:
                            task_queue.append(task_id)
        
        task_listener = threading.Thread(target=listen_for_tasks)
        task_listener.daemon = True
        task_listener.start()
        
        try:
            while not self.shutdown_flag.is_set():
                # Wait for worker requests
                try:
                    # Set a timeout so we can check shutdown_flag periodically
                    if self.socket.poll(1000):  # 1 second timeout
                        message = self.socket.recv_json()
                        print(f"Received message from worker: {message}")
                        
                        message_type = message.get("type")
                        worker_id = message.get("worker_id")
                        
                        if message_type == "register":
                            # Register worker
                            self.register_worker(worker_id)
                            self.socket.send_json({"status": "ok", "message": "Worker registered"})
                        
                        elif message_type == "heartbeat":
                            # Update worker heartbeat
                            self.update_heartbeat(worker_id)
                            self.socket.send_json({"status": "ok"})
                        
                        elif message_type == "request_task":
                            # Worker is requesting a task
                            self.update_heartbeat(worker_id)
                            
                            task_id = None
                            with queue_lock:
                                if task_queue:
                                    task_id = task_queue.pop(0)
                            
                            if task_id:
                                # Get task data from Redis
                                task_data_raw = self.redis_client.get(f"task:{task_id}")
                                if task_data_raw:
                                    task_data = json.loads(task_data_raw)
                                    
                                    # Update task status
                                    task_data["status"] = "RUNNING"
                                    self.redis_client.set(f"task:{task_id}", json.dumps(task_data))
                                    
                                    # Assign task to worker
                                    self.assign_task_to_worker(task_id, worker_id)
                                    
                                    # Send task to worker
                                    self.socket.send_json({
                                        "status": "ok",
                                        "task_id": task_id,
                                        "fn_payload": task_data["fn_payload"],
                                        "param_payload": task_data["param_payload"]
                                    })
                                else:
                                    self.socket.send_json({"status": "error", "message": "Task not found"})
                            else:
                                # No tasks available
                                self.socket.send_json({"status": "no_task"})
                        
                        elif message_type == "task_result":
                            # Worker is reporting task result
                            task_id = message.get("task_id")
                            status = message.get("status")
                            result = message.get("result")
                            
                            self.complete_task(task_id, worker_id, status, result)
                            self.socket.send_json({"status": "ok"})
                        
                        else:
                            # Unknown message type
                            self.socket.send_json({"status": "error", "message": "Unknown message type"})
                
                except zmq.ZMQError as e:
                    if not self.shutdown_flag.is_set():
                        print(f"ZMQ Error: {e}")
                    time.sleep(0.1)
                except Exception as e:
                    if not self.shutdown_flag.is_set():
                        print(f"Error processing worker message: {e}")
                        try:
                            self.socket.send_json({"status": "error", "message": str(e)})
                        except:
                            pass
        
        except KeyboardInterrupt:
            print("Received keyboard interrupt in pull mode")
        finally:
            print("Cleaning up pull mode...")
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
    
    def run(self):
        """Run the task dispatcher based on mode"""
        try:
            if self.mode == 'local':
                self.run_local_mode()
            elif self.mode == 'pull':
                self.run_pull_mode()
            elif self.mode == 'push':
                self.run_push_mode()
            else:
                print(f"Unknown mode: {self.mode}")
        except KeyboardInterrupt:
            print("Keyboard interrupt received")
        except Exception as e:
            print(f"Error in run method: {e}")
        finally:
            # Ensure cleanup happens
            self.handle_shutdown(None, None)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MPCSFaaS Task Dispatcher")
    parser.add_argument('-m', '--mode', type=str, required=True, choices=['local', 'pull', 'push'],
                        help='Dispatcher mode (local, pull, push)')
    parser.add_argument('-p', '--port', type=int, default=5555,
                        help='Port for ZMQ communication (only for pull/push modes)')
    parser.add_argument('-w', '--workers', type=int, default=4,
                        help='Number of worker processes (only for local mode)')
    
    args = parser.parse_args()
    
    dispatcher = TaskDispatcher(
        mode=args.mode,
        port=args.port,
        num_workers=args.workers
    )
    
    dispatcher.run()