"""A minimal HTTP surface over the service layer.

This exists to show that the endpoint list in the blueprint maps cleanly onto
the modules in this package - it is a demonstrator, not a production server.
A real deployment would put FastAPI/NestJS/Laravel here and keep the service
calls below unchanged. Authentication is a static bearer-token table; replace
it with OTP login and signed sessions.

Run with::

    python -m emi_locker.api --port 8080 --db emi.db
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Tuple

from . import devices as devices_mod
from . import finance as finance_mod
from . import licensing, lifecycle, payments, reports
from .core import Actor
from .db import file_db, tx
from .errors import DomainError, PermissionDenied

Route = Tuple[str, "re.Pattern[str]", Callable[..., Any], bool]


class Api:
    """Routing table + request dispatch, independent of the HTTP server."""

    def __init__(self, conn: sqlite3.Connection, webhook_secret: str,
                 tokens: Dict[str, str] | None = None):
        self.conn = conn
        self.webhook_secret = webhook_secret
        self.tokens = tokens or {}
        # One connection shared by the threading server, so requests are
        # serialised here. A production server hands each request its own
        # pooled connection and drops this lock entirely.
        self._lock = threading.Lock()
        self.routes: List[Route] = []
        self._register()

    def _add(self, method: str, pattern: str, handler, needs_auth: bool = True) -> None:
        self.routes.append((method, re.compile("^%s$" % pattern), handler, needs_auth))

    def _register(self) -> None:
        self._add("POST", r"/customers", self.create_customer)
        self._add("GET", r"/customers/([A-Z]+-\d+)", self.get_customer)
        self._add("POST", r"/customers/([A-Z]+-\d+)/consents", self.record_consent)
        self._add("POST", r"/finance", self.create_finance)
        self._add("GET", r"/finance/([A-Z]+-\d+)", self.get_finance)
        self._add("GET", r"/finance/([A-Z]+-\d+)/emi-schedule", self.get_schedule)
        self._add("POST", r"/payments/create", self.create_payment)
        self._add("POST", r"/payments/webhook", self.webhook, needs_auth=False)
        self._add("POST", r"/collections", self.create_collection)
        self._add("POST", r"/licenses/generate", self.license_generate)
        self._add("POST", r"/licenses/redeem", self.license_redeem)
        self._add("POST", r"/licenses/allocate", self.license_allocate)
        self._add("GET", r"/licenses/wallet", self.license_wallet)
        self._add("POST", r"/licenses/renew", self.license_renew)
        self._add("POST", r"/device-actions", self.device_action)
        self._add("POST", r"/device-actions/([A-Z]+-\d+)/approve", self.device_approve)
        self._add("GET", r"/reports/outstanding", self.report_outstanding)
        self._add("GET", r"/reports/overdue", self.report_overdue)
        self._add("GET", r"/reports/dashboard", self.report_dashboard)

    # ------------------------------------------------------------------ core

    def dispatch(self, method: str, path: str, body: bytes,
                 headers: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
        with self._lock:
            return self._dispatch(method, path, body, headers)

    def _dispatch(self, method: str, path: str, body: bytes,
                  headers: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
        for route_method, pattern, handler, needs_auth in self.routes:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            try:
                actor = self._authenticate(headers) if needs_auth else None
                payload = json.loads(body.decode()) if body else {}
            except DomainError as exc:
                return exc.http_status, {"error": exc.code, "message": str(exc)}
            except ValueError:
                return 400, {"error": "BAD_JSON", "message": "request body is not JSON"}
            try:
                status, result = handler(actor, payload, body, headers, *match.groups())
                return status, result
            except DomainError as exc:
                return exc.http_status, {"error": exc.code, "message": str(exc)}
        return 404, {"error": "NOT_FOUND", "message": "no route for %s %s" % (method, path)}

    def _authenticate(self, headers: Dict[str, str]) -> Actor:
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        user_id = self.tokens.get(token)
        if not user_id:
            raise PermissionDenied("missing or unknown bearer token")
        return Actor.load(self.conn, user_id)

    # -------------------------------------------------------------- handlers

    def create_customer(self, actor, payload, *_):
        with tx(self.conn):
            cid = finance_mod.create_customer(
                self.conn, actor, payload["retailer_id"], payload["name"],
                payload["mobile"], payload.get("address"))
        return 201, {"customer_id": cid}

    def get_customer(self, actor, payload, body, headers, customer_id):
        row = self.conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if row is None:
            return 404, {"error": "NOT_FOUND", "message": customer_id}
        from .core import assert_can_touch_retailer

        assert_can_touch_retailer(self.conn, actor, row["retailer_id"])
        out = dict(row)
        out["missing_consents"] = finance_mod.missing_consents(self.conn, customer_id)
        return 200, out

    def record_consent(self, actor, payload, body, headers, customer_id):
        with tx(self.conn):
            cid = finance_mod.record_consent(
                self.conn, actor, customer_id, payload["consent_type"],
                payload.get("doc_version", "v1"), payload.get("channel", "APP"),
                payload.get("meta"))
        return 201, {"consent_id": cid}

    def create_finance(self, actor, payload, body, headers):
        with tx(self.conn):
            result = finance_mod.create_finance(
                self.conn, actor, payload["customer_id"], payload["imei"],
                payload["product_price"], payload["down_payment"], payload["tenure_months"],
                model=payload.get("model"), late_fee_paise=payload.get("late_fee_paise", 0),
                grace_days=payload.get("grace_days", 5),
                idempotency_key=headers.get("idempotency-key"))
        return 201, result

    def get_finance(self, actor, payload, body, headers, finance_id):
        return 200, finance_mod.finance_summary(self.conn, actor, finance_id)

    def get_schedule(self, actor, payload, body, headers, finance_id):
        finance_mod.finance_summary(self.conn, actor, finance_id)  # scope check
        return 200, {"finance_id": finance_id,
                     "schedule": finance_mod.get_schedule(self.conn, finance_id)}

    def create_payment(self, actor, payload, *_):
        with tx(self.conn):
            out = payments.initiate_payment(
                self.conn, actor, payload["finance_id"], payload["amount_paise"],
                payload.get("emi_id"), payload.get("gateway_order"))
        return 201, out

    def webhook(self, actor, payload, body, headers):
        signature = headers.get("x-signature", "")
        try:
            with tx(self.conn):
                out = payments.handle_webhook(self.conn, body, signature, self.webhook_secret)
        except DomainError as exc:
            if exc.code == "REPLAYED_EVENT":
                # Tell the gateway we have it so it stops retrying.
                return 200, {"status": "IGNORED", "reason": str(exc)}
            raise
        return 200, out

    def create_collection(self, actor, payload, body, headers):
        with tx(self.conn):
            out = payments.record_cash_collection(
                self.conn, actor, payload["finance_id"], payload["amount_paise"],
                payload.get("emi_id"), payload.get("mode", "CASH"),
                idempotency_key=headers.get("idempotency-key"))
        return 201, out

    def license_generate(self, actor, payload, *_):
        with tx(self.conn):
            out = licensing.generate_license(
                self.conn, actor, payload["plan_id"], payload["owner_type"],
                payload.get("owner_id"), payload.get("quota"), payload.get("validity_days"))
        return 201, out

    def license_redeem(self, actor, payload, *_):
        with tx(self.conn):
            return 200, licensing.redeem_license(self.conn, actor, payload["key"])

    def license_allocate(self, actor, payload, body, headers):
        with tx(self.conn):
            return 200, licensing.allocate_quota(
                self.conn, actor, payload["to_owner"], payload["quota"],
                payload.get("license_id"), idempotency_key=headers.get("idempotency-key"))

    def license_wallet(self, actor, *_):
        return 200, licensing.wallet(self.conn, actor.user_id)

    def license_renew(self, actor, payload, *_):
        with tx(self.conn):
            return 200, licensing.renew_license(
                self.conn, actor, payload["license_id"], payload["extra_days"],
                payload.get("order_id"), payload.get("carry_forward_unused", True))

    def device_action(self, actor, payload, *_):
        with tx(self.conn):
            return 201, devices_mod.request_command(
                self.conn, actor, payload["device_id"], payload["command"], payload["reason"])

    def device_approve(self, actor, payload, body, headers, command_id):
        with tx(self.conn):
            out = devices_mod.approve_command(self.conn, actor, command_id)
            # Dispatch uses the configured provider; the default sends nothing.
            sent = devices_mod.send_to_provider(self.conn, actor, command_id)
        return 200, {"approval": out, "dispatch": sent}

    def report_outstanding(self, actor, *_):
        return 200, {"rows": reports.outstanding_report(self.conn, actor)}

    def report_overdue(self, actor, *_):
        return 200, {"rows": lifecycle.overdue_report(self.conn)}

    def report_dashboard(self, actor, *_):
        return 200, reports.admin_dashboard(self.conn, actor)


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _run(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, payload = api.dispatch(method, self.path.split("?")[0], body, headers)
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._run("GET")

        def do_POST(self):  # noqa: N802
            self._run("POST")

        def log_message(self, fmt, *args):  # keep test output clean
            pass

    return Handler


def serve(conn, secret: str, tokens: Dict[str, str], host="127.0.0.1", port=8080):
    """Build a threading HTTP server around an existing connection."""
    api = Api(conn, secret, tokens)
    server = ThreadingHTTPServer((host, port), make_handler(api))
    return server


def main() -> None:  # pragma: no cover - manual entry point
    parser = argparse.ArgumentParser(description="EMI Locker demo API")
    parser.add_argument("--db", default="emi_locker.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--secret", default="change-me")
    args = parser.parse_args()
    conn = file_db(args.db, same_thread=False)
    server = serve(conn, args.secret, tokens={}, host=args.host, port=args.port)
    print("listening on http://%s:%d (no tokens configured)" % (args.host, args.port))
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
