"""Refund authority and uncertainty extend the existing shared workroom controller."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import time
from urllib.parse import urlsplit
import uuid

from relayloom.controller import Controller, Rejected, ROLES, digest, packed, task_input, validate_output
from .paypal import BASE, RehearsalGateway, amount, identifier


@dataclass(frozen=True)
class RefundCase:
    capture: str = "DEMO-CAPTURE-0001"
    amount: str = "1.00"
    currency: str = "USD"

    def __post_init__(self):
        identifier(self.capture); amount(self.amount)
        if self.currency != "USD":
            raise ValueError("This bounded case supports USD only.")

    def fields(self):
        return {"capture": self.capture, "amount": self.amount, "currency": self.currency}


def validate_capture(record, case):
    if not isinstance(record, dict) or record.get("id") != case.capture or record.get("status") != "COMPLETED":
        raise Rejected("The current capture must be the configured, completed sandbox capture.", 409)
    money = record.get("amount")
    try:
        if not isinstance(money, dict) or money.get("currency_code") != case.currency:
            raise ValueError()
        amount(money.get("value"), maximum=Decimal("999999999.99"))
        if Decimal(money["value"]) < Decimal(case.amount):
            raise ValueError()
    except (ValueError, TypeError):
        raise Rejected("The capture's current currency/amount does not cover this exact refund.", 409) from None


def validate_receipt(record, operation, expected_id=None):
    """Validate only known fields; never follow provider URLs or keep payer details."""
    if not isinstance(record, dict):
        raise Rejected("The refund evidence is malformed.", 409)
    try:
        refund_id = identifier(record.get("id"))
    except ValueError:
        raise Rejected("The provider refund ID is invalid.", 409) from None
    if expected_id and refund_id != expected_id:
        raise Rejected("The provider record changed refund identity.", 409)
    if record.get("amount") != {"value": operation["amount"], "currency_code": operation["currency"]}:
        raise Rejected("The provider amount or currency does not match the approved case.", 409)
    if record.get("custom_id") != operation["request_id"]:
        raise Rejected("The provider record is not correlated to this reserved request.", 409)
    linked = False
    links = record.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict) or link.get("rel") != "up" or link.get("method") != "GET":
                continue
            try:
                url = urlsplit(link.get("href", ""))
                linked = linked or (url.scheme == "https" and url.netloc in {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
                    and url.path == f"/v2/payments/captures/{operation['capture']}" and not url.query and not url.fragment)
            except (ValueError, TypeError):
                pass
    if not linked or record.get("status") not in {"COMPLETED", "PENDING", "FAILED", "CANCELLED"}:
        raise Rejected("The provider record lacks a valid sandbox capture link/status.", 409)
    return {"id": refund_id, "status": record["status"], "amount": record["amount"],
        "capture": operation["capture"], "custom_id": operation["request_id"]}


class RefundController(Controller):
    def __init__(self, path, *, case=None, gateway=None, worker=None):
        self.case = case or RefundCase()
        if worker is None:
            super().__init__(path)
        else:
            super().__init__(path, worker=worker)
        self.gateway = gateway or RehearsalGateway(self.path.with_name("rehearsal-provider.sqlite3"))
        self.case_fingerprint = digest({**self.case.fields(), "gateway": self.gateway.mode,
            "merchant": self.gateway.client_id, "policy": "clearwake-single-capture-v1"})
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cw_config(id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cw_grants(id TEXT PRIMARY KEY,room TEXT NOT NULL,revision INTEGER NOT NULL,
                  capture TEXT NOT NULL,amount TEXT NOT NULL,currency TEXT NOT NULL,expires REAL NOT NULL,
                  active INTEGER NOT NULL,artifact_hash TEXT NOT NULL,created REAL NOT NULL,UNIQUE(room,revision));
                CREATE TABLE IF NOT EXISTS cw_refunds(id TEXT PRIMARY KEY,room TEXT NOT NULL,revision INTEGER NOT NULL,
                  grant_id TEXT NOT NULL,capture TEXT NOT NULL UNIQUE,amount TEXT NOT NULL,currency TEXT NOT NULL,
                  request_id TEXT NOT NULL UNIQUE,payload_hash TEXT NOT NULL,state TEXT NOT NULL,
                  provider_id TEXT,receipt TEXT,created REAL NOT NULL,updated REAL NOT NULL,reason TEXT NOT NULL);
            """)
            old = db.execute("SELECT fingerprint FROM cw_config WHERE id=1").fetchone()
            if old and old[0] != self.case_fingerprint:
                raise ValueError("This database belongs to another immutable payment case/merchant/mode.")
            db.execute("INSERT OR IGNORE INTO cw_config VALUES(1,?)", (self.case_fingerprint,))
            # A crash can happen after a request is sent but before the DB commits.
            # A reserved row therefore remains held, never automatically replayed.
            db.execute("UPDATE cw_refunds SET state='UNKNOWN',reason='Interrupted reservation: no automatic retry; reconcile a known provider record.',updated=? WHERE state='RESERVED'", (time.time(),))

    def create(self, body):
        token = super().create(body)
        if self.mode == "local-ai":
            with self.db() as db:
                member = self.authenticate(db, token)
                db.execute("UPDATE events SET message=? WHERE room=? AND type='created'", ("Synthetic-only local AI configured. Inference occurs only when specialists are run.", member["room"]))
        return token

    def _plan(self, db, room):
        artifact = db.execute("SELECT * FROM artifacts WHERE room=? AND revision=?", (room["id"], room["revision"])).fetchone()
        if not artifact:
            raise Rejected("Complete and publish current specialist evidence before granting a refund.", 409)
        payload, checks = json.loads(artifact["payload"]), json.loads(artifact["checks"])
        intent = json.loads(room["intent"])
        if payload.get("intent") != intent or payload.get("scope") != "local-artifact-only" or any(checks.get(key) is not True for key in ("current_revision", "inputs_and_dependencies", "owner_permission", "draft_only_scope")):
            raise Rejected("The current plan's evidence is not valid for approval.", 409)
        tasks = {row["role"]: row for row in db.execute("SELECT * FROM tasks WHERE room=? AND revision=?", (room["id"], room["revision"]))}
        if any(role not in tasks or tasks[role]["state"] not in ("COMPLETE", "REUSED") for role in ROLES):
            raise Rejected("Current specialist work is incomplete.", 409)
        outputs = {role: json.loads(tasks[role]["output"]) for role in ROLES}
        for role in ROLES:
            dependencies = {key: outputs[key] for key in ROLES[:2]} if role == "support" else {}
            if tasks[role]["input_hash"] != task_input(role, intent, dependencies, self.configuration):
                raise Rejected("Current plan provenance no longer matches.", 409)
            validate_output(role, outputs[role], intent, dependencies)
        if payload.get("specialists") != outputs:
            raise Rejected("Published evidence differs from current specialist records.", 409)
        return digest(payload)

    def _exact_case(self, body):
        if any(body.get(key) != value for key, value in self.case.fields().items()):
            raise Rejected("Review the exact configured capture, USD amount and currency before proceeding.", 409)

    def _grant_record(self, db, member, room, body):
        grant = db.execute("SELECT * FROM cw_grants WHERE room=? AND revision=?", (member["room"], room["revision"])).fetchone()
        if not grant or grant["id"] != body.get("grant_id") or not grant["active"] or grant["expires"] <= time.time():
            raise Rejected("The bound refund grant is missing, changed, revoked or expired.", 403)
        if grant["artifact_hash"] != self._plan(db, room):
            raise Rejected("The approved plan has changed.", 409)
        return grant

    def _grant(self, token, csrf, body):
        with self.db() as db:
            member = self.authenticate(db, token, csrf); self.authority(member, owner=True)
            room = self.current(db, member, body.get("revision"))
            existing = db.execute("SELECT * FROM cw_grants WHERE room=? AND revision=?", (member["room"], room["revision"])).fetchone()
            if (existing["id"] if existing else None) != body.get("grant_id"):
                raise Rejected("The refund grant changed; review its latest state.", 409)
            if type(body.get("allow")) is not bool:
                raise Rejected("Explicitly allow or revoke this refund grant.")
            if not body["allow"]:
                if not existing:
                    raise Rejected("There is no current grant to revoke.", 409)
                db.execute("UPDATE cw_grants SET active=0 WHERE id=?", (existing["id"],))
                self.event(db, member["room"], "refund_revoked", "Owner revoked the bound refund grant. Already sent effects remain held for reconciliation.")
                return {"ok": True, "revoked": True}
            self._exact_case(body)
            artifact_hash = self._plan(db, room)
            if db.execute("SELECT 1 FROM cw_refunds WHERE capture=?", (self.case.capture,)).fetchone():
                raise Rejected("This capture already has a reserved operation. Reconcile it; do not grant another effect.", 409)
            grant_id, now = str(uuid.uuid4()), time.time()
            if existing:
                db.execute("DELETE FROM cw_grants WHERE id=?", (existing["id"],))
            db.execute("INSERT INTO cw_grants VALUES(?,?,?,?,?,?,?,?,?,?)", (grant_id, member["room"], room["revision"], self.case.capture,
                self.case.amount, self.case.currency, now + 300, 1, artifact_hash, now))
            self.event(db, member["room"], "refund_granted", f"Owner granted exactly USD {self.case.amount} for the configured sandbox capture on revision {room['revision']}; expires in five minutes.")
            return {"ok": True, "grant_id": grant_id}

    def _blocked(self, operation_id, reason):
        with self.db() as db:
            row = db.execute("SELECT room FROM cw_refunds WHERE id=? AND state='RESERVED'", (operation_id,)).fetchone()
            if row:
                db.execute("UPDATE cw_refunds SET state='BLOCKED',reason=?,updated=? WHERE id=?", (reason, time.time(), operation_id))
                self.event(db, row["room"], "refund_blocked", reason)

    def _refund(self, token, csrf, body):
        with self.db() as db:
            member = self.authenticate(db, token, csrf); self.authority(member, owner=True)
            room = self.current(db, member, body.get("revision")); self._exact_case(body)
            grant = self._grant_record(db, member, room, body)
            existing = db.execute("SELECT * FROM cw_refunds WHERE capture=?", (self.case.capture,)).fetchone()
            if existing:
                if existing["room"] == member["room"] and existing["revision"] == room["revision"] and existing["grant_id"] == grant["id"]:
                    return {"ok": True, "replayed": True, "state": existing["state"]}
                raise Rejected("This capture is already held by an operation. No additional refund was sent.", 409)
            op_id, request_id, now = str(uuid.uuid4()), str(uuid.uuid4()), time.time()
            payload_hash = digest({**self.case.fields(), "request_id": request_id})
            db.execute("INSERT INTO cw_refunds VALUES(?,?,?,?,?,?,?,?,?,'RESERVED',NULL,NULL,?,?,?)", (op_id, member["room"], room["revision"], grant["id"], self.case.capture,
                self.case.amount, self.case.currency, request_id, payload_hash, now, now, "Reserved before provider dispatch; no automatic retry."))
            self.event(db, member["room"], "refund_reserved", "Refund identity was durably reserved before provider dispatch.")
        try:
            validate_capture(self.gateway.capture(self.case.capture), self.case)
        except Exception:
            self._blocked(op_id, "Capture preflight failed. No refund POST was sent; review the held case.")
            raise Rejected("The capture could not pass preflight. No refund was sent.", 409) from None
        try:
            # BEGIN IMMEDIATE is the dispatch linearization boundary: revocation,
            # intent edits and competing dispatches must commit before this fresh
            # check to stop the send. Revocation after send cannot undo a payment.
            with self.db() as db:
                member = self.authenticate(db, token, csrf); self.authority(member, owner=True)
                room = self.current(db, member, body.get("revision")); self._exact_case(body)
                self._grant_record(db, member, room, body)
                operation = db.execute("SELECT * FROM cw_refunds WHERE id=?", (op_id,)).fetchone()
                if operation["state"] != "RESERVED" or operation["payload_hash"] != digest({**self.case.fields(), "request_id": operation["request_id"]}):
                    raise Rejected("This operation is already held or its identity changed.", 409)
                try:
                    result = self.gateway.refund(self.case.capture, self.case.amount, self.case.currency, request_id)
                    receipt = validate_receipt(result, operation)
                    db.execute("UPDATE cw_refunds SET state='AWAITING_VERIFICATION',provider_id=?,receipt=?,updated=?,reason=? WHERE id=?",
                        (receipt["id"], packed(receipt), time.time(), "Refund response received. Read the known provider record before declaring completion.", op_id))
                    self.event(db, member["room"], "refund_sent", "One refund request was sent; provider-record verification remains required.")
                except Exception:
                    db.execute("UPDATE cw_refunds SET state='UNKNOWN',updated=?,reason=? WHERE id=?", (time.time(), "Dispatch may have taken effect. Keep this request identity held; reconcile a known provider refund record.", op_id))
                    self.event(db, member["room"], "refund_unknown", "The refund response is uncertain. No automatic retry or replacement request ID is allowed.")
        except Rejected:
            self._blocked(op_id, "Authority or current intent changed before dispatch. No refund POST was sent.")
            raise
        return {"ok": True}

    def _reconcile(self, token, csrf, body):
        with self.db() as db:
            member = self.authenticate(db, token, csrf); self.authority(member, owner=True)
            self.current(db, member, body.get("revision"))
            operation = db.execute("SELECT * FROM cw_refunds WHERE id=? AND room=?", (body.get("operation_id"), member["room"])).fetchone()
            if not operation or operation["state"] in ("RESERVED", "BLOCKED"):
                raise Rejected("Choose this room's sent/uncertain refund operation.", 409)
            candidate = body.get("refund_id") or operation["provider_id"]
            try:
                identifier(candidate)
            except ValueError:
                raise Rejected("Enter a known refund ID from the sandbox merchant records. No retry will be sent.") from None
            if operation["provider_id"] and operation["provider_id"] != candidate:
                raise Rejected("The known provider refund identity cannot be replaced.", 409)
            operation = dict(operation)
        try:
            receipt = validate_receipt(self.gateway.refund_record(candidate), operation, candidate)
        except Exception:
            raise Rejected("The provider record did not verify. Amount, currency, capture, request correlation and status must match; the operation remains held.", 409) from None
        with self.db() as db:
            member = self.authenticate(db, token, csrf); self.authority(member, owner=True)
            self.current(db, member, body.get("revision"))
            current = db.execute("SELECT * FROM cw_refunds WHERE id=? AND room=?", (operation["id"], member["room"])).fetchone()
            if current["provider_id"] and current["provider_id"] != candidate:
                raise Rejected("Another reconciliation bound a different provider record.", 409)
            if current["state"] == "VERIFIED" and receipt["status"] != "COMPLETED":
                raise Rejected("An older/non-completed provider response cannot replace a verified receipt.", 409)
            state = {"COMPLETED": "VERIFIED", "PENDING": "PENDING", "FAILED": "DECLINED", "CANCELLED": "DECLINED"}[receipt["status"]]
            db.execute("UPDATE cw_refunds SET state=?,provider_id=?,receipt=?,updated=?,reason=? WHERE id=?", (state, candidate, packed(receipt), time.time(),
                "Known provider record checked against the reserved amount, currency, capture and request identity.", operation["id"]))
            self.event(db, member["room"], "refund_reconciled", f"Explicit provider-record reconciliation: {state.lower()}. No refund POST was sent.")
        return {"ok": True, "state": state}

    def mutate(self, token, csrf, action, body):
        handler = {"refund-grant": self._grant, "refund": self._refund, "reconcile": self._reconcile}.get(action)
        if handler:
            return handler(token, csrf, body)
        return super().mutate(token, csrf, action, body)

    def snapshot(self, token):
        state = super().snapshot(token)
        with self.db() as db:
            member = self.authenticate(db, token)
            room = db.execute("SELECT * FROM rooms WHERE id=?", (member["room"],)).fetchone()
            if room["revision"] != state["room"]["revision"]:
                raise Rejected("The room changed during refresh. Refresh its current revision.", 409)
            grant = db.execute("SELECT * FROM cw_grants WHERE room=? AND revision=?", (member["room"], room["revision"])).fetchone()
            operation = db.execute("SELECT * FROM cw_refunds WHERE room=? ORDER BY created DESC LIMIT 1", (member["room"],)).fetchone()
            grant_status = "NOT_GRANTED" if not grant else "REVOKED" if not grant["active"] else "EXPIRED" if grant["expires"] <= time.time() else "ACTIVE"
            state["payment"] = {"mode": self.gateway.mode, "case": self.case.fields(), "grant": {"id": grant["id"], "status": grant_status, "expires": grant["expires"]} if grant else {"id": None, "status": grant_status},
                "operation": {**dict(operation), "receipt": json.loads(operation["receipt"]) if operation["receipt"] else None} if operation else None,
                "scope": "one configured sandbox capture; at most USD5; one durable operation per capture; no production endpoints"}
        return state
