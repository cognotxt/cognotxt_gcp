"""CognoTXT B2B v1. Rotas adicionais: frontend legado não é alterado."""
import hashlib
import hmac
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter()
api_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Injetado pelo main.py; mantém um único cliente Firestore/GCS e assinatura de URL.
db = None
bucket = None
create_session = None
signed_url = None
firebase_user = None
max_pdf_bytes = 0


def configure(*, database, storage_bucket, make_session, make_signed_url, firebase_dependency, maximum_bytes):
    global db, bucket, create_session, signed_url, firebase_user, max_pdf_bytes
    db, bucket, create_session = database, storage_bucket, make_session
    signed_url, firebase_user, max_pdf_bytes = make_signed_url, firebase_dependency, maximum_bytes


def now():
    return datetime.now(timezone.utc)


def error(status, msg):
    raise HTTPException(status_code=status, detail=msg)


def hash_key(token):
    # Token criado por secrets.token_urlsafe(32), com pelo menos 256 bits de aleatoriedade.
    # SHA-256 é adequado para comparar tokens gerados aleatoriamente (não senhas humanas).
    return hashlib.sha256(token.encode()).hexdigest()


def public_key(record, key_id):
    fields = ("company_id", "alias", "description", "department", "environment", "status",
              "valid_from", "valid_until", "rpm_limit", "concurrency_limit", "monthly_page_limit",
              "scopes", "created_at", "last_used_at", "revoked_at", "active_count", "pages_total", "jobs_total", "errors_total")
    return {"key_id": key_id, **{f: record.get(f) for f in fields}}


def to_iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def normalize(item):
    return {k: to_iso(v) for k, v in item.items()}


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=1000)
    contact_email: str = Field(default="", max_length=254)


class KeyCreate(BaseModel):
    alias: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=1500)
    department: str = Field(default="", max_length=100)
    environment: str = Field(default="production", pattern="^(production|sandbox)$")
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    rpm_limit: int = Field(default=60, ge=1, le=3000)
    concurrency_limit: int = Field(default=3, ge=1, le=100)
    monthly_page_limit: int = Field(default=100000, ge=1)
    scopes: list[str] = Field(default_factory=lambda: ["jobs:create", "jobs:read", "jobs:download"])


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(gt=0)
    content_type: str = "application/pdf"


def require_admin(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        error(401, "Token Firebase necessário")
    user = firebase_user(authorization[7:].strip())
    allowed = {e.strip().lower() for e in os.getenv("B2B_ADMIN_EMAILS", "").split(",") if e.strip()}
    # Não habilita rotas administrativas sem allowlist explícita.
    if not allowed or not user.get("email_verified") or user.get("email", "").lower() not in allowed:
        error(403, "Usuário não autorizado a administrar clientes")
    return user


def require_key(x_api_key: str | None = Security(api_header)):
    if not x_api_key:
        error(401, "Informe X-API-Key")
    m = re.fullmatch(r"cgt_live_([a-f0-9]{32})_([A-Za-z0-9_-]{40,80})", x_api_key)
    if not m:
        error(401, "API Key inválida")
    key_id = m.group(1)
    snap = db.collection("b2b_api_keys").document(key_id).get()
    value = snap.to_dict() if snap.exists else None
    if not value or not hmac.compare_digest(str(value.get("hash", "")), hash_key(x_api_key)):
        error(401, "API Key inválida")
    t = now()
    if value.get("status") != "ACTIVE":
        error(403, "API Key inativa ou revogada")
    start, end = value.get("valid_from"), value.get("valid_until")
    if start and t < start: error(403, "API Key ainda não válida")
    if end and t > end: error(403, "API Key expirada")
    company = db.collection("b2b_companies").document(value["company_id"]).get()
    if not company.exists or company.to_dict().get("status") != "ACTIVE":
        error(403, "Empresa inativa")
    return {"id": key_id, **value}


def need_scope(key, permission):
    if permission not in key.get("scopes", []):
        error(403, "Esta API Key não tem a permissão necessária")


@router.post("/admin/companies", status_code=201, tags=["Administração B2B"])
def add_company(body: CompanyCreate, admin=Depends(require_admin)):
    ident = uuid.uuid4().hex
    db.collection("b2b_companies").document(ident).set({**body.model_dump(), "status": "ACTIVE", "created_at": firestore.SERVER_TIMESTAMP, "created_by": admin["uid"]})
    return {"company_id": ident, "status": "ACTIVE"}


@router.get("/admin/companies", tags=["Administração B2B"])
def companies(admin=Depends(require_admin)):
    return {"companies": [{"company_id": s.id, **normalize(s.to_dict())} for s in db.collection("b2b_companies").limit(200).stream()]}


@router.patch("/admin/companies/{company_id}/status", tags=["Administração B2B"])
def company_status(company_id: str, active: bool, admin=Depends(require_admin)):
    ref = db.collection("b2b_companies").document(company_id)
    if not ref.get().exists: error(404, "Empresa não encontrada")
    ref.update({"status": "ACTIVE" if active else "SUSPENDED", "updated_at": firestore.SERVER_TIMESTAMP})
    return {"company_id": company_id, "status": "ACTIVE" if active else "SUSPENDED"}


@router.post("/admin/companies/{company_id}/keys", status_code=201, tags=["Administração B2B"])
def issue_key(company_id: str, body: KeyCreate, admin=Depends(require_admin)):
    company = db.collection("b2b_companies").document(company_id).get()
    if not company.exists: error(404, "Empresa não encontrada")
    if company.to_dict().get("status") != "ACTIVE": error(409, "Empresa suspensa")
    start, end = body.valid_from, body.valid_until
    if start and start.utcoffset() is None: error(422, "valid_from precisa incluir fuso horário")
    if end and end.utcoffset() is None: error(422, "valid_until precisa incluir fuso horário")
    if end and end <= (start or now()): error(422, "valid_until precisa ser posterior ao início")
    authorized = {"jobs:create", "jobs:read", "jobs:download"}
    if not body.scopes or not set(body.scopes) <= authorized: error(422, "Escopos inválidos")
    key_id = uuid.uuid4().hex
    secret = f"cgt_live_{key_id}_{secrets.token_urlsafe(32)}"
    record = {**body.model_dump(), "company_id": company_id, "hash": hash_key(secret),
              "status": "ACTIVE", "active_count": 0, "pages_total": 0, "jobs_total": 0,
              "errors_total": 0, "created_at": firestore.SERVER_TIMESTAMP, "created_by": admin["uid"]}
    db.collection("b2b_api_keys").document(key_id).create(record)
    log.info("Credencial B2B emitida empresa=%s key_id=%s", company_id, key_id)
    # ÚNICO momento em que o segredo completo é retornado.
    return {"api_key": secret, "warning": "Guarde agora: não será exibida novamente.", **public_key(record, key_id)}


@router.get("/admin/companies/{company_id}/keys", tags=["Administração B2B"])
def keys(company_id: str, admin=Depends(require_admin)):
    items = db.collection("b2b_api_keys").where(filter=FieldFilter("company_id", "==", company_id)).stream()
    return {"keys": [normalize(public_key(s.to_dict(), s.id)) for s in items]}


@router.post("/admin/keys/{key_id}/revoke", tags=["Administração B2B"])
def revoke(key_id: str, admin=Depends(require_admin)):
    ref = db.collection("b2b_api_keys").document(key_id)
    if not ref.get().exists: error(404, "Credencial não encontrada")
    ref.update({"status": "REVOKED", "revoked_at": firestore.SERVER_TIMESTAMP, "revoked_by": admin["uid"]})
    return {"key_id": key_id, "status": "REVOKED"}


@firestore.transactional
def reserve_request(tx, key_ref, rate_ref, key_id, for_job, job_ref=None, job_data=None):
    # Todas as leituras antes das gravações: validação atômica de RPM/concorrência.
    snap = key_ref.get(transaction=tx)
    rate_snap = rate_ref.get(transaction=tx)
    k = snap.to_dict()
    if k.get("status") != "ACTIVE": error(403, "Credencial não está ativa")
    current = rate_snap.to_dict() if rate_snap.exists else {}
    count = int(current.get("count", 0))
    if count >= int(k.get("rpm_limit", 60)): error(429, "Limite de requisições por minuto atingido")
    if for_job and int(k.get("active_count", 0)) >= int(k.get("concurrency_limit", 3)):
        error(429, "Limite de processamentos simultâneos atingido")
    # Este limite mensal considera páginas concluídas (não o consumo em andamento).
    month = now().strftime("%Y%m")
    pages_month = int(k.get("pages_month", 0)) if k.get("usage_month") == month else 0
    if for_job and pages_month >= int(k.get("monthly_page_limit", 100000)):
        error(429, "Limite mensal de páginas atingido")
    tx.set(rate_ref, {"count": count + 1, "expires_at": now() + timedelta(hours=2)}, merge=True)
    if for_job:
        tx.update(key_ref, {"active_count": firestore.Increment(1), "jobs_total": firestore.Increment(1), "last_used_at": firestore.SERVER_TIMESTAMP})
        tx.create(job_ref, job_data)
    else:
        tx.update(key_ref, {"last_used_at": firestore.SERVER_TIMESTAMP})


def charge_rate(key, for_job=False, job_id=None, job_data=None):
    key_ref = db.collection("b2b_api_keys").document(key["id"])
    bucket_id = now().strftime("%Y%m%d%H%M")
    rate_ref = key_ref.collection("rate_limits").document(bucket_id)
    job_ref = db.collection("jobs").document(job_id) if job_id else None
    reserve_request(db.transaction(), key_ref, rate_ref, key["id"], for_job, job_ref, job_data)


def own_job(key, job_id):
    doc = db.collection("jobs").document(job_id).get()
    if not doc.exists: error(404, "Job não encontrado")
    job = doc.to_dict()
    # Não é suficiente validar uid: exige *empresa E chave*.
    if job.get("channel") != "B2B" or job.get("company_id") != key["company_id"] or job.get("api_key_id") != key["id"]:
        error(404, "Job não encontrado")
    return job


def view_job(item, job_id):
    start, finish = item.get("started_at"), item.get("finished_at")
    secs = max(0, int(((finish or now()) - start).total_seconds())) if start else None
    total = item.get("total_pages") or 0
    done = item.get("processed_pages") or 0
    pct = int(done * 100 / total) if total else item.get("processing_progress", 0)
    eta = int((total - done) * secs / done) if secs is not None and done >= 3 and total > done and item.get("status") == "PROCESSING" else None
    return {"job_id": job_id, "company_id": item.get("company_id"), "api_key_id": item.get("api_key_id"),
            "filename": item.get("filename"), "file_size": item.get("file_size"), "status": item.get("status"),
            "total_pages": item.get("total_pages"), "processed_pages": done, "progress_percent": pct,
            "elapsed_seconds": secs, "estimated_remaining_seconds": eta,
            "created_at": to_iso(item.get("created_at")), "started_at": to_iso(start), "finished_at": to_iso(finish),
            "error": item.get("error")}


@router.post("/v1/uploads", status_code=201, tags=["Integração B2B"])
def upload(body: UploadCreate, key=Depends(require_key)):
    need_scope(key, "jobs:create")
    if body.content_type != "application/pdf" or not body.filename.lower().endswith(".pdf"):
        error(400, "Somente PDFs são aceitos")
    if body.size > max_pdf_bytes: error(413, "PDF excede tamanho máximo")
    filename = re.sub(r"[^A-Za-z0-9._()\- áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]", "_", PurePosixPath(body.filename).name)
    filename = re.sub(r"\s+", "_", filename).strip("._") or "arquivo.pdf"
    job_id = uuid.uuid4().hex
    # Namespace de GCS compatível com dispatcher/worker já existentes: uploads/{uid}/{job}/{file}
    uid = f"b2b_{key['company_id']}_{key['id']}"
    obj = f"uploads/{uid}/{job_id}/{filename}"
    record = {"uid": uid, "channel": "B2B", "company_id": key["company_id"], "api_key_id": key["id"],
              "filename": filename, "file_size": body.size, "input_object": obj, "output_object": None,
              "status": "UPLOADING", "upload_progress": 0, "processing_progress": 0,
              "processed_pages": 0, "total_pages": None, "error": None,
              "quota_released": False, "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP}
    charge_rate(key, for_job=True, job_id=job_id, job_data=record)
    try:
        # URL de upload é credencial temporária: não registrar em logs.
        session = create_session(obj, body.size, job_id, uid)
    except Exception:
        log.exception("Falha ao criar upload B2B job=%s", job_id)
        try:
            db.collection("jobs").document(job_id).update({"status": "ERROR", "error": "Falha ao iniciar upload", "updated_at": firestore.SERVER_TIMESTAMP})
            release_slot(job_id)
        except Exception:
            log.exception("Falha ao liberar quota do job=%s; requer reconciliação", job_id)
        error(500, "Falha ao iniciar sessão de upload")
    return {"job_id": job_id, "status": "UPLOADING", "upload_url": session,
            "upload_method": "PUT", "upload_content_type": "application/pdf", "expires_note": "Use a URL prontamente; trate-a como segredo."}


@firestore.transactional
def release_tx(tx, ref, key_ref):
    s = ref.get(transaction=tx)
    if not s.exists or s.to_dict().get("quota_released"): return
    item = s.to_dict()
    tx.update(ref, {"quota_released": True})
    tx.update(key_ref, {"active_count": firestore.Increment(-1)})


def release_slot(job_id):
    ref = db.collection("jobs").document(job_id)
    doc = ref.get()
    item = doc.to_dict() if doc.exists else {}
    if item.get("api_key_id"):
        release_tx(db.transaction(), ref, db.collection("b2b_api_keys").document(item["api_key_id"]))


@router.get("/v1/jobs/{job_id}", tags=["Integração B2B"])
def get_job(job_id: str, key=Depends(require_key)):
    need_scope(key, "jobs:read")
    charge_rate(key)
    return view_job(own_job(key, job_id), job_id)


@router.get("/v1/jobs", tags=["Integração B2B"])
def list_jobs(key=Depends(require_key), limit: int = 30):
    need_scope(key, "jobs:read")
    if limit < 1 or limit > 100: error(422, "limit deve ficar entre 1 e 100")
    charge_rate(key)
    # Consulta por uid utiliza o índice simples atual; filtro secundário no servidor.
    uid = f"b2b_{key['company_id']}_{key['id']}"
    docs = db.collection("jobs").where(filter=FieldFilter("uid", "==", uid)).limit(300).stream()
    rows = [(d.id, d.to_dict()) for d in docs]
    rows.sort(key=lambda r: to_iso(r[1].get("created_at")) or "", reverse=True)
    return {"jobs": [view_job(x, j) for j, x in rows[:limit]], "limit": limit,
            "note": "Lista limitada aos 300 registros recuperados; use GET /v1/jobs/{id} para histórico específico."}


@router.get("/v1/jobs/{job_id}/download", tags=["Integração B2B"])
def download(job_id: str, key=Depends(require_key)):
    need_scope(key, "jobs:download")
    charge_rate(key)
    job = own_job(key, job_id)
    if job.get("status") != "COMPLETED" or not job.get("output_object"):
        error(409, "TXT ainda não disponível")
    return signed_url(job["output_object"])


@router.get("/admin/companies/{company_id}/usage", tags=["Administração B2B"])
def company_usage(company_id: str, admin=Depends(require_admin)):
    snaps = db.collection("b2b_api_keys").where(filter=FieldFilter("company_id", "==", company_id)).stream()
    keys = [s.to_dict() | {"key_id": s.id} for s in snaps]
    return {"company_id": company_id,
            "jobs_total": sum(int(k.get("jobs_total", 0)) for k in keys),
            "pages_total": sum(int(k.get("pages_total", 0)) for k in keys),
            "errors_total": sum(int(k.get("errors_total", 0)) for k in keys),
            "by_key": [{"key_id": k["key_id"], "alias": k["alias"], "jobs_total": k.get("jobs_total", 0),
                        "pages_total": k.get("pages_total", 0), "errors_total": k.get("errors_total", 0),
                        "active_count": k.get("active_count", 0)} for k in keys]}

@router.post("/admin/keys/{key_id}/suspend", tags=["Administração B2B"])
def suspend_key(key_id: str, admin=Depends(require_admin)):
    ref = db.collection("b2b_api_keys").document(key_id)
    snap = ref.get()
    if not snap.exists: error(404, "API Key não encontrada")
    if snap.to_dict().get("status") == "REVOKED": error(409, "Chaves revogadas não podem ser reativadas")
    ref.update({"status": "SUSPENDED", "updated_at": firestore.SERVER_TIMESTAMP})
    return {"key_id": key_id, "status": "SUSPENDED"}


@router.post("/admin/keys/{key_id}/activate", tags=["Administração B2B"])
def activate_key(key_id: str, admin=Depends(require_admin)):
    ref = db.collection("b2b_api_keys").document(key_id)
    snap = ref.get()
    if not snap.exists: error(404, "API Key não encontrada")
    if snap.to_dict().get("status") == "REVOKED": error(409, "Chave revogada não pode ser reativada: emita outra")
    ref.update({"status": "ACTIVE", "updated_at": firestore.SERVER_TIMESTAMP})
    return {"key_id": key_id, "status": "ACTIVE"}
