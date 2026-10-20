"""Exemplo de integração B2B. Requer pip install requests.

Uso:
    export COGNOTXT_API_URL=https://cognotxt-api-940153605624.us-central1.run.app
    export COGNOTXT_API_KEY='cgt_live_...'
    python cliente.py documento.pdf

IMPORTANTE: não registre sua API Key nem a URL de upload em logs públicos.
"""
import os
import sys
import time
from pathlib import Path
import requests

BASE = os.environ["COGNOTXT_API_URL"].rstrip("/")
KEY = os.environ["COGNOTXT_API_KEY"]
HEADERS = {"X-API-Key": KEY}


def main(path):
    file = Path(path)
    with requests.Session() as client:
        # 1. Criar job. A URL de upload é uma credencial temporária.
        r = client.post(f"{BASE}/v1/uploads", headers=HEADERS,
                        json={"filename": file.name, "size": file.stat().st_size,
                              "content_type": "application/pdf"}, timeout=30)
        r.raise_for_status()
        job = r.json()
        job_id = job["job_id"]
        print("Job criado:", job_id)

        # 2. Enviar PDF diretamente para o GCS; não inserir X-API-Key no PUT.
        # requests usa stream em arquivo aberto, sem carregar PDF inteiro na memória.
        with file.open("rb") as stream:
            response = client.put(job["upload_url"], data=stream,
                                  headers={"Content-Type": "application/pdf",
                                           "Content-Length": str(file.stat().st_size)},
                                  timeout=(30, 900))
            response.raise_for_status()
        print("Upload concluído")

        # 3. Consultar periodicamente (não exceder RPM contratado).
        while True:
            status_resp = client.get(f"{BASE}/v1/jobs/{job_id}", headers=HEADERS, timeout=30)
            if status_resp.status_code == 429:
                time.sleep(int(status_resp.headers.get("Retry-After", "15")))
                continue
            status_resp.raise_for_status()
            state = status_resp.json()
            print(state["status"], state["processed_pages"], "/", state["total_pages"])
            if state["status"] == "COMPLETED":
                break
            if state["status"] == "ERROR":
                raise RuntimeError(state.get("error") or "Erro de processamento")
            time.sleep(15)

        # 4. Obter link assinado de curta duração, sem baixar com a API Key.
        r = client.get(f"{BASE}/v1/jobs/{job_id}/download", headers=HEADERS, timeout=30)
        r.raise_for_status()
        signed = r.json()["url"]
        output = file.with_suffix(".txt")
        with client.get(signed, stream=True, timeout=(30, 300)) as resp:
            resp.raise_for_status()
            with output.open("wb") as f:
                for chunk in resp.iter_content(1024 * 1024):
                    f.write(chunk)
        print("TXT salvo em:", output)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python cliente.py documento.pdf")
    main(sys.argv[1])
