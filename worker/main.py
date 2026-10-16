import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore, storage

from processor import process_pdf_to_txt

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("cognotxt.worker")

#PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")

if not PROJECT_ID:
    import google.auth

    _, PROJECT_ID = google.auth.default()

if not PROJECT_ID:
    raise RuntimeError(
        "Não foi possível determinar GOOGLE_CLOUD_PROJECT"
    )


BUCKET_NAME = os.environ["BUCKET_NAME"]
JOB_ID = os.environ["JOB_ID"]
USER_ID = os.environ["USER_ID"]
INPUT_OBJECT = os.environ["INPUT_OBJECT"]
ORIGINAL_FILENAME = os.getenv("ORIGINAL_FILENAME", Path(INPUT_OBJECT).name)

storage_client = storage.Client(project=PROJECT_ID)
db = firestore.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)
job_ref = db.collection("jobs").document(JOB_ID)


def sanitize_stem(name):
    stem = Path(name).stem
    stem = re.sub(r"[^A-Za-z0-9._()\- áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]", "_", stem)
    return re.sub(r"\s+", "_", stem).strip("._") or "resultado"


def update_progress(done, total):
    percent = int(done * 100 / total) if total else 0
    job_ref.set({
        "processed_pages": done,
        "total_pages": total,
        "processing_progress": percent,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)


def main():
    workdir = Path("/tmp/cognotxt")
    workdir.mkdir(parents=True, exist_ok=True)
    input_path = workdir / ORIGINAL_FILENAME
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_filename = f"{sanitize_stem(ORIGINAL_FILENAME)}_{timestamp}.txt"
    output_path = workdir / output_filename
    output_object = f"outputs/{USER_ID}/{JOB_ID}/{output_filename}"

    job_ref.set({
        "status": "PROCESSING",
        "processing_progress": 0,
        "started_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "error": None,
    }, merge=True)

    try:
        logger.info("Baixando gs://%s/%s", BUCKET_NAME, INPUT_OBJECT)
        bucket.blob(INPUT_OBJECT).download_to_filename(str(input_path))
        total = process_pdf_to_txt(input_path, output_path, update_progress)
        logger.info("Enviando resultado para gs://%s/%s", BUCKET_NAME, output_object)
        blob = bucket.blob(output_object)
        blob.upload_from_filename(str(output_path), content_type="text/plain; charset=utf-8")
        job_ref.set({
            "status": "COMPLETED",
            "processing_progress": 100,
            "processed_pages": total,
            "total_pages": total,
            "output_object": output_object,
            "finished_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        logger.info("Concluído: %s", output_object)
    except Exception as exc:
        logger.exception("Falha no processamento")
        job_ref.set({
            "status": "ERROR",
            "error": str(exc)[:2000],
            "finished_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        raise


if __name__ == "__main__":
    main()
