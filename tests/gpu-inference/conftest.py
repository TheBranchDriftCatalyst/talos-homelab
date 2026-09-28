"""Fixtures + config for the SOTA GPU node suite (marker: gpu_inference).

These are LIVE functional/integration checks against the real inference server (the
AWS g6e.12xlarge running vLLM + ComfyUI, reached over the mesh). They are OFF by
default and only run with `--live` AND when the endpoint env vars are set + reachable
— so CI and offline runs skip cleanly. Stdlib urllib only (matches the repo; no requests).

Config (env):
  GPU_LLM_BASE_URL    OpenAI-compatible base for the LLM, incl. /v1
                      (e.g. http://gpu-box.mesh.catalyst:8000/v1, or the LiteLLM proxy
                       http://litellm.talos00/v1). REQUIRED for the LLM tests.
  GPU_LLM_MODEL       served model id. Optional — auto-discovered from /v1/models if unset.
  GPU_LLM_API_KEY     bearer token if the endpoint requires one (default: none).
  GPU_IMAGE_BASE_URL  comfyui-shim OpenAI base incl. /v1 (e.g. http://gpu-box.mesh.catalyst:8012/v1).
  GPU_IMAGE_MODEL     image pipeline id. Optional — auto-discovered from the shim's /v1/models.
"""
import json
import os
import re
import urllib.error
import urllib.request

import pytest

LLM_BASE = os.environ.get("GPU_LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.environ.get("GPU_LLM_MODEL", "").strip()
LLM_KEY = os.environ.get("GPU_LLM_API_KEY", "").strip()
IMAGE_BASE = os.environ.get("GPU_IMAGE_BASE_URL", "").rstrip("/")
IMAGE_MODEL = os.environ.get("GPU_IMAGE_MODEL", "").strip()

CHAT_TIMEOUT = int(os.environ.get("GPU_LLM_TIMEOUT", "120"))      # 235B can be slow, esp. cold
IMAGE_TIMEOUT = int(os.environ.get("GPU_IMAGE_TIMEOUT", "240"))   # diffusion is slow

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Qwen3 is a reasoning model; drop <think>…</think> — and a trailing UNCLOSED <think>
    (a reasoning block truncated by max_tokens) — before content assertions."""
    t = _THINK.sub("", text or "")
    t = _THINK_OPEN.sub("", t)
    return t.strip()


def _headers(key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def http(method, url, headers, body=None, timeout=30):
    """Return (status, raw_bytes). Never raises on HTTP status (returns it)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post_json(url, key, body, timeout):
    status, raw = http("POST", url, _headers(key), body=body, timeout=timeout)
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        pass
    return status, parsed, raw


def get_json(url, key, timeout=15):
    status, raw = http("GET", url, _headers(key), timeout=timeout)
    if status != 200:
        raise RuntimeError(f"GET {url} -> HTTP {status}: {raw[:200]!r}")
    return json.loads(raw)


class LLMClient:
    def __init__(self, base, model, key):
        self.base, self.model, self.key = base, model, key

    def models(self):
        return [m["id"] for m in get_json(f"{self.base}/models", self.key).get("data", [])]

    def chat(self, messages, max_tokens=512, temperature=0.2, **extra):
        body = {"model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": temperature,
                # Qwen3 (and other reasoning models) emit <think> by default, which burns the
                # whole token budget before the answer. These are functional/capability checks,
                # not reasoning-depth benchmarks -> disable thinking for determinism. Harmless to
                # models that don't read it. Override via extra if a test wants thinking on.
                "chat_template_kwargs": {"enable_thinking": False}, **extra}
        status, parsed, raw = post_json(f"{self.base}/chat/completions", self.key, body, CHAT_TIMEOUT)
        assert status == 200, f"chat/completions -> HTTP {status}: {raw[:300]!r}"
        return parsed


@pytest.fixture(scope="session")
def llm(request):
    """Live LLM client, or skip the whole LLM suite if unconfigured/unreachable."""
    if not request.config.getoption("--live"):
        pytest.skip("gpu_inference LLM tests need --live")
    if not LLM_BASE:
        pytest.skip("set GPU_LLM_BASE_URL to run the LLM tests")
    try:
        avail = LLMClient(LLM_BASE, LLM_MODEL, LLM_KEY).models()
    except Exception as e:
        pytest.skip(f"LLM endpoint {LLM_BASE} unreachable: {e}")
    if not avail:
        pytest.skip(f"LLM endpoint {LLM_BASE} lists no models")
    model = LLM_MODEL or avail[0]
    if LLM_MODEL and LLM_MODEL not in avail:
        pytest.skip(f"GPU_LLM_MODEL={LLM_MODEL!r} not served (available: {avail})")
    return LLMClient(LLM_BASE, model, LLM_KEY)


@pytest.fixture(scope="session")
def image(request):
    """Live comfyui-shim client (base, key, model, pipelines), or skip if unconfigured/unreachable."""
    if not request.config.getoption("--live"):
        pytest.skip("gpu_inference image tests need --live")
    if not IMAGE_BASE:
        pytest.skip("set GPU_IMAGE_BASE_URL to run the image-generation tests")
    try:
        pipelines = [m["id"] for m in get_json(f"{IMAGE_BASE}/models", LLM_KEY).get("data", [])]
    except Exception as e:
        pytest.skip(f"image endpoint {IMAGE_BASE} unreachable: {e}")
    if not pipelines:
        pytest.skip(f"image endpoint {IMAGE_BASE} lists no pipelines")
    if IMAGE_MODEL and IMAGE_MODEL not in pipelines:
        pytest.skip(f"GPU_IMAGE_MODEL={IMAGE_MODEL!r} not available (have: {pipelines})")
    return {"base": IMAGE_BASE, "key": LLM_KEY, "model": IMAGE_MODEL or pipelines[0], "pipelines": pipelines}
