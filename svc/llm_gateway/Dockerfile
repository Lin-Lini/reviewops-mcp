FROM python:3.12-slim

WORKDIR /app
COPY req.txt .
RUN pip install --no-cache-dir -r req.txt

COPY main.py .

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
