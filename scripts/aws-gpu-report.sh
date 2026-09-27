#!/usr/bin/env bash
# aws-gpu-report.sh — current AWS G/VT (GPU) quotas + spot availability, per region.
#
# Shows, for each region: the SPOT and ON-DEMAND G/VT vCPU limits, and the spot
# placement score (0=none .. 9=wide open) for each GPU instance type. Handy for
# deciding WHERE a GPU box will actually place (quota != capacity).
#
# Runs a transient Job in-cluster using the aws-credentials secret, so it needs
# only kubectl — no local AWS setup. (Falls back to a local `aws` if present.)
#
# Usage:
#   scripts/aws-gpu-report.sh
#   REGIONS="us-west-2 us-east-2" TYPES="g6e.12xlarge g5.12xlarge" scripts/aws-gpu-report.sh
set -euo pipefail

NS="${NS:-crossplane-system}"
SECRET="${SECRET:-aws-credentials}"
REGIONS="${REGIONS:-us-west-2 us-east-2 us-east-1 eu-central-1}"
TYPES="${TYPES:-g6e.xlarge g6e.12xlarge g5.xlarge g5.12xlarge}"

# The reporting logic, run wherever aws-cli lives (local or in the Job).
read -r -d '' REPORT << 'REPORT_EOF' || true
set -u
echo "account: $(aws sts get-caller-identity --query Account --output text 2>/dev/null)"
SPOT_Q=L-3819A6DF        # All G and VT Spot Instance Requests (vCPU)
OD_Q=L-DB2E81BA          # Running On-Demand G and VT instances (vCPU)
q() { aws service-quotas get-service-quota --region "$1" --service-code ec2 --quota-code "$2" --query 'Quota.Value' --output text 2>/dev/null | cut -d. -f1; }
score() { aws ec2 get-spot-placement-scores --region us-east-1 --instance-types "$2" --target-capacity 1 --region-names "$1" --query 'SpotPlacementScores[0].Score' --output text 2>/dev/null; }

echo
echo "AWS G/VT (GPU) QUOTAS  —  vCPU limits   (96GB 4-GPU .12xlarge needs >= 48)"
printf '  %-14s %10s %14s\n' REGION SPOT ON-DEMAND
printf '  %-14s %10s %14s\n' -------------- ---------- --------------
for R in $REGIONS; do
  printf '  %-14s %10s %14s\n' "$R" "$(q "$R" "$SPOT_Q")" "$(q "$R" "$OD_Q")"
done

echo
echo "SPOT PLACEMENT SCORE  —  0/none .. 9/wide-open   (per region, target 1x)"
printf '  %-16s' "INSTANCE\\REGION"; for R in $REGIONS; do printf '%-13s' "$R"; done; echo
for T in $TYPES; do
  printf '  %-16s' "$T"
  for R in $REGIONS; do
    S=$(score "$R" "$T"); [ -z "$S" ] && S="-"
    printf '%-13s' "$S"
  done
  echo
done
echo
REPORT_EOF

if command -v aws > /dev/null 2>&1 && aws sts get-caller-identity > /dev/null 2>&1; then
  echo "(using local aws-cli)"
  REGIONS="$REGIONS" TYPES="$TYPES" bash -c "$REPORT"
  exit 0
fi

echo "(running in-cluster Job via $NS/$SECRET — needs only kubectl)"
JOB="aws-gpu-report-$$"
B64="$(printf '%s' "$REPORT" | base64 | tr -d '\n')"
cat << YAML | kubectl apply -f - > /dev/null
apiVersion: batch/v1
kind: Job
metadata: {name: $JOB, namespace: $NS}
spec:
  ttlSecondsAfterFinished: 120
  backoffLimit: 0
  activeDeadlineSeconds: 180
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: aws
          image: amazon/aws-cli:2.31.24
          env:
            - {name: AWS_SHARED_CREDENTIALS_FILE, value: /creds/creds}
            - {name: AWS_REGION, value: us-east-1}
            - {name: REGIONS, value: "$REGIONS"}
            - {name: TYPES, value: "$TYPES"}
          command: ["/bin/bash","-c"]
          args: ["echo $B64 | base64 -d | bash"]
          volumeMounts: [{name: creds, mountPath: /creds, readOnly: true}]
      volumes:
        - {name: creds, secret: {secretName: $SECRET}}
YAML
kubectl wait --for=condition=complete --timeout=180s "job/$JOB" -n "$NS" > /dev/null 2>&1 || true
kubectl logs -n "$NS" "job/$JOB" 2> /dev/null
kubectl delete job "$JOB" -n "$NS" --wait=false > /dev/null 2>&1 || true
