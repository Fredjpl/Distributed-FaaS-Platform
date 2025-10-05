import uuid
import time
import sys
import zmq
import threading
from multiprocessing import Pool
import signal
from utils import *
import json

class PushWorker:
    def __init__(self, worker_processes, dispatcher_url):
        self.worker_id = str(uuid.uuid4())
        self.dispatcher_url = dispatcher_url
        self.worker_processes = worker_processes
        self.pool = Pool(processes=worker_processes)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt_string(zmq.IDENTITY, self.worker_id)
        self.socket.connect(dispatcher_url)
        self.running = True
        
        # Track active tasks
        self.active_tasks = set()
        self.tasks_lock = threading.Lock()
        
        # Use a queue for results to avoid concurrent socket access
        self.result_queue = []
        self.result_lock = threading.Lock()
        
        # Register heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self.send_heartbeat)
        self.heartbeat_thread.daemon = True
        
        # Result sender thread
        self.result_sender_thread = threading.Thread(target=self.result_sender)
        self.result_sender_thread.daemon = True
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        print(f"Push worker started with ID {self.worker_id}, {worker_processes} processes, connecting to {dispatcher_url}")
    
    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM"""
        print("Shutting down push worker...")
        self.running = False
        if hasattr(self, 'pool'):
            self.pool.close()
            self.pool.join()
        if hasattr(self, 'socket'):
            self.socket.close()
        if hasattr(self, 'context'):
            self.context.term()
        sys.exit(0)
    
    def register(self):
        """Register with the task dispatcher"""
        try:
            message = {
                "type": "register",
                "worker_id": self.worker_id
            }
            self.socket.send_json(message)
            print(f"Sent registration request")
            
            # Wait for acknowledgment with timeout
            if self.socket.poll(5000):  # 5 second timeout
                try:
                    response = self.socket.recv_json()
                    if response.get("status") == "ok":
                        print(f"Successfully registered with dispatcher")
                        return True
                    else:
                        print(f"Failed to register: {response.get('message')}")
                        return False
                except Exception as e:
                    print(f"Error parsing registration response: {e}")
                    return False
            else:
                print("Registration timeout - no response from dispatcher")
                return False
                
        except Exception as e:
            print(f"Error registering with dispatcher: {e}")
            return False
    
    def send_heartbeat(self):
        """Send heartbeat to task dispatcher"""
        while self.running:
            try:
                message = {
                    "type": "heartbeat",
                    "worker_id": self.worker_id
                }
                self.socket.send_json(message)
                # No need to wait for response in DEALER pattern
            except Exception as e:
                if self.running:  # Only log if we're not shutting down
                    print(f"Error sending heartbeat: {e}")
            
            # Sleep between heartbeats
            time.sleep(1)
    
    def result_sender(self):
        """Thread to send results back to dispatcher"""
        while self.running:
            result_to_send = None
            
            with self.result_lock:
                if self.result_queue:
                    result_to_send = self.result_queue.pop(0)
            
            if result_to_send:
                try:
                    self.socket.send_json(result_to_send)
                    print(f"Sent result for task {result_to_send['task_id']}")
                except Exception as e:
                    print(f"Error sending result: {e}")
                    # Put it back in the queue to retry
                    with self.result_lock:
                        self.result_queue.append(result_to_send)
                    time.sleep(0.1)
            else:
                time.sleep(0.01)  # Small sleep when no results to send
    
    def queue_task_result(self, task_id, status, result):
        """Queue a task result for sending"""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                self.active_tasks.remove(task_id)
        
        result_message = {
            "type": "task_result",
            "worker_id": self.worker_id,
            "task_id": task_id,
            "status": status,
            "result": result
        }
        
        with self.result_lock:
            self.result_queue.append(result_message)
    
    def task_completed(self, result):
        """Callback when a task completes"""
        task_id, status, result_payload = result
        print(f"Task {task_id} completed with status {status}")
        self.queue_task_result(task_id, status, result_payload)
    
    def handle_task(self, task_id, fn_payload, param_payload):
        """Handle a task received from the dispatcher"""
        print(f"Received task {task_id}, executing...")
        
        with self.tasks_lock:
            self.active_tasks.add(task_id)
        
        # Execute task in process pool
        self.pool.apply_async(
            execute_task,
            args=(task_id, fn_payload, param_payload),
            callback=self.task_completed,
            error_callback=lambda e: self.task_completed((task_id, "FAILED", serialize(str(e))))
        )
    
    def run(self):
        """Run the worker"""
        # Register with the dispatcher
        if not self.register():
            print("Failed to register with dispatcher, exiting")
            return
        
        # Start background threads
        self.heartbeat_thread.start()
        self.result_sender_thread.start()
        
        # Main message receiving loop
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        
        while self.running:
            try:
                # Poll with timeout to allow checking self.running
                socks = dict(poller.poll(1000))  # 1 second timeout
                
                if self.socket in socks:
                    # Receive message
                    try:
                        message_raw = self.socket.recv_string()
                        if not message_raw:
                            continue
                            
                        message = json.loads(message_raw)
                        message_type = message.get("type")
                        
                        if message_type == "task":
                            # Got a task to execute
                            task_id = message.get("task_id")
                            fn_payload = message.get("fn_payload")
                            param_payload = message.get("param_payload")
                            
                            if task_id and fn_payload and param_payload:
                                self.handle_task(task_id, fn_payload, param_payload)
                            else:
                                print(f"Incomplete task message: {message}")
                        
                        elif message_type in ["register", "heartbeat", "task_result"]:
                            # Response to our message
                            if message.get("status") != "ok":
                                print(f"Response error: {message}")
                            else:
                                print(f"Received {message_type} response: {message}")
                        
                        else:
                            # Other message types
                            print(f"Received message of type {message_type}")
                            
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        
            except zmq.ZMQError as e:
                if self.running:
                    print(f"ZMQ Error: {e}")
                    time.sleep(0.1)
            except Exception as e:
                if self.running:
                    print(f"Error in main worker loop: {e}")
                    time.sleep(1)
        
        print("Worker shutting down...")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python push_worker.py <num_worker_processors> <dispatcher_url>")
        sys.exit(1)
    
    try:
        num_processes = int(sys.argv[1])
        dispatcher_url = sys.argv[2]
        
        worker = PushWorker(num_processes, dispatcher_url)
        worker.run()
    except ValueError:
        print("Number of worker processors must be an integer")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)