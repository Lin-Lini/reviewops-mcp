FROM python:3.12-slim
WORKDIR /app
COPY req.txt .
RUN pip install -r req.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9300"]
