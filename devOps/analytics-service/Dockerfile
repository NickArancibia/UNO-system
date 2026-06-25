FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV SERVICE_NAME=placeholder-service
EXPOSE 8080
CMD ["python", "app.py"]
