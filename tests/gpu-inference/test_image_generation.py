"""Live ComfyUI image-generation checks via the comfyui-shim (marker: gpu_inference).

The shim exposes an OpenAI-compatible surface (/v1/models, /v1/images/generations).
Skips unless --live AND GPU_IMAGE_BASE_URL is set + reachable — unless GPU_IMAGE_REQUIRE=1,
which turns every skip into a failure. Set that when ACCEPTING a rig: see conftest.py for
why a suite of skips is indistinguishable from a suite of passes, and how that is exactly
how a rig got recorded as "verified + ComfyUI" having rendered nothing.

Stdlib only — no PIL, so the PNG header is parsed by hand (see _png_size).
"""
import base64
import struct
import zlib

import pytest

from conftest import (
    IMAGE_OWNED_BY,
    IMAGE_REQUIRED_PIPELINES,
    IMAGE_TIMEOUT,
    http,
    post_json,
)

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


def _png_size(blob: bytes):
    """(width, height) from a PNG's IHDR, or None. Stdlib only, no PIL."""
    if not blob.startswith(b"\x89PNG\r\n\x1a\n") or blob[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", blob[16:24])


def png_pixel_stats(blob: bytes, max_rows: int = 64):
    """(distinct_colours, stddev) from a PNG's ACTUAL pixels, or None if undecodable.

    Minimal stdlib PNG reader: non-interlaced, 8-bit, colour type 2 (RGB) or 6 (RGBA),
    which is what these pipelines emit. Returns None rather than guessing for anything
    else, so an unsupported format SKIPS the check instead of faking a pass.

    WHY A REAL DECODER AND NOT A SIZE HEURISTIC. The obvious cheap proxy is "a flat image
    compresses enormously, so flag anything under N bits/pixel". I measured it, and it
    does not work: a 1024x1024 flat black PNG is 0.0239 bits/px while a noiseless render
    of THIS FILE'S OWN PROMPT — a red cube on plain white — is 0.0400. A 1.15x gap, with
    no threshold between them. Any cutoff either passes an all-black frame or fails a
    legitimate minimal render. Decoding is ~40 lines and actually answers the question.

    Verified against synthetic PNGs encoded with all five filter types (None/Sub/Up/
    Average/Paeth), which agree per case — real encoders pick filters per row, so the
    un-filtering below is exercised in practice, not just in theory.
    """
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, ihdr = 8, bytearray(), None
    while pos + 8 <= len(blob):
        ln = struct.unpack(">I", blob[pos:pos + 4])[0]
        typ = blob[pos + 4:pos + 8]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", blob[pos + 8:pos + 21])
        elif typ == b"IDAT":
            idat += blob[pos + 8:pos + 8 + ln]
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if not ihdr:
        return None
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8 or interlace != 0 or ctype not in (2, 6) or not w or not h:
        return None
    nch = 3 if ctype == 2 else 4
    stride = w * nch
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    step = max(1, h // max_rows)
    xstep = max(1, w // 64)
    prev = bytearray(stride)
    colours, vals = set(), []
    for y in range(h):
        off = y * (stride + 1)
        if off + stride + 1 > len(raw):
            break
        f = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        # Un-filter. EVERY row must be processed even when sampling, because Up/Average/
        # Paeth are defined relative to the previous reconstructed scanline.
        if f == 1:
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                c = prev[i - nch] if i >= nch else 0
                b = prev[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        prev = line
        if y % step:
            continue
        for x in range(0, w, xstep):
            i = x * nch
            px = (line[i], line[i + 1], line[i + 2])
            colours.add(px)
            vals.append((px[0] + px[1] + px[2]) / 3.0)
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return len(colours), var ** 0.5


def _decode(item, image):
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        st, blob = http("GET", item["url"], {}, timeout=60)
        assert st == 200, f"fetching image url -> HTTP {st}"
        return blob
    pytest.fail(f"image item had neither b64_json nor url: {list(item.keys())}")


# ── catalogue ────────────────────────────────────────────────────────────────────────


def test_shim_lists_pipelines(image):
    assert image["pipelines"], "comfyui-shim /v1/models returned no pipelines"
    assert image["model"] in image["pipelines"]


def test_shim_serves_the_four_staged_pipelines(image):
    """All four staged pipelines must be listed.

    Asserted as a SUBSET so adding a fifth does not fail the suite, but losing one of
    these does. These are `_meta.name` values, NOT filename stems — pipelines.py keys by
    `meta.get("name") or path.stem`, so a test written against filenames would pass
    against the wrong thing.
    """
    missing = [p for p in IMAGE_REQUIRED_PIPELINES if p not in image["pipelines"]]
    assert not missing, (
        f"staged pipelines missing from /v1/models: {missing}. "
        f"Served: {sorted(image['pipelines'])}"
    )


def test_shim_reports_the_expected_backend(image):
    """`owned_by` must name the host we think we are talking to.

    THE SECOND-MOST-IMPORTANT ASSERTION IN THIS FILE. The Mac's comfyui-shim serves the
    SAME pipeline ids from the SAME pipelines/ directory on the SAME port as the AWS rig,
    so every other test here passes identically against either one. Nothing else in the
    response distinguishes them: the request contract has no backend field and the
    operator's image_cells table has no backend column.

    Skipped when GPU_IMAGE_OWNED_BY is unset, because pointing this suite at the Mac
    deliberately is legitimate. Set it to aws-l40s-comfyui when accepting the rig.
    """
    if not IMAGE_OWNED_BY:
        pytest.skip("set GPU_IMAGE_OWNED_BY to assert which backend answered")
    assert image["owned_by"] == [IMAGE_OWNED_BY], (
        f"expected every model owned_by {IMAGE_OWNED_BY!r}, got {image['owned_by']}. "
        "A mismatch means this suite is talking to a different host than intended — "
        "most likely the Mac's local shim instead of the rig."
    )


# ── rendering ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pipeline", IMAGE_REQUIRED_PIPELINES)
def test_generate_image(image, pipeline):
    """Render through EVERY staged pipeline, at each one's native size.

    This is the only layer that proves the WEIGHTS are present and correct: the catalogue
    lists pipelines, not files, and a missing .safetensors fails at ComfyUI graph-submit
    time, which the shim surfaces as a 502. Four renders exercise all 14 staged files and
    prove the per-workflow VRAM swap works on a single L40S — the core architectural bet
    of the two-rig split.

    1024x1024, not 512: all four declare default_size 1024x1024, and the
    flux-architecture and EmptySD3LatentImage models degrade badly below it.
    """
    if pipeline not in image["pipelines"]:
        pytest.skip(f"{pipeline} not served here (have: {sorted(image['pipelines'])})")
    body = {
        "model": pipeline,
        "prompt": "a single red cube centered on a plain white background, product photo",
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
        # Fixed seed so a re-run is comparable; the shim drops it if unsupported.
        "seed": 42,
    }
    status, parsed, raw = post_json(
        f"{image['base']}/images/generations", image["key"], body, IMAGE_TIMEOUT
    )
    assert status == 200, f"{pipeline}: image gen HTTP {status}: {raw[:300]!r}"
    data = (parsed or {}).get("data") or []
    assert data, f"{pipeline}: no image data returned: {raw[:300]!r}"

    blob = _decode(data[0], image)

    kind = _looks_like_image(blob)
    assert kind is not None, (
        f"{pipeline}: returned bytes are not a known image format "
        f"(first bytes: {blob[:12]!r})"
    )
    assert len(blob) > 1024, f"{pipeline}: image suspiciously small ({len(blob)} bytes)"

    if kind == "png":
        size = _png_size(blob)
        assert size == (1024, 1024), f"{pipeline}: expected 1024x1024, got {size}"
        stats = png_pixel_stats(blob)
        if stats is not None:
            colours, stddev = stats
            # STDDEV, not colour count. A uniform frame is a perfectly VALID PNG and is
            # the classic signature of a model that loaded but rendered nothing — wrong
            # VAE, missing text encoder, all-zero latent — so magic bytes and byte length
            # both pass it happily. Measured: a flat fill is EXACTLY 0.000, while even a
            # two-colour image of this prompt is 34.9. Colour count alone would have
            # misread that two-colour case as uniform.
            assert stddev > 0.5, (
                f"{pipeline}: rendered a UNIFORM {size} frame "
                f"({colours} distinct colour(s), stddev {stddev:.3f}). Valid PNG, no "
                "image — check the VAE and text encoder for this pipeline."
            )


def test_comfyui_itself_is_serving(image):
    """ComfyUI's OWN endpoint must answer, not just the shim's.

    The shim's /healthz returns HTTP 200 with "comfyui_reachable" as a BODY FIELD whether
    or not ComfyUI is up, so neither it nor a readiness probe can prove ComfyUI exists.
    /system_stats is ComfyUI's own server and cannot answer unless it is genuinely
    listening — which is also why the image relay probes it.

    Reached by stripping /v1 off the shim base and using the UI host, so it only runs
    where ComfyUI is routed alongside the shim.
    """
    base = image["base"]
    if not base.endswith("/v1"):
        pytest.skip("GPU_IMAGE_BASE_URL does not end in /v1; cannot derive the UI host")
    # imagegen.talos00/v1 -> comfy.talos00 ; localhost:8012/v1 -> localhost:8188
    root = base[: -len("/v1")]
    candidates = [
        root.replace("imagegen.", "comfy."),
        root.replace(":8012", ":8188"),
    ]
    errors = []
    for cand in dict.fromkeys(candidates):
        if cand == root:
            continue
        try:
            st, raw = http("GET", f"{cand}/system_stats", {}, timeout=15)
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(f"{cand}: {e}")
            continue
        if st == 200 and b"devices" in raw:
            return
        errors.append(f"{cand}: HTTP {st}")
    pytest.skip(
        "ComfyUI /system_stats not reachable from here; tried: " + "; ".join(errors)
    )
