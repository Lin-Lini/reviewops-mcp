FROM python:3.12-slim
WORKDIR /app
COPY req.txt .
RUN pip install -r req.txt
COPY app.py .
CMD ["python", "app.py"]