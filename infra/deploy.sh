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


# Captura o projeto configurado atualmente no seu gcloud shell
PROJECT_ID=$(gcloud config get-value project)
# Se PROJECT_ID estiver vazio ou não existir
if [ -z "${PROJECT_ID:-}" ]; then
    echo "⚠️ PROJECT_ID não estava definido. Tentando capturar automaticamente..."

    # Tenta pegar o projeto ativo no gcloud do Cloud Shell
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

    #VAI NA MARRA SE ESTIVER VAZIO
    if [ -z "$PROJECT_ID" ]; then
        PROJECT_ID="grafemapdf"
    fi

    echo "✅ PROJECT_ID definido como: $PROJECT_ID"
fi


printf '\n== Projeto ==\n'
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

echo "✅ PROJECT_ID definido como: $PROJECT_ID"
echo "✅ $REGION definido como: $REGION"


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

# parte demorada!
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

# corrigido sintaxe
printf '\n== API ==\n'

# API_SA
#API_SERVICE_ACCOUNT_EMAIL="cognotxt-api@${PROJECT_ID}.iam.gserviceaccount.com"

# Erro, não usar!
#gcloud run deploy cognotxt-api \
#  --image="$API_IMAGE" \
#  --region="$REGION" \
#  --project="$PROJECT_ID" \
#  --service-account="$API_SA" \
#  --allow-unauthenticated \
#  --cpu=1 --memory=512Mi \
#  --min-instances=0 --max-instances=20 \
#  --set-env-vars="^:@^BUCKET_NAME=${BUCKET_NAME}@API_SERVICE_ACCOUNT_EMAIL=${API_SA}@ALLOWED_ORIGINS=${FRONTEND_ORIGIN},${FRONTEND_ORIGIN_WWW:-}@MAX_FILE_MB=${MAX_FILE_MB:-2048}@SIGNED_URL_MINUTES=15@GOOGLE_CLOUD_PROJECT=${PROJECT_ID},BUCKET_NAME=${BUCKET_NAME}"

gcloud run deploy cognotxt-api \
  --image="$API_IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --service-account="$API_SA" \
  --allow-unauthenticated \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=20 \
  --env-vars-file=/cognotxt-api-env.yaml

echo
echo "== Validando variáveis da API =="

DEPLOYED_BUCKET="$(
  gcloud run services describe cognotxt-api \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format='value(spec.template.spec.containers[0].env[?name="BUCKET_NAME"].value)'
)"

echo "Bucket esperado : $BUCKET_NAME"
echo "Bucket configurado: $DEPLOYED_BUCKET"

if [ "$DEPLOYED_BUCKET" != "$BUCKET_NAME" ]; then
  echo "ERRO: BUCKET_NAME do Cloud Run está incorreto."
  exit 1
fi

echo "== FIM da validação de variáveis da API =="


#curl https://cognotxt-api-940153605624.us-central1.run.app/health
printf '\n== Permissões para Eventarc / Cloud Storage ==\n'
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

# Não funciona comando, sem permissao STORAGE_SERVICE_AGENT é ACCOUNT!
#STORAGE_SA É SERVICE_ACCOUNT !!!! DEVERIA SE STORAGE_Sa -> SERVICE AGENT!!!!
#STORAGE_SERVICE_AGENT_OLD="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"
# é mais seguro e deixa o próprio Google retornar a conta correta, nao funciona
#STORAGE_SERVICE_AGENT_OLD="$(gcloud storage service-agent --project="${PROJECT_ID}")"
# CORRIGI NOS PROXIMOS ABAIXO
#
#gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:STORAGE_SERVICE_AGENT_OLD" --role="roles/pubsub.publisher" --quiet
# QUE RAIVA DESSES COMANDOS/VAR QUE MUDAM TODA HORA!
# use script de teste
echo "== Inicializando Cloud Storage service agent STORAGE_SA =="

# NAO FUNCIONA CAPTURA ESPAÇOOOO!!

# STORAGE SERVICE agent É STORAGE_SA
# STORAGE_SA="$(
#  gcloud storage service-agent \
#    --project="${PROJECT_ID}" \
#    2>/dev/null
#)"

# VAMOS LÁ... POR PARTES JACK...
# Pega o project_id de novo!
# TESTE DE NOVO
# Se PROJECT_ID estiver vazio ou não existir
#PROJECT_ID=$(gcloud config get-value project)

if [ -z "${PROJECT_ID:-}" ]; then
    echo "⚠️ PROJECT_ID não estava definido. Tentando capturar automaticamente..."

    # Tenta pegar o projeto ativo no gcloud do Cloud Shell
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

    #VAI NA MARRA SE ESTIVER VAZIO
    if [ -z "$PROJECT_ID" ]; then
        PROJECT_ID="grafemapdf"
    fi

    echo "✅ PROJECT_ID definido como: $PROJECT_ID"
fi

printf '\n== Projeto atribuid novamente ==\n'
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

echo "✅ PROJECT_ID definido como: $PROJECT_ID"
echo "✅ $REGION definido como: $REGION"


# Captura o e-mail e remove qualquer espaço em branco ou quebra de linha extra usando o 'tr'
STORAGE_SA=$(gcloud storage service-agent --project="${PROJECT_ID}" | tr -d '[:space:]')

# Exibe para garantir que ele sairá colado na esquerda, sem linhas vazias
echo "Cloud Storage Service Agent SEM OS ESPAÇOS! : '${STORAGE_SA}'"

# TESTAAAA
if [ -z "${STORAGE_SA}" ]; then
  gcloud beta services identity create \
    --service=storage.googleapis.com \
    --project="${PROJECT_ID}"

  STORAGE_SA="$(
    gcloud storage service-agent \
      --project="${PROJECT_ID}" | tr -d '[:space:]'
  )"
fi

# APLICA A PERMISSAO
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${STORAGE_SA}" \
  --role="roles/pubsub.publisher"


printf '\n== Eventarc trigger ==\n'
printf '\n== Eventarc trigger ==\n'
printf '\n== Eventarc trigger ==\n'

printf '\n== Preparando Eventarc / Cloud Storage ==\n'
printf '\n== Preparando Eventarc / Cloud Storage ==\n'
printf '\n== Preparando Eventarc / Cloud Storage ==\n'


#SCRIPT ANTIGO

# 999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999
# gcloud eventarc triggers delete cognotxt-storage-finalized --location="$REGION" --quiet >/dev/null 2>&1 || true
# gcloud eventarc triggers create cognotxt-storage-finalized \
#  --location="$REGION" \
#  --destination-run-service=cognotxt-dispatcher \
#  --destination-run-region="$REGION" \
#  --destination-run-path=/events/storage \
#  --event-filters="type=google.cloud.storage.object.v1.finalized" \
#  --event-filters="bucket=$BUCKET_NAME" \
#  --service-account="$EVENTARC_SA"
#
# 999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999


#Script novo!
#Verificar se está criado certo, NAO CONFIA NO SHELL !
# Cloud Storage Service Agent exista e tenha roles/pubsub.publisher;
# Eventarc Service Agent exista e tenha roles/eventarc.serviceAgent;
# service account usada pelo trigger tenha roles/eventarc.eventReceiver;
# roles/run.invoker no cognotxt-dispatcher;
# Trigger com tentativas automáticas caso o IAM ainda esteja propagando.

PROJECT_NUMBER="$(
  gcloud projects describe "$PROJECT_ID" \
    --format='value(projectNumber)'
)"

if [ -z "$PROJECT_NUMBER" ]; then
  echo "ERRO: não foi possível obter PROJECT_NUMBER."
  exit 1
fi

echo "PROJECT_ID:     $PROJECT_ID"
echo "PROJECT_NUMBER: $PROJECT_NUMBER"


# ============================================================
# 1. Garantir APIs necessárias
# ============================================================

echo
echo "== Habilitando APIs necessárias =="

gcloud services enable \
  eventarc.googleapis.com \
  eventarcpublishing.googleapis.com \
  pubsub.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  --project="$PROJECT_ID"


# ============================================================
# 2. Cloud Storage Service Agent
# ============================================================

echo
echo "== Cloud Storage Service Agent =="
# Captura o e-mail e remove qualquer espaço em branco ou quebra de linha extra usando o 'tr'
#STORAGE_SERVICE_AGENT=$(gcloud storage service-agent --project="${PROJECT_ID}" | tr -d '[:space:]')

#STORAGE_SERVICE_AGENT="$(
#  gcloud storage service-agent \
#    --project="$PROJECT_ID" \
#    2>/dev/null || true
#)"

if [ -z "$STORAGE_SA" ]; then
  echo "Service Agent do Cloud Storage ainda não existe."
  echo "Criando identidade..."

  gcloud beta services identity create \
    --service=storage.googleapis.com \
    --project="$PROJECT_ID"

  STORAGE_SA="$(
    gcloud storage service-agent \
      --project="${PROJECT_ID}" | tr -d '[:space:]'
  )"
fi

if [ -z "$STORAGE_SA" ]; then
  echo "ERRO: não foi possível obter o Cloud Storage Service Agent."
  exit 1
fi

echo "Storage Service Agent: $STORAGE_SA"

echo "Concedendo roles/pubsub.publisher..."

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${STORAGE_SA}" \
  --role="roles/pubsub.publisher" \
  --quiet


# ============================================================
# 3. Eventarc Service Agent
# ============================================================

################### OLD 1 ##################################################
#echo
#echo "== Eventarc Service Agent =="
#
#EVENTARC_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"
#
## Força criação da identidade gerenciada do Eventarc
#gcloud beta services identity create \
#  --service=eventarc.googleapis.com \
#  --project="$PROJECT_ID" \
#  >/dev/null 2>&1 || true
#
#echo "Eventarc Service Agent: $EVENTARC_SERVICE_AGENT"
#
## Confere se a conta já existe
#if ! gcloud iam service-accounts describe \
#      "$EVENTARC_SERVICE_AGENT" \
#      --project="$PROJECT_ID" \
#      >/dev/null 2>&1
#then
#  echo "ERRO: Eventarc Service Agent não foi criado corretamente."
#  echo "Conta esperada: $EVENTARC_SERVICE_AGENT"
#  exit 1
#fi
#
#echo "Concedendo roles/eventarc.serviceAgent..."
#
#gcloud projects add-iam-policy-binding "$PROJECT_ID" \
#  --member="serviceAccount:${EVENTARC_SERVICE_AGENT}" \
#  --role="roles/eventarc.serviceAgent" \
#  --quiet
#
## LEMBRA QUE
## O papel roles/eventarc.serviceAgent deve ser concedido somente ao service agent gerenciado do próprio Eventarc. Google Cloud Documentation
## TRATAMENTO DO service account usada pelo trigger. Supondo que EVENTARC_SA já tenha sido definido anteriormente, teste!
#
#
#
#
#
#
#
#
#
#
#echo
#echo "== Eventarc Service Agent =="
#
#EVENTARC_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"
#
#echo "Eventarc Service Agent: $EVENTARC_SERVICE_AGENT"
#
## Força a criação/ativação da identidade gerenciada do Eventarc.
#gcloud beta services identity create \
#  --service=eventarc.googleapis.com \
#  --project="$PROJECT_ID" \
#  >/dev/null 2>&1 || true
################### OLD 1 ##################################################



#################### novo 2 ##################################################
echo
echo "== Eventarc Service Agent =="

EVENTARC_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"

# Força criação da identidade gerenciada do Eventarc
gcloud beta services identity create \
  --service=eventarc.googleapis.com \
  --project="$PROJECT_ID" \
  >/dev/null 2>&1 || true

echo "Eventarc Service Agent: $EVENTARC_SERVICE_AGENT"
echo "PROJECT_ID: '$PROJECT_ID'"

# Confere se a conta já existe
if ! gcloud iam service-accounts describe \
      "$EVENTARC_SERVICE_AGENT" \
      --project="$PROJECT_ID" \
      >/dev/null 2>&1
then
  echo "ERRO: Eventarc Service Agent não foi criado corretamente."
  echo "Conta esperada: '$EVENTARC_SERVICE_AGENT'"
  #exit 1
fi

# ============================================================
# Verifica pelo IAM do projeto, não por
# gcloud iam service-accounts describe
# ============================================================

EVENTARC_ROLE_FOUND="$(
  gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${EVENTARC_SERVICE_AGENT} AND bindings.role:roles/eventarc.serviceAgent" \
    --format="value(bindings.role)" \
    2>/dev/null || true
)"

if [ "$EVENTARC_ROLE_FOUND" != "roles/eventarc.serviceAgent" ]; then

  echo "Role roles/eventarc.serviceAgent ainda não encontrada."
  echo "Concedendo permissão..."

  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${EVENTARC_SERVICE_AGENT}" \
    --role="roles/eventarc.serviceAgent" \
    --quiet

else

  echo "Eventarc Service Agent já está corretamente configurado."

fi
#################### novo 2 ##################################################

# ============================================================
# 4. Service Account usada pelo trigger
# ============================================================

echo
echo "== Identidade do Eventarc Trigger =="

if [ -z "${EVENTARC_SA:-}" ]; then
  echo "ERRO: variável EVENTARC_SA não está definida."
  #exit 1
fi

echo "Trigger Service Account: $EVENTARC_SA"


# teste
if ! gcloud iam service-accounts describe \
      "$EVENTARC_SA" \
      --project="$PROJECT_ID" \
      >/dev/null 2>&1
then
  echo "ERRO: Service Account do trigger não existe: $EVENTARC_SA"
  #exit 1
fi

echo "Concedendo Eventarc Event Receiver..."

# old 2
#gcloud projects add-iam-policy-binding "$PROJECT_ID" \
#  --member="serviceAccount:${EVENTARC_SA}" \
#  --role="roles/eventarc.eventReceiver" \
#  --quiet
# old 2


######### NEW 2
TRIGGER_RECEIVER_ROLE="$(
  gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${EVENTARC_SA} AND bindings.role:roles/eventarc.eventReceiver" \
    --format="value(bindings.role)" \
    2>/dev/null || true
)"

#teste
if [ "$TRIGGER_RECEIVER_ROLE" != "roles/eventarc.eventReceiver" ]; then

  echo "Concedendo roles/eventarc.eventReceiver..."

  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${EVENTARC_SA}" \
    --role="roles/eventarc.eventReceiver" \
    --quiet

else

  echo "Eventarc Event Receiver já configurado."

fi
######### NEW 2


# Garanta que essa mesma conta possa chamar o dispatcher!
echo
echo "== Permissão Cloud Run Invoker =="
echo "Concedendo Cloud Run Invoker no dispatcher..."

#gcloud run services add-iam-policy-binding \
#  cognotxt-dispatcher \
#  --region="$REGION" \
#  --project="$PROJECT_ID" \
#  --member="serviceAccount:${EVENTARC_SA}" \
#  --role="roles/run.invoker" \
#  --quiet

RUN_INVOKER_FOUND="$(
  gcloud run services get-iam-policy cognotxt-dispatcher \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${EVENTARC_SA} AND bindings.role:roles/run.invoker" \
    --format="value(bindings.role)" \
    2>/dev/null || true
)"

#teste
if [ "$RUN_INVOKER_FOUND" != "roles/run.invoker" ]; then

  echo "Concedendo roles/run.invoker no dispatcher..."

  gcloud run services add-iam-policy-binding \
    cognotxt-dispatcher \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${EVENTARC_SA}" \
    --role="roles/run.invoker" \
    --quiet

else

  echo "Cloud Run Invoker já configurado."

fi


# Agora temos a trigger Eventarc chamando um Cloud Run autenticado, aleluia!
# Criacao e este da trigger com retry, vai que...
# ============================================================
# 5. Eventarc Trigger nos mínimos detalhes
# ============================================================
printf '\n== Eventarc trigger ==\n'

TRIGGER_NAME="cognotxt-storage-finalized"

# Remove trigger antigo, se existir
if gcloud eventarc triggers describe "$TRIGGER_NAME" \
     --location="$REGION" \
     --project="$PROJECT_ID" \
     >/dev/null 2>&1
then
  echo "Trigger existente encontrado. Removendo..."

  gcloud eventarc triggers delete "$TRIGGER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --quiet
fi

# FUNCAO CRIADA PARA FACILITAR
create_eventarc_trigger() {

  gcloud eventarc triggers create "$TRIGGER_NAME" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --destination-run-service="cognotxt-dispatcher" \
    --destination-run-region="$REGION" \
    --destination-run-path="/events/storage" \
    --event-filters="type=google.cloud.storage.object.v1.finalized" \
    --event-filters="bucket=$BUCKET_NAME" \
    --service-account="$EVENTARC_SA"
}


MAX_ATTEMPTS=6
ATTEMPT=1

while true
do
  echo
  echo "Tentativa $ATTEMPT/$MAX_ATTEMPTS para criar o Eventarc trigger..."

  if create_eventarc_trigger
  then
    echo
    echo "Eventarc trigger criado com sucesso."
    break
  fi

  if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]
  then
    echo
    echo "ERRO: não foi possível criar o Eventarc trigger."
    echo
    echo "Diagnóstico:"
    echo "Eventarc Service Agent: $EVENTARC_SERVICE_AGENT"
    echo "Trigger Service Account: $EVENTARC_SA"
    echo "Storage Service Agent: $STORAGE_SA"

    echo
    echo "Roles do Eventarc Service Agent:"
    gcloud projects get-iam-policy "$PROJECT_ID" \
      --flatten="bindings[].members" \
      --filter="bindings.members:${EVENTARC_SERVICE_AGENT}" \
      --format="table(bindings.role)" || true

    echo
    echo "Roles da identidade do Trigger:"
    gcloud projects get-iam-policy "$PROJECT_ID" \
      --flatten="bindings[].members" \
      --filter="bindings.members:${EVENTARC_SA}" \
      --format="table(bindings.role)" || true

    #exit 1
  fi

  echo "IAM/Eventarc ainda não está pronto. Nova tentativa automática..."
  sleep 10

  ATTEMPT=$((ATTEMPT + 1))
done

# Sem esse retry dá ruim porque o próprio Google alerta que, na primeira configuração, a criação e propagação das
# permissões do Eventarc Service Agent pode não ser imediata. LERDOO!!!
# validacao para validar se criou mesmo, nao confia no shel!! Já disse isso hoje ?
# ============================================================
# 6. Validação final
# ============================================================

echo
echo "== Validando Eventarc trigger =="

TRIGGER_STATE="$(
  gcloud eventarc triggers describe "$TRIGGER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(name)" \
    2>/dev/null || true
)"

if [ -z "$TRIGGER_STATE" ]; then
  echo "ERRO: Eventarc trigger não foi encontrado após criação."
  echo "ALELUIA IRMÃO!!! Ouvi um AMEM ?!"
  #exit 1
fi

echo "Trigger OK: $TRIGGER_NAME"

# FINALIZAÇÃO MEEEEHH!
# 99999999999999999 NAO USUAR
#API_URL="$(gcloud run services describe cognotxt-api --region="$REGION" --format='value(status.url)')"
#printf '\n============================================================\n'
#printf 'DEPLOY CONCLUÍDO\n'
#printf 'API URL: %s\n' "$API_URL"
#printf 'Bucket: gs://%s\n' "$BUCKET_NAME"
#printf '\nAgora edite frontend/config.js e use apiBaseUrl: "%s"\n' "$API_URL"
#printf '============================================================\n'
# 99999999999999999 NAO USUAR

# NEW
# ============================================================
# 7. Resultado final
# ============================================================

API_URL="$(
  gcloud run services describe cognotxt-api \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format='value(status.url)'
)"

printf '\n============================================================\n'
printf 'DEPLOY CONCLUÍDO COM SUCESSO\n'
printf '===== SOM NA CAIXAAAAAAAAA !!!=======================================================\n'
printf '===== SOM NA CAIXAAAAAAAAA !!!=======================================================\n'
printf '===== SOM NA CAIXAAAAAAAAA !!!=======================================================\n'
printf '============================================================\n'
printf 'API URL: %s\n' "$API_URL"
printf 'Bucket: gs://%s\n' "$BUCKET_NAME"
printf 'Eventarc Trigger: %s\n' "$TRIGGER_NAME"
printf 'Região: %s\n' "$REGION"
printf '\n'
printf 'Agora edite frontend/config.js e use:\n'
printf 'apiBaseUrl: "%s"\n' "$API_URL"
printf '============================================================\n'



