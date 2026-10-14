#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$ROOT/infra/config.env}"
if [[ ! -f "$CONFIG" ]]; then
  echo "ERRO: crie $ROOT/infra/config.env a partir de config.env.example"
  exit 1
fi
source "$CONFIG"

: "${PROJECT_ID:?}"
: "${REGION:?}"
: "${BUCKET_NAME:?}"
: "${FRONTEND_ORIGIN:?}"
: "${DOCUMENT_AI_LOCATION:?}"
: "${GOOGLE_OCR_PROCESSOR_ID:?}"

API_SA="cognotxt-api@${PROJECT_ID}.iam.gserviceaccount.com"
DISPATCHER_SA="cognotxt-dispatcher@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="cognotxt-worker@${PROJECT_ID}.iam.gserviceaccount.com"
EVENTARC_SA="cognotxt-eventarc@${PROJECT_ID}.iam.gserviceaccount.com"
REPO="cognotxt"
API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:latest"
DISPATCHER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/dispatcher:latest"
WORKER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/worker:latest"

printf '\n== Projeto ==\n'
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

printf '\n== APIs ==\n'
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  eventarc.googleapis.com \
  pubsub.googleapis.com \
  documentai.googleapis.com \
  iamcredentials.googleapis.com

printf '\n== Service Accounts ==\n'
for sa in cognotxt-api cognotxt-dispatcher cognotxt-worker cognotxt-eventarc; do
  gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$sa" --display-name="$sa"
done

printf '\n== IAM de projeto ==\n'
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$API_SA" --role="roles/datastore.user" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DISPATCHER_SA" --role="roles/datastore.user" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DISPATCHER_SA" --role="roles/run.developer" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$WORKER_SA" --role="roles/datastore.user" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$WORKER_SA" --role="roles/documentai.apiUser" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$EVENTARC_SA" --role="roles/eventarc.eventReceiver" --quiet

# Permite que a API assine URLs V4 sem chave JSON local.
gcloud iam service-accounts add-iam-policy-binding "$API_SA" \
  --member="serviceAccount:$API_SA" \
  --role="roles/iam.serviceAccountTokenCreator" --quiet

printf '\n== Bucket ==\n'
if ! gcloud storage buckets describe "gs://$BUCKET_NAME" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET_NAME" --location="$REGION" --uniform-bucket-level-access
fi

# Atualiza origens no arquivo CORS de forma simples.
python3 - "$ROOT/infra/cors.json" "$FRONTEND_ORIGIN" "${FRONTEND_ORIGIN_WWW:-}" <<'PY'
import json, sys
p, a, b = sys.argv[1:]
data=json.load(open(p, encoding='utf-8'))
data[0]['origin']=[x for x in [a,b] if x]
json.dump(data, open(p,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY

gcloud storage buckets update "gs://$BUCKET_NAME" --cors-file="$ROOT/infra/cors.json"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$API_SA" --role="roles/storage.objectCreator" --quiet
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$API_SA" --role="roles/storage.objectViewer" --quiet
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$WORKER_SA" --role="roles/storage.objectViewer" --quiet
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$WORKER_SA" --role="roles/storage.objectCreator" --quiet

printf '\n== Artifact Registry ==\n'
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" --description="CognoTXT containers"

printf '\n== Build das imagens ==\n'
gcloud builds submit "$ROOT/api" --tag "$API_IMAGE"
gcloud builds submit "$ROOT/dispatcher" --tag "$DISPATCHER_IMAGE"
gcloud builds submit "$ROOT/worker" --tag "$WORKER_IMAGE"

printf '\n== Cloud Run Job worker ==\n'
if gcloud run jobs describe cognotxt-worker --region="$REGION" >/dev/null 2>&1; then
  JOB_CMD=update
else
  JOB_CMD=create
fi
gcloud run jobs "$JOB_CMD" cognotxt-worker \
  --image="$WORKER_IMAGE" \
  --region="$REGION" \
  --service-account="$WORKER_SA" \
  --cpu=4 \
  --memory=8Gi \
  --task-timeout=21600s \
  --max-retries=1 \
  --set-env-vars="BUCKET_NAME=$BUCKET_NAME,DOCUMENT_AI_LOCATION=$DOCUMENT_AI_LOCATION,GOOGLE_OCR_PROCESSOR_ID=$GOOGLE_OCR_PROCESSOR_ID,GOOGLE_FORM_PROCESSOR_ID=${GOOGLE_FORM_PROCESSOR_ID:-},SMART_TABLE_FORM_PARSER=true,JOB_ID=placeholder,USER_ID=placeholder,INPUT_OBJECT=placeholder,ORIGINAL_FILENAME=placeholder"

printf '\n== Dispatcher ==\n'
gcloud run deploy cognotxt-dispatcher \
  --image="$DISPATCHER_IMAGE" \
  --region="$REGION" \
  --service-account="$DISPATCHER_SA" \
  --no-allow-unauthenticated \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=10 \
  --set-env-vars="CLOUD_RUN_REGION=$REGION,WORKER_JOB_NAME=cognotxt-worker,WORKER_TIMEOUT=21600s"

gcloud run services add-iam-policy-binding cognotxt-dispatcher \
  --region="$REGION" \
  --member="serviceAccount:$EVENTARC_SA" \
  --role="roles/run.invoker" --quiet

printf '\n== API ==\n'
gcloud run deploy cognotxt-api \
  --image="$API_IMAGE" \
  --region="$REGION" \
  --service-account="$API_SA" \
  --allow-unauthenticated \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=20 \
  --set-env-vars="^@^BUCKET_NAME=$BUCKET_NAME@API_SERVICE_ACCOUNT_EMAIL=$API_SA@ALLOWED_ORIGINS=$FRONTEND_ORIGIN,${FRONTEND_ORIGIN_WWW:-}@MAX_FILE_MB=${MAX_FILE_MB:-2048}@SIGNED_URL_MINUTES=15"

printf '\n== Permissões para Eventarc / Cloud Storage ==\n'
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
STORAGE_SERVICE_AGENT="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$STORAGE_SERVICE_AGENT" --role="roles/pubsub.publisher" --quiet

printf '\n== Eventarc trigger ==\n'
gcloud eventarc triggers delete cognotxt-storage-finalized --location="$REGION" --quiet >/dev/null 2>&1 || true
gcloud eventarc triggers create cognotxt-storage-finalized \
  --location="$REGION" \
  --destination-run-service=cognotxt-dispatcher \
  --destination-run-region="$REGION" \
  --destination-run-path=/events/storage \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=$BUCKET_NAME" \
  --service-account="$EVENTARC_SA"

API_URL="$(gcloud run services describe cognotxt-api --region="$REGION" --format='value(status.url)')"
printf '\n============================================================\n'
printf 'DEPLOY CONCLUÍDO\n'
printf 'API URL: %s\n' "$API_URL"
printf 'Bucket: gs://%s\n' "$BUCKET_NAME"
printf '\nAgora edite frontend/config.js e use apiBaseUrl: "%s"\n' "$API_URL"
printf '============================================================\n'
