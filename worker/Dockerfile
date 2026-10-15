FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Corrigido: DEBIAN_FRONTEND impede o travamento com prompts interativos de interface no Cloud Build
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt
COPY processor.py main.py ./
CMD ["python", "main.py"]
