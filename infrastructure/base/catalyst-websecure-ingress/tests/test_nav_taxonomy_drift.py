"""Phase 5: the copies of the nav taxonomy, pinned to each other.

NO CLUSTER, NO KUBECTL. Pure file reading, so it runs anywhere and always.

WHY THIS SUITE EXISTS. The `nav` block the CatalystWebSecureIngress XRD gained in phase 5 buys
real admission-time validation (see the catalyst-nav operator's internal/xrdschema for the
rejection evidence) at the cost of DUPLICATION, and this file is the price being paid honestly
rather than hidden:

  * the taxonomy itself          infrastructure/base/catalyst-nav/taxonomy.yaml  (8 NavGroups)
  * the XRD's enum               spec.nav.group                                 (8 names)
  * the composition's title map  the gethomepage.dev/group patch                (8 name->title)

An OpenAPI enum cannot be computed from other objects, which is exactly why the enum is a copy
and exactly why it is the only reference check available (NavEntry.spec.navGroupRef makes the
same point about itself and defers to a webhook). A copy nobody compares is drift waiting to
happen — the repo's own cautionary case is a schema comment that CLAIMED a constraint with no
rule behind it. So: compared, every run.

The shared-middleware trio is the same story one layer down. `themed` is derived from middleware
NAMES, and the trio that must be EXCLUDED from that derivation appears in three places (this
XRD's CEL rules, the operator's sharedMiddlewares, and themepark/middlewares.yaml which defines
them). Two of those three are machine-readable and are compared here. The third is the
definition itself and is out of this file's reach.

IT WAS FOUR PLACES until build_nav.py was deleted. For the length of the nav migration the
derivation had two implementations — a Python sidecar and the Go operator — and this file had to
pin both against the XRD. The operator is now the sole producer, so one copy and one test went
away together.
"""
import re
from pathlib import Path

import pytest
import yaml

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())

XRD = _ROOT / "infrastructure/base/catalyst-websecure-ingress/xrd.yaml"
COMPOSITION = _ROOT / "infrastructure/base/catalyst-websecure-ingress/composition.yaml"
TAXONOMY = _ROOT / "infrastructure/base/catalyst-nav/taxonomy.yaml"
DERIVE_GO = _ROOT / "infrastructure/base/catalyst-nav/operator/internal/navmodel/derive.go"

# The trio as the XRD's CEL rules spell it. Asserted against the other two copies below rather
# than trusted: this constant is the claim, not the evidence.
SHARED = {"catalyst-compress", "catalyst-accept-encoding", "catalyst-asset-cache"}


# ---- fixtures ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def xrd():
    return yaml.safe_load(XRD.read_text())


@pytest.fixture(scope="module")
def nav_schema(xrd):
    spec = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
    assert "nav" in spec["properties"], "the XRD has no spec.nav block; phase 5 is not present"
    return spec


@pytest.fixture(scope="module")
def composition():
    return yaml.safe_load(COMPOSITION.read_text())


@pytest.fixture(scope="module")
def websecure_patches(composition):
    """The patch list on the websecure IngressRoute — the only resource carrying annotations."""
    resources = composition["spec"]["pipeline"][0]["input"]["resources"]
    ir = next(r for r in resources if r["name"] == "ir-websecure")
    return ir["patches"]


@pytest.fixture(scope="module")
def taxonomy():
    """{metadata.name: spec.title} for every NavGroup in the reviewed taxonomy."""
    docs = [d for d in yaml.safe_load_all(TAXONOMY.read_text()) if d]
    assert all(d["kind"] == "NavGroup" for d in docs), "taxonomy.yaml holds something else now"
    return {d["metadata"]["name"]: d["spec"]["title"] for d in docs}


@pytest.fixture(scope="module")
def title_map(websecure_patches):
    """The name->title map transform behind the gethomepage.dev/group patch."""
    for p in websecure_patches:
        if p["toFieldPath"].endswith('annotations["gethomepage.dev/group"]') and p["fromFieldPath"] == "spec.nav.group":
            transforms = p["transforms"]
            assert len(transforms) == 1 and transforms[0]["type"] == "map", (
                "the nav.group -> gethomepage.dev/group patch no longer uses a single map "
                "transform; this suite can no longer see the title mapping it is here to pin"
            )
            return transforms[0]["map"]
    pytest.fail("no patch derives gethomepage.dev/group from spec.nav.group")


# ---- the three copies of the taxonomy ---------------------------------------------------


def test_enum_matches_the_taxonomy_objects(nav_schema, taxonomy):
    """The XRD's enum is exactly the set of NavGroup names that exist.

    A name in the enum with no NavGroup is the worse direction: the claim is admitted, the
    annotation is emitted, and the entry resolves to nothing — the same dangling reference the
    enum was added to prevent, just moved one file along.
    """
    enum = set(nav_schema["properties"]["nav"]["properties"]["group"]["enum"])
    assert enum == set(taxonomy), (
        f"spec.nav.group's enum and taxonomy.yaml disagree.\n"
        f"  in the enum, no NavGroup:  {sorted(enum - set(taxonomy))}\n"
        f"  NavGroup, not in the enum: {sorted(set(taxonomy) - enum)}"
    )


def test_enum_is_sorted(nav_schema):
    """Not cosmetic — an unsorted enum makes "did this list change?" unreadable in review."""
    enum = nav_schema["properties"]["nav"]["properties"]["group"]["enum"]
    assert enum == sorted(enum), f"spec.nav.group's enum is not sorted: {enum}"


def test_title_map_covers_the_enum_exactly(title_map, nav_schema):
    """A `map` transform ERRORS on an unmapped key.

    function-patch-and-transform's ResolveMap returns "key %s is not found in map", which
    Crossplane surfaces as a render failure and Synced=False on the claim. So a key missing here
    is not a missing annotation — it is an app whose whole ingress stops reconciling, including
    the NetworkPolicy that locks it down east-west. The enum is what keeps the input inside this
    key set; this test is what keeps the key set covering the enum.
    """
    enum = set(nav_schema["properties"]["nav"]["properties"]["group"]["enum"])
    assert set(title_map) == enum, (
        f"the composition's title map and the XRD's enum disagree.\n"
        f"  admissible but unmapped (render failure): {sorted(enum - set(title_map))}\n"
        f"  mapped but inadmissible (dead entry):     {sorted(set(title_map) - enum)}"
    )


def test_title_map_emits_the_taxonomy_titles(title_map, taxonomy):
    """The emitted gethomepage.dev/group must be the NavGroup's own display title.

    This is the assertion that actually prevents a THIRD spelling of a group appearing in the
    live nav. The live pipeline groups by this annotation verbatim, so a title here that the
    taxonomy does not use would render a brand-new dropdown — which is the Monitoring vs
    Observability fork, reproduced by the very mechanism meant to end it.
    """
    wrong = {k: (v, taxonomy[k]) for k, v in title_map.items() if taxonomy.get(k) != v}
    assert not wrong, (
        "the composition would emit a gethomepage.dev/group that is not the NavGroup's title: "
        + ", ".join(f"{k}: emits {got!r}, taxonomy says {want!r}" for k, (got, want) in sorted(wrong.items()))
    )


# ---- the shared-middleware trio ---------------------------------------------------------


def test_xrd_cel_rules_exclude_exactly_the_shared_trio(nav_schema):
    """Both middleware-walking CEL rules subtract the same trio, and only it.

    Counting the shared middlewares would make `injected` tautologically true for every route in
    the cluster (they ride along in every chain) and would make `themed` true for apps carrying
    nothing but compression. build_nav.py subtracts them; the rules that must agree with
    build_nav.py have to subtract them too.
    """
    rules = [r["rule"] for r in nav_schema["x-kubernetes-validations"]]
    walking = [r for r in rules if "self.middlewares.exists" in r]
    assert len(walking) == 2, (
        f"expected exactly two middleware-walking CEL rules (injection + themed), found "
        f"{len(walking)}; this test no longer knows which rules it is checking"
    )
    for rule in walking:
        listed = set(re.findall(r"'(catalyst-[a-z-]+)'", rule))
        # The themed rule also mentions no bare middleware names outside the trio; the
        # prefix/substring tests use 'catalyst-' and 'nav', which the pattern above would
        # pick up as 'catalyst-' only if quoted with a trailing hyphen.
        listed.discard("catalyst-")
        assert listed == SHARED, (
            f"a CEL rule's shared-middleware exclusion list drifted.\n"
            f"  rule:    {rule}\n"
            f"  missing: {sorted(SHARED - listed)}\n"
            f"  extra:   {sorted(listed - SHARED)}"
        )


def test_operator_shared_set_matches():
    """The operator's sharedMiddlewares is the live definition the CEL rules must track.

    THIS USED TO BE TWO TESTS. build_nav.py carried its own `SHARED` set and was checked
    separately, because for the length of the migration there were two implementations of the
    derivation and both had to agree with the XRD. The sidecar is deleted and the operator is
    now the sole producer, so there is one definition and one test — which is the point of
    having done the migration, not a reduction in coverage. The four copies the module
    docstring warns about are three.
    """
    src = DERIVE_GO.read_text()
    block = re.search(r"sharedMiddlewares = map\[string\]struct\{\}\{(.*?)\n\}", src, re.S)
    assert block, "navmodel no longer defines sharedMiddlewares"
    assert set(re.findall(r'"([^"]+)"', block.group(1))) == SHARED, (
        "the operator's sharedMiddlewares and the XRD's CEL exclusion list have diverged. The "
        "XRD would then admit a claim whose declared `themed` disagrees with what the live "
        "pipeline derives — which is the exact failure spec.nav exists to make impossible."
    )


def test_operator_classifier_is_unchanged(nav_schema):
    """Pin the two expressions the CEL rules are a translation OF.

    RE-POINTED FROM build_nav.py TO derive.go, not weakened. The CEL rules were originally
    derived from the Python classifier; the Go classifier was proven byte-equivalent to it over
    the whole committed corpus plus 38 edge cases (see the catalyst-nav operator's
    internal/render parity gate, whose oracle is build_nav.py's frozen output), and is now the
    only implementation. So this asserts against the surviving one.

    This is deliberately a source-text assertion, which is normally a bad smell. It earns its
    place because the CEL rules claim to be equivalent to these two conditions, and equivalence
    to a line that has silently changed is worth nothing. When this fails, the fix is not to
    update the expected string — it is to re-derive both CEL rules from the new classifier and
    then update it.
    """
    src = DERIVE_GO.read_text()
    for expr in (
        # injected: ANY catalyst* middleware, shared trio already subtracted by the caller.
        'if strings.HasPrefix(n, "catalyst") {',
        # themed: catalyst-<slug> but NOT anything with "nav" in the name.
        'if strings.HasPrefix(n, "catalyst-") && !strings.Contains(n, "nav") {',
    ):
        assert expr in src, (
            f"the operator's classifier changed; {expr!r} is gone. The XRD's CEL rules are a "
            f"translation of it and must be re-derived, not merely re-pinned."
        )


# ---- backward compatibility is a property of the source paths ---------------------------


def test_every_nav_patch_is_skippable(websecure_patches):
    """THE backward-compatibility invariant, asserted rather than asserted-in-a-comment.

    function-patch-and-transform's only conditional is "skip the patch when its source field
    path is absent" (v0.10.9, fn.go:221). Every phase-5 patch therefore has to read from
    spec.nav.*, because that is what makes it vanish on a claim with no nav block — and a claim
    with no nav block is both live claims in the cluster today plus every app not yet migrated.
    A patch that read from, say, a defaulted field outside the block would fire on EVERY claim
    the moment this composition revision is created, and compositionUpdatePolicy: Automatic
    means that is immediate and unprompted.
    """
    offenders = [
        p["toFieldPath"]
        for p in websecure_patches
        if "nav.catalyst.io/" in p["toFieldPath"] and not p["fromFieldPath"].startswith("spec.nav.")
    ]
    assert not offenders, (
        "these nav.catalyst.io/* annotations are not sourced from spec.nav.*, so they would be "
        f"emitted onto claims that never asked for them: {offenders}"
    )


def test_nav_only_touches_the_two_gethomepage_keys(websecure_patches):
    """The nav block may derive group and weight. Nothing else the live pipeline reads.

    build_nav.py reads enabled/name/group/weight/icon under gethomepage.dev/. group and weight
    are the two the migration deliberately derives, because they are the two whose values move
    into spec.nav. If a later edit pointed a spec.nav.* patch at, say,
    gethomepage.dev/enabled, the nav block would silently start deciding whether the app
    appears at all — a much bigger promise than this schema makes.
    """
    derived = {
        p["toFieldPath"].split('"')[1]
        for p in websecure_patches
        if p["fromFieldPath"].startswith("spec.nav.") and "gethomepage.dev/" in p["toFieldPath"]
    }
    assert derived == {"gethomepage.dev/group", "gethomepage.dev/weight"}, (
        f"spec.nav now derives a different set of gethomepage.dev keys: {sorted(derived)}"
    )


def test_live_claim_in_this_repo_is_untouched_by_phase_5():
    """The one CatalystWebSecureIngress claim this repo owns must still be pre-migration.

    kubeview is the claim the admission suite uses as its backward-compatibility fixture. If it
    gets migrated without that suite being repointed, the suite keeps passing while testing
    nothing — so the fact is asserted in both places.
    """
    claim = yaml.safe_load((_ROOT / "infrastructure/base/infra-control/kubeview/websecure-ingress.yaml").read_text())
    spec = claim["spec"]
    if "nav" in spec:
        pytest.fail(
            "the kubeview claim has been migrated to spec.nav. That is fine, but the "
            "backward-compatibility fixture in the catalyst-nav operator's internal/xrdschema "
            "suite must be repointed at an un-migrated claim in the same change."
        )
    assert "group" in spec["homepage"] and "weight" in spec["homepage"], (
        "kubeview no longer sets spec.homepage.group/.weight, so it no longer exercises the "
        "mutual-exclusion rules that could wrongly reject an un-migrated claim"
    )
