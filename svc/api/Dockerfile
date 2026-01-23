FROM python:3.12-slim
WORKDIR /app
COPY req.txt .
RUN pip install -r req.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
