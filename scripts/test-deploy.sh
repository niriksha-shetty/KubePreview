#!/usr/bin/env bash
set -euo pipefail

# KubePreview Week 1 Validation Script: Test Deploy
# Usage: ./test-deploy.sh <PR_NUMBER> [IMAGE_TAG]

if [ "$#" -lt 1 ]; then
    echo "Error: Missing Pull Request Number."
    echo "Usage: $0 <PR_NUMBER> [IMAGE_TAG]"
    echo "Example: $0 101 v1"
    exit 1
fi

PR_NUMBER="$1"
IMAGE_TAG="${2:-latest}"
NAMESPACE="pr-${PR_NUMBER}"

# Locate root directory relative to script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFESTS_DIR="${PROJECT_ROOT}/manifests"
TEMP_DIR="/tmp/kubepreview-rendered-pr-${PR_NUMBER}"

echo "============================================================"
echo "🚀 Deploying KubePreview Environment for PR #${PR_NUMBER}"
echo "   Target Namespace : ${NAMESPACE}"
echo "   Image Tag        : ${IMAGE_TAG}"
echo "============================================================"

# Ensure cleanup on script exit or cancellation
cleanup() {
    if [ -d "${TEMP_DIR}" ]; then
        echo "🧹 Cleaning up temporary rendered manifests at ${TEMP_DIR}..."
        rm -rf "${TEMP_DIR}"
    fi
}
trap cleanup EXIT INT TERM

# Prepare temporary directory
mkdir -p "${TEMP_DIR}"

echo "📝 Rendering parameterized manifests..."
for manifest in "${MANIFESTS_DIR}"/*.yaml; do
    filename="$(basename "${manifest}")"
    sed -e "s/__PR_NUMBER__/${PR_NUMBER}/g" \
        -e "s/__IMAGE_TAG__/${IMAGE_TAG}/g" \
        "${manifest}" > "${TEMP_DIR}/${filename}"
done

echo "📦 Applying manifests to Kubernetes cluster..."
kubectl apply -f "${TEMP_DIR}"

echo "⏳ Waiting for ephemeral PostgreSQL database rollout..."
kubectl rollout status deployment/postgres -n "${NAMESPACE}" --timeout=120s

echo "⏳ Waiting for sample application rollout..."
kubectl rollout status deployment/sample-app -n "${NAMESPACE}" --timeout=120s

PREVIEW_URL="http://pr-${PR_NUMBER}.127.0.0.1.nip.io"

echo "============================================================"
echo "✅ Preview Environment Successfully Provisioned!"
echo "------------------------------------------------------------"
echo "   PR Number   : ${PR_NUMBER}"
echo "   Namespace   : ${NAMESPACE}"
echo "   Preview URL : ${PREVIEW_URL}"
echo "============================================================"
echo "👉 You can test the application by curling or opening in browser:"
echo "   curl -H \"Host: pr-${PR_NUMBER}.127.0.0.1.nip.io\" http://localhost"
echo "============================================================"
