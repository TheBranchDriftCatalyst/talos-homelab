#!/usr/bin/env python3
"""Fail when catalyst-themepark's palette disagrees with catalyst-ui's.

WHY THIS EXISTS. catalyst-ui is the design system of record; catalyst-themepark
hand-copies its palette into src/00-tokens.css because it ships raw injected CSS
and cannot consume a React package. A hand-copy guarded only by a comment drifts,
and this one did: themepark's --neon-gold held #ffb800, which is catalyst-ui's
--neon-YELLOW, while catalyst-ui's real gold (#f9a410) was absent entirely. Every
themepark rule using var(--neon-gold) painted a different colour from the same
token name in catalyst-ui, across ~60 injected apps.

It went unnoticed because the guarding comment asserted the divergence was CLOSED
and told the reader to treat the `DRIFT was` markers as history rather than
warnings. A false comment is worse than no comment, which is why this is a script
and not a paragraph.

WHICH BLOCK IS COMPARED. themepark is a dark netrunner theme, so it mirrors
catalyst-ui's `.dark` override block, not its :root defaults. Comparing against
:root would report ~8 false divergences.

SCOPE. Only tokens themepark actually defines are checked. themepark is
deliberately a SUBSET — it has no reason to carry every catalyst-ui token — so a
token missing from themepark is not a finding. A token present in both with
different values always is.
"""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# Overridable so the check itself can be tested against fixtures. A parity check
# that has only ever been observed FAILING is not known to be able to pass.
UI = Path(os.environ.get("CATALYST_UI_TOKENS")
          or HERE.parent / "catalyst-ui" / "lib/contexts/Theme/styles/catalyst.css")
TP = Path(os.environ.get("CATALYST_THEMEPARK_TOKENS")
          or HERE.parent / "catalyst-themepark" / "src/00-tokens.css")

# A CI marker turns "sibling absent" from a skip into a failure. The existing
# theme-drift check exit 0's when the sibling is missing, which is exactly how a
# real drift survived a day unnoticed — a check that cannot run and says nothing
# is indistinguishable from a check that passed.
CI = os.environ.get("CATALYST_SIBLINGS_REQUIRED") == "1"

TOKEN = re.compile(r"^\s*(--[a-z0-9-]+)\s*:\s*(.+?)\s*;", re.M)
# hsl() is frequently prettier-wrapped across four lines in catalyst-ui.
HSL_MULTILINE = re.compile(r"(--[a-z0-9-]+)\s*:\s*hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)", re.S)


def hsl_to_rgb(h, s, light):
    s, light = s / 100.0, light / 100.0
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs(((h / 60.0) % 2) - 1))
    m = light - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(round((v + m) * 255) for v in (r, g, b))


def normalise(value):
    """Reduce a colour to an (r,g,b) tuple so #fff, rgb() and hsl() compare equal.

    Returns the raw string for anything that is not a colour, so non-colour
    tokens still compare — just textually.
    """
    v = " ".join(value.split()).lower().rstrip(";")
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)", v)
    if m:
        return hsl_to_rgb(*(float(g) for g in m.groups()))
    m = re.fullmatch(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", v)
    if m:
        return tuple(int(g) for g in m.groups())
    return v


def resolve_vars(table):
    """Inline single-level var(--x) using the SAME file's tokens.

    Without this the check reports differences that are textual only. Real case:
    catalyst-ui writes `rgba(var(--shadow-base-rgb), 0.3)` while themepark writes
    `rgba(0, 0, 0, 0.3)` — and --shadow-base-rgb IS `0, 0, 0`, so the two paint
    the same pixels. themepark inlines deliberately, because it cannot reference
    a token it does not define.

    A check that reports a benign difference every run is a check people learn to
    ignore, which costs more than the difference it reports.
    """
    def sub(value):
        if not isinstance(value, str):
            return value
        for _ in range(3):                      # bounded: no cycles, no deep chains
            m = re.search(r"var\(\s*(--[a-z0-9-]+)\s*\)", value)
            if not m:
                break
            ref = table.get(m.group(1))
            if ref is None:
                break
            text = ", ".join(str(n) for n in ref) if isinstance(ref, tuple) else str(ref)
            value = value[:m.start()] + text + value[m.end():]
        return value
    return {k: sub(v) for k, v in table.items()}


def parse_block(text):
    out = {}
    for name, raw in TOKEN.findall(text):
        out[name] = normalise(re.sub(r"/\*.*?\*/", "", raw, flags=re.S))
    for name, h, s, light in HSL_MULTILINE.findall(text):
        out[name] = hsl_to_rgb(float(h), float(s), float(light))
    return resolve_vars(out)


def dark_block(text):
    """catalyst-ui's dark override. Starts at a .dark selector, ends at its brace."""
    i = text.find(".dark")
    if i == -1:
        return ""
    depth, start = 0, text.find("{", i)
    for j in range(start, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j]
    return text[start:]


def main() -> int:
    for label, p in (("catalyst-ui", UI), ("catalyst-themepark", TP)):
        if not p.exists():
            msg = f"[token-parity] {label} not checked out at {p}"
            if CI:
                print(msg + " — REQUIRED (CATALYST_SIBLINGS_REQUIRED=1)", file=sys.stderr)
                return 1
            print(msg + " — skipping")
            return 0

    ui = parse_block(dark_block(UI.read_text()))
    tp = parse_block(TP.read_text())
    if not ui or not tp:
        print("[token-parity] parsed no tokens — the file format changed", file=sys.stderr)
        return 1

    shared = sorted(set(ui) & set(tp))
    bad = [(k, ui[k], tp[k]) for k in shared if ui[k] != tp[k]]

    print(f"[token-parity] {len(shared)} shared tokens compared "
          f"(catalyst-ui .dark vs catalyst-themepark)")
    if not bad:
        print("[token-parity] in sync")
        return 0

    print(f"\n[token-parity] {len(bad)} DIVERGENT token(s):\n", file=sys.stderr)
    for name, a, b in bad:
        print(f"  {name}", file=sys.stderr)
        print(f"      catalyst-ui : {a}", file=sys.stderr)
        print(f"      themepark   : {b}", file=sys.stderr)
        # Name the confusion when one repo's value is another token's value.
        for other, val in ui.items():
            if other != name and val == b:
                print(f"      ^ themepark's {name} is catalyst-ui's {other}", file=sys.stderr)
    print("\n  catalyst-ui is the design system of record: change the value there "
          "first, then port it.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
