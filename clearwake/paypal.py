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
import uuid
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


LIMIT = Decimal("5.00")  # The hard per refund cap for this bounded case.


def amount(value, maximum=LIMIT):
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
            or not re.fullmatch(r"/v1/oauth2/token|/v2/payments/captures/[A-Za-z0-9_-]{1,64}(?:/refund)?|/v2/payments/refunds/[A-Za-z0-9_-]{1,64}"
                                r"|/v2/checkout/orders(?:/[A-Za-z0-9_-]{1,64}(?:/capture|/track)?)?"
                                r"|/v1/customer/disputes(?:/[A-Za-z0-9_-]{1,64}(?:/provide-evidence|/accept-claim|/adjudicate)?)?", parsed.path)):
        raise GatewayError("Only reviewed PayPal sandbox routes are allowed.")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise GatewayError("The provider response exceeded its bound.")
            result = json.loads(raw) if raw.strip() else {}
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
        if os.environ.get("PAYPAL_BASE_URL") != BASE:
            raise ValueError(f"PAYPAL_BASE_URL must be exactly {BASE}. Clearwake refuses to run against anything else.")
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

    def create_order(self, value, request_id, return_url):
        """One-time setup: a sandbox order the operator approves as the sandbox buyer."""
        amount(value, maximum=Decimal("50.00"))
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id) or not re.fullmatch(r"http://127\.0\.0\.1:\d{1,5}/[a-z-]*", return_url):
            raise ValueError("The setup request identity or loopback return URL is invalid.")
        self._access_token()
        return self._request("/v2/checkout/orders", {"intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": value}, "description": "Clearwake sandbox setup order"}],
            "payment_source": {"paypal": {"experience_context": {"user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
                "return_url": return_url, "cancel_url": return_url}}}}, request_id)

    def create_card_order(self, value, request_id, card_number, expiry):
        """One-time setup without a buyer login: pay a sandbox order with one of PayPal's published sandbox test cards.

        PayPal lists these numbers at developer.paypal.com/tools/sandbox/card-testing; they only work in the sandbox."""
        amount(value, maximum=Decimal("50.00"))
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id) or not re.fullmatch(r"\d{13,19}", card_number) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", expiry):
            raise ValueError("The setup request identity or sandbox test card is invalid.")
        self._access_token()
        return self._request("/v2/checkout/orders", {"intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": value}, "description": "Clearwake sandbox setup order (test card)"}],
            "payment_source": {"card": {"number": card_number, "expiry": expiry, "name": "Sandbox Test",
                "billing_address": {"address_line_1": "1 Test Street", "admin_area_2": "San Jose", "admin_area_1": "CA", "postal_code": "95131", "country_code": "US"}}}},
            request_id)

    # Disputes (sandbox). Opening a dispute for the buyer needs partner permission this app does not have,
    # so disputes are opened by the sandbox buyer and Clearwake handles them from here.
    def disputes(self):
        return self._request("/v1/customer/disputes").get("items", [])

    def dispute(self, dispute_id):
        return self._request(f"/v1/customer/disputes/{identifier(dispute_id)}")

    def _post(self, path, payload, request_id, content_type="application/json"):
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id):
            raise ValueError("A stable request identity is required.")
        self._access_token()
        with self._lock:
            token = self._token
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            return self.send(Request(BASE + path, data=body, method="POST", headers={"Authorization": "Bearer " + token,
                "Accept": "application/json", "Content-Type": content_type, "PayPal-Request-Id": request_id}), 15)
        except Exception:
            raise GatewayError("The sandbox response is uncertain. No automatic retry was sent.") from None

    def provide_evidence(self, dispute_id, evidences, request_id):
        """Evidence from the record only, as PayPal's multipart 'input' part. No files are attached by this build."""
        boundary = "clearwake" + request_id.replace("-", "")
        part = json.dumps({"evidences": evidences})
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"input\"\r\nContent-Type: application/json\r\n\r\n{part}\r\n--{boundary}--\r\n").encode()
        return self._post(f"/v1/customer/disputes/{identifier(dispute_id)}/provide-evidence", body, request_id, f"multipart/form-data; boundary={boundary}")

    def accept_claim(self, dispute_id, note, refund_value, currency, request_id):
        amount(refund_value)
        return self._post(f"/v1/customer/disputes/{identifier(dispute_id)}/accept-claim",
                          {"note": note[:2000], "refund_amount": {"currency_code": currency, "value": refund_value}}, request_id)

    def adjudicate(self, dispute_id, outcome, request_id):
        """Sandbox only: settle a dispute so a test can finish without waiting for PayPal."""
        if outcome not in ("BUYER_FAVOR", "SELLER_FAVOR"):
            raise ValueError("Outcome must be BUYER_FAVOR or SELLER_FAVOR.")
        return self._post(f"/v1/customer/disputes/{identifier(dispute_id)}/adjudicate", {"adjudication_outcome": outcome}, request_id)

    def add_tracking(self, order_id, capture_id, tracking_number, carrier, request_id):
        identifier(capture_id)
        if not re.fullmatch(r"[A-Za-z0-9]{6,40}", tracking_number) or not re.fullmatch(r"[A-Z_]{2,40}", carrier):
            raise ValueError("Invalid tracking number or carrier code.")
        return self._post(f"/v2/checkout/orders/{identifier(order_id)}/track",
                          {"capture_id": capture_id, "tracking_number": tracking_number, "carrier": carrier, "notify_payer": False}, request_id)

    def order(self, order_id):
        return self._request(f"/v2/checkout/orders/{identifier(order_id)}")

    def capture_order(self, order_id, request_id):
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id):
            raise ValueError("The capture request identity is invalid.")
        self._access_token()
        return self._request(f"/v2/checkout/orders/{identifier(order_id)}/capture", {}, request_id)


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

    # Rehearsal disputes, shaped like PayPal's Disputes API. Synthetic data only.
    def _disputes_db(self):
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE IF NOT EXISTS disputes(id TEXT PRIMARY KEY,body TEXT NOT NULL)")
        return db

    def open_dispute(self, capture_id, reason, value, due_iso, message=""):
        """Rehearsal only: stands in for a buyer opening a dispute in PayPal's Resolution Center."""
        dispute_id = "PP-D-REH-" + uuid.uuid4().hex[:10].upper()
        body = {"dispute_id": dispute_id, "status": "WAITING_FOR_SELLER_RESPONSE", "reason": reason,
                "dispute_amount": {"currency_code": "USD", "value": value}, "seller_response_due_date": due_iso,
                "disputed_transactions": [{"seller_transaction_id": identifier(capture_id)}],
                "messages": [{"posted_by": "BUYER", "content": message[:500]}] if message else []}
        with closing(self._disputes_db()) as db, db:
            db.execute("INSERT INTO disputes VALUES(?,?)", (dispute_id, json.dumps(body)))
        return body

    def disputes(self):
        with closing(self._disputes_db()) as db, db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM disputes")]

    def dispute(self, dispute_id):
        with closing(self._disputes_db()) as db, db:
            row = db.execute("SELECT body FROM disputes WHERE id=?", (identifier(dispute_id),)).fetchone()
        if not row:
            raise GatewayError("This fake dispute was not found.")
        return json.loads(row[0])

    def _update_dispute(self, dispute_id, **changes):
        body = {**self.dispute(dispute_id), **changes}
        with closing(self._disputes_db()) as db, db:
            db.execute("UPDATE disputes SET body=? WHERE id=?", (json.dumps(body), dispute_id))
        return body

    def provide_evidence(self, dispute_id, evidences, request_id):
        self._update_dispute(dispute_id, status="UNDER_REVIEW", evidences=evidences)
        if self.outcome == "lost-response":
            raise GatewayError("The fake provider recorded the evidence but the response was lost.")
        return {"links": []}

    def accept_claim(self, dispute_id, note, refund_value, currency, request_id):
        capture_id = self.dispute(dispute_id)["disputed_transactions"][0]["seller_transaction_id"]
        outcome, self.outcome = self.outcome, "completed"
        try:
            self.refund(capture_id, refund_value, currency, request_id)
        finally:
            self.outcome = outcome
        self._update_dispute(dispute_id, status="RESOLVED", dispute_outcome={"outcome_code": "RESOLVED_BUYER_FAVOUR",
                             "amount_refunded": {"currency_code": currency, "value": refund_value}})
        if self.outcome == "lost-response":
            raise GatewayError("The fake provider accepted the claim but the response was lost.")
        return {"links": []}
