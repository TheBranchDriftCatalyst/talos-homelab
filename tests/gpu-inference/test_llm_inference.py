"""Live LLM functional/integration checks against the SOTA GPU node (marker: gpu_inference).

Run:  task test:gpu-inference:live
  or  GPU_LLM_BASE_URL=http://gpu-box.mesh.catalyst:8000/v1 python3 -m pytest -m gpu_inference --live
Skips cleanly unless --live AND GPU_LLM_BASE_URL is set + reachable.
"""
import pytest

from conftest import strip_think
from prompts import CASES

pytestmark = pytest.mark.gpu_inference


def test_models_endpoint_lists_served_model(llm):
    models = llm.models()
    assert models, "/v1/models returned no models"
    assert llm.model in models


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_prompt_type(llm, case):
    resp = llm.chat(case["messages"], max_tokens=case["max_tokens"])

    # ---- structure (strict): a well-formed OpenAI chat completion ----
    assert resp.get("choices"), f"no choices in response: {resp}"
    choice = resp["choices"][0]
    content = strip_think(choice["message"]["content"])
    assert content, f"[{case['id']}] empty content after stripping <think>"
    assert choice.get("finish_reason") in ("stop", "length", "tool_calls"), \
        f"[{case['id']}] unexpected finish_reason={choice.get('finish_reason')}"
    usage = resp.get("usage") or {}
    assert usage.get("completion_tokens", 0) > 0, f"[{case['id']}] no completion tokens"

    # ---- content (lenient but meaningful): the prompt type actually worked ----
    assert case["check"](content), \
        f"[{case['id']}] content failed its {case['kind']} check: {content[:280]!r}"


def test_concurrent_requests_batch(llm):
    """vLLM continuous batching: a few concurrent requests all return cleanly."""
    import concurrent.futures as cf
    msgs = [{"role": "user", "content": f"In one word, what is {n} squared?"} for n in (2, 3, 4, 5)]
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda m: llm.chat([m], max_tokens=32), msgs))
    for r in results:
        assert strip_think(r["choices"][0]["message"]["content"]), "empty concurrent completion"
