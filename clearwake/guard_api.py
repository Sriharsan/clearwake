"""One line drop in for PayPal's Agent Toolkit.

    pip install git+https://github.com/Sriharsan/clearwake
    from clearwake import guard
    tools = guard(paypal_toolkit_tools, policy="policy.yaml")

Clearwake adds what the toolkit leaves to you: limits, one request id per money move, a read of PayPal's record before any retry,
and a signed receipt.

guard() takes the tool list a toolkit hands to an agent (a list of tool objects with a name, or a dict of name to callable) and
returns a list of the same length and order:

  read and write tools     the same objects, untouched.
  accept_dispute_claim     the amount is read from PayPal's dispute record, checked against the signed policy, held for a person when
  create_refund            above the limit, given one request id from the hash of the payload, and a retry reads PayPal's record
                           first. Same engine as clearwake/mcp_guard.py (McpGuard).
  pay_order, send_invoice, send_invoice_reminder, record_payment_for_invoice, record_refund_for_invoice, activate_recurring_series
                           money tools whose amount the guard cannot read from one record. They run only when the policy names the
                           tool as an operation (no max_amount_minor, which the guard could not check); otherwise held for a person.
                           Receipt and request id either way.

Every guarded call writes a signed, hash chained receipt (verdock_core.receipts). A single toolkit object (accept_dispute_claim, or
a PayPalAPI style run(name, params)) goes to clearwake/toolkit_guard.py unchanged.
"""
import argparse
import asyncio
from collections.abc import Mapping
import json
import sys
import threading
from pathlib import Path

from verdock_core.outcome import UNKNOWN, VERIFIED
from verdock_core.policy import decide
from verdock_core.receipts import verify_log

from . import guard as checks
from .mcp_guard import McpGuard, UpstreamTools, interpret
from .paypal import ProviderRefused
from .swarm import POLICY as REPO_POLICY
from .toolkit_guard import AWAITING, DONE_ELSEWHERE, HELD, REFUSED, payload_hash, request_id_for, guard as _guard_one

PACKAGED_POLICY = Path(__file__).resolve().parent / "packaged" / "merchant.yaml"
DEFAULT_POLICY = REPO_POLICY if Path(REPO_POLICY).is_file() else PACKAGED_POLICY

ENFORCED = ("accept_dispute_claim", "create_refund")
POLICY_ONLY = ("pay_order", "send_invoice", "send_invoice_reminder", "record_payment_for_invoice", "record_refund_for_invoice", "activate_recurring_series")
MONEY_TOOLS = ENFORCED + POLICY_ONLY
APPROVAL_OPERATION = {"accept_dispute_claim": "accept_claim", "create_refund": "refund"}
APPROVAL_SUBJECT_ARG = {"accept_dispute_claim": "dispute_id", "create_refund": "capture_id"}


# calling a tool object ---------------------------------------------------------------------------------------------------------
def _arguments(tool_input, keywords):
    if isinstance(tool_input, (str, bytes)):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            tool_input = {"input": tool_input}
    merged = dict(tool_input) if isinstance(tool_input, Mapping) else {}
    merged.update(keywords)
    return merged


def _invoker(tool):
    """name-free caller for one toolkit tool: dict in, whatever the tool returns out."""
    for attribute in ("invoke", "_run", "func", "run"):
        function = getattr(tool, attribute, None)
        if callable(function):
            return (lambda args, f=function: f(args)) if attribute in ("invoke", "run") else (lambda args, f=function: f(**args))
    if callable(tool):
        return lambda args: tool(**args)
    raise TypeError(f"Cannot call the tool {getattr(tool, 'name', tool)!r}: it has no invoke, _run, func, run or call.")


def _as_text(result):
    return result if isinstance(result, str) else json.dumps(result, default=str)


class _Toolbox:
    """The upstream UpstreamTools talks to: PayPal's own tools, called by name."""

    def __init__(self, tools):
        self.calls = {name: _invoker(tool) for name, tool in tools.items()}

    def call_tool(self, name, arguments):
        if name not in self.calls:
            raise ProviderRefused(f"the tool list has no {name}; the guard cannot read PayPal's record")
        return _as_text(self.calls[name](dict(arguments))), False


class GuardedTool:
    """A money moving tool behind the guard. It keeps the original's name, description and schema; every way of running it goes
    through the guard, none reaches the original directly."""

    def __init__(self, inner, name, run):
        self._inner, self.name, self._guarded = inner, name, run

    def _call(self, tool_input=None, **keywords):
        return self._guarded(self.name, _arguments(tool_input, keywords))

    def invoke(self, tool_input=None, config=None, **keywords):
        return self._call(tool_input, **keywords)

    def run(self, tool_input=None, **keywords):
        return self._call(tool_input, **keywords)

    def _run(self, **keywords):
        return self._call(None, **keywords)

    def __call__(self, tool_input=None, **keywords):
        return self._call(tool_input, **keywords)

    @property
    def func(self):
        return lambda **keywords: self._call(None, **keywords)

    coroutine = None

    async def ainvoke(self, tool_input=None, config=None, **keywords):
        return await asyncio.to_thread(self._call, tool_input, **keywords)

    arun = _arun = ainvoke

    async def on_invoke_tool(self, context, json_arguments):   # the OpenAI Agents SDK function tool entry point
        return await asyncio.to_thread(self._call, json_arguments)

    def __getattr__(self, attribute):
        if attribute.startswith("__") or attribute in ("_inner", "_guarded"):
            raise AttributeError(attribute)
        return getattr(self._inner, attribute)

    def __repr__(self):
        return f"GuardedTool({self.name})"


class GuardedTools(list):
    """The guarded tool list. A list, so an agent framework takes it as it took the original; .guard is the engine."""
    guard = None

    def verify(self):
        """Check the signed receipt log offline against its own public key."""
        return verify_log(self.guard.receipts.path, self.guard.public_key)

    @property
    def receipts_path(self):
        return self.guard.receipts.path

    @property
    def policy_hash(self):
        return self.guard.policy_hash

    def pending(self):
        return self.guard.approvals.list("pending")

    def approve(self, approval_id, by):
        self.guard.approvals.approve(approval_id, by)


class ToolListGuard:
    def __init__(self, tools, policy=None, data_dir=None, receipts=None, strict=True):
        self.tools = dict(tools)
        self.strict = strict
        self.backend = UpstreamTools(_Toolbox(self.tools))
        data = Path(data_dir or ".clearwake-toolkit-guard")
        self.engine = McpGuard(self.backend, policy=policy or DEFAULT_POLICY, data_dir=data, receipts=receipts)
        self.engine.agent = "clearwake-toolkit-guard"
        self._moves = threading.Lock()   # one money move at a time: two identical calls in flight cannot both pass the ledger

    # one guarded call ----------------------------------------------------------------------------------------------------------
    def call(self, name, args):
        with self._moves:
            outcome = self._enforced(name, args) if name in ENFORCED else self._policy_only(name, args)
        return self._result(name, outcome)

    def _enforced(self, name, args):
        args = dict(args)
        self.backend.last_text = None
        if name == "accept_dispute_claim":
            dispute = args.pop("dispute_id", None)
            approval = self.engine.approvals.approved_for("accept_claim", dispute)
            return self.engine.accept_dispute_claim(dispute, args.pop("note", ""), approval_id=approval, **args)
        capture = args.pop("capture_id", None)
        approval = self.engine.approvals.approved_for("refund", capture)
        return self.engine.create_refund(capture, args.pop("amount", None), args.pop("invoice_id", None), args.pop("note_to_payer", None), approval_id=approval, **args)

    def _policy_only(self, name, args):
        engine = self.engine
        digest = checks.digest(json.dumps(args, sort_keys=True, default=str))
        request_id = request_id_for(payload_hash(name, digest, 0, ""))
        step = f"toolkit:{name}:{digest[:16]}"
        text = " ".join(str(v) for v in args.values() if isinstance(v, str))[:2000]
        signals = checks.injection_signals(text)
        end = lambda state, detail, sent=False, approval=None: engine._end(step, name, digest[:16], 0, "USD", request_id, state, detail, signals, -1, sent, approval)
        spec = (engine.policy.get("operations") or {}).get(name)
        if spec is None and not self.strict:   # the caller chose to forward a money tool the policy does not name
            engine.receipt(f"{step}:no-policy", "clearwake.toolkit.money_tool_without_policy", {"tool": name, "arguments_sha256": digest, "forwarded": True, "reason": "the policy has no operation for this tool"}, True)
            return self._forward(step, name, args, digest, request_id, end)
        if spec is None:
            engine.receipt(f"{step}:refused", "clearwake.policy.refused", {"tool": name, "arguments_sha256": digest, "reason": "the policy has no operation for this tool"}, False)
            return end(HELD, f"The policy has no operation named {name}. Held for a person; nothing was sent. Add the operation to the policy to allow it.")
        if spec.get("max_amount_minor") is not None:
            engine.receipt(f"{step}:refused", "clearwake.policy.refused", {"tool": name, "arguments_sha256": digest, "reason": "the amount of this move is not readable from one record"}, False)
            return end(HELD, f"The policy limits {name} by amount, and the guard cannot read the amount of this move from PayPal's record. Held for a person; nothing was sent.")
        decision = decide(engine.policy, name, 0, None)
        if not decision.allowed:
            engine.receipt(f"{step}:refused", "clearwake.policy.refused", {"tool": name, "arguments_sha256": digest, "reason": decision.reason}, False)
            return end(HELD, f"Policy refused: {decision.reason}. Held for a person; nothing was sent.")
        if decision.needs_approval:
            approval = engine.approvals.approved_for(name, digest[:16])
            if approval is None:
                approval = engine.approvals.request(name, f"run {name}", digest[:16], 0, "USD", None, engine.agent, 3600)
                engine.receipt(f"{step}:approval-request", "clearwake.approval.requested", {"tool": name, "approval": approval}, True)
                return end(AWAITING, "Approval required by the policy. A person decides; nothing was sent.", approval=approval)
            try:
                engine.approvals.require(approval, name, digest[:16], 0, "USD")
            except Exception as error:
                return end(REFUSED, f"Approval not valid: {error}", approval=approval)
            engine.approvals.consume(approval)
        return self._forward(step, name, args, digest, request_id, end)

    def _forward(self, step, name, args, digest, request_id, end):
        engine = self.engine
        engine.receipt(f"{step}:send", "clearwake.toolkit.money_tool_forwarded", {"tool": name, "arguments_sha256": digest, "request_id": request_id}, True)
        try:
            text, is_error = self.backend.up.call_tool(name, args)
            interpret(text, is_error)
            self.backend.last_text = text
        except ProviderRefused as refused:
            engine.receipt(f"{step}:refused-by-paypal", "clearwake.toolkit.refused_by_paypal", {"tool": name, "reason": str(refused)[:200]}, False)
            return end("refused by PayPal", f"{refused} Nothing was applied.")
        except Exception as error:   # the move may have applied: receipted as UNKNOWN, then raised to the agent as without the guard
            engine.receipt(f"{step}:unknown", "clearwake.toolkit.no_answer", {"tool": name, "request_id": request_id, "error": type(error).__name__}, False)
            end(UNKNOWN, f"No answer ({type(error).__name__}). The move may have applied.", sent=True)
            raise
        return end(VERIFIED, "Sent within the policy.", sent=True)

    def _result(self, name, outcome):
        """What the agent sees. A move that went through returns PayPal's own reply; a stopped one returns the reason as JSON text."""
        if outcome.sent and outcome.state in (VERIFIED, DONE_ELSEWHERE) and self.backend.last_text is not None:
            return self.backend.last_text
        info = {"state": outcome.state, "detail": outcome.detail, "sent": outcome.sent, "request_id": outcome.request_id}
        if outcome.approval_id:
            info["approval_id"] = outcome.approval_id
        return json.dumps({"clearwake_guard": info})


def _names(tools):
    if isinstance(tools, Mapping):
        return dict(tools), None
    items = list(tools)
    named = {}
    for tool in items:
        name = tool.get("name") if isinstance(tool, Mapping) else getattr(tool, "name", None)
        if not isinstance(name, str):
            raise TypeError("Each tool needs a name (a tool object with .name, or a dict of name to callable).")
        named[name] = tool
    return named, items


def guard(tools, policy=None, receipts=None, data_dir=None, strict=True, **options):
    """Wrap PayPal Agent Toolkit tools.

    tools     the list the toolkit gives an agent (tool objects with a name), or a dict of name to callable. A single toolkit object
              (accept_dispute_claim, or run(name, params)) is handed to clearwake.toolkit_guard.
    policy    path to a policy file, or a loaded policy. Default: the merchant policy that ships with Clearwake
              (python -m clearwake.guard_api policy > policy.yaml writes a copy to edit). Its hash is in every receipt.
    data_dir  where the ledger, approvals and signed receipts live (default .clearwake-toolkit-guard in the working directory).
    strict    False forwards a money tool the policy has no operation for (with a receipt) instead of holding it.
    Returns a GuardedTools list: same order and length, read and write tools are the original objects, money tools are GuardedTool.
    """
    if not isinstance(tools, (list, tuple, Mapping)):
        return _guard_one(tools, policy=policy or DEFAULT_POLICY, receipts=receipts, data_dir=data_dir, **options)
    named, items = _names(tools)
    engine = ToolListGuard(named, policy=policy, data_dir=data_dir, receipts=receipts, strict=strict)
    wrapped = {name: GuardedTool(tool, name, engine.call) if name in MONEY_TOOLS else tool for name, tool in named.items()}
    out = GuardedTools(wrapped[n] for n in ([t.get("name") if isinstance(t, Mapping) else t.name for t in items] if items is not None else wrapped))
    out.guard = engine.engine
    out.engine = engine
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m clearwake.guard_api", description="Helpers for the Clearwake toolkit guard.")
    p.add_argument("action", choices=("policy", "verify"), help="policy: print the default merchant policy; verify: check a receipt log offline")
    p.add_argument("--receipts", help="receipt log to verify (default .clearwake-toolkit-guard/toolkit-receipts.ndjson)")
    args = p.parse_args(argv)
    if args.action == "policy":
        sys.stdout.write(Path(DEFAULT_POLICY).read_text(encoding="utf-8"))
        return 0
    from verdock_core.receipts import ReceiptLog, load_seed
    path = Path(args.receipts or ".clearwake-toolkit-guard/toolkit-receipts.ndjson")
    log = ReceiptLog(str(path), load_seed(str(path.with_suffix(".seed"))))
    result = verify_log(str(path), log.public_key)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
