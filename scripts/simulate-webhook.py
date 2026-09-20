#!/usr/bin/env python3
"""Local Webhook Test Simulator for KubePreview Control Plane.

Constructs a valid GitHub pull_request JSON payload, signs it using HMAC-SHA256,
and POSTs it to the local control plane webhook endpoint.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.request
import urllib.error


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute GitHub-compatible X-Hub-Signature-256 header value."""
    mac = hmac.new(
        secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    )
    return f"sha256={mac.hexdigest()}"


def main():
    parser = argparse.ArgumentParser(
        description="Simulate GitHub Pull Request webhook payloads with HMAC signature."
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["opened", "closed", "synchronize", "reopened"],
        default="opened",
        help="Pull request action (default: opened)",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=101,
        help="Pull request number (default: 101)",
    )
    parser.add_argument(
        "--sha",
        type=str,
        default="a1b2c3d4e5f678901234567890abcdef12345678",
        help="Git commit head SHA (default: sample SHA)",
    )
    parser.add_argument(
        "--secret",
        type=str,
        default=os.getenv("GITHUB_WEBHOOK_SECRET", "dev-secret"),
        help="HMAC secret key (default: 'dev-secret' or GITHUB_WEBHOOK_SECRET env var)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000/api/v1/webhook",
        help="Control plane webhook URL (default: http://localhost:8000/api/v1/webhook)",
    )

    args = parser.parse_args()

    payload = {
        "action": args.action,
        "number": args.pr,
        "pull_request": {
            "number": args.pr,
            "title": f"Feature preview for PR #{args.pr}",
            "state": "closed" if args.action == "closed" else "open",
            "head": {
                "sha": args.sha,
                "ref": f"feature/pr-{args.pr}",
            },
        },
        "repository": {
            "name": "sample-app",
            "full_name": "acme/sample-app",
        },
    }

    payload_bytes = json.dumps(payload, indent=2).encode("utf-8")
    signature = compute_signature(payload_bytes, args.secret)

    print("==================================================")
    print("      KubePreview Webhook Simulator             ")
    print("==================================================")
    print(f" Target URL  : {args.url}")
    print(f" Event Action: {args.action}")
    print(f" PR Number   : #{args.pr}")
    print(f" Head SHA    : {args.sha[:7]}")
    print(f" Signature   : {signature[:20]}...")
    print("--------------------------------------------------")

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "User-Agent": "KubePreview-Simulator/1.0",
    }

    req = urllib.request.Request(
        args.url,
        data=payload_bytes,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.status
            response_body = resp.read().decode("utf-8")
            print(f" HTTP Response Status: {status_code}")
            try:
                formatted_json = json.dumps(json.loads(response_body), indent=2)
                print(" Response Body:")
                print(formatted_json)
            except Exception:
                print(f" Response Body: {response_body}")
            print("==================================================")
            print("  Webhook simulation successfully delivered!")
            print("==================================================")
    except urllib.error.HTTPError as e:
        print(f" HTTP Error: {e.code} {e.reason}")
        err_body = e.read().decode("utf-8")
        print(f" Error Body: {err_body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f" Connection Failed: {e.reason}")
        print(" Verify that the FastAPI control plane service is running on port 8000.")
        sys.exit(1)


if __name__ == "__main__":
    main()
