FROM python:3.12-slim

WORKDIR /app

# Fonts make the summary card readable. Tesseract is only used for the OCR fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 botuser \
    && mkdir -p /data \
    && chown botuser:botuser /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=botuser:botuser . .

USER botuser

# Named volumes inherit this directory's owner on first use.
ENV SERIES_DB_PATH=/data/cod_bot.db
VOLUME /data

CMD ["python", "bot.py"]
