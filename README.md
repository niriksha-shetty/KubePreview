# KubePreview — Automated Multi-Tenant Preview Environment Orchestrator

> Automated Multi-Tenant Preview Environment Orchestrator on Kubernetes.

KubePreview is a lightweight, cloud-native control plane and preview environment orchestrator designed to automatically spin up and tear down isolated, dynamic staging environments for every Pull Request in Kubernetes.

---

## 🏗️ Repository Architecture

```text
Kubepreview/
├── cluster/
│   └── kind-config.yaml         # KinD cluster setup with ingress port mappings (80/443)
├── control-plane/               # Week 2: Automated Control Plane Service
│   ├── routers/
│   │   └── webhook.py           # Webhook endpoint (POST /api/v1/webhook) & background tasks
│   ├── config.py                # Environment configuration (Pydantic BaseSettings)
│   ├── k8s_manager.py           # Non-blocking Kubernetes SDK orchestrator & rollout waiter
│   ├── main.py                  # FastAPI application entry point & lifespan hooks
│   ├── requirements.txt         # Control plane Python dependencies
│   ├── schemas.py               # Pydantic models for GitHub PR webhooks
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
│   ├── simulate-webhook.py      # Local GitHub webhook E2E simulator with HMAC signing
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

### Step 3: Run the Control Plane Service (Week 2)

```bash
# Install control plane dependencies
pip install -r control-plane/requirements.txt

# Start control plane service
cd control-plane
uvicorn main:app --port 8000 --reload
```

The control plane starts up on `http://localhost:8000` with live OpenAPI docs at `http://localhost:8000/docs`.

---

### Step 4: Simulate Webhook Events (Local E2E Testing)

Open a new terminal and use the test simulator to trigger automated Kubernetes orchestration:

#### Provision / Update Environment:
```bash
# Trigger PR #101 creation
python scripts/simulate-webhook.py --action opened --pr 101

# Trigger PR #101 synchronization (idempotent patch)
python scripts/simulate-webhook.py --action synchronize --pr 101
```

#### Teardown Environment:
```bash
# Trigger PR #101 removal
python scripts/simulate-webhook.py --action closed --pr 101
```

---

## 🔒 Security & Architecture Highlights

1. **HMAC-SHA256 Payload Verification**: All incoming webhooks are validated against `X-Hub-Signature-256` using constant-time comparison (`hmac.compare_digest`).
2. **Non-Blocking Async Event Loop**: Heavy Kubernetes API calls and rollout polling (`asyncio.to_thread`) run off-thread to ensure immediate HTTP 200 responses to GitHub (<50ms).
3. **Multi-Tenant Isolation**: Programmatically creates dedicated namespaces (`pr-<PR_NUMBER>`) with strict `ResourceQuota` limits (CPU, Memory, Pod count).
4. **Idempotent Reconciliation**: Handles HTTP 409 (`AlreadyExists`) gracefully via dynamic resource patching (`patch_*`) and HTTP 404 cleanly on namespace deletion.
