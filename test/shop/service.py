"""Real HTTP shopping processes with explicit, bounded demo fault injection."""
from __future__ import annotations

import ctypes
from concurrent.futures import ThreadPoolExecutor
import http.client
import inspect
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROLE = os.environ["SHOP_ROLE"]
ORDINAL = int(os.environ["SHOP_ORDINAL"])
PROCESS_ID = os.environ["FAULTDEBUG_PROCESS_ID"]
SESSION = os.environ["FAULTDEBUG_SESSION_ID"]
PEERS = json.loads(os.environ["SHOP_PEERS"])
SCENARIOS = {"success", "inventory_shortage", "payment_decline", "payment_crash",
             "inventory_timeout", "notification_failure"}
METHODS = {"/products": 1, "/cart": 2, "/checkout": 3, "/reserve": 4,
           "/release": 5, "/authorize": 6, "/ship": 7, "/notify": 8, "/risk": 9}
# Linux/glibc also exports no-op __cyg_profile hooks. Prefer this module's
# runtime dependency so its instrumented callbacks cannot bind to those stubs.
NATIVE = ctypes.CDLL(os.environ["SHOP_BOUNDARY"], mode=os.RTLD_NOW | os.RTLD_DEEPBIND)
NATIVE.fd_rpc_begin.argtypes = [ctypes.c_uint64] * 4 + [ctypes.c_uint32, ctypes.c_uint64]
NATIVE.fd_rpc_end.argtypes = [ctypes.c_uint64] * 4 + [ctypes.c_uint32] * 2 + [ctypes.c_uint64, ctypes.c_uint32]
NATIVE.fd_rpc_begin.restype = NATIVE.fd_rpc_end.restype = ctypes.c_int
NATIVE.shop_request_boundary.argtypes = NATIVE.shop_payment_fault.argtypes = []
NATIVE.shop_request_boundary.restype = NATIVE.shop_payment_fault.restype = None
LOCK = threading.RLock()
EVENT_LOCK = threading.Lock()
COUNTER = 0
STATE = {"stock": 10000, "reservations": {}, "charges": {}, "orders": {},
         "carts": {}, "shipments": {}, "notifications": {}}
EVENT_PATH = Path("/evidence/events.jsonl")
EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)


def emit(kind: str, ctx: dict | None = None, **fields) -> None:
    caller = inspect.currentframe().f_back
    row = {"schema": 1, "kind": kind, "service": ROLE, "process_id": PROCESS_ID,
           "process_generation": 1, "session_id": SESSION, "pid": os.getpid(), "tid": threading.get_native_id(),
           "monotonic_ns": time.monotonic_ns(), "source_file": "test/shop/service.py",
           "source_line": caller.f_lineno, **(ctx or {}), **fields}
    with EVENT_LOCK, EVENT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        stream.flush()
        if kind in {"failure", "fault_triggered"}:
            os.fsync(stream.fileno())


def new_id() -> int:
    global COUNTER
    with LOCK:
        COUNTER += 1
        return ORDINAL * 1_000_000_000 + COUNTER


def span(ctx: dict, path: str, direction: int, status: int | None = None) -> None:
    args = (ctx["rpc_id"], 0, ctx["trace_id"], METHODS[path], direction)
    accepted = (NATIVE.fd_rpc_begin(*args, time.monotonic_ns()) if status is None else
                NATIVE.fd_rpc_end(*args, status, time.monotonic_ns(), 2))
    if accepted != 1:
        raise RuntimeError("numeric RPC event not accepted by native runtime")


def call(peer: str, path: str, body: dict, parent: dict, timeout: float = 3) -> tuple[int, dict]:
    ctx = {"trace_id": parent["trace_id"], "rpc_id": new_id(),
           "parent_rpc_id": parent["rpc_id"], "request_id": parent["request_id"]}
    span(ctx, path, 2)
    emit("client_begin", ctx, peer=peer, path=path, timeout_ms=int(timeout * 1000))
    connection = http.client.HTTPConnection(PEERS[peer], timeout=timeout)
    headers = {"Content-Type": "application/json", "X-Shop-Trace": str(ctx["trace_id"]),
               "X-Shop-Rpc": str(ctx["rpc_id"]), "X-Shop-Parent": str(ctx["parent_rpc_id"]),
               "X-Shop-Request": ctx["request_id"],
               "X-Shop-Deadline": str(time.monotonic_ns() + int(timeout * 1e9))}
    try:
        connection.request("POST", path, json.dumps(body), headers)
        response = connection.getresponse()
        status, result = response.status, json.loads(response.read(65537))
    except TimeoutError:
        status, result = 504, {"code": "upstream_deadline", "peer": peer}
        emit("symptom", ctx, peer=peer, status=status, code="upstream_deadline",
             reason="No response arrived within the caller's RPC timeout.")
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        status, result = 502, {"code": "upstream_transport", "peer": peer}
        emit("symptom", ctx, peer=peer, status=status, code="upstream_transport",
             reason=f"Upstream connection failed: {type(exc).__name__}")
    finally:
        connection.close()
    span(ctx, path, 2, status)
    emit("client_end", ctx, peer=peer, path=path, status=status)
    return status, result


def failure(ctx: dict, code: str, reason: str, status: int) -> tuple[int, dict]:
    emit("failure", ctx, code=code, reason=reason, status=status,
         source_line=inspect.currentframe().f_back.f_lineno)
    return status, {"code": code, "service": ROLE}


def dispatch(path: str, body: dict, ctx: dict, deadline: int) -> tuple[int, dict]:
    scenario = body.get("scenario", "success")
    if scenario not in SCENARIOS:
        return 400, {"code": "invalid_scenario"}
    order = body.get("order_id", ctx["request_id"])
    quantity = body.get("quantity", 1)
    if not isinstance(order, str) or len(order) > 80 or not isinstance(quantity, int) or not 1 <= quantity <= 20:
        return 400, {"code": "invalid_order"}
    if ROLE == "gateway":
        if path == "/products":
            return call("catalog", path, body, ctx)
        if path == "/cart":
            return call("cart", path, body, ctx)
        if path == "/checkout":
            # A real cart process participates in every order.
            status, cart = call("cart", "/cart", body, ctx)
            if status != 200:
                return status, cart
            return call("checkout", path, {**body, "quantity": cart["quantity"]}, ctx)
    if ROLE == "catalog" and path == "/products":
        return 200, {"products": [{"sku": "FD-01", "name": "FaultDebug hoodie", "price": 39000}]}
    if ROLE == "cart" and path == "/cart":
        status, products = call("catalog", "/products", body, ctx)
        if status != 200:
            return status, products
        with LOCK:
            STATE["carts"][order] = quantity
        return 200, {"order_id": order, "quantity": quantity,
                     "amount": products["products"][0]["price"] * quantity}
    if ROLE == "checkout" and path == "/checkout":
        # Serialize this fixture's orchestration to make replay deterministic.
        with LOCK:
            if order in STATE["orders"]:
                return 200, {**STATE["orders"][order], "replayed": True}
            for peer in sorted(p for p in PEERS if p.startswith("risk-")):
                status, result = call(peer, "/risk", body, ctx)
                if status != 200:
                    return status, result
            status, result = call("inventory", "/reserve", body, ctx, timeout=0.3)
            if status != 200:
                return status, result
            status, result = call("payment", "/authorize", body, ctx)
            if status != 200:
                rollback, _ = call("inventory", "/release", body, ctx)
                emit("compensation", ctx, peer="inventory", status=rollback, order_id=order)
                return status, {**result, "reservation_released": rollback == 200}
            status, shipping = call("shipping", "/ship", body, ctx)
            if status != 200:
                return status, shipping
            status, notification = call("notification", "/notify", body, ctx)
            result = {"order_id": order, "state": "completed", "quantity": quantity,
                      "notification": "sent" if status == 200 else "deferred",
                      "shipment": shipping["shipment_id"], "replayed": False}
            STATE["orders"][order] = result
            emit("order_completed", ctx, order_id=order, notification_status=status)
            return 200, result
    if ROLE == "inventory":
        if path == "/reserve":
            if scenario == "inventory_shortage":
                return failure(ctx, "inventory_shortage", "Injected stock budget is zero; requested quantity cannot be reserved.", 409)
            if scenario == "inventory_timeout":
                emit("fault_triggered", ctx, code="inventory_latency", delay_ms=900,
                     reason="Injected 900 ms inventory delay exceeds the checkout RPC timeout of 300 ms.")
                time.sleep(0.9)
            with LOCK:
                if time.monotonic_ns() >= deadline:
                    return failure(ctx, "expired_before_reservation", "Caller deadline expired before stock mutation; no reservation was created.", 504)
                if order not in STATE["reservations"]:
                    if STATE["stock"] < quantity:
                        return failure(ctx, "stock_exhausted", "Insufficient remaining stock.", 409)
                    STATE["stock"] -= quantity
                    STATE["reservations"][order] = quantity
                return 200, {"reserved": STATE["reservations"][order]}
        if path == "/release":
            with LOCK:
                STATE["stock"] += STATE["reservations"].pop(order, 0)
                return 200, {"released": True}
    if ROLE == "payment" and path == "/authorize":
        if scenario == "payment_decline":
            return failure(ctx, "payment_declined", "Injected authorization policy rejects this demo payment before charging.", 402)
        if scenario == "payment_crash":
            emit("fault_triggered", ctx, code="payment_native_trap",
                 reason="Injected invalid authorization transition calls the native payment invariant trap.")
            NATIVE.shop_payment_fault()
        with LOCK:
            STATE["charges"].setdefault(order, quantity * 39000)
            return 200, {"authorized": True, "amount": STATE["charges"][order]}
    if ROLE == "shipping" and path == "/ship":
        with LOCK:
            STATE["shipments"].setdefault(order, "shipment-" + order)
            return 200, {"shipment_id": STATE["shipments"][order]}
    if ROLE == "notification" and path == "/notify":
        if scenario == "notification_failure":
            return failure(ctx, "notification_unavailable", "Injected notification provider outage; the paid order remains completed.", 503)
        with LOCK:
            STATE["notifications"][order] = "sent"
        return 200, {"sent": True}
    if ROLE.startswith("risk-") and path == "/risk":
        # Every extra application process runs a distinct risk check.
        return 200, {"approved": True, "worker": ROLE}
    return 404, {"code": "unknown_route"}


class ServiceServer(ThreadingHTTPServer):
    """Bounded, persistent workers preserve native per-thread ring history."""
    request_queue_size = 128

    def __init__(self, *args):
        super().__init__(*args)
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="shop-http")

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)

    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status: int, data: dict | bytes, content_type="application/json"):
        encoded = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"role": ROLE, "pid": os.getpid(), "process_id": PROCESS_ID})
        if self.path == "/state":
            with LOCK:
                return self.respond(200, STATE)
        if self.path == "/" and ROLE == "gateway":
            return self.respond(200, Path(__file__).with_name("store.html").read_bytes(), "text/html; charset=utf-8")
        self.respond(404, {"code": "unknown_route"})

    def do_POST(self):
        if self.path == "/shutdown":
            self.respond(200, {"stopping": True})
            threading.Thread(target=self.server.shutdown).start()
            return
        if self.path not in METHODS:
            return self.respond(404, {"code": "unknown_route"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise ValueError("body size")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("object required")
            ctx = {"rpc_id": int(self.headers.get("X-Shop-Rpc") or new_id()),
                   "trace_id": int(self.headers.get("X-Shop-Trace") or new_id()),
                   "parent_rpc_id": int(self.headers.get("X-Shop-Parent") or 0),
                   "request_id": self.headers.get("X-Shop-Request") or body.get("order_id") or str(new_id())}
            if any(not 0 <= ctx[key] < 2**64 for key in ("rpc_id", "trace_id", "parent_rpc_id")):
                raise ValueError("identifier bounds")
            if not isinstance(ctx["request_id"], str) or len(ctx["request_id"]) > 80:
                raise ValueError("request identity")
            deadline = int(self.headers.get("X-Shop-Deadline") or time.monotonic_ns() + 5_000_000_000)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.respond(400, {"code": "invalid_request"})
        span(ctx, self.path, 1)
        NATIVE.shop_request_boundary()
        emit("server_begin", ctx, path=self.path)
        try:
            status, result = dispatch(self.path, body, ctx, deadline)
        except Exception as exc:
            status, result = failure(ctx, "unhandled_service_error", f"Service exception: {type(exc).__name__}", 500)
        span(ctx, self.path, 1, status)
        emit("server_end", ctx, path=self.path, status=status)
        self.respond(status, result)


if __name__ == "__main__":
    emit("process_started")
    server = ServiceServer(("0.0.0.0", 8080), Handler)
    server.daemon_threads = False
    server.serve_forever(poll_interval=0.1)
    server.server_close()
    emit("process_stopped")
