"""Fixtures + config for the SOTA GPU node suite (marker: gpu_inference).

These are LIVE functional/integration checks against the real rigs. They are OFF by
default and only run with `--live` AND when the endpoint env vars are set + reachable
— so CI and offline runs skip cleanly. Stdlib urllib only (matches the repo; no requests).

TWO RIGS, NOT ONE. The old docstring described "the AWS g6e.12xlarge running vLLM +
ComfyUI" — a single box serving both, which never worked and no longer exists. Text comes
from the inference rig (vLLM) and images from the image-gen rig (ComfyUI + comfyui-shim),
each with its own endpoint, its own relay and its own on-switch.

── WHY STRICT MODE EXISTS ───────────────────────────────────────────────────────────
Every fixture below SKIPS when its endpoint is unreachable or lists nothing. That is
right for CI, and dangerous for acceptance: a suite of skips is visually
indistinguishable from a suite of passes, and the comfyui-shim image shipped for a month
answering /v1/models with HTTP 200 and an EMPTY list. Under the plain fixture that reads
as "green with skips" — which is mechanically how a rig came to be recorded as
"verified 9/9 tests + ComfyUI" having never rendered anything.

So set GPU_IMAGE_REQUIRE=1 (or GPU_LLM_REQUIRE=1) when you are ACCEPTING a rig. Every
skip path becomes a failure, and the suite can finally catch the original class of bug.

Config (env):
  GPU_LLM_BASE_URL    OpenAI-compatible base for the LLM, incl. /v1
                      (e.g. http://gpu-box.mesh.catalyst:8000/v1, or the LiteLLM proxy
                       http://litellm.talos00/v1). REQUIRED for the LLM tests.
  GPU_LLM_MODEL       served model id. Optional — auto-discovered from /v1/models if unset.
  GPU_LLM_API_KEY     bearer token if the endpoint requires one (default: none).
  GPU_IMAGE_BASE_URL  comfyui-shim OpenAI base incl. /v1 (e.g. http://imagegen.talos00/v1).
  GPU_IMAGE_MODEL     image pipeline id. Optional — auto-discovered from the shim's /v1/models.
  GPU_IMAGE_API_KEY   bearer token for the shim. Falls back to GPU_LLM_API_KEY only so
                      existing invocations keep working; they are separate parameters.
  GPU_IMAGE_OWNED_BY  expected `owned_by` on every model. Set it to aws-l40s-comfyui when
                      accepting the rig: the Mac's shim serves the SAME pipeline ids from
                      the SAME pipelines/ directory on the SAME port, so without this a
                      fully passing image suite proves nothing about WHICH host answered.
  GPU_IMAGE_REQUIRE   set to 1 to turn every image skip into a FAILURE (see below).
  GPU_LLM_REQUIRE     same, for the LLM fixture.
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
# Its own parameter, falling back to the LLM key only for compatibility with existing
# invocations. The two rigs read the same SSM parameter today, but coupling the TESTS to
# that coincidence would hide the day they diverge.
IMAGE_KEY = (os.environ.get("GPU_IMAGE_API_KEY", "").strip()
             or os.environ.get("GPU_LLM_API_KEY", "").strip())
IMAGE_OWNED_BY = os.environ.get("GPU_IMAGE_OWNED_BY", "").strip()
# The four pipelines the image rig stages. Asserted as a SUBSET, so adding a fifth does
# not fail the suite, but losing one of these does.
IMAGE_REQUIRED_PIPELINES = ("z-image-turbo", "qwen-image-2.1",
                            "hidream-i1-fast", "chroma-radiance")

CHAT_TIMEOUT = int(os.environ.get("GPU_LLM_TIMEOUT", "120"))      # 235B can be slow, esp. cold
# 600, not 240. The old default was UNDER chroma-radiance's 274s reference time on an
# M5 Max, so the slowest of the four pipelines would have timed out before rendering —
# and a timeout here reads as "the rig is broken" rather than "the budget was wrong".
# Reference step counts / seconds: z-image 8/37, hidream 16/18, qwen 25/112, chroma 30/274.
IMAGE_TIMEOUT = int(os.environ.get("GPU_IMAGE_TIMEOUT", "600"))

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Qwen3 is a reasoning model; drop <think>…</think> — and a trailing UNCLOSED <think>
    (a reasoning block truncated by max_tokens) — before content assertions."""
    t = _THINK.sub("", text or "")
    t = _THINK_OPEN.sub("", t)
    return t.strip()


def _bail(request, env_flag: str, msg: str):
    """Skip, or FAIL when the matching REQUIRE flag is set.

    The flag is what separates "this endpoint is not configured in CI" from "I am
    accepting a rig and an unreachable endpoint is a defect".
    """
    if os.environ.get(env_flag, "").strip() in ("1", "true", "yes"):
        pytest.fail(f"{msg}  [{env_flag}=1 — skips are failures]")
    pytest.skip(msg)


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
        _bail(request, "GPU_LLM_REQUIRE", "set GPU_LLM_BASE_URL to run the LLM tests")
    try:
        avail = LLMClient(LLM_BASE, LLM_MODEL, LLM_KEY).models()
    except Exception as e:
        _bail(request, "GPU_LLM_REQUIRE", f"LLM endpoint {LLM_BASE} unreachable: {e}")
    if not avail:
        _bail(request, "GPU_LLM_REQUIRE", f"LLM endpoint {LLM_BASE} lists no models")
    model = LLM_MODEL or avail[0]
    if LLM_MODEL and LLM_MODEL not in avail:
        _bail(request, "GPU_LLM_REQUIRE",
              f"GPU_LLM_MODEL={LLM_MODEL!r} not served (available: {avail})")
    return LLMClient(LLM_BASE, model, LLM_KEY)


@pytest.fixture(scope="session")
def image(request):
    """Live comfyui-shim client (base, key, model, pipelines), or skip if unconfigured/unreachable."""
    if not request.config.getoption("--live"):
        pytest.skip("gpu_inference image tests need --live")
    if not IMAGE_BASE:
        _bail(request, "GPU_IMAGE_REQUIRE",
              "set GPU_IMAGE_BASE_URL to run the image-generation tests")
    try:
        payload = get_json(f"{IMAGE_BASE}/models", IMAGE_KEY).get("data", [])
    except Exception as e:
        _bail(request, "GPU_IMAGE_REQUIRE", f"image endpoint {IMAGE_BASE} unreachable: {e}")
    pipelines = [m["id"] for m in payload]
    if not pipelines:
        # THE BUG THIS CATCHES: Path.glob on a missing pipelines dir returns empty
        # WITHOUT raising, so a misconfigured shim answers HTTP 200 with data: [].
        _bail(request, "GPU_IMAGE_REQUIRE",
              f"image endpoint {IMAGE_BASE} lists NO pipelines (HTTP 200 with an empty "
              "data array — check PIPELINES_DIR on the shim)")
    if IMAGE_MODEL and IMAGE_MODEL not in pipelines:
        _bail(request, "GPU_IMAGE_REQUIRE",
              f"GPU_IMAGE_MODEL={IMAGE_MODEL!r} not available (have: {pipelines})")
    return {
        "base": IMAGE_BASE,
        "key": IMAGE_KEY,
        "model": IMAGE_MODEL or pipelines[0],
        "pipelines": pipelines,
        # owned_by per model — the only field that says which HOST rendered.
        "owned_by": sorted({m.get("owned_by", "") for m in payload}),
    }
