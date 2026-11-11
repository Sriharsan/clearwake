"""A guard proxy between any MCP client and PayPal's MCP server (stdio).

    python -m clearwake.mcp_guard -- npx -y @paypal/mcp --tools=all

The client (Claude, ChatGPT, an agent framework) talks to this process exactly as it would to PayPal's server; this process starts
the real server as a child and forwards every message. initialize, tools/list, notifications and every read only tool are forwarded
untouched, line for line (schemas and descriptions are never edited). For the money moving tools it enforces the signed policy
(policy/merchant.yaml) with the same logic as clearwake/toolkit_guard.py:

  accept_dispute_claim  PayPal's dispute record is read first (get_dispute). The amount comes from that record and the policy, never from
                        the arguments or from message text. Above the limit: held for a person, an MCP error result, nothing sent.
  create_refund         PayPal's record of the capture is read first (list_transactions). A refund above the policy limit, or above what
                        the record shows is left on the capture, is held for a person. An omitted amount means "the rest of the capture",
                        which the guard computes from the record and checks like any other amount.
  both                  one request id from the hash of the payload, a durable ledger, and a read of PayPal's record before any retry: a
                        retry after a lost response never repeats the money move. Order giving text in a note or message is receipted
                        (clearwake.model.injection_attempt) and changes nothing. Every call writes a signed, hash chained receipt
                        (verdock_core.receipts) that verifies offline.
  other money tools     pay_order, send_invoice, send_invoice_reminder, record_payment_for_invoice, record_refund_for_invoice and
                        activate_recurring_series have no operation in the policy. They are receipted and forwarded, or held with --strict.

It is Clearwake's own code and not a PayPal product. It was written from the published @paypal/mcp 1.8.1 and @paypal/agent-toolkit 1.11.0
source (docs/PAYPAL_MCP_TOOLS.md). The package's tool results are text blocks of JSON; a PayPal error comes back as text JSON
{"ok": false, "status": ...} with isError false, and the guard reads it that way.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading

from verdock_core import Refused
from verdock_core.approvals import ApprovalStore
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED
from verdock_core.policy import decide
from verdock_core.receipts import ReceiptLog, create_seed, load_seed, verify_log

from . import guard as checks
from .paypal import Offline, ProviderRefused
from .swarm import money
from .toolkit_guard import (AWAITING, BUSY, DONE_ELSEWHERE, HELD, OFFLINE, REFUSED, ToolkitGuard, Outcome, _minor, payload_hash, request_id_for)

AGENT = "clearwake-mcp-guard"
# Tools of @paypal/mcp (--tools=all) that move money or send a payment request, and how the guard treats them.
ENFORCED = ("accept_dispute_claim", "create_refund")
OTHER_MONEY = ("pay_order", "send_invoice", "send_invoice_reminder", "record_payment_for_invoice", "record_refund_for_invoice", "activate_recurring_series")
NOTE_OK = re.compile(r"^[A-Za-z0-9_-]{1,255}$")   # the pattern @paypal/agent-toolkit puts on accept_dispute_claim.note
SAFE_NOTE = "Accepted-within-the-merchant-limit"


class UpstreamLost(Exception):
    """No usable answer from PayPal's server (timeout, process gone, 5xx, no response). The move may have been applied."""


class Upstream:
    """The real MCP server as a child process; newline delimited JSON-RPC both ways."""

    def __init__(self, command, timeout, forward):
        exe = shutil.which(command[0]) or command[0]   # npx is npx.cmd on Windows
        self.proc = subprocess.Popen([exe, *command[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.timeout, self.forward = timeout, forward
        self._pending, self._lock, self._n, self._write = {}, threading.Lock(), 0, threading.Lock()
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                msg = None
            mid = msg.get("id") if isinstance(msg, dict) else None
            with self._lock:
                waiter = self._pending.pop(mid, None) if isinstance(mid, str) and "method" not in msg else None
            if waiter is not None:
                waiter.put(msg)
            else:
                self.forward(line)
        self.alive = False
        with self._lock:
            waiters, self._pending = list(self._pending.values()), {}
        for waiter in waiters:
            waiter.put(None)

    def write(self, raw):
        with self._write:
            try:
                self.proc.stdin.write(raw.rstrip(b"\r\n") + b"\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.alive = False
                raise UpstreamLost("the PayPal MCP server is not running")

    def request(self, method, params):
        with self._lock:
            self._n += 1
            mid = f"cwguard-{self._n}"
            waiter = self._pending[mid] = queue.Queue()
        try:
            self.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}).encode("utf-8"))
            msg = waiter.get(timeout=self.timeout)
        except queue.Empty:
            raise UpstreamLost(f"no answer within {self.timeout:g} seconds")
        finally:
            with self._lock:
                self._pending.pop(mid, None)
        if msg is None:
            raise UpstreamLost("the PayPal MCP server stopped")
        return msg

    def call_tool(self, name, arguments):
        """(text, is_error). A JSON-RPC error (the server rejected the input) raises ProviderRefused: nothing was applied."""
        msg = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in msg:
            raise ProviderRefused(str((msg["error"] or {}).get("message", "rejected"))[:200])
        result = msg.get("result") or {}
        text = "".join(block.get("text", "") for block in result.get("content", []) if isinstance(block, dict) and block.get("type") == "text")
        return text, bool(result.get("isError"))

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()


def interpret(text, is_error=False):
    """Parse a tool result's text. A PayPal error is JSON with ok false (LlmError) or {"error": ...}; 4xx means nothing was applied,
    anything else (5xx, no response, unknown) means the move may have been applied."""
    try:
        data = json.loads(text)
    except ValueError:
        if is_error:
            raise UpstreamLost("the server reported an error")
        return text
    if isinstance(data, dict) and data.get("ok") is False:
        status = data.get("status")
        message = str(data.get("message", "refused"))[:200]
        if isinstance(status, int) and 400 <= status < 500:
            raise ProviderRefused(message)
        raise UpstreamLost(message)
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        raise UpstreamLost(str(data["error"].get("message", "error"))[:200])
    return data


def _unsigned_minor(amount):
    """Minor units of an amount PayPal shows with a sign (refund rows are negative)."""
    value = dict(amount or {})
    value["value"] = str(value.get("value", "")).lstrip("+-")
    return _minor(value)


class UpstreamTools:
    """What ToolkitGuard calls: PayPal's record and the money moves, each as one MCP tools/call to the real server."""

    def __init__(self, upstream):
        self.up, self._local = upstream, threading.local()

    @property
    def last_text(self):   # per thread: concurrent calls do not see each other's reply
        return getattr(self._local, "text", None)

    @last_text.setter
    def last_text(self, value):
        self._local.text = value

    def read(self, name, arguments):
        text, is_error = self.up.call_tool(name, arguments)
        return interpret(text, is_error)

    def dispute(self, dispute_id):
        return self.read("get_dispute", {"dispute_id": dispute_id})

    def capture(self, capture_id):
        """{"id", "amount", "refunded_minor"} from PayPal's transaction record, or None when it cannot be read."""
        try:
            info = self.read("list_transactions", {"transaction_id": capture_id})["transaction_details"][0]["transaction_info"]
            record = {"id": capture_id, "amount": info["transaction_amount"], "refunded_minor": None}
            end = datetime.now(timezone.utc)
            window = {"start_date": (end - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+0000"), "end_date": end.strftime("%Y-%m-%dT%H:%M:%S+0000"), "page_size": 100}
            try:   # refunds are their own transactions that point at the capture; the tool searches 31 days at a time
                rows = self.read("list_transactions", window).get("transaction_details", [])
                record["refunded_minor"] = sum(_unsigned_minor((r["transaction_info"] or {}).get("transaction_amount")) for r in rows
                                               if (r.get("transaction_info") or {}).get("paypal_reference_id") == capture_id
                                               and str((r["transaction_info"]).get("transaction_event_code", "")).startswith("T11"))
            except Exception:
                pass
            return record
        except Exception:
            return None

    def accept_dispute_claim(self, dispute_id, note, request_id=None):
        note = note if NOTE_OK.match(note or "") else (re.sub(r"[^A-Za-z0-9_-]+", "-", note or "").strip("-")[:255] or SAFE_NOTE)
        self.last_text, is_error = self.up.call_tool("accept_dispute_claim", {"dispute_id": dispute_id, "note": note})
        interpret(self.last_text, is_error)
        return self.last_text

    def create_refund(self, capture_id, amount, invoice_id=None, note_to_payer=None, request_id=None):
        arguments = {"capture_id": capture_id, "amount": amount}
        if invoice_id:
            arguments["invoice_id"] = invoice_id
        if note_to_payer:
            arguments["note_to_payer"] = note_to_payer
        self.last_text, is_error = self.up.call_tool("create_refund", arguments)
        interpret(self.last_text, is_error)
        return self.last_text


class DedupApprovals(ApprovalStore):
    """One pending request per exact move: a retry before a person decides does not queue a second request."""

    def request(self, operation, action, subject, amount_minor, currency, limit_minor, requested_by, ttl_seconds):
        for record in self.list("pending"):
            if not record["expired"] and (record["operation"], record["subject"], record["amount_minor"], record["currency"]) == (operation, subject, amount_minor, currency):
                return record["id"]
        return super().request(operation, action, subject, amount_minor, currency, limit_minor, requested_by, ttl_seconds)

    def approved_for(self, operation, subject):
        found = [r for r in self.list("approved") if not r["expired"] and r["operation"] == operation and r["subject"] == subject]
        return found[0]["id"] if found else None


class McpGuard(ToolkitGuard):
    """ToolkitGuard for the MCP server, plus the refund tool."""

    def __init__(self, tools, policy=None, data_dir=None, receipts=None, **kw):
        data = Path(data_dir or ".clearwake-mcp-guard")
        data.mkdir(parents=True, exist_ok=True)
        super().__init__(tools, policy=policy, receipts=receipts or data / "mcp-receipts.ndjson", reader=tools, data_dir=data, agent=AGENT, **kw)
        self.approvals = DedupApprovals(str(data / "approvals.sqlite3"))

    # create_refund ------------------------------------------------------------------------------------------------------------
    def create_refund(self, capture_id, amount=None, invoice_id=None, note_to_payer=None, approval_id=None, **claimed):
        tool, step = "create_refund", f"mcp:{capture_id}"
        try:
            record = self._capture_record(capture_id)
            total, currency = _minor(record["amount"]), record["amount"]["currency_code"]
            before = record["refunded_minor"]
            if total < 0 or not currency or before is None:
                raise ValueError("no readable capture record")
        except Exception as error:
            return self._end(step, tool, capture_id, 0, "USD", "", REFUSED, f"Could not read PayPal's record of the capture ({type(error).__name__}). Nothing was sent.", [], -1, False)
        left = total - before
        said = _minor(amount) if amount else -1
        if amount and amount.get("currency_code") != currency:
            return self._end(step, tool, capture_id, 0, currency, "", REFUSED, "The refund currency differs from the capture's. Nothing was sent.", [], said, False)
        value = said if amount else left   # an omitted amount is the rest of the capture, from PayPal's record
        if value <= 0 or value > left:
            return self._end(step, tool, capture_id, max(value, 0), currency, "", REFUSED, f"The amount is outside what PayPal's record shows is left on the capture ({money(max(left, 0))} {currency}). Nothing was sent.", [], said, False)
        digest = payload_hash(tool, capture_id, value, currency)
        request_id, op = request_id_for(digest), f"toolkit:{digest}"
        signals = checks.injection_signals(str(note_to_payer or ""))
        if signals:
            self.receipt(f"{step}:injection", "clearwake.model.injection_attempt", {"capture": capture_id, "signals": signals, "text_sha256": checks.digest(str(note_to_payer)),
                         "effect": "none: the amount comes from PayPal's record and the policy; the note is not sent"}, True)
        if not self.invariants.lock(op, self.agent, ttl_seconds=300):
            return self._end(step, tool, capture_id, value, currency, request_id, BUSY, "Another call holds this move. Nothing was sent.", signals, said, False)
        try:
            return self._refund(step, tool, capture_id, invoice_id, note_to_payer, total, before, value, currency, digest, request_id, op, said, signals, approval_id)
        finally:
            self.invariants.unlock(op, self.agent)

    def _refund(self, step, tool, capture_id, invoice_id, note, total, before, value, currency, digest, request_id, op, said, signals, approval_id):
        end = lambda state, detail, sent=False, approval=None: self._end(step, tool, capture_id, value, currency, request_id, state, detail, signals, said, sent, approval)
        history = self.outcomes.history(op)
        latest = history[-1]["state"] if history else None
        if latest == VERIFIED:
            return end(VERIFIED, "Already done: this refund of the same amount on this capture went through. Nothing was sent again. A refund of another amount is a different move.")
        if latest in (PENDING, MISMATCH):
            return end(HELD, "The ledger shows this move sent and PayPal's record does not agree. A person checks. Nothing was sent.")
        retry = latest == UNKNOWN
        if retry:   # read PayPal's record (above): did the earlier call apply?
            earlier = ((history[-1]["observed"] or {}).get("refunded_before"))
            if earlier is not None and before >= earlier + value:
                self.outcomes.record(op, VERIFIED, {"refunded_minor": before})
                self._release_or_commit(self._reserved(op, history), commit=True)
                return end(VERIFIED, "PayPal's record shows the refund applied. Nothing was sent again.")
        decision = decide(self.policy, "refund", value, currency)
        if not decision.allowed:
            self.receipt(f"{step}:refused", "clearwake.policy.refused", {"capture": capture_id, "amount_minor": value, "limit_minor": decision.limit_minor or 0, "reason": decision.reason}, False)
            self.receipt(f"{step}:held", "clearwake.guard.held_for_person", {"capture": capture_id, "amount_minor": value, "sent_anything": False}, True)
            limit = f" (limit {money(decision.limit_minor)} {currency})" if decision.limit_minor is not None else ""
            return end(HELD, f"Policy refused: {decision.reason}{limit}. Held for a person; nothing was sent to PayPal.")
        if decision.needs_approval and not retry:
            approval_id = approval_id or self.approvals.approved_for("refund", capture_id)
            if approval_id is None:
                approval_id = self.approvals.request("refund", f"refund {money(value)} {currency}", capture_id, value, currency, decision.limit_minor, self.agent, 3600)
                self.receipt(f"{step}:approval-request", "clearwake.approval.requested", {"capture": capture_id, "approval": approval_id, "amount_minor": value}, True)
                return end(AWAITING, "Above the approval threshold. A person decides; nothing was sent.", approval=approval_id)
            try:
                approved = self.approvals.require(approval_id, "refund", capture_id, value, currency)
            except Refused as error:
                return end(REFUSED, f"Approval not valid: {error}", approval=approval_id)
            self.approvals.consume(approval_id)
            self.receipt(f"{step}:approval-used", "clearwake.approval.used", {"capture": capture_id, "approval": approval_id, "approver": approved["approver"]}, True)
        reservation = None
        if not retry:
            try:
                day = datetime.now(timezone.utc).date().isoformat()
                reservation = self.invariants.reserve(f"capture:{capture_id}", total, value, "unknown", day, None)
            except Refused as error:
                self.receipt(f"{step}:invariant", "clearwake.invariant.refused", {"capture": capture_id, "amount_minor": value, "reason": str(error)[:200]}, False)
                return end(REFUSED, f"Swarm limit: {error}. Nothing was sent.")
        try:
            self.outcomes.expect(op, {"refunded_minor": before + value}, ["refunded_minor"])
        except Refused:
            pass
        try:
            self.tool.create_refund(capture_id, {"currency_code": currency, "value": f"{value / 100:.2f}"}, invoice_id, None if (signals or not note) else note, request_id=request_id)
        except Offline:
            self._release(reservation)
            return end(OFFLINE, "Network down. Nothing was sent; it can be called again.")
        except ProviderRefused as refused:
            self._release(reservation)
            self.receipt(f"{step}:refused-by-paypal", "clearwake.refund.refused_by_paypal", {"capture": capture_id, "reason": str(refused)[:200]}, False)
            return end("refused by PayPal", f"{refused} Nothing was applied.")
        except Exception as error:   # the refund may have been applied: keep the ledger; the next call reads PayPal's record first
            observed = {"refunded_before": before, **({"reservation": reservation} if reservation else {})}
            self.outcomes.record(op, UNKNOWN, observed)
            if reservation:
                self._reservations[op] = reservation
            self.receipt(f"{step}:unknown", "clearwake.refund.unknown", {"capture": capture_id, "request_id": request_id, "amount_minor": value, "error": type(error).__name__}, False)
            self._end(step, tool, capture_id, value, currency, request_id, UNKNOWN, f"No answer ({type(error).__name__}). Held as UNKNOWN; the next call reads PayPal's record first.", signals, said, True)
            raise
        after = self._capture_record(capture_id)
        now = (after or {}).get("refunded_minor")
        state = UNKNOWN if now is None else VERIFIED if now == before + value else MISMATCH
        self.outcomes.record(op, state, None if now is None else {"refunded_minor": now})
        self.receipt(f"{step}:check", "clearwake.refund.checked", {"capture": capture_id, "state": state, "amount_minor": value}, state == VERIFIED)
        if state == VERIFIED:
            self._release_or_commit(reservation, commit=True)
        return end(state, {VERIFIED: "Matches PayPal's record: the capture shows the refund.", MISMATCH: "PayPal's record does not match. A person checks.", UNKNOWN: "No readable record yet."}[state], sent=True)

    def _capture_record(self, capture_id):
        record = self.tool.capture(capture_id)
        if record is None:
            raise ValueError("unreadable")
        return record


def tool_error(text, state="", **extra):
    body = {"clearwake_guard": {"state": state, "detail": text, **extra}}
    return {"content": [{"type": "text", "text": json.dumps(body)}], "isError": True}


def outcome_result(out, upstream_text):
    """The MCP tools/call result for a guard outcome. A move that went through returns PayPal's own reply."""
    info = {"state": out.state, "detail": out.detail, "sent": out.sent, "request_id": out.request_id}
    if out.approval_id:
        info["approval_id"] = out.approval_id
    if out.state == VERIFIED and out.sent and upstream_text is not None:
        return {"content": [{"type": "text", "text": upstream_text}]}
    if out.state in (VERIFIED, DONE_ELSEWHERE):
        return {"content": [{"type": "text", "text": json.dumps({"clearwake_guard": info})}]}
    return {"content": [{"type": "text", "text": json.dumps({"clearwake_guard": info})}], "isError": True}


class Proxy:
    def __init__(self, command, policy=None, data_dir=None, timeout=60.0, strict=False, stdin=None, stdout=None, log=None):
        self.stdin, self.stdout = stdin or sys.stdin.buffer, stdout or sys.stdout.buffer
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))
        self._out = threading.Lock()
        self.strict, self.workers = strict, []
        self._moves = threading.Lock()   # one money move at a time: two identical calls in flight cannot both pass the ledger
        self.up = Upstream(command, timeout, self.to_client)
        self.tools = UpstreamTools(self.up)
        self.guard = McpGuard(self.tools, policy=policy, data_dir=data_dir)

    def to_client(self, raw):
        with self._out:
            self.stdout.write(raw.rstrip(b"\r\n") + b"\n")
            self.stdout.flush()

    def reply(self, mid, result=None, error=None):
        body = {"jsonrpc": "2.0", "id": mid}
        body.update({"error": error} if error else {"result": result})
        self.to_client(json.dumps(body, separators=(",", ":")).encode("utf-8"))

    def run(self):
        self.log(f"Clearwake MCP guard running on stdio. Policy {self.guard.policy_hash[:12]}, receipts {self.guard.receipts.path}")
        for raw in iter(self.stdin.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.reply(None, error={"code": -32700, "message": "Parse error"})
                continue
            if isinstance(msg, dict) and msg.get("method") == "tools/call" and msg.get("id") is not None:
                name = (msg.get("params") or {}).get("name")
                if name in ENFORCED:
                    worker = threading.Thread(target=self.guarded_call, args=(msg,), daemon=True)
                    worker.start(); self.workers.append(worker)
                    continue
                if name in OTHER_MONEY and self.other_money(msg):
                    continue
            try:
                self.up.write(line)
            except UpstreamLost as error:
                if isinstance(msg, dict) and msg.get("id") is not None:
                    self.reply(msg["id"], error={"code": -32603, "message": f"PayPal MCP server unavailable: {error}"})
        for worker in self.workers:
            worker.join(timeout=self.up.timeout + 5)
        self.up.close()

    def other_money(self, msg):
        """A money tool the policy has no operation for: receipt it, then forward (False) or hold it with --strict (True)."""
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        digest = checks.digest(json.dumps(args, sort_keys=True))
        held = self.strict
        self.guard.receipt(f"mcp:{name}", "clearwake.mcp.money_tool_without_policy", {"tool": name, "arguments_sha256": digest, "forwarded": not held,
                           "reason": "the policy has no operation for this tool"}, not held)
        if held:
            self.reply(msg["id"], tool_error("This money tool has no operation in the signed policy and --strict is on. Held for a person; nothing was sent.", HELD))
        return held

    def guarded_call(self, msg):
        with self._moves:
            self._guarded_call(msg)

    def _guarded_call(self, msg):
        mid, params = msg["id"], msg["params"]
        name, args = params["name"], dict(params.get("arguments") or {})
        self.tools.last_text = None
        try:
            if name == "accept_dispute_claim":
                dispute = args.pop("dispute_id", None)
                approval = self.guard.approvals.approved_for("accept_claim", dispute)
                out = self.guard.accept_dispute_claim(dispute, args.pop("note", ""), approval_id=approval, **args)
            else:
                capture = args.pop("capture_id", None)
                approval = self.guard.approvals.approved_for("refund", capture)
                out = self.guard.create_refund(capture, args.pop("amount", None), args.pop("invoice_id", None), args.pop("note_to_payer", None), approval_id=approval, **args)
            self.reply(mid, outcome_result(out, self.tools.last_text))
        except (UpstreamLost, ProviderRefused, Offline) as error:   # no answer after the request left: held as UNKNOWN in the ledger
            self.reply(mid, tool_error("No answer from PayPal for this move. It is held as UNKNOWN. Call it again: the guard reads PayPal's record first and never repeats a move that applied.",
                                       UNKNOWN, error=type(error).__name__))
        except Exception as error:
            self.log(f"guard error: {type(error).__name__}")
            self.reply(mid, tool_error("The guard could not complete this call. Nothing further was sent.", REFUSED, error=type(error).__name__))


def split_argv(argv):
    return (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])


def main(argv=None):
    left, command = split_argv(list(sys.argv[1:] if argv is None else argv))
    p = argparse.ArgumentParser(prog="python -m clearwake.mcp_guard", description="Guard proxy for PayPal's MCP server. Usage: python -m clearwake.mcp_guard -- npx -y @paypal/mcp --tools=all")
    p.add_argument("action", nargs="?", choices=("serve", "approve", "reject", "pending", "verify"), default="serve")
    p.add_argument("target", nargs="?", help="approval id (approve, reject)")
    p.add_argument("--policy", default=None, help="signed policy file (default policy/merchant.yaml)")
    p.add_argument("--data-dir", default=".clearwake-mcp-guard", help="ledger, approvals and signed receipts")
    p.add_argument("--timeout", type=float, default=None, help="seconds to wait for PayPal's server on one call (default 60; 3 with --dry-run)")
    p.add_argument("--strict", action="store_true", help="hold money tools the policy has no operation for")
    p.add_argument("--dry-run", action="store_true", help="use the local PayPal MCP stand-in (clearwake.mcp_local_upstream) instead of a command")
    p.add_argument("--stand-in-state", default=None, help="state file of the local stand-in (--dry-run)")
    p.add_argument("--stand-in-fault", default="", help="drop_answer:N, the stand-in applies the next N money moves and loses the answer (--dry-run)")
    p.add_argument("--by", default=None, help="who decides (approve, reject)")
    p.add_argument("--reason", default="rejected", help="reason (reject)")
    args = p.parse_args(left)
    data = Path(args.data_dir)
    if args.action in ("approve", "reject", "pending", "verify"):
        data.mkdir(parents=True, exist_ok=True)
        approvals = DedupApprovals(str(data / "approvals.sqlite3"))
        if args.action == "pending":
            for r in approvals.list("pending"):
                print(f"{r['id']}  {r['action']}  subject {r['subject']}  expires {int(r['expires_at'])}")
            return 0
        if args.action == "verify":
            path = data / "mcp-receipts.ndjson"
            result = verify_log(str(path), load_seed_public(path))
            print(json.dumps(result)); return 0 if result.get("ok") else 1
        if not (args.target and args.by):
            p.error(f"{args.action} needs an approval id and --by NAME")
        (approvals.approve if args.action == "approve" else lambda i, b: approvals.reject(i, b, args.reason))(args.target, args.by)
        print(f"{args.action}d {args.target}")
        return 0
    if args.dry_run:
        command = [sys.executable, "-m", "clearwake.mcp_local_upstream", "--tools=all"]
        if args.stand_in_state:
            command += ["--state", args.stand_in_state]
        if args.stand_in_fault:
            command += ["--fault", args.stand_in_fault]
    if not command:
        p.error("give the PayPal MCP server command after --, for example: -- npx -y @paypal/mcp --tools=all (or use --dry-run)")
    timeout = args.timeout if args.timeout is not None else (3.0 if args.dry_run else 60.0)
    Proxy(command, policy=args.policy, data_dir=args.data_dir, timeout=timeout, strict=args.strict).run()
    return 0


def load_seed_public(path):
    from verdock_core.receipts import ReceiptLog
    return ReceiptLog(str(path), load_seed(str(Path(path).with_suffix(".seed")))).public_key


if __name__ == "__main__":
    sys.exit(main())
