"""The hosted-model client, against a small fake OpenAI-style server on a random local port (no internet, no key)."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from studybridge.agent import INTENT_SCHEMA
from studybridge.llm import LLMError, OllamaClient, OpenAICompatClient, make_client

KEY = "gsk_test_SECRET_123"


class Fake(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Fake.seen.append(("GET", self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer " + KEY:
            return self._send(401, {"error": "bad key"})
        self._send(200, {"data": [{"id": "qwen/test-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append(("POST", self.path, self.headers.get("Authorization"), body))
        if Fake.mode == "429":
            return self._send(429, {"error": f"rate limited for key {KEY}"})
        if Fake.mode == "garbage":
            return self._send(200, {"nope": 1})
        text = {"json": '```json\n{"intent": "tuition_plan"}\n```',
                "think": '<think>let me reason about it</think>{"intent": "tuition_plan"}',
                "ok": "You owe CNY {amount}."}.get(Fake.mode, "You owe CNY {amount}.")
        self._send(200, {"choices": [{"message": {"content": text}}]})


class HostedBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Fake.mode = "ok"
        Fake.seen.clear()

    def client(self, **kw):
        kw.setdefault("api_key", KEY)
        return OpenAICompatClient(self.url, "qwen/test-model", **kw)


class TestHostedClient(HostedBase):
    def test_available_checks_key_and_model_and_says_why_not(self):
        self.assertTrue(self.client().available())
        c = self.client(api_key="wrong")
        self.assertFalse(c.available())
        self.assertIn("refused the key", c.reason)
        c = OpenAICompatClient(self.url, "other/model", KEY)
        self.assertFalse(c.available())
        self.assertIn("other/model", c.reason)
        c = OpenAICompatClient("https://example.invalid/v1", "m", "")
        self.assertFalse(c.available())
        self.assertIn("no API key", c.reason)

    def test_key_goes_in_the_header_only(self):
        c = self.client()
        c.chat_text("system", "user")
        _, path, auth, body = Fake.seen[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(auth, "Bearer " + KEY)
        self.assertNotIn(KEY, json.dumps(body))
        self.assertEqual(body["temperature"], 0)

    def test_chat_json_asks_for_json_with_the_schema_and_tolerates_code_fences_and_think_tags(self):
        for mode in ("json", "think"):
            Fake.mode = mode
            out = self.client().chat_json("Read the request.", "<user_message>x</user_message>", INTENT_SCHEMA)
            self.assertEqual(out, {"intent": "tuition_plan"}, mode)
        body = Fake.seen[-1][3]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("JSON schema", body["messages"][0]["content"])
        self.assertIn("intent", body["messages"][0]["content"])

    def test_errors_become_llm_errors_without_the_key(self):
        Fake.mode = "429"
        with self.assertRaises(LLMError) as cm:
            self.client().chat_text("s", "u")
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("429", str(cm.exception))
        Fake.mode = "garbage"
        with self.assertRaises(LLMError):
            self.client().chat_text("s", "u")
        with self.assertRaises(LLMError):
            OpenAICompatClient("http://127.0.0.1:9/v1", "m", KEY, timeout=2).chat_text("s", "u")

    def test_local_call_budget_stops_calls_before_the_provider_does(self):
        c = self.client(per_minute=2)
        c.chat_text("s", "u")
        c.chat_text("s", "u")
        before = len(Fake.seen)
        with self.assertRaises(LLMError) as cm:
            c.chat_text("s", "u")
        self.assertIn("budget", str(cm.exception))
        self.assertEqual(len(Fake.seen), before)          # nothing was sent
        c = self.client(per_day=1)
        c.chat_text("s", "u")
        with self.assertRaises(LLMError):
            c.chat_text("s", "u")


class TestChoosingTheClient(unittest.TestCase):
    def test_default_is_local_ollama(self):
        c = make_client(env={})
        self.assertIsInstance(c, OllamaClient)
        self.assertEqual(c.model, "qwen2.5:7b")

    def test_a_groq_key_selects_the_hosted_qwen(self):
        c = make_client(env={"GROQ_API_KEY": KEY})
        self.assertIsInstance(c, OpenAICompatClient)
        self.assertEqual(c.base_url, "https://api.groq.com/openai/v1")
        self.assertIn("qwen", c.model)
        self.assertEqual(c.label, "Groq (hosted)")
        self.assertLessEqual(c.per_day, 1000)             # stays under the free daily limit

    def test_a_pasted_key_with_spaces_newline_or_quotes_still_works(self):
        for raw in (f" {KEY}\n", f'"{KEY}"', f"'{KEY}' "):
            c = make_client("http://example.test/v1", " my/model ", env={"STUDYBRIDGE_LLM_KEY": raw})
            self.assertEqual(c.api_key, KEY)
            self.assertEqual(c.model, "my/model")

    def test_settings_come_from_arguments_then_environment(self):
        c = make_client("http://example.test/v1", "my/model", env={"STUDYBRIDGE_LLM_KEY": KEY,
                                                                   "STUDYBRIDGE_LLM_PER_DAY": "5"})
        self.assertEqual((c.base_url, c.model, c.per_day), ("http://example.test/v1", "my/model", 5))
        c = make_client(env={"STUDYBRIDGE_LLM_URL": "http://example.test/v1", "STUDYBRIDGE_LLM_MODEL": "m2"})
        self.assertEqual((c.base_url, c.model), ("http://example.test/v1", "m2"))


class TestSwitchOnTheScreen(HostedBase):
    def test_qwen_switch_uses_the_hosted_client_and_names_the_reason_when_it_fails(self):
        from tests.test_payments import make_sandbox
        sb = make_sandbox()
        sb.llm_client = self.client()
        r = sb.act("operator", "set_llm", {"on": True})
        self.assertEqual(r.code, "SETTING_CHANGED")
        self.assertIs(sb.llm, sb.llm_client)
        sb.act("operator", "set_llm", {"on": False})
        sb.llm_client = self.client(api_key="wrong")
        r = sb.act("operator", "set_llm", {"on": True})
        self.assertEqual(r.code, "LLM_UNAVAILABLE")
        self.assertIn("refused the key", r.text)
        self.assertIsNone(sb.llm)


if __name__ == "__main__":
    unittest.main()
