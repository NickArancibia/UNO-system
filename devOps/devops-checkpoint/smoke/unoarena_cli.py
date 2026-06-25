#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.request


def request_json(api_url, path):
    url = api_url.rstrip("/") + path
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description="UnoArena Client Checkpoint smoke CLI adapter")
    parser.add_argument("--api", required=True, help="Staging API base URL")
    subparsers = parser.add_subparsers(dest="resource", required=True)

    room_parser = subparsers.add_parser("room")
    room_subparsers = room_parser.add_subparsers(dest="action", required=True)
    list_parser = room_subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true", required=True)

    args = parser.parse_args()

    if args.resource == "room" and args.action == "list":
        payload = request_json(args.api, "/v1/room/list")
        print(json.dumps(payload, separators=(",", ":")))
        return 0

    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"unoarena-cli smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
