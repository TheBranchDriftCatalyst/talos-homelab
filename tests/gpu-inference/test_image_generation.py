"""Live ComfyUI image-generation checks via the comfyui-shim (marker: gpu_inference).

The shim exposes an OpenAI-compatible surface (/v1/models, /v1/images/generations).
Skips unless --live AND GPU_IMAGE_BASE_URL is set + reachable. Stdlib urllib only.
"""
import base64

import pytest

from conftest import IMAGE_TIMEOUT, http, post_json

pytestmark = pytest.mark.gpu_inference

_MAGICS = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
}


def _looks_like_image(blob: bytes):
    for magic, kind in _MAGICS.items():
        if blob.startswith(magic):
            return kind
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return None


def test_shim_lists_pipelines(image):
    assert image["pipelines"], "comfyui-shim /v1/models returned no pipelines"
    assert image["model"] in image["pipelines"]


def test_generate_image(image):
    body = {
        "model": image["model"],
        "prompt": "a single red cube centered on a plain white background, product photo",
        "n": 1,
        "size": "512x512",
        "response_format": "b64_json",
    }
    status, parsed, raw = post_json(f"{image['base']}/images/generations", image["key"], body, IMAGE_TIMEOUT)
    assert status == 200, f"image gen HTTP {status}: {raw[:300]!r}"
    data = (parsed or {}).get("data") or []
    assert data, f"no image data returned: {raw[:300]!r}"

    item = data[0]
    if item.get("b64_json"):
        blob = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        st, blob = http("GET", item["url"], {}, timeout=60)
        assert st == 200, f"fetching image url -> HTTP {st}"
    else:
        pytest.fail(f"image item had neither b64_json nor url: {list(item.keys())}")

    kind = _looks_like_image(blob)
    assert kind is not None, f"returned bytes are not a known image format (first bytes: {blob[:12]!r})"
    assert len(blob) > 1024, f"image suspiciously small ({len(blob)} bytes) for {kind}"
