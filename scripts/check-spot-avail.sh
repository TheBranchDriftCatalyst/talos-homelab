#!/usr/bin/env bash
# check-spot-avail.sh — GPU quota + spot capacity + price report, driven by the
# sizing table that sits next to the manifests.
#
# Reads infrastructure/base/aws/apps/gpu-profiles.yaml so this report and the
# XGPUInstance claims cannot drift. Run it BEFORE flipping a claim on: quota and
# capacity move independently, and quota != capacity.
#
# THE QUOTA TRAP: "All G and VT Spot Instance Requests" (L-3819A6DF) is a
# per-REGION vCPU ceiling. There is no per-AZ GPU quota. A 4-GPU .12xlarge is
# 48 vCPU, so a region at 48 hosts exactly ONE and nothing else; a region at 32
# cannot host one at all, regardless of capacity.
#
# Usage:
#   scripts/check-spot-avail.sh
#   REGIONS="us-west-2 us-east-2" scripts/check-spot-avail.sh
#   TYPES="g6e.2xlarge g6e.12xlarge" scripts/check-spot-avail.sh
#   PROFILES=/path/to/gpu-profiles.yaml scripts/check-spot-avail.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILES="${PROFILES:-$REPO_ROOT/infrastructure/base/aws/apps/gpu-profiles.yaml}"
# NOT dirname($PROFILES) — see the STATE column comment below. PROFILES is overridable
# for ad-hoc sizing runs; "which rig is armed" is a fact about this checkout.
APPS_DIR="$REPO_ROOT/infrastructure/base/aws/apps"

SPOT_Q=L-3819A6DF # All G and VT Spot Instance Requests (vCPU)
OD_Q=L-DB2E81BA   # Running On-Demand G and VT instances (vCPU)

# ── derive the candidate lists from the profiles table ───────────────────────
# ruby ships with macOS and has YAML in stdlib; env vars override for ad-hoc runs.
yq_rb() { ruby -ryaml -e "$1" "$PROFILES" 2> /dev/null; }

HAVE_TABLE=0
if [ -r "$PROFILES" ] && command -v ruby > /dev/null 2>&1; then
  HAVE_TABLE=1
  : "${REGIONS:=$(yq_rb 'puts YAML.load_file(ARGV[0])["regions"].keys.join(" ")')}"
  : "${TYPES:=$(yq_rb 'puts YAML.load_file(ARGV[0])["shapes"].map { |s| s["instanceType"] }.join(" ")')}"
else
  echo "WARN: $PROFILES unreadable or ruby missing — falling back to built-in defaults" >&2
  : "${REGIONS:=us-west-2 us-east-2 us-east-1 eu-central-1}"
  : "${TYPES:=g6e.2xlarge g6e.12xlarge g5.2xlarge g6.12xlarge}"
fi

if ! command -v aws > /dev/null 2>&1 || ! aws sts get-caller-identity > /dev/null 2>&1; then
  echo "ERROR: no usable local aws CLI. (scripts/aws-gpu-report.sh has the in-cluster"
  echo "       Job fallback if you only have kubectl.)" >&2
  exit 1
fi

echo "account: $(aws sts get-caller-identity --query Account --output text 2> /dev/null)"
echo "profiles: $PROFILES"
echo "generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# shape metadata lookups (vcpu / vram / gpu count) from the table
shape_field() { # $1=instanceType $2=field
  if [ "$HAVE_TABLE" -ne 1 ]; then
    echo "?"
    return
  fi
  ruby -ryaml -e '
    d = YAML.load_file(ARGV[0]); s = (d["shapes"] || []).find { |x| x["instanceType"] == ARGV[1] }
    print s ? s[ARGV[2]] : "?"
  ' "$PROFILES" "$1" "$2" 2> /dev/null
}

q() { aws service-quotas get-service-quota --region "$1" --service-code ec2 \
  --quota-code "$2" --query 'Quota.Value' --output text 2> /dev/null | cut -d. -f1; }

echo
echo "═══ 1. REGIONAL G/VT QUOTA  (vCPU ceiling — the usual blocker) ═══"
printf '  %-14s %8s %12s   %s\n' REGION SPOT ON-DEMAND "largest shape that fits (spot)"
printf '  %-14s %8s %12s   %s\n' -------------- -------- ------------ ------------------------------
for R in $REGIONS; do
  SQ=$(q "$R" "$SPOT_Q")
  OQ=$(q "$R" "$OD_Q")
  SQ=${SQ:-0}
  OQ=${OQ:-0}
  BEST="(none — quota $SQ)"
  BEST_V=0
  for T in $TYPES; do
    V=$(shape_field "$T" vcpu)
    [ "$V" = "?" ] && continue
    if [ "$V" -le "$SQ" ] 2> /dev/null && [ "$V" -gt "$BEST_V" ]; then
      BEST_V=$V
      BEST="$T (${V}vCPU)"
    fi
  done
  printf '  %-14s %8s %12s   %s\n' "$R" "$SQ" "$OQ" "$BEST"
done
cat << 'NOTE'

  Raise a ceiling (opens an AWS support case; approval is hours-to-days):
    aws service-quotas request-service-quota-increase --region <R> \
      --service-code ec2 --quota-code L-3819A6DF --desired-value 64
  64 fits one 4-GPU box (48) plus a 1-GPU box (8) concurrently; 48 fits only the 4-GPU box.
NOTE

echo
echo "═══ 2. SPOT PLACEMENT SCORE  (0=none .. 9=wide open, target 1 instance) ═══"
printf '  %-16s' "SHAPE\\REGION"
for R in $REGIONS; do printf '%-14s' "$R"; done
printf '%8s %8s %6s\n' VCPU VRAM GPUS
for T in $TYPES; do
  printf '  %-16s' "$T"
  for R in $REGIONS; do
    S=$(aws ec2 get-spot-placement-scores --region us-east-1 --instance-types "$T" \
      --target-capacity 1 --region-names "$R" \
      --query 'SpotPlacementScores[0].Score' --output text 2> /dev/null)
    printf '%-14s' "${S:--}"
  done
  printf '%8s %7sG %6s\n' "$(shape_field "$T" vcpu)" "$(shape_field "$T" vramGib)" "$(shape_field "$T" gpus)"
done
echo "  (score is capacity ONLY — a 9 in a zero-quota region still cannot launch)"

echo
echo "═══ 3. LIVE SPOT PRICE per AZ  (\$/hr, cheapest first) ═══"
for R in $REGIONS; do
  Q=$(q "$R" "$SPOT_Q")
  [ "${Q:-0}" -eq 0 ] 2> /dev/null && {
    echo "  $R — skipped (quota 0)"
    continue
  }
  echo "  -- $R --"
  START=$(python3 -c 'import datetime as d;print((d.datetime.now(d.timezone.utc)-d.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"))' 2> /dev/null)
  # shellcheck disable=SC2086  # TYPES is an intentional word-split list
  aws ec2 describe-spot-price-history --region "$R" --instance-types $TYPES \
    --product-descriptions "Linux/UNIX" --start-time "$START" \
    --query 'SpotPriceHistory[].[InstanceType,AvailabilityZone,SpotPrice]' --output text 2> /dev/null |
    sort -u -k1,1 -k3,3n | awk '{printf "     %-16s %-16s $%s\n", $1, $2, $3}'
done

echo
echo "═══ 4. AZs OFFERING each shape  (EBS cache must land in the SAME AZ) ═══"
for R in $REGIONS; do
  Q=$(q "$R" "$SPOT_Q")
  [ "${Q:-0}" -eq 0 ] 2> /dev/null && continue
  echo "  -- $R --"
  for T in $TYPES; do
    AZS=$(aws ec2 describe-instance-type-offerings --region "$R" \
      --location-type availability-zone --filters "Name=instance-type,Values=$T" \
      --query 'InstanceTypeOfferings[].Location' --output text 2> /dev/null | tr '\t' ' ')
    printf '     %-16s %s\n' "$T" "${AZS:-<not offered>}"
  done
done

echo
echo "═══ 5. MODEL → SHAPE FIT  (from the profiles table) ═══"
if [ "$HAVE_TABLE" -eq 1 ]; then
  ruby -ryaml -r"$REPO_ROOT/scripts/lib/armed-rigs" -e '
    d = YAML.load_file(ARGV[0])
    shapes = d["shapes"] || []
    printf("  %-38s %8s %9s   %s\n", "MODEL", "SIZE", "MIN VRAM", "FITS")
    (d["models"] || []).each do |m|
      ok = shapes.select { |s| s["vramGib"].to_f >= m["minVramGib"].to_f }.map { |s| s["instanceType"] }
      printf("  %-38s %7.1fG %8sG   %s\n", m["hfModel"], m["sizeGb"].to_f,
             m["minVramGib"], ok.empty? ? "(nothing in the table)" : ok.join(", "))
    end
    puts
    # STATE is DERIVED from the kustomization, never stored here (TALOS-cmni): an
    # uncommented claim line is the switch Flux acts on, so it cannot disagree with
    # reality. A stored copy did, on 2026-10-02, printing "off" for a rig that was armed
    # and billing on AWS. The rule lives in scripts/lib/armed-rigs.rb and identifies a
    # rig by its kind+role, NOT by a filename prefix, so renaming one cannot silently
    # empty this column.
    #
    # The apps dir is ARGV[1] (REPO_ROOT-derived), NOT File.dirname(PROFILES): "which
    # rig is armed" is a fact about THIS checkout, while PROFILES is overridable for
    # ad-hoc sizing runs. Deriving both from the override meant PROFILES=/tmp/copy.yaml
    # found no kustomization and printed EVERY rig "off" — and a rename is exactly when
    # someone reaches for a scratch copy.
    armed = ArmedRigs.names(ARGV[1])
    printf("  %-20s %-5s %-16s %-14s %-34s %s\n", "RIG", "STATE", "SHAPE", "REGION", "MODEL", "~$/hr")
    (d["rigs"] || []).each do |r|
      printf("  %-20s %-5s %-16s %-14s %-34s %s\n", r["name"],
             armed.include?(r["name"]) ? "ON" : "off",
             r["instanceType"], r["region"], r["hfModel"], r["spotUsdPerHour"])
    end
    (armed - (d["rigs"] || []).map { |r| r["name"] }).each do |n|
      printf("  %-20s %-5s %s\n", n, "ON", "(armed but NOT in this table)")
    end
  ' "$PROFILES" "$APPS_DIR"
else
  echo "  (needs ruby + $PROFILES)"
fi
echo
