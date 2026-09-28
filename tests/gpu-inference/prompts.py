"""Prompt corpus for the LLM functional suite — one entry per prompt *type*.

Each case asserts on the STRUCTURE strictly (valid completion, usage, finish_reason —
done in the test) and the CONTENT leniently here (substring/parse), so a quantized
model's phrasing variance doesn't make it flaky while a genuinely broken server fails.
`check(text)` receives the assistant content with any <think>…</think> stripped.
"""
import json
import re


def _extract_json(text: str):
    """Pull the first JSON object out of a reply (may be fenced or prose-wrapped)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = m.group(1) if m else None
    if blob is None:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        blob = m.group(0) if m else None
    return json.loads(blob) if blob else None


def _json_ok(text: str) -> bool:
    try:
        obj = _extract_json(text)
        return isinstance(obj, dict) and "name" in obj and "age" in obj
    except Exception:
        return False


# id, kind, messages, max_tokens, check(stripped_content) -> bool
CASES = [
    dict(id="chat_greeting", kind="chat",
         messages=[{"role": "user", "content": "Say hello in one short, friendly sentence."}],
         max_tokens=64, check=lambda t: len(t.strip()) > 0),

    dict(id="coding_function", kind="coding",
         messages=[{"role": "user", "content":
                    "Write a Python function `is_prime(n)` that returns True iff n is prime. "
                    "Return only the code."}],
         max_tokens=400, check=lambda t: "def" in t and "is_prime" in t),

    dict(id="reasoning_math", kind="reasoning",
         messages=[{"role": "user", "content":
                    "A train travels 60 km in 1.5 hours. What is its average speed in km/h? "
                    "Answer with just the number."}],
         max_tokens=256, check=lambda t: "40" in t),

    dict(id="structured_json", kind="structured",
         messages=[{"role": "user", "content":
                    "Return ONLY a JSON object with keys \"name\" (string) and \"age\" (integer) "
                    "for a person named Ada who is 36. No prose."}],
         max_tokens=128, check=_json_ok),

    dict(id="instruction_following", kind="instruction",
         messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
         max_tokens=16, check=lambda t: t.strip().rstrip(".").upper() == "OK"),

    dict(id="multi_turn_context", kind="multi_turn",
         messages=[{"role": "user", "content": "My favorite color is teal. Remember it."},
                   {"role": "assistant", "content": "Got it — teal."},
                   {"role": "user", "content": "What did I say my favorite color is? One word."}],
         max_tokens=32, check=lambda t: "teal" in t.lower()),

    dict(id="summarization", kind="summarize",
         messages=[{"role": "user", "content":
                    "Summarize in ONE sentence: Talos Linux is a minimal, immutable, API-managed "
                    "operating system purpose-built for Kubernetes, with no shell or SSH; all "
                    "configuration flows through a declarative machine config applied via talosctl, "
                    "which reduces the attack surface and makes nodes reproducible."}],
         max_tokens=160, check=lambda t: 0 < len(t.strip()) < 600 and "talos" in t.lower()),
]
