import uuid
import time
import sys
import zmq
import threading
from multiprocessing import Pool
import signal
from utils import *

class PullWorker:
    def __init__(self, worker_processes, dispatcher_url):
        self.worker_id = str(uuid.uuid4())
        self.dispatcher_url = dispatcher_url
        self.worker_processes = worker_processes
        self.pool = Pool(processes=worker_processes)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(dispatcher_url)
        self.running = True
        self.socket_lock = threading.Lock()
        
        # Register heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self.send_heartbeat)
        self.heartbeat_thread.daemon = True
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        print(f"Pull worker started with ID {self.worker_id}, {worker_processes} processes, connecting to {dispatcher_url}")
    
    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM"""
        print("Shutting down pull worker...")
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
        with self.socket_lock:
            try:
                self.socket.send_json({
                    "type": "register",
                    "worker_id": self.worker_id
                })
                response = self.socket.recv_json()
                if response.get("status") == "ok":
                    print(f"Successfully registered with dispatcher")
                    return True
                else:
                    print(f"Failed to register with dispatcher: {response.get('message')}")
                    return False
            except Exception as e:
                print(f"Error registering with dispatcher: {e}")
                return False
    
    def send_heartbeat(self):
        """Send heartbeat to task dispatcher"""
        while self.running:
            with self.socket_lock:
                try:
                    self.socket.send_json({
                        "type": "heartbeat",
                        "worker_id": self.worker_id
                    })
                    response = self.socket.recv_json()
                    if response.get("status") != "ok":
                        print(f"Heartbeat error: {response.get('message')}")
                except Exception as e:
                    print(f"Error sending heartbeat: {e}")
            
            # Sleep between heartbeats
            time.sleep(1)
    
    def request_task(self):
        """Request a task from the dispatcher"""
        with self.socket_lock:
            try:
                self.socket.send_json({
                    "type": "request_task",
                    "worker_id": self.worker_id
                })
                response = self.socket.recv_json()
                return response
            except Exception as e:
                print(f"Error requesting task: {e}")
                return {"status": "error", "message": str(e)}
    
    def send_task_result(self, task_id, status, result):
        """Send task result back to dispatcher"""
        with self.socket_lock:
            try:
                self.socket.send_json({
                    "type": "task_result",
                    "worker_id": self.worker_id,
                    "task_id": task_id,
                    "status": status,
                    "result": result
                })
                response = self.socket.recv_json()
                return response
            except Exception as e:
                print(f"Error sending task result: {e}")
                return {"status": "error", "message": str(e)}
    
    def run(self):
        """Run the worker"""
        # Register with the dispatcher
        if not self.register():
            print("Failed to register with dispatcher, exiting")
            return
        
        # Start heartbeat thread
        self.heartbeat_thread.start()
        
        # Main task requesting loop
        while self.running:
            try:
                # Request a task from the dispatcher
                response = self.request_task()
                
                if response.get("status") == "ok":
                    # Got a task, execute it
                    task_id = response.get("task_id")
                    fn_payload = response.get("fn_payload")
                    param_payload = response.get("param_payload")
                    
                    print(f"Received task {task_id}, executing...")
                    
                    # Execute task in process pool
                    result = self.pool.apply_async(
                        execute_task,
                        args=(task_id, fn_payload, param_payload),
                        callback=self.task_completed
                    )
                    
                elif response.get("status") == "no_task":
                    # No tasks available, wait a bit before trying again
                    time.sleep(0.5)
                
                else:
                    # Error from dispatcher
                    print(f"Error from dispatcher: {response.get('message')}")
                    time.sleep(1)
            
            except Exception as e:
                print(f"Error in main worker loop: {e}")
                time.sleep(1)
    
    def task_completed(self, result):
        """Callback when a task completes"""
        task_id, status, result_payload = result
        print(f"Task {task_id} completed with status {status}")
        
        # Send result back to dispatcher
        response = self.send_task_result(task_id, status, result_payload)
        if response.get("status") != "ok":
            print(f"Error sending task result: {response.get('message')}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python pull_worker.py <num_worker_processors> <dispatcher_url>")
        sys.exit(1)
    
    try:
        num_processes = int(sys.argv[1])
        dispatcher_url = sys.argv[2]
        
        worker = PullWorker(num_processes, dispatcher_url)
        worker.run()
    except ValueError:
        print("Number of worker processors must be an integer")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)