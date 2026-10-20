import os
import re
import uuid
from datetime import timedelta
from io import BytesIO
import zipfile
from fastapi.responses import Response
from pathlib import PurePosixPath

import firebase_admin
import google
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import auth
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field

import logging

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")

if not PROJECT_ID:
    import google.auth

    _, PROJECT_ID = google.auth.default()

if not PROJECT_ID:
    raise RuntimeError(
        "Não foi possível determinar GOOGLE_CLOUD_PROJECT"
    )


#BUCKET_NAME = os.environ["BUCKET_NAME"]
BUCKET_NAME = os.getenv(
    "BUCKET_NAME"
)
#API_SERVICE_ACCOUNT_EMAIL = os.environ["API_SERVICE_ACCOUNT_EMAIL"]

API_SERVICE_ACCOUNT_EMAIL = os.getenv(
    "API_SERVICE_ACCOUNT_EMAIL"
)

if not API_SERVICE_ACCOUNT_EMAIL:
    API_SERVICE_ACCOUNT_EMAIL = (
        f"cognotxt-api@{PROJECT_ID}.iam.gserviceaccount.com"
    )

required_config = {
    "GOOGLE_CLOUD_PROJECT": PROJECT_ID,
    "BUCKET_NAME": BUCKET_NAME,
    "API_SERVICE_ACCOUNT_EMAIL": API_SERVICE_ACCOUNT_EMAIL,
}

missing = [
    name
    for name, value in required_config.items()
    if not value
]

if missing:
    raise RuntimeError(
        "Configuração obrigatória ausente: "
        + ", ".join(missing)
    )


ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "https://cognotxt.com.br,https://www.cognotxt.com.br").split(",") if x.strip()]
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "2048"))
SIGNED_URL_MINUTES = int(os.getenv("SIGNED_URL_MINUTES", "15"))

# testa se esta vazio
if not PROJECT_ID:
    _, detected_project = google.auth.default()
    PROJECT_ID = detected_project

if not PROJECT_ID:
    raise RuntimeError(
        "Não foi possível determinar o Google Cloud Project ID."
    )

#if not firebase_admin._apps:
#    firebase_admin.initialize_app()

if not firebase_admin._apps:
    firebase_admin.initialize_app(
        options={
            "projectId": PROJECT_ID
        }
    )

storage_client = storage.Client(project=PROJECT_ID)
firestore_client = firestore.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)

app = FastAPI(title="CognoTXT API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

logger.info(
    "Configuração | project=%s | bucket=%s | api_sa=%s",
    PROJECT_ID,
    BUCKET_NAME,
    API_SERVICE_ACCOUNT_EMAIL,
)


class UploadSessionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(gt=0)
    content_type: str = "application/pdf"


def safe_filename(name: str) -> str:
    name = PurePosixPath(name).name
    name = re.sub(r"[^A-Za-z0-9._()\- áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("._")
    return name or "arquivo.pdf"

#valida token
def validar_token(token: str):
    try:
        decoded = auth.verify_id_token(
            token,
            check_revoked=False
        )

        logger.info(
            "Firebase token OK | uid=%s | email=%s | aud=%s | iss=%s",
            decoded.get("uid"),
            decoded.get("email"),
            decoded.get("aud"),
            decoded.get("iss"),
        )

        return decoded

    except auth.ExpiredIdTokenError as exc:
        logger.warning("Firebase token expirado: %s", exc)

        raise HTTPException(
            status_code=401,
            detail="Token expirado"
        )

    except auth.RevokedIdTokenError as exc:
        logger.warning("Firebase token revogado: %s", exc)

        raise HTTPException(
            status_code=401,
            detail="Token revogado"
        )

    except auth.InvalidIdTokenError as exc:
        logger.exception(
            "Firebase InvalidIdTokenError: %s",
            exc
        )

        raise HTTPException(
            status_code=401,
            detail="Token Firebase inválido"
        )

    except Exception as exc:
        logger.exception(
            "Erro verificando Firebase token: %s: %s",
            type(exc).__name__,
            exc,
        )

        raise HTTPException(
            status_code=401,
            detail="Falha na validação do token"
        )


async def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente")
    token = authorization[7:].strip()
    return validar_token(token)

@app.get("/health")
def health():
    return {"ok": True}


@app.post("/uploads/session")
def create_upload_session(payload: UploadSessionRequest, request: Request, user=Depends(current_user)):
    if payload.content_type != "application/pdf" or not payload.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Somente arquivos PDF são aceitos")
    if payload.size > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Arquivo excede {MAX_FILE_MB} MB")

    origin = request.headers.get("origin", "")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origem não autorizada")

    uid = user["uid"]
    filename = safe_filename(payload.filename)
    job_id = uuid.uuid4().hex
    object_name = f"uploads/{uid}/{job_id}/{filename}"

    logger.info(
        "Criando upload | uid=%s | job=%s | arquivo=%s | size=%d",
        uid,
        job_id,
        filename,
        payload.size,
    )

    # ------------------------------------------
    # Firestore
    # ------------------------------------------

    try:
        job_ref = firestore_client.collection("jobs").document(job_id)
        job_ref.set({
            "uid": uid,
            "filename": filename,
            "file_size": payload.size,
            "input_object": object_name,
            "output_object": None,
            "status": "UPLOADING",
            "upload_progress": 0,
            "processing_progress": 0,
            "processed_pages": 0,
            "total_pages": None,
            "error": None,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })

        logger.info(
            "Firestore OK | job=%s",
            job_id,
        )

    except Exception as exc:
        logger.exception(
            "ERRO FIRESTORE | job=%s | %s",
            job_id,
            exc,
        )

        raise HTTPException(
            status_code=500,
            detail="Erro ao criar registro do processamento",
        )

    # ------------------------------------------
    # Cloud Storage resumable session
    # ------------------------------------------
    try:
        blob = bucket.blob(object_name)

        blob.content_type = "application/pdf"

        blob.metadata = {"job_id": job_id, "uid": uid, "original_filename": filename}

        logger.info(
            "Criando resumable session | bucket=%s | object=%s",
            BUCKET_NAME,
            object_name,
        )

        session_url = blob.create_resumable_upload_session(
            content_type="application/pdf",
            size=payload.size,
            origin=origin,
            if_generation_match=0,
        )

        logger.info(
            "Resumable session criada | job=%s",
            job_id,
        )

    except Exception as exc:
        logger.exception(
            "ERRO STORAGE | bucket=%s | object=%s | %s",
            BUCKET_NAME,
            object_name,
            exc,
        )

        # Atualiza o job para não ficar eternamente UPLOADING.
        try:
            job_ref.update({
                "status": "ERROR",
                "error": str(exc)[:1000],
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail="Erro ao iniciar upload no Cloud Storage",
        )

    return {"job_id": job_id, "session_url": session_url, "object_name": object_name}


@app.get("/jobs")
def list_jobs(user=Depends(current_user)):
    uid = user["uid"]
    docs = firestore_client.collection("jobs").where(filter=FieldFilter("uid", "==", uid)).stream()
    jobs = []
    for doc in docs:
        item = doc.to_dict()
        item["id"] = doc.id
        for key in ("created_at", "updated_at", "started_at", "finished_at"):
            if item.get(key):
                item[key] = item[key].isoformat()
        jobs.append(item)
    jobs.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"jobs": jobs}


@app.get("/jobs/{job_id}/download")
def download_url(job_id: str, user=Depends(current_user)):
    doc = firestore_client.collection("jobs").document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job = doc.to_dict()
    if job.get("uid") != user["uid"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    if job.get("status") != "COMPLETED" or not job.get("output_object"):
        raise HTTPException(status_code=409, detail="Arquivo ainda não está disponível")

    blob = bucket.blob(job["output_object"])
    creds, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(GoogleAuthRequest())
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=SIGNED_URL_MINUTES),
        method="GET",
        service_account_email=API_SERVICE_ACCOUNT_EMAIL,
        access_token=creds.token,
        response_disposition=f'attachment; filename="{PurePosixPath(job["output_object"]).name}"',
    )
    return {"url": url, "expires_in_minutes": SIGNED_URL_MINUTES}


# EVOLUTIVA FRONTEND: prévia limitada ao início do TXT, com validação de proprietário.
@app.get("/jobs/{job_id}/preview")
def preview_txt(job_id: str, user=Depends(current_user)):
    doc = firestore_client.collection("jobs").document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    job = doc.to_dict()
    if job.get("uid") != user["uid"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    if job.get("status") != "COMPLETED" or not job.get("output_object"):
        raise HTTPException(status_code=409, detail="TXT ainda não disponível")
    # Limite de 16 KiB: não baixa um TXT de centenas de páginas para exibir uma prévia.
    content = bucket.blob(job["output_object"]).download_as_bytes(start=0, end=16383)
    return {"filename": job.get("filename", ""), "preview": content.decode("utf-8", errors="replace"), "truncated": len(content) >= 16384}


# EVOLUTIVA FRONTEND: ZIP em memória limitado, autenticado e restrito aos jobs do usuário.
# Para volumes maiores, o próximo passo é gerar o ZIP em um Cloud Run Job/GCS.
class ZipRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=20)


@app.post("/jobs/download-zip")
def download_zip(payload: ZipRequest, user=Depends(current_user)):
    if len(set(payload.job_ids)) != len(payload.job_ids):
        raise HTTPException(status_code=400, detail="Seleção contém itens repetidos")
    entries = []
    total_bytes = 0
    for job_id in payload.job_ids:
        doc = firestore_client.collection("jobs").document(job_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Um dos arquivos não foi encontrado")
        item = doc.to_dict()
        if item.get("uid") != user["uid"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        if item.get("status") != "COMPLETED" or not item.get("output_object"):
            raise HTTPException(status_code=409, detail="Selecione apenas arquivos concluídos")
        blob = bucket.blob(item["output_object"])
        blob.reload()
        total_bytes += blob.size or 0
        if total_bytes > 40 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Os TXTs selecionados excedem 40 MB. Baixe individualmente.")
        entries.append((job_id, blob))

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
        for job_id, blob in entries:
            # Nome prefixado por ID para evitar colisões e impedir paths arbitrários no ZIP.
            filename = PurePosixPath(blob.name).name
            archive.writestr(f"{job_id[:8]}_{filename}", blob.download_as_bytes())
    return Response(
        content=output.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="cognotxt-resultados.zip"', "Cache-Control": "no-store"},
    )
