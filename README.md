# KubePreview — Automated Multi-Tenant Preview Environment Orchestrator

> **Week 1 Milestone**: Foundations, Multi-Tenancy & Parameterized Manifests

KubePreview is a lightweight, cloud-native preview environment orchestrator designed to automatically spin up isolated, dynamic staging environments for every Pull Request in Kubernetes.

---

## 🏗️ Repository Architecture

```text
Kubepreview/
├── cluster/
│   └── kind-config.yaml         # KinD cluster setup with ingress port mappings (80/443)
├── sample-app/
│   ├── app/ (main.py)           # Two-tier Python FastAPI app with exponential DB retry
│   ├── db/
│   │   └── init.sql             # PostgreSQL seed script for ephemeral database
│   ├── Dockerfile               # Non-root container definition
│   └── requirements.txt         # Python dependencies
├── manifests/
│   ├── 01-namespace.yaml        # Tenant namespace with TTL annotations & metadata
│   ├── 02-resource-quota.yaml   # Hard CPU/Memory/Pod boundaries per tenant
│   ├── 03-mock-db.yaml          # Ephemeral PostgreSQL Deployment, ConfigMap & Service
│   ├── 04-app-deployment.yaml   # Sample App Deployment & Service with Downward API
│   └── 05-ingress.yaml          # NGINX Ingress routing host pr-X.127.0.0.1.nip.io
├── scripts/
│   ├── test-deploy.sh           # Automated deployment script for testing PR environments
│   └── test-teardown.sh         # Cleanup & namespace removal script
└── README.md
```

---

## ⚡ Quickstart Guide

### Prerequisites
Ensure you have the following installed on your host machine:
- [Docker](https://docs.docker.com/get-docker/)
- [KinD (Kubernetes in Docker)](https://kind.sigs.k8s.io/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

---

### Step 1: Create the KinD Cluster

Create the KinD cluster using our custom configuration with extra host port mappings (80 and 443) and control-plane node labels:

```bash
kind create cluster --config cluster/kind-config.yaml
```

Verify cluster status:
```bash
kubectl cluster-info --context kind-kubepreview
```

---

### Step 2: Install NGINX Ingress Controller

Deploy the official NGINX Ingress Controller tailored for KinD:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
```

Wait until the ingress controller pods reach the `Ready` state:

```bash
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=90s
```

---

### Step 3: Build & Load Sample Application Image

Build the lightweight sample application container:

```bash
docker build -t kubepreview-sample-app:latest ./sample-app
```

Load the Docker image directly into the KinD cluster nodes (no external container registry required):

```bash
kind load docker-image kubepreview-sample-app:latest --name kubepreview
```

---

### Step 4: Deploy a Preview Environment

Run the validation script to spin up an isolated environment for Pull Request `#101`:

```bash
# Make scripts executable
chmod +x scripts/test-deploy.sh scripts/test-teardown.sh

# Deploy PR #101
./scripts/test-deploy.sh 101
```

The script will:
1. Substitute placeholders into `/tmp/kubepreview-rendered-pr-101`.
2. Apply the K8s manifests in sequence.
3. Wait for PostgreSQL and FastAPI pods to become `Ready`.
4. Output the live preview URL (`http://pr-101.127.0.0.1.nip.io`).

---

### Step 5: Test the Preview URL

Open your web browser or run `curl`:

```bash
curl -H "Host: pr-101.127.0.0.1.nip.io" http://localhost
```

You will receive an HTML response featuring:
- **Environment Metadata**: PR ID (`PR #101`), Pod Name, and Namespace (`pr-101`).
- **Database Query Results**: Seeded records from the ephemeral PostgreSQL instance.

---

### Step 6: Teardown & Purge Environment

To delete the preview environment and free up cluster resources:

```bash
./scripts/test-teardown.sh 101
```

---

## 🔒 Multi-Tenancy & Security Design

1. **Namespace Isolation**: Each PR gets a dedicated namespace (`pr-<PR_NUMBER>`) preventing cross-tenant access.
2. **Hard Resource Quotas**: `02-resource-quota.yaml` prevents noisy-neighbor syndrome by bounding CPU (600m max), Memory (512Mi max), and Pod count (max 4 per namespace).
3. **Non-Root Execution**: Container specs enforce UID 10001 execution for security compliance.
4. **Lifecycle & TTL**: Metadata annotations (`kubepreview.io/ttl-hours: "2"`) prepare the cluster for the automated garbage collection controller in upcoming weeks.
