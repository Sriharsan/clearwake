"""Sandbox-only PayPal transport and a durable, explicitly fake gateway."""
from __future__ import annotations
from contextlib import closing

import base64
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE = "https://api-m.sandbox.paypal.com"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MONEY = re.compile(r"(?:0|[1-9][0-9]{0,8})\.[0-9]{2}\Z")


class GatewayError(Exception):
    """A sanitized provider failure, with no credential or response disclosure."""


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Use a valid sandbox capture/refund identifier.")
    return value


def amount(value, maximum=Decimal("5.00")):
    if not isinstance(value, str) or not MONEY.fullmatch(value) or not Decimal("0") < Decimal(value) <= maximum:
        raise ValueError("The amount must be a positive USD value with two decimals, at most 5.00 for this case.")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(request, timeout=15):
    """No ambient proxies, redirects, arbitrary URLs or unbounded responses."""
    parsed = urlsplit(request.full_url)
    if (parsed.scheme != "https" or parsed.netloc != "api-m.sandbox.paypal.com"
            or parsed.query or parsed.fragment or parsed.username or parsed.password
            or not re.fullmatch(r"/v1/oauth2/token|/v2/payments/captures/[A-Za-z0-9_-]{1,64}(?:/refund)?|/v2/payments/refunds/[A-Za-z0-9_-]{1,64}", parsed.path)):
        raise GatewayError("Only reviewed PayPal sandbox routes are allowed.")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise GatewayError("The provider response exceeded its bound.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise GatewayError("The provider response was malformed.")
            return result
    except Exception:
        raise GatewayError("The sandbox request could not be confirmed. No automatic retry was sent.") from None


class SandboxGateway:
    mode = "paypal-sandbox"

    def __init__(self, client_id, secret, *, base=BASE, send=transport):
        if base != BASE:
            raise ValueError("Production, custom endpoints and proxies are not supported.")
        if any(not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n") for value in (client_id, secret)):
            raise ValueError("Sandbox client ID and secret are required in the server environment.")
        self.client_id, self.secret, self.send = client_id, secret, send
        self._token, self._expires, self._lock = None, 0, threading.Lock()

    @classmethod
    def from_environment(cls):
        if os.environ.get("CLEARWAKE_SANDBOX_ACK") != "I_CONFIRM_SANDBOX_ONLY":
            raise ValueError("Explicit sandbox-only acknowledgement is required.")
        return cls(os.environ.get("PAYPAL_CLIENT_ID", ""), os.environ.get("PAYPAL_CLIENT_SECRET", ""))

    def _access_token(self):
        with self._lock:
            if self._token and self._expires > time.monotonic():
                return self._token
            basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
            result = self.send(Request(BASE + "/v1/oauth2/token", data=b"grant_type=client_credentials",
                headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, method="POST"), 15)
            token, lifetime = result.get("access_token"), result.get("expires_in")
            if (not isinstance(token, str) or not token or len(token) > 8192 or any(c in token for c in "\r\n")
                    or result.get("token_type", "Bearer").lower() != "bearer" or type(lifetime) is not int or lifetime < 60):
                raise GatewayError("The provider authentication response was invalid.")
            self._token, self._expires = token, time.monotonic() + min(lifetime - 30, 3600)
            return token

    def _request(self, path, payload=None, request_id=None):
        if payload is None:
            token = self._access_token()
        else:
            # Capture preflight prepares authentication. Never perform a hidden
            # OAuth round trip between the controller's final grant check and POST.
            with self._lock:
                if not self._token or self._expires <= time.monotonic():
                    raise GatewayError("Sandbox authentication expired before dispatch. No refund was sent.")
                token = self._token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if payload is not None:
            headers.update({"Content-Type": "application/json", "PayPal-Request-Id": request_id, "Prefer": "return=representation"})
        try:
            return self.send(Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None,
                headers=headers, method="POST" if payload is not None else "GET"), 15)
        except Exception:
            raise GatewayError("The sandbox response is uncertain. No automatic retry was sent.") from None

    def capture(self, capture_id):
        return self._request(f"/v2/payments/captures/{identifier(capture_id)}")

    def refund(self, capture_id, value, currency, request_id):
        identifier(capture_id); amount(value)
        if currency != "USD" or not re.fullmatch(r"[0-9a-f-]{36}", request_id):
            raise ValueError("The bounded request identity/currency is invalid.")
        return self._request(f"/v2/payments/captures/{capture_id}/refund",
            {"amount": {"value": value, "currency_code": currency}, "custom_id": request_id}, request_id)

    def refund_record(self, refund_id):
        return self._request(f"/v2/payments/refunds/{identifier(refund_id)}")


class RehearsalGateway:
    """Separate durable fake provider records. It makes zero network calls."""
    mode = "rehearsal"
    client_id = "synthetic-merchant"

    def __init__(self, path, outcome="completed"):
        if outcome not in ("completed", "pending", "lost-response"):
            raise ValueError("Choose completed, pending or lost-response for the fake provider.")
        self.path, self.outcome = Path(path), outcome
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS records(request_id TEXT PRIMARY KEY,refund_id TEXT UNIQUE,body TEXT NOT NULL)")

    def capture(self, capture_id):
        return {"id": identifier(capture_id), "status": "COMPLETED", "amount": {"value": "10.00", "currency_code": "USD"}}

    def refund(self, capture_id, value, currency, request_id):
        refund_id = "SIM" + request_id.replace("-", "")[:17].upper()
        result = {"id": refund_id, "status": "PENDING" if self.outcome == "pending" else "COMPLETED",
            "amount": {"value": value, "currency_code": currency}, "custom_id": request_id,
            "links": [{"rel": "up", "method": "GET", "href": f"{BASE}/v2/payments/captures/{capture_id}"}]}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?)", (request_id, refund_id, json.dumps(result)))
            stored = json.loads(db.execute("SELECT body FROM records WHERE request_id=?", (request_id,)).fetchone()[0])
        if self.outcome == "lost-response":
            raise GatewayError("The fake provider recorded the refund but the response was lost.")
        return stored

    def refund_record(self, refund_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT body FROM records WHERE refund_id=?", (identifier(refund_id),)).fetchone()
        if not row:
            raise GatewayError("This fake provider record was not found.")
        return json.loads(row[0])
