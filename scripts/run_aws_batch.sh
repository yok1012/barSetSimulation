#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -lt 1 ]]; then
  echo '使い方: bash scripts/run_aws_batch.sh configs/aws_batch.json [--workers 8] [--resume]' >&2
  exit 2
fi
mkdir -p logs
log="logs/batch_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
.venv/bin/python -u aws_batch.py "$@" 2>&1 | tee "$log"
