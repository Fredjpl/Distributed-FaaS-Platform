import uuid
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
from utils import *

app = FastAPI(title="MPCSFaaS - Function as a Service Platform")

# Connect to Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# API Models
class RegisterFn(BaseModel):
    name: str
    payload: str

class RegisterFnRep(BaseModel):
    function_id: uuid.UUID

class ExecuteFnReq(BaseModel):
    function_id: uuid.UUID
    payload: str

class ExecuteFnRep(BaseModel):
    task_id: uuid.UUID

class TaskStatusRep(BaseModel):
    task_id: uuid.UUID
    status: str

class TaskResultRep(BaseModel):
    task_id: uuid.UUID
    status: str
    result: str

# API Routes

@app.post("/register_function", response_model=RegisterFnRep)
async def register_function(fn_req: RegisterFn):
    try:
        # Try to deserialize the payload to validate it
        fn = deserialize(fn_req.payload)
        if not callable(fn):
            raise HTTPException(status_code=400, detail="Payload is not a callable function")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid function payload: {str(e)}")
    
    function_id = uuid.uuid4()
    
    function_data = {
        "name": fn_req.name,
        "payload": fn_req.payload,
    }
    
    try:
        redis_client.set(f"function:{function_id}", json.dumps(function_data))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store function: {str(e)}")
    
    return RegisterFnRep(function_id=function_id)

@app.post("/execute_function", response_model=ExecuteFnRep)
async def execute_function(fn_req: ExecuteFnReq):
    function_data_raw = redis_client.get(f"function:{fn_req.function_id}")
    
    if not function_data_raw:
        raise HTTPException(status_code=404, detail=f"Function with ID {fn_req.function_id} not found")
    
    try:
        # Validate parameter format
        params = deserialize(fn_req.payload)
        
        # Check if params is a tuple with exactly 2 elements
        if not isinstance(params, tuple) or len(params) != 2:
            raise HTTPException(status_code=400, detail="Parameters must be a tuple of (args, kwargs)")
        
        args, kwargs = params
        
        # Check if args is a tuple and kwargs is a dict
        if not isinstance(args, tuple):
            raise HTTPException(status_code=400, detail="First element must be a tuple of positional arguments")
        
        if not isinstance(kwargs, dict):
            raise HTTPException(status_code=400, detail="Second element must be a dictionary of keyword arguments")

        function_data = json.loads(function_data_raw)
        
        task_id = uuid.uuid4()
        
        task_data = {
            "function_id": str(fn_req.function_id),
            "fn_payload": function_data["payload"],
            "param_payload": fn_req.payload,
            "status": "QUEUED",
            "result": ""
        }
        
        redis_client.set(f"task:{task_id}", json.dumps(task_data))
        
        # Publish task to Tasks queue
        redis_client.publish("tasks", str(task_id))
        
        return ExecuteFnRep(task_id=task_id)
    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute function: {str(e)}")

@app.get("/status/{task_id}", response_model=TaskStatusRep)
async def task_status(task_id: uuid.UUID):
    task_data_raw = redis_client.get(f"task:{task_id}")
    
    if not task_data_raw:
        raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
    
    try:
        task_data = json.loads(task_data_raw)
        
        return TaskStatusRep(task_id=task_id, status=task_data["status"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")

@app.get("/result/{task_id}", response_model=TaskResultRep)
async def task_result(task_id: uuid.UUID):

    task_data_raw = redis_client.get(f"task:{task_id}")

    if not task_data_raw:
        raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
    
    try:
        task_data = json.loads(task_data_raw)

        return TaskResultRep(
            task_id=task_id,
            status=task_data["status"],
            result=task_data["result"]
        )
    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task result: {str(e)}")

# For testing purposes
@app.get("/")
async def root():
    return {"message": "MPCSFaaS Platform is running"}