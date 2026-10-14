import os
import requests
from fastapi import FastAPI, Request
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ["CLOUD_RUN_REGION"]
WORKER_JOB_NAME = os.environ.get("WORKER_JOB_NAME", "cognotxt-worker")
WORKER_TIMEOUT = os.environ.get("WORKER_TIMEOUT", "21600s")

db = firestore.Client(project=PROJECT_ID)
app = FastAPI(title="CognoTXT Dispatcher")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/events/storage")
async def storage_event(request: Request):
    data = await request.json()
    object_name = data.get("name")
    bucket = data.get("bucket")
    event_id = request.headers.get("ce-id", "unknown")

    if not object_name or not object_name.startswith("uploads/"):
        return {"ignored": True}

    parts = object_name.split("/", 3)
    if len(parts) != 4:
        return {"ignored": True, "reason": "invalid_path"}

    _, uid, job_id, filename = parts

    lock_ref = db.collection("event_locks").document(event_id)
    try:
        lock_ref.create({
            "job_id": job_id,
            "object_name": object_name,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
    except AlreadyExists:
        return {"duplicate": True, "event_id": event_id}

    job_ref = db.collection("jobs").document(job_id)
    job_ref.set({
        "uid": uid,
        "filename": filename,
        "input_object": object_name,
        "status": "QUEUED",
        "upload_progress": 100,
        "processing_progress": 0,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    try:
        creds, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(GoogleAuthRequest())
        endpoint = f"https://run.googleapis.com/v2/projects/{PROJECT_ID}/locations/{REGION}/jobs/{WORKER_JOB_NAME}:run"
        payload = {
            "overrides": {
                "containerOverrides": [{
                    "env": [
                        {"name": "JOB_ID", "value": job_id},
                        {"name": "USER_ID", "value": uid},
                        {"name": "INPUT_OBJECT", "value": object_name},
                        {"name": "ORIGINAL_FILENAME", "value": filename},
                    ]
                }],
                "timeout": WORKER_TIMEOUT,
                "taskCount": 1,
            }
        }
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        job_ref.set({
            "execution_operation": body.get("name"),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        return {"queued": True, "job_id": job_id}
    except Exception as exc:
        job_ref.set({
            "status": "ERROR",
            "error": f"Falha ao iniciar worker: {exc}",
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        try:
            lock_ref.delete()
        except Exception:
            pass
        raise
