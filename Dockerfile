# Risk Miner – jeden kontener: API (FastAPI) + zbudowany interfejs (Vite) + lokalny model Bielik-11B (llama.cpp, CPU).
# Dane (SQLite, cache, plik GGUF) są w wolumenie /data.

# --- 1. interfejs -------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- 2. zależności Pythona (llama-cpp-python bywa kompilowany ze źródeł, stąd kompilator) ---
FROM python:3.12-slim AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- 3. obraz uruchomieniowy ----------------------------------------------------------------
FROM python:3.12-slim
# tesseract-ocr + pol: OCR skanów PDF i zdjęć dokumentów (riskminer/ocr.py)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 tesseract-ocr tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*
COPY --from=wheels /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt && rm -rf /wheels

WORKDIR /app
COPY api.py app.py cli.py bip_sources.json ./
COPY riskminer/ riskminer/
COPY --from=web /web/dist web/dist

ENV RISKMINER_DATA_DIR=/data \
    RISKMINER_SAMPLE_XLSX=/import/Risk_Miner_dane_projekty.xlsx \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/stats', timeout=4)"
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
