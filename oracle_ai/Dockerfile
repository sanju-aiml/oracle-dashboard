FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV ORACLE_DB=/data/oracle_data.db ORACLE_MODELS=/data/models ORACLE_UPLOADS=/data/uploads ORACLE_GATE_LOG=/data/gate_log.jsonl
VOLUME /data
EXPOSE 8000
# restart: always (docker run --restart always) keeps the bot running 24/7
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
