FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir --timeout 120 --index-url "$PIP_INDEX_URL" -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY --chown=app:app . .
RUN mkdir -p /app/output && chown -R app:app /app/output

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
USER app
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
