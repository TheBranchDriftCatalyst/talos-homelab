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

## Interactive mode (SSM) — Phase 2, built

A genuine off-net **shell** on any of our EC2 boxes, still with **no inbound and no SSH key**,
via AWS Session Manager. This is the counterpart to the autonomous probe-and-halt mode.

How it fits together:

- `spec.instanceProfileName: catalyst-ssm` on an XInstance/XGPUInstance attaches the shared IAM
  instance profile (`infrastructure/base/aws/apps/ssm-instance-profile.yaml`:
  Role + `AmazonSSMManagedInstanceCore` + InstanceProfile). The XRD field is optional and unset by
  default, so nothing changes for boxes that do not ask for it.
- `ssm-jump.yaml` is a **manual** in-cluster launcher (not in `kustomization.yaml`, same as
  `retrieve-console.yaml`). Exec into it and it lists every SSM-registered instance, you pick one,
  and it opens a shell (or a port-forward, e.g. vLLM `:8000`).

```sh
kubectl apply  -f infrastructure/base/aws-redteam/ssm-jump.yaml
kubectl wait -n crossplane-system --for=condition=ready pod/ssm-jump --timeout=60s
kubectl exec -it -n crossplane-system ssm-jump -- bash /scripts/jump.sh
# ... pick a target, get a shell ...
kubectl delete -f infrastructure/base/aws-redteam/ssm-jump.yaml   # when done (it mounts creds)
```

A target appears in the menu only once it has the `catalyst-ssm` profile, the SSM agent running
(AL2023 / DL GPU AMI ship it enabled), and egress to the SSM endpoints (the default public subnet
provides this via its IGW). The autonomous `redteam-vantage` box does NOT set `instanceProfileName`,
so it stays SSM-less by design.

`redteam-interactive.yaml` is the ready-made interactive box (a second on-switch in
`kustomization.yaml`): it sets `instanceProfileName: catalyst-ssm`, installs the pentest toolkit
(`curl`/`dig`/`jq`/`nmap`/`ncat`), and **stays up** (no probe→halt) so you can `ssm-jump` in and run
probes by hand. Flip it on the same way as the autonomous box:

```sh
# edit kustomization.yaml → uncomment "- redteam-interactive.yaml"
git commit -am "redteam: interactive vantage up" && git push
flux reconcile kustomization aws-redteam --with-source
# ~3 min for boot + SSM registration, then:
kubectl apply -f infrastructure/base/aws-redteam/ssm-jump.yaml
kubectl exec -it -n crossplane-system ssm-jump -- bash /scripts/jump.sh   # → pick redteam-interactive → shell
# ... probe by hand (see the box's MOTD) ...
# TEAR DOWN: re-comment redteam-interactive.yaml, commit, push, reconcile (self-halts in 2h regardless)
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

- **Interactive mode (SSM) — BUILT** (2026-09-26, see "Interactive mode" above). Optional
  `instanceProfileName` is on both the XInstance and XGPUInstance XRD/composition, the shared
  `catalyst-ssm` role/policy/instanceprofile MRs live in `aws/apps/ssm-instance-profile.yaml`, and
  `instanceprofiles.iam.aws.upbound.io` is activated. `ssm-jump.yaml` is the launcher.
- **Credentials are the AWS account ROOT keys** (`arn:...:root`) — over-privileged; rotate to a
  scoped IAM user with just EC2 + `iam:PassRole` for the catalyst-ssm role. Filed as TALOS-lq5y.
- The AMI id is pinned; re-run the preflight to refresh it if the launch fails on a deregistered AMI.
