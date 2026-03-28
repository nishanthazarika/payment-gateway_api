"""
Dummy microservices for testing the API Gateway.
Run each on a different port:
    python services/user_service.py        -> port 8001
    INSTANCE=2 PORT=8002 python services/user_service.py  -> port 8002
    PORT=8003 SERVICE=order python services/user_service.py -> port 8003
    PORT=8004 SERVICE=payment python services/user_service.py -> port 8004
"""
import os
import time
import random
from fastapi import FastAPI, Request
import uvicorn

SERVICE_NAME = os.environ.get("SERVICE", "user")
INSTANCE = os.environ.get("INSTANCE", "1")
PORT = int(os.environ.get("PORT", "8001"))

app = FastAPI(title=f"{SERVICE_NAME.title()} Service (Instance {INSTANCE})")

# sample data
USERS = {
    "1": {"id": "1", "name": "Alice", "email": "alice@example.com"},
    "2": {"id": "2", "name": "Bob", "email": "bob@example.com"},
    "3": {"id": "3", "name": "Charlie", "email": "charlie@example.com"},
}

ORDERS = {
    "101": {"id": "101", "user_id": "1", "item": "Laptop", "amount": 999.99},
    "102": {"id": "102", "user_id": "2", "item": "Phone", "amount": 599.99},
}

PAYMENTS = {
    "201": {"id": "201", "order_id": "101", "status": "completed", "amount": 999.99},
}


@app.get("/health")
async def health():
    return {"service": SERVICE_NAME, "instance": INSTANCE, "status": "healthy"}


# ---- User routes ----
@app.get("/users")
async def list_users(request: Request):
    return {
        "service": SERVICE_NAME,
        "instance": INSTANCE,
        "headers": dict(request.headers),
        "data": list(USERS.values()),
    }


@app.get("/users/{user_id}")
async def get_user(user_id: str, request: Request):
    user = USERS.get(user_id)
    if not user:
        return {"error": "User not found"}, 404
    return {
        "service": SERVICE_NAME,
        "instance": INSTANCE,
        "data": user,
    }


@app.post("/users")
async def create_user(request: Request):
    body = await request.json()
    uid = str(random.randint(100, 999))
    user = {"id": uid, **body}
    USERS[uid] = user
    return {"service": SERVICE_NAME, "instance": INSTANCE, "data": user}


# ---- Order routes ----
@app.get("/orders")
async def list_orders():
    return {"service": SERVICE_NAME, "instance": INSTANCE, "data": list(ORDERS.values())}


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    oid = str(random.randint(1000, 9999))
    order = {"id": oid, **body}
    ORDERS[oid] = order
    return {"service": SERVICE_NAME, "instance": INSTANCE, "data": order}


# ---- Payment routes ----
@app.get("/payments")
async def list_payments():
    return {"service": SERVICE_NAME, "instance": INSTANCE, "data": list(PAYMENTS.values())}


@app.post("/payments")
async def create_payment(request: Request):
    # simulate occasional slow responses for circuit breaker testing
    if random.random() < 0.1:
        time.sleep(8)  # intentionally slow
    body = await request.json()
    pid = str(random.randint(2000, 9999))
    payment = {"id": pid, "status": "pending", **body}
    PAYMENTS[pid] = payment
    return {"service": SERVICE_NAME, "instance": INSTANCE, "data": payment}


if __name__ == "__main__":
    print(f"Starting {SERVICE_NAME} service (instance {INSTANCE}) on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)