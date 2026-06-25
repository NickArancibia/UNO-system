from flask import Flask, jsonify
import json
import os
import sys

app = Flask(__name__)
SERVICE_NAME = os.getenv("SERVICE_NAME", "api-gateway")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/v1/whoami")
def whoami():
    print(json.dumps({"event": "smoke_hit", "endpoint": "/v1/whoami", "service": SERVICE_NAME}), file=sys.stdout, flush=True)
    return jsonify({"result": "ok", "service": SERVICE_NAME, "user": "stub-user"})


@app.get("/v1/room/list")
def room_list():
    print(json.dumps({"event": "smoke_hit", "endpoint": "/v1/room/list", "service": SERVICE_NAME}), file=sys.stdout, flush=True)
    return jsonify({"result": "ok", "rooms": []})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
