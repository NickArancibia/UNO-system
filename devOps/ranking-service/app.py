from flask import Flask, jsonify
import os

app = Flask(__name__)
SERVICE_NAME = os.getenv("SERVICE_NAME", "placeholder-service")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/")
def root():
    return jsonify({"message": f"{SERVICE_NAME} placeholder"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
