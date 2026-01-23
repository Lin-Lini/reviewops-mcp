FROM python:3.12-slim
WORKDIR /app
COPY req.txt .
RUN pip install -r req.txt
COPY server.py .
CMD ["python", "server.py"]
