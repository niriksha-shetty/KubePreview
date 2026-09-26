# KubePreview — Automated Multi-Tenant Preview Environment Orchestrator

> Automated Multi-Tenant Preview Environment Orchestrator on Kubernetes with GitHub PR Feedback Loop & TTL Reaper.

KubePreview is a lightweight, cloud-native control plane and preview environment orchestrator designed to automatically spin up and tear down isolated, dynamic staging environments for every Pull Request in Kubernetes.

---

## 🏗️ Repository Architecture

```text
Kubepreview/
├── cluster/
│   └── kind-config.yaml         # KinD cluster setup with ingress port mappings (80/443)
├── control-plane/               # FastAPI Control Plane Service & Orchestrator
│   ├── routers/
│   │   ├── webhook.py           # Webhook endpoint (POST /api/v1/webhook) & background notification tasks
│   │   └── previews.py          # Admin Telemetry API endpoint (GET /api/v1/previews)
│   ├── config.py                # Configuration settings (Pydantic BaseSettings: GITHUB_TOKEN, TTL_HOURS, REAPER_INTERVAL)
│   ├── formatter.py             # Rich Markdown comment generator with status badges (🟢 🔴 ⚪)
│   ├── github_client.py         # GitHub REST API client with comment deduplication & mock fallback mode
│   ├── k8s_manager.py           # Non-blocking Kubernetes SDK orchestrator, rollout waiter & namespace telemetry
│   ├── main.py                  # FastAPI application entry point, routers & TTL Reaper lifespan hooks
│   ├── reaper.py                # Asynchronous TTL Reaper Daemon background loop (60s tick)
│   ├── requirements.txt         # Control plane Python dependencies
│   ├── schemas.py               # Pydantic models for GitHub PR webhooks & telemetry payloads
│   └── security.py              # HMAC-SHA256 signature verification (X-Hub-Signature-256)
├── manifests/                   # Declarative Kubernetes Templates
│   ├── 01-namespace.yaml        # Tenant namespace with TTL annotations & metadata
│   ├── 02-resource-quota.yaml   # Hard CPU/Memory/Pod boundaries per tenant
│   ├── 03-mock-db.yaml          # Ephemeral PostgreSQL Deployment, ConfigMap & Service
│   ├── 04-app-deployment.yaml   # Sample App Deployment & Service with Downward API
│   └── 05-ingress.yaml          # NGINX Ingress routing host pr-X.127.0.0.1.nip.io
├── sample-app/                  # Sample Application Container
│   ├── app/ (main.py)           # Two-tier Python FastAPI app with exponential DB retry
│   ├── db/
│   │   └── init.sql             # PostgreSQL seed script for ephemeral database
│   ├── Dockerfile               # Non-root container definition
│   └── requirements.txt         # App Python dependencies
├── scripts/
│   ├── simulate-webhook.py      # Local GitHub webhook E2E simulator & TTL expiration tester (--simulate-ttl-expire)
│   ├── test-deploy.sh           # Week 1 manual test deployment script
│   └── test-teardown.sh         # Week 1 manual cleanup & namespace removal script
├── .gitignore                   # Workspace gitignore rules
└── README.md
```

---

## ⚡ Quickstart Guide

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & [KinD](https://kind.sigs.k8s.io/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- Python 3.10+

---

### Step 1: Create the KinD Cluster & Ingress Controller

```bash
# Create cluster
kind create cluster --config cluster/kind-config.yaml

# Deploy NGINX Ingress Controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# Wait for Ingress Controller readiness
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=90s
```

---

### Step 2: Build & Load Sample Application Image

```bash
docker build -t kubepreview-sample-app:latest ./sample-app
kind load docker-image kubepreview-sample-app:latest --name kubepreview
```

---

### Step 3: Run the Control Plane Service

```bash
# Install control plane dependencies
pip install -r control-plane/requirements.txt

# Start control plane service
cd control-plane
uvicorn main:app --port 8000 --reload
```

The control plane starts up on `http://localhost:8000` with live OpenAPI docs at `http://localhost:8000/docs` and starts the **TTL Reaper Daemon** in the background.

---

### Step 4: Simulate Webhook Events & TTL Expiration (E2E Testing)

Open a new terminal and use the test simulator to trigger automated Kubernetes orchestration and PR feedback comments:

#### 1. Provision / Update Environment:
```bash
# Trigger PR #101 creation (provisions namespace & posts 🟢 Ready comment)
python scripts/simulate-webhook.py --action opened --pr 101

# Trigger PR #101 synchronization (idempotent patch)
python scripts/simulate-webhook.py --action synchronize --pr 101
```

#### 2. Query Telemetry Admin API:
```bash
# List all active preview sandboxes & remaining lifetime
curl http://localhost:8000/api/v1/previews
```

#### 3. Test TTL Reaper Daemon (Expired Environment Cleanup):
```bash
# Set namespace pr-101 creation timestamp to 3 hours ago (exceeds 2h TTL)
python scripts/simulate-webhook.py --simulate-ttl-expire --pr 101
```
*The Reaper Daemon will detect expiration within 60s, purge `pr-101`, and post the 🔴 Expired comment.*

#### 4. Teardown Environment on PR Close:
```bash
# Trigger PR #101 removal (deletes namespace & posts ⚪ Terminated comment)
python scripts/simulate-webhook.py --action closed --pr 101
```

---

## 🔒 Security & Architecture Highlights

1. **HMAC-SHA256 Payload Verification**: All incoming webhooks are validated against `X-Hub-Signature-256` using constant-time comparison (`hmac.compare_digest`).
2. **GitHub PR Feedback Loop & Deduplication**: Utilizes `httpx.AsyncClient` to update PR comments dynamically using hidden comment markers (`<!-- kubepreview-bot-comment -->`). Falls back gracefully to stdout mock mode when `GITHUB_TOKEN="mock"`.
3. **Automated TTL Reaper Daemon**: Async background task in FastAPI lifespan startup scanning every 60 seconds to self-destruct expired environments and free cluster capacity.
4. **Non-Blocking Async Event Loop**: Heavy Kubernetes API calls and rollout polling (`asyncio.to_thread`) run off-thread to ensure immediate HTTP 200 responses to GitHub (<50ms).
5. **Multi-Tenant Isolation**: Programmatically creates dedicated namespaces (`pr-<PR_NUMBER>`) with strict `ResourceQuota` limits (CPU, Memory, Pod count).
6. **Idempotent Reconciliation**: Handles HTTP 409 (`AlreadyExists`) gracefully via dynamic resource patching (`patch_*`) and HTTP 404 cleanly on namespace deletion.
