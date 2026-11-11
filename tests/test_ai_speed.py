"""The speed settings of the local model call: small window, capped reply, schema, fixed prompt prefix. No model needed."""
import json
import unittest
from unittest import mock

from clearwake import buyer_ai, models, swarm
from clearwake.models import Adapter, fields_instruction, schema_for


class StandInResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return json.dumps(self.body).encode()


class SpeedSettingsTests(unittest.TestCase):
    def native_body(self, **propose):
        seen = {}

        def opener_open(request, timeout=None):
            seen["url"], seen["body"] = request.full_url, json.loads(request.data)
            return StandInResponse({"message": {"content": '{"choice": "accept"}'}, "prompt_eval_count": 90, "eval_count": 6})

        class Opener:
            open = staticmethod(opener_open)

        with mock.patch.object(models, "build_opener", lambda *a: Opener()):
            proposal = Adapter("ollama", "m").propose("system", "user", ["choice"], lambda: {"choice": "x"}, **propose)
        return seen, proposal

    def test_native_call_is_small_capped_cold_free_and_deterministic(self):
        seen, proposal = self.native_body(schema=schema_for(["choice"]), max_tokens=16)
        body = seen["body"]
        self.assertTrue(seen["url"].endswith("/api/chat"))
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["options"]["num_predict"], 16)
        self.assertLessEqual(body["options"]["num_ctx"], 1024)
        self.assertEqual(body["keep_alive"], "30m")
        self.assertIs(body["think"], False)
        self.assertNotIn("format", body)                     # no grammar on the first try: it costs time on every token
        self.assertEqual(proposal.value, {"choice": "accept"})
        self.assertEqual((proposal.call["prompt_tokens"], proposal.call["completion_tokens"]), (90, 6))

    def test_a_reply_that_is_not_json_is_asked_again_once_with_the_schema(self):
        bodies, replies = [], iter(["Sure! accept", '```json\n{"choice": "counter"}\n```'])

        class Opener:
            @staticmethod
            def open(request, timeout=None):
                bodies.append(json.loads(request.data))
                return StandInResponse({"message": {"content": next(replies)}, "prompt_eval_count": 50, "eval_count": 5})

        with mock.patch.object(models, "build_opener", lambda *a: Opener()):
            proposal = Adapter("ollama", "m").propose("s", "u", ["choice"], lambda: {}, schema=schema_for(["choice"]), max_tokens=16)
        self.assertEqual(proposal.value, {"choice": "counter"})
        self.assertNotIn("format", bodies[0]); self.assertEqual(bodies[1]["format"]["required"], ["choice"])
        self.assertEqual(proposal.call["completion_tokens"], 10)

    def test_a_code_fence_is_read_without_a_second_call(self):
        self.assertEqual(models.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            models.extract_json("no object here")

    def test_schema_holds_exactly_the_fields_and_enums(self):
        s = schema_for(["a", "b"], {"a": ("x", "y")})
        self.assertEqual(s["required"], ["a", "b"]); self.assertFalse(s["additionalProperties"])
        self.assertEqual(s["properties"]["a"]["enum"], ["x", "y"])
        self.assertIn("a, b", fields_instruction(["a", "b"]))

    def test_the_system_text_is_fixed_and_carries_no_case_data(self):
        for text in (swarm.INQUIRY_SYSTEM, buyer_ai.DRAFT_SYSTEM, buyer_ai.CHOICE_SYSTEM):
            self.assertNotRegex(text, r"\d+\.\d\d")           # no amount, so the processed prefix is the same for every case
            self.assertIn("<", text)                          # names the tag that holds untrusted text
        self.assertLess(len(swarm.INQUIRY_SYSTEM.split()), 120)
        self.assertEqual(swarm.INQUIRY_SCHEMA["properties"]["action"]["enum"], ["settle_by_offer", "refund_within_limit", "fight_with_evidence", "escalate"])
        self.assertLessEqual(swarm.INQUIRY_MAX_TOKENS, 80)

    def test_the_model_writes_no_message_unless_text_is_switched_on(self):
        for flag, expect in ((False, ["action", "offer_usd"]), (True, ["action", "offer_usd", "message"])):
            system, fields, schema, cap = swarm.inquiry_spec(flag)
            self.assertEqual(fields, expect); self.assertEqual(list(schema["properties"]), expect); self.assertEqual(schema["required"], expect)
            self.assertEqual("message" in system, flag)
            self.assertLessEqual(cap, 72 if flag else 40)

    def test_buyer_draft_puts_the_data_after_the_fixed_prompt_and_caps_the_reply(self):
        captured = {}

        def send(url, payload, headers):
            captured.update(payload)
            return {"choices": [{"message": {"content": json.dumps({"message": "Order ORD-12345678 is missing one notebook. Please refund it."})}}]}

        buyer_ai.draft_dispute_message(Adapter("ollama", "m", send=send), "NOT_RECEIVED", "3 notebooks", "ORD-12345678", 900, "Only 2 arrived.")
        system, user = (m["content"] for m in captured["messages"])
        self.assertTrue(system.startswith(buyer_ai.DRAFT_SYSTEM))
        self.assertIn("<facts>", user); self.assertIn("ORD-12345678", user); self.assertNotIn("ORD-12345678", system)
        self.assertEqual(captured["max_tokens"], buyer_ai.DRAFT_MAX_TOKENS)
        self.assertEqual(captured["ollama_format"]["required"], ["message"])   # kept for the one retry

    def test_choice_schema_allows_only_the_three_choices_and_is_short(self):
        self.assertEqual(buyer_ai.CHOICE_SCHEMA["properties"]["choice"]["enum"], list(buyer_ai.CHOICES))
        self.assertLessEqual(buyer_ai.CHOICE_MAX_TOKENS, 24)


if __name__ == "__main__":
    unittest.main()
