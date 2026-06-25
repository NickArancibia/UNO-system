from flask import Flask, jsonify
import os

app = Flask(__name__)
SERVICE_NAME = os.getenv("SERVICE_NAME", "api-gateway")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/v1/whoami")
def whoami():
    return jsonify({"result": "ok", "service": SERVICE_NAME, "user": "stub-user"})


@app.get("/v1/room/list")
def room_list():
    return jsonify({"result": "ok", "rooms": []})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
