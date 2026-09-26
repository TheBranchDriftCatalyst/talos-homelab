# aws-redteam — on-demand external pentest vantage

A small AWS EC2 box, **off by default**, that gives a *genuine off-net* vantage for testing what
the homelab exposes to the internet. LAN and the gluetun VPN both NAT-hairpin back to the same home
WAN IP, so neither can answer that honestly — the pentest framework's own
`talos-ingress/evidence/external_pass_notes.txt` records this and leaves a "deferred true-cold
pass" open. This closes it.

## What it is

- Reuses the existing Crossplane `XInstance` composition (`aws.catalyst.io/v1alpha1`) — no new
  composition. `t3.micro`, us-west-2, `openPort: 0` (no inbound).
- **Autonomous** (`redteam-auto.yaml`): boots, runs `probe.sh` (the framework's `PLAYBOOK.md`
  host-spoof / forged-header battery) against the WAN origin, writes the summary to the EC2 **serial
  console**, halts. No inbound, no SSH key, no SSM. Results pulled with `aws ec2 get-console-output`.
- `probe.sh` is the canonical script; `redteam-auto.yaml` embeds it verbatim (base64) in cloud-init.
  Edit `probe.sh`, then re-embed (see below), so the two never drift.
- `reaper-cronjob.yaml` is a cost backstop (deletes the box if it lives >2h). **Git-off is the real
  teardown**, the reaper is belt-not-braces.

## Run a pass

```sh
# 1. turn it on
#    edit kustomization.yaml → uncomment "- redteam-auto.yaml"
git commit -am "redteam: spin up external vantage" && git push
flux reconcile kustomization aws-redteam --with-source

# 2. wait ~3 min for boot+probe, confirm it came up
kubectl get xinstance redteam-vantage -o jsonpath='{.status.publicIp}{"\n"}'

# 3. pull the results off the serial console
kubectl apply -f infrastructure/base/aws-redteam/retrieve-console.yaml
kubectl logs -n crossplane-system job/redteam-console -f
#    → paste the CATALYST-REDTEAM PROBE block into
#      pentest/target-packages/talos-ingress/evidence/finding013_EXTERNAL_aws.txt

# 4. TEAR DOWN (do not skip)
#    edit kustomization.yaml → re-comment "- redteam-auto.yaml"
git commit -am "redteam: tear down external vantage" && git push
flux reconcile kustomization aws-redteam --with-source
#    verify nothing lingers:
kubectl get xinstance,instance.ec2.aws.upbound.io -A | grep -i redteam || echo "clean"
```

## Re-embedding probe.sh after an edit

```sh
B64=$(base64 < infrastructure/base/aws-redteam/probe.sh | tr -d '\n')
# replace the single-line base64 in redteam-auto.yaml's `echo "<...>" | base64 -d` with $B64
```

## Preflight values (from the read-only redteam-preflight Job, us-west-2)

| | |
|---|---|
| account | 744062333585 |
| default VPC | `vpc-3536d651` |
| public subnet | `subnet-36191741` |
| AL2023 x86_64 AMI | `ami-075d448db8fb256af` (re-resolve before each run; AMIs rotate) |
| EC2 RunInstances | permitted (dry-run reached AMI validation, not UnauthorizedOperation) |

## Rules of engagement

Authorised per `pentest/target-packages/talos-ingress/scope.md` (operator owns the assets and the
WAN link). **Non-destructive only.** Prove reachability; do not pivot through the open proxies to
third parties. CrowdSec two-phase (cold first to measure detection, then optionally allowlist the
EC2 IP for a functional pass) is in scope — snapshot and restore decisions.

## Known gaps / follow-ups

- **Interactive mode (SSM) is not built yet** — needs an optional `instanceProfileName` on the
  XInstance XRD/composition + activating the iam role/policy/instanceprofile MRDs. Phase 2.
- **Credentials are the AWS account ROOT keys** (`arn:...:root`) — over-privileged; rotate to a
  scoped IAM user with just EC2 + (phase 2) iam:PassRole. Filed.
- The AMI id is pinned; re-run the preflight to refresh it if the launch fails on a deregistered AMI.
