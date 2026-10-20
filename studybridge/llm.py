"""Model clients (standard library only): local Ollama, or a hosted OpenAI-compatible API such as Groq.

The agent works without an LLM. When a model is reachable it is used for two
narrow jobs: turning a free-text request into a schema-constrained intent,
and writing a short plain-language explanation of numbers that the
deterministic tools already computed. Both clients offer the same three methods
(`available`, `chat_json`, `chat_text`) and the same `model`, `label` and `reason` attributes.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque

from .config import HOSTED_LLM, OLLAMA_MODEL, OLLAMA_URL


class LLMError(Exception):
    pass


class OllamaClient:
    label = "Ollama (local)"
    reason = ""

    def __init__(self, base_url: str = OLLAMA_URL, model: str = OLLAMA_MODEL, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=3) as r:
                tags = json.loads(r.read().decode())
            return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _chat(self, messages: list, fmt=None) -> str:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0, "seed": 7}}
        if fmt is not None:
            body["format"] = fmt
        req = urllib.request.Request(self.base_url + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())["message"]["content"]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            raise LLMError(str(exc)) from exc

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        raw = self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}], fmt=schema)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise LLMError(f"model returned invalid JSON: {raw[:200]}") from exc

    def chat_text(self, system: str, user: str) -> str:
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}]).strip()


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


class OpenAICompatClient:
    """Hosted model behind an OpenAI-style `/chat/completions` API (Groq, OpenRouter, Together, Ollama's /v1).

    The key is read from the environment by `make_client`, goes only into the Authorization header, and is cut out of
    every error text (errors reach the audit log). Pasted scam-check text and invoice free text never get here (agent.py
    strips them), and a local call budget keeps a public demo inside the provider's free quota: when it is used up the
    call raises `LLMError` and the agent carries on rules-only, exactly as when the model does not answer.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 45,
                 per_minute: int = 20, per_day: int = 800, name: str = "hosted"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.per_minute, self.per_day = per_minute, per_day
        self.label = f"{name} (hosted)"
        self.reason = ""
        self._calls = deque()          # monotonic times of calls in the last day
        self._lock = threading.Lock()

    # -- plumbing
    def _clean(self, text) -> str:
        text = str(text)
        return text.replace(self.api_key, "***") if self.api_key else text

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "User-Agent": "studybridge-sandbox"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def _budget(self):
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] > 86400:
                self._calls.popleft()
            last_minute = sum(1 for t in self._calls if now - t <= 60)
            if len(self._calls) >= self.per_day:
                raise LLMError("local call budget for today is used up")
            if last_minute >= self.per_minute:
                raise LLMError("local call budget for this minute is used up")
            self._calls.append(now)

    def available(self) -> bool:
        """The key is set, the service answers and lists the model. `reason` says what is missing."""
        self.reason = ""
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            self.reason = "no API key is set on the server"
            return False
        req = urllib.request.Request(self.base_url + "/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            self.reason = "the service refused the key" if exc.code in (401, 403) else f"the service answered {exc.code}"
            return False
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.reason = "the service cannot be reached: " + self._clean(exc)[:80]
            return False
        ids = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
        if ids and self.model not in ids:
            self.reason = f"the service does not list the model '{self.model}'"
            return False
        return True

    def _chat(self, messages: list, json_mode: bool = False) -> str:
        self._budget()
        body = {"model": self.model, "messages": messages, "temperature": 0, "seed": 7, "max_tokens": 700}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                content = json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            raise LLMError(self._clean(f"service answered {exc.code}")) from None
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(self._clean(exc)) from None
        if not isinstance(content, str):
            raise LLMError("model returned no text")
        return _THINK.sub("", content).strip()      # some Qwen models print their reasoning in <think> tags

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        # JSON mode only promises valid JSON, so the schema goes into the prompt; the agent checks every field again.
        system = (system + "\n\nReply with one JSON object only, matching this JSON schema:\n" +
                  json.dumps(schema, separators=(",", ":")))
        raw = self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True)
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise LLMError(f"model returned invalid JSON: {raw[:200]}") from exc

    def chat_text(self, system: str, user: str) -> str:
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}])


def make_client(llm_url=None, model=None, env=None):
    """Pick the model client. Hosted when a URL is given or GROQ_API_KEY / STUDYBRIDGE_LLM_KEY is set; Ollama otherwise.

    Settings: --llm-url / STUDYBRIDGE_LLM_URL, --model / STUDYBRIDGE_LLM_MODEL, key in STUDYBRIDGE_LLM_KEY or
    GROQ_API_KEY. A key never comes from a command-line argument, so it does not show in process lists or history.
    """
    env = os.environ if env is None else env
    url = llm_url or env.get("STUDYBRIDGE_LLM_URL")
    key = (env.get("STUDYBRIDGE_LLM_KEY") or env.get("GROQ_API_KEY") or "").strip().strip("\"'").strip()   # pasted keys often carry a space, newline or quotes
    url = url.strip() if url else url
    model = (model or env.get("STUDYBRIDGE_LLM_MODEL") or "").strip() or None
    if url or key:
        url = url or HOSTED_LLM["url"]
        name = "Groq" if "groq.com" in url else (re.sub(r"^https?://", "", url).split("/")[0] or "hosted")
        return OpenAICompatClient(url, model or HOSTED_LLM["model"], key, name=name,
                                  per_minute=int(env.get("STUDYBRIDGE_LLM_PER_MINUTE", HOSTED_LLM["per_minute"])),
                                  per_day=int(env.get("STUDYBRIDGE_LLM_PER_DAY", HOSTED_LLM["per_day"])))
    return OllamaClient(base_url=env.get("OLLAMA_URL", OLLAMA_URL), model=model or OLLAMA_MODEL)
