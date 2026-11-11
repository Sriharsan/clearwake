"""401 and 429 handling in clearwake/paypal.py. Local transport only: no network."""
import base64
import io
import json
import unittest
from urllib.error import HTTPError

from clearwake import paypal
from clearwake.paypal import GatewayError, ProviderRefused, SandboxGateway

RID = "12345678-1234-4234-8234-123456789abc"


class Recorder:
    """Records the waits a call asked for instead of sleeping."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


def refused(status, retry_after=None):
    error = ProviderRefused(f"PayPal refused it ({status}).")
    error.status, error.retry_after = status, retry_after
    return error


class Script:
    """A send function that answers token requests and replays a script for everything else."""

    def __init__(self, answers):
        self.answers, self.calls, self.tokens = list(answers), [], 0

    def __call__(self, request, timeout):
        if request.full_url.endswith("/v1/oauth2/token"):
            self.tokens += 1
            self.calls.append(("token", request.get_header("Authorization")))
            return {"access_token": f"token-{self.tokens}", "token_type": "Bearer", "expires_in": 3600}
        self.calls.append((request.get_method(), request.get_header("Authorization"), request.get_header("Paypal-request-id")))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def api_calls(self):
        return [c for c in self.calls if c[0] != "token"]


def gateway(answers):
    send = Script(answers)
    gw = SandboxGateway("test-client", "test-secret", send=send)
    gw._sleep = Recorder()
    return gw, send


class UnauthorizedTest(unittest.TestCase):
    def test_read_drops_token_and_retries_once(self):
        gw, send = gateway([refused(401), {"id": "CAP1"}])
        self.assertEqual(gw.capture("CAP1"), {"id": "CAP1"})
        self.assertEqual(send.tokens, 2)
        self.assertEqual([c[1] for c in send.api_calls()], ["Bearer token-1", "Bearer token-2"])

    def test_read_gives_up_after_one_retry(self):
        gw, send = gateway([refused(401), refused(401)])
        with self.assertRaises(ProviderRefused):
            gw.capture("CAP1")
        self.assertEqual(len(send.api_calls()), 2)

    def test_write_retries_once_with_same_request_id(self):
        gw, send = gateway([refused(401), {"id": "R1"}])
        gw._access_token()
        self.assertEqual(gw.refund("CAP1", "1.00", "USD", RID), {"id": "R1"})
        calls = send.api_calls()
        self.assertEqual([c[1] for c in calls], ["Bearer token-1", "Bearer token-2"])
        self.assertEqual({c[2] for c in calls}, {RID})

    def test_dispute_post_retries_once_with_same_request_id(self):
        gw, send = gateway([refused(401), {"links": []}])
        gw.send_message("PP-D-1", "hello", RID)
        calls = send.api_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual({c[2] for c in calls}, {RID})
        self.assertEqual(calls[1][1], "Bearer token-2")

    def test_write_without_request_id_is_not_repeated(self):
        gw, send = gateway([refused(401), {"id": "never"}])
        gw._access_token()
        with self.assertRaises(ProviderRefused):
            gw._request("/v2/payments/captures/CAP1/refund", {"x": 1}, None)
        self.assertEqual(len(send.api_calls()), 1)

    def test_cached_token_is_dropped(self):
        gw, send = gateway([refused(401), {"id": "A"}, {"id": "B"}])
        gw.capture("CAP1")
        gw.capture("CAP2")
        self.assertEqual(send.tokens, 2)  # the second read reuses token-2


class RateLimitTest(unittest.TestCase):
    def test_read_backs_off_exponentially(self):
        gw, send = gateway([refused(429), refused(429), {"id": "CAP1"}])
        self.assertEqual(gw.capture("CAP1"), {"id": "CAP1"})
        self.assertEqual(gw._sleep.waits, [1.0, 2.0])

    def test_retry_after_is_honoured(self):
        gw, _ = gateway([refused(429, "7"), {"id": "CAP1"}])
        gw.capture("CAP1")
        self.assertEqual(gw._sleep.waits, [7.0])

    def test_retry_after_forms(self):
        self.assertEqual(paypal.retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT"), 0.0)
        self.assertIsNone(paypal.retry_after_seconds("soon"))
        self.assertEqual(paypal.retry_after_seconds("12"), 12.0)

    def test_wait_is_bounded_in_attempts(self):
        gw, send = gateway([refused(429)] * 10)
        with self.assertRaises(ProviderRefused):
            gw.capture("CAP1")
        self.assertEqual(len(send.api_calls()), 1 + paypal.RATE_LIMIT_RETRIES)

    def test_wait_is_bounded_in_seconds(self):
        gw, send = gateway([refused(429, "120"), {"id": "never"}])
        with self.assertRaises(ProviderRefused):
            gw.capture("CAP1")
        self.assertEqual(gw._sleep.waits, [])
        self.assertEqual(len(send.api_calls()), 1)

    def test_write_with_request_id_retries_with_same_id(self):
        gw, send = gateway([refused(429, "2"), {"id": "R1"}])
        gw._access_token()
        self.assertEqual(gw.refund("CAP1", "1.00", "USD", RID), {"id": "R1"})
        self.assertEqual({c[2] for c in send.api_calls()}, {RID})
        self.assertEqual(gw._sleep.waits, [2.0])

    def test_dispute_post_retries(self):
        gw, send = gateway([refused(429), {"links": []}])
        gw.make_offer("PP-D-1", "note", "1.00", "USD", RID)
        self.assertEqual(len(send.api_calls()), 2)

    def test_write_without_request_id_is_never_retried(self):
        gw, send = gateway([refused(429), {"id": "never"}])
        gw._access_token()
        with self.assertRaises(ProviderRefused):
            gw._request("/v2/payments/captures/CAP1/refund", {"x": 1}, None)
        self.assertEqual(len(send.api_calls()), 1)
        self.assertEqual(gw._sleep.waits, [])

    def test_other_refusals_are_not_retried(self):
        gw, send = gateway([refused(422), {"id": "never"}])
        with self.assertRaises(ProviderRefused):
            gw.capture("CAP1")
        self.assertEqual(len(send.api_calls()), 1)

    def test_uncertain_write_is_still_sent_once(self):
        gw, send = gateway([GatewayError("lost"), {"id": "never"}])
        gw._access_token()
        with self.assertRaises(GatewayError):
            gw.refund("CAP1", "1.00", "USD", RID)
        self.assertEqual(len(send.api_calls()), 1)


class TransportTest(unittest.TestCase):
    def test_transport_carries_status_and_retry_after(self):
        body = io.BytesIO(json.dumps({"name": "RATE_LIMIT_REACHED"}).encode())
        error = HTTPError("https://api-m.sandbox.paypal.com/v2/payments/captures/CAP1", 429, "Too Many", {"Retry-After": "5"}, body)

        class Opener:
            def open(self, request, timeout=None):
                raise error

        request = paypal.Request("https://api-m.sandbox.paypal.com/v2/payments/captures/CAP1")
        original = paypal.build_opener
        paypal.build_opener = lambda *handlers: Opener()
        try:
            with self.assertRaises(ProviderRefused) as caught:
                paypal.transport(request)
        finally:
            paypal.build_opener = original
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, "5")


class CredentialEncodingTest(unittest.TestCase):
    def basic(self, client_id, secret):
        send = Script([])
        SandboxGateway(client_id, secret, send=send)._access_token()
        return base64.b64decode(send.calls[0][1].removeprefix("Basic ")).decode()

    def test_id_and_secret_are_percent_encoded_before_base64(self):
        self.assertEqual(self.basic("id:with colon", "se+cret/%&é"), "id%3Awith%20colon:se%2Bcret%2F%25%26%C3%A9")

    def test_plain_credentials_are_unchanged(self):
        self.assertEqual(self.basic("abc-123_X", "Secret.9"), "abc-123_X:Secret.9")


if __name__ == "__main__":
    unittest.main()
