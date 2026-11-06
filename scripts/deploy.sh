#!/usr/bin/env bash
# Deploy to Cloud Run. Reads PROD_DATABASE_URL from .env and passes it to the
# service as DATABASE_URL through a temporary env file, so the value never
# appears on the command line or in the shell history.
#
#   ./scripts/deploy.sh
#
# First time only: rebuild and load the production database.
#   uv run python -m scripts.migrate --prod && uv run python -m scripts.seed --prod
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${GCP_PROJECT:-headcount-desk-demo}"
REGION="${GCP_REGION:-us-east1}"
SERVICE="headcount-desk"

ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT
python3 - "$ENV_FILE" <<'PY'
import sys
for line in open(".env"):
    if line.startswith("PROD_DATABASE_URL="):
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        open(sys.argv[1], "w").write(f'DATABASE_URL: "{value}"\n')
        break
else:
    sys.exit("PROD_DATABASE_URL is not set in .env")
PY

gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --source . \
  --allow-unauthenticated --min-instances=0 --max-instances=2 \
  --memory=512Mi --cpu=1 --cpu-boost --concurrency=40 --timeout=60 \
  --env-vars-file "$ENV_FILE" --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
