FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY iprintd /app/iprintd
WORKDIR /app
ENV OMP_THREAD_LIMIT=2
USER 99:100
HEALTHCHECK --interval=60s --timeout=10s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('IPRINT_PORT','631')+'/healthz',timeout=5)"
ENTRYPOINT ["python", "-m", "iprintd"]
