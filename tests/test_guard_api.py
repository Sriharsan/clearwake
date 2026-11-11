"""guard(tools, policy=...) on the real toolkit tool list recorded in docs/paypal_mcp_tools.json (47 tools). No network."""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import clearwake
from clearwake import guard
from clearwake import guard_api
from clearwake.guard_api import GuardedTool, GuardedTools

ROOT = Path(__file__).resolve().parent.parent
RECORD = json.loads((ROOT / "docs" / "paypal_mcp_tools.json").read_text(encoding="utf-8"))
KIND = {t["name"]: t["kind"] for t in RECORD["tools"]}
MONEY = sorted(n for n, k in KIND.items() if k == "money")


class Tool:
    """One toolkit tool: the real name and description, a call log, and a canned reply."""
    def __init__(self, name, description, store):
        self.name, self.description, self.store = name, description, store

    def invoke(self, args):
        self.store.calls.append((self.name, dict(args)))
        return self.store.answer(self.name, args)


class Store:
    """PayPal's record for one dispute D-1 (USD 1.50) and one capture CAP-1 (USD 50.00); every call is logged."""
    def __init__(self, dispute_amount="1.50", capture_amount="50.00"):
        self.calls, self.dispute_amount, self.capture_amount = [], dispute_amount, capture_amount
        self.status, self.refunded = "WAITING_FOR_SELLER_RESPONSE", 0

    def answer(self, name, args):
        if name == "get_dispute":
            return json.dumps({"dispute_id": args["dispute_id"], "status": self.status, "dispute_amount": {"currency_code": "USD", "value": self.dispute_amount},
                               "disputed_transactions": [{"seller_transaction_id": "CAP-1"}], "messages": [],
                               "dispute_outcome": {"amount_refunded": {"currency_code": "USD", "value": self.dispute_amount}}})
        if name == "accept_dispute_claim":
            self.status = "RESOLVED"
            return json.dumps({"links": []})
        if name == "list_transactions":
            if "transaction_id" in args:
                return json.dumps({"transaction_details": [{"transaction_info": {"transaction_amount": {"currency_code": "USD", "value": self.capture_amount}}}]})
            return json.dumps({"transaction_details": []})
        if name == "create_refund":
            self.refunded += int(round(float(args["amount"]["value"]) * 100))
            return json.dumps({"id": "R-1", "status": "COMPLETED"})
        return json.dumps({"ok": True, "tool": name})

    def sent(self, name):
        return [c for c in self.calls if c[0] == name]


def toolkit(store):
    return [Tool(t["name"], t["description"], store) for t in RECORD["tools"]]


class GuardApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="guard-api-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = Store()

    def wrap(self, store=None, **kw):
        self.store = store or self.store
        self.original = toolkit(self.store)
        return self.original, guard(self.original, data_dir=self.dir / "g", **kw)

    def receipts(self, tools):
        return [json.loads(line) for line in Path(tools.receipts_path).read_text(encoding="utf-8").splitlines()]

    def test_the_record_has_47_tools_and_8_that_move_money(self):
        self.assertEqual(len(RECORD["tools"]), 47)
        self.assertEqual(len(MONEY), 8)

    def test_from_clearwake_import_guard_is_callable_and_keeps_the_text_checks(self):
        self.assertIs(guard, clearwake.guard)
        self.assertTrue(callable(guard))
        self.assertTrue(hasattr(guard, "injection_signals"))

    def test_every_money_tool_is_wrapped_and_every_other_tool_is_the_same_object(self):
        original, tools = self.wrap()
        self.assertIsInstance(tools, GuardedTools)
        self.assertEqual([t.name for t in tools], [t.name for t in original])
        self.assertEqual(len(tools), 47)
        for before, after in zip(original, tools):
            if KIND[before.name] == "money":
                self.assertIsInstance(after, GuardedTool, before.name)
                self.assertEqual(after.description, before.description)   # name, description and schema stay as the toolkit gave them
            else:
                self.assertIs(after, before, before.name)

    def test_read_tools_pass_through_with_no_receipt(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        out = by_name["get_order"].invoke({"id": "O-1"})
        self.assertEqual(json.loads(out), {"ok": True, "tool": "get_order"})
        self.assertEqual(self.store.sent("get_order"), [("get_order", {"id": "O-1"})])
        self.assertFalse(Path(tools.receipts_path).exists() and self.receipts(tools))

    def test_a_dispute_above_the_policy_limit_is_refused_before_any_request(self):
        _, tools = self.wrap(Store(dispute_amount="18.25"))
        by_name = {t.name: t for t in tools}
        reply = json.loads(by_name["accept_dispute_claim"].invoke({"dispute_id": "D-1", "note": "Accepted"}))["clearwake_guard"]
        self.assertEqual((reply["state"], reply["sent"]), ("held for a person", False))
        self.assertIn("above limit", reply["detail"])
        self.assertEqual(self.store.sent("accept_dispute_claim"), [])   # nothing reached PayPal's money tool
        refused = [r for r in self.receipts(tools) if r["action_id"] == "clearwake.policy.refused"]
        self.assertEqual((refused[0]["params"]["amount_minor"], refused[0]["params"]["limit_minor"]), (1825, 500))

    def test_a_refund_above_the_policy_limit_is_refused_before_any_request(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        reply = json.loads(by_name["create_refund"].invoke({"capture_id": "CAP-1", "amount": {"currency_code": "USD", "value": "20.00"}}))["clearwake_guard"]
        self.assertEqual((reply["state"], reply["sent"]), ("held for a person", False))
        self.assertEqual(self.store.sent("create_refund"), [])

    def test_a_call_within_the_limit_goes_through_and_writes_a_signed_receipt(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        reply = by_name["accept_dispute_claim"].invoke({"dispute_id": "D-1", "note": "Accepted"})
        self.assertEqual(json.loads(reply), {"links": []})   # PayPal's own reply, unchanged
        sent = self.store.sent("accept_dispute_claim")
        self.assertEqual(len(sent), 1)
        lines = self.receipts(tools)
        call = [r for r in lines if r["action_id"] == "clearwake.toolkit.call"][0]
        self.assertEqual((call["params"]["state"], call["params"]["sent"]), ("VERIFIED", True))
        self.assertEqual(call["params"]["amount_minor"], 150)
        self.assertEqual(len(call["params"]["request_id"]), 36)
        self.assertEqual(call["params"]["policy_hash"], tools.policy_hash)
        self.assertTrue(tools.verify()["ok"])

    def test_the_same_move_again_sends_nothing(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        by_name["accept_dispute_claim"].invoke({"dispute_id": "D-1", "note": "Accepted"})
        again = json.loads(by_name["accept_dispute_claim"].invoke({"dispute_id": "D-1", "note": "Worded another way"}))["clearwake_guard"]
        self.assertFalse(again["sent"])
        self.assertEqual(len(self.store.sent("accept_dispute_claim")), 1)

    def test_a_refund_is_taken_from_the_record_and_checked_after_sending(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        by_name["create_refund"].invoke({"capture_id": "CAP-1", "amount": {"currency_code": "USD", "value": "1.50"}})
        self.assertEqual(self.store.refunded, 150)
        call = [r for r in self.receipts(tools) if r["action_id"] == "clearwake.toolkit.call"][0]
        self.assertEqual(call["params"]["tool"], "create_refund")

    def test_the_six_other_money_tools_are_held_unless_the_policy_names_them(self):
        _, tools = self.wrap()
        by_name = {t.name: t for t in tools}
        for name in guard_api.POLICY_ONLY:
            reply = json.loads(by_name[name].invoke({"invoice_id": "INV-1", "id": "O-1"}))["clearwake_guard"]
            self.assertEqual((reply["state"], reply["sent"]), ("held for a person", False), name)
            self.assertEqual(self.store.sent(name), [], name)
        self.assertEqual(len([r for r in self.receipts(tools) if r["action_id"] == "clearwake.policy.refused"]), 6)

    def test_a_policy_file_that_names_the_tool_lets_it_through_with_a_receipt(self):
        policy = self.dir / "policy.yaml"
        text = (ROOT / "policy" / "merchant.yaml").read_text(encoding="utf-8").replace("  propose_resolution:", "  send_invoice:\n    level: Execute within Limits\n    retry: never\n  propose_resolution:")
        policy.write_text(text, encoding="utf-8")
        _, tools = self.wrap(policy=str(policy))
        by_name = {t.name: t for t in tools}
        reply = by_name["send_invoice"].invoke({"invoice_id": "INV-1"})
        self.assertEqual(json.loads(reply), {"ok": True, "tool": "send_invoice"})
        self.assertEqual(len(self.store.sent("send_invoice")), 1)
        self.assertEqual(len([r for r in self.receipts(tools) if r["action_id"] == "clearwake.toolkit.call"]), 1)
        self.assertTrue(tools.verify()["ok"])

    def test_strict_false_forwards_a_tool_the_policy_does_not_name_and_receipts_it(self):
        _, tools = self.wrap(strict=False)
        by_name = {t.name: t for t in tools}
        by_name["pay_order"].invoke({"id": "O-1"})
        self.assertEqual(len(self.store.sent("pay_order")), 1)
        self.assertEqual([r["action_id"] for r in self.receipts(tools)][0], "clearwake.toolkit.money_tool_without_policy")

    def test_every_way_to_run_a_wrapped_tool_goes_through_the_guard(self):
        _, tools = self.wrap(Store(dispute_amount="18.25"))
        tool = {t.name: t for t in tools}["accept_dispute_claim"]
        args = {"dispute_id": "D-1", "note": "Accepted"}
        for reply in (tool.invoke(args), tool(args), tool.run(args), tool._run(**args), tool.func(**args), tool(**args),
                      asyncio.run(tool.ainvoke(args)), asyncio.run(tool.on_invoke_tool(None, json.dumps(args)))):
            self.assertIn("held for a person", reply)
        self.assertEqual(self.store.sent("accept_dispute_claim"), [])

    def test_a_dict_of_callables_is_wrapped_too(self):
        store = self.store
        table = {t.name: (lambda t=t, **a: t.invoke(a)) for t in toolkit(store)}
        tools = guard(table, data_dir=self.dir / "d")
        self.assertEqual(len(tools), 47)
        self.assertTrue(all(isinstance(t, GuardedTool) for t in tools if getattr(t, "name", "") in MONEY))

    def test_the_default_policy_that_ships_in_the_package_is_the_repository_policy(self):
        self.assertEqual(guard_api.PACKAGED_POLICY.read_text(encoding="utf-8"), (ROOT / "policy" / "merchant.yaml").read_text(encoding="utf-8"))

    def test_no_request_leaves_the_machine(self):
        import socket
        real = socket.socket.connect
        socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        try:
            _, tools = self.wrap()
            {t.name: t for t in tools}["accept_dispute_claim"].invoke({"dispute_id": "D-1", "note": "Accepted"})
        finally:
            socket.socket.connect = real


if __name__ == "__main__":
    unittest.main()
