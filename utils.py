import dill
import codecs
from typing import Any, Dict, List, Tuple, Optional

def serialize(obj) -> str:
    """Serialize an object to a base64-encoded string"""
    return codecs.encode(dill.dumps(obj), "base64").decode()

def deserialize(obj: str) -> Any:
    """Deserialize a base64-encoded string to an object"""
    return dill.loads(codecs.decode(obj.encode(), "base64"))

def execute_task(task_id, fn_payload, param_payload):
    """Execute a task and return the result"""
    try:
        # Deserialize function and parameters
        fn = deserialize(fn_payload)
        params = deserialize(param_payload)
        
        # Execute function with arguments
        args, kwargs = params
        result = fn(*args, **kwargs)
        
        # Serialize result
        result_payload = serialize(result)
        status = "COMPLETED"
        
    except Exception as e:
        # Serialize exception
        result_payload = serialize(str(e))
        status = "FAILED"
        print(f"Task {task_id} failed: {e}")
    
    return task_id, status, result_payload
