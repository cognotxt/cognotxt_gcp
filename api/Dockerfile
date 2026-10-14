FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD exec gunicorn -k uvicorn.workers.UvicornWorker -b :${PORT:-8080} --workers 2 --threads 4 --timeout 0 main:app
