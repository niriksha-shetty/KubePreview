#!/usr/bin/env python3
"""Local Webhook Test Simulator for KubePreview Control Plane.

Constructs a valid GitHub pull_request JSON payload, signs it using HMAC-SHA256,
and POSTs it to the local control plane webhook endpoint.

Also supports setting a namespace's created-at annotation to 3 hours in the past
to simulate TTL expiration for testing the Reaper Daemon.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute GitHub-compatible X-Hub-Signature-256 header value."""
    mac = hmac.new(
        secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    )
    return f"sha256={mac.hexdigest()}"


def send_webhook(url: str, action: str, pr_number: int, sha: str, secret: str) -> str:
    """Send simulated GitHub webhook request to control plane."""
    payload = {
        "action": action,
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "title": f"Feature preview for PR #{pr_number}",
            "state": "closed" if action == "closed" else "open",
            "head": {
                "sha": sha,
                "ref": f"feature/pr-{pr_number}",
            },
        },
        "repository": {
            "name": "sample-app",
            "full_name": "acme/sample-app",
        },
    }

    payload_bytes = json.dumps(payload, indent=2).encode("utf-8")
    signature = compute_signature(payload_bytes, secret)

    print("==================================================")
    print("      KubePreview Webhook Simulator             ")
    print("==================================================")
    print(f" Target URL  : {url}")
    print(f" Event Action: {action}")
    print(f" PR Number   : #{pr_number}")
    print(f" Head SHA    : {sha[:7]}")
    print(f" Signature   : {signature[:20]}...")
    print("--------------------------------------------------")

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "User-Agent": "KubePreview-Simulator/1.0",
    }

    req = urllib.request.Request(
        url,
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
            return response_body
    except urllib.error.HTTPError as e:
        print(f" HTTP Error: {e.code} {e.reason}")
        err_body = e.read().decode("utf-8")
        print(f" Error Body: {err_body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f" Connection Failed: {e.reason}")
        print(" Verify that the FastAPI control plane service is running on port 8000.")
        sys.exit(1)


def simulate_ttl_expire(pr_number: int, webhook_url: str, secret: str, sha: str) -> None:
    """Simulate TTL expiration by patching namespace created-at annotation 3 hours into the past."""
    namespace_name = f"pr-{pr_number}"
    past_dt = datetime.now(timezone.utc) - timedelta(hours=3)
    past_iso_str = past_dt.isoformat()

    print("==================================================")
    print("      KubePreview TTL Expiration Simulator        ")
    print("==================================================")
    print(f" Target Namespace : {namespace_name}")
    print(f" Simulated Time   : {past_iso_str} (3 hours ago)")
    print("--------------------------------------------------")

    if not KUBERNETES_AVAILABLE:
        print(" Error: 'kubernetes' Python package is not installed.")
        print(" Please run: pip install kubernetes")
        sys.exit(1)

    try:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
    except Exception as err:
        print(f" Error loading kubeconfig: {err}")
        print(" Make sure your Kubernetes cluster (KinD/Minikube) is accessible.")
        sys.exit(1)

    core_api = client.CoreV1Api()

    # Check if namespace exists
    try:
        ns = core_api.read_namespace(name=namespace_name)
    except ApiException as e:
        if e.status == 404:
            print(f" Namespace '{namespace_name}' not found.")
            print(f" Dispatching 'opened' webhook to trigger environment provision first...")
            send_webhook(webhook_url, "opened", pr_number, sha, secret)
            print(" Waiting 3 seconds for namespace creation...")
            time.sleep(3)
            try:
                ns = core_api.read_namespace(name=namespace_name)
            except ApiException as e2:
                print(f" Could not find namespace after provisioning: {e2}")
                sys.exit(1)
        else:
            print(f" Error reading namespace '{namespace_name}': {e}")
            sys.exit(1)

    # Patch annotations on namespace
    metadata = ns.metadata or client.V1ObjectMeta()
    annotations = metadata.annotations or {}
    annotations["kubepreview.io/created-at"] = past_iso_str
    annotations["kubepreview.io/ttl-hours"] = "2"

    patch_body = {"metadata": {"annotations": annotations}}

    try:
        core_api.patch_namespace(name=namespace_name, body=patch_body)
        print(f" Successfully updated namespace '{namespace_name}' metadata!")
        print(f" Annotation 'kubepreview.io/created-at' set to: {past_iso_str}")
        print("--------------------------------------------------")
        print(" 🎯 The TTL Reaper Daemon will detect and purge this environment")
        print("    on its next scan tick (<= 60 seconds).")
        print("==================================================")
    except ApiException as e:
        print(f" Failed to patch namespace '{namespace_name}': {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Simulate GitHub Pull Request webhook payloads and TTL expiration."
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
    parser.add_argument(
        "--simulate-ttl-expire",
        action="store_true",
        help="Set namespace created-at annotation to 3 hours in the past to test Reaper Daemon",
    )

    args = parser.parse_args()

    if args.simulate_ttl_expire:
        simulate_ttl_expire(args.pr, args.url, args.secret, args.sha)
    else:
        send_webhook(args.url, args.action, args.pr, args.sha, args.secret)


if __name__ == "__main__":
    main()
