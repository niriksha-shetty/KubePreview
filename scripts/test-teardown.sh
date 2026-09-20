#!/usr/bin/env bash
set -euo pipefail

# KubePreview Week 1 Validation Script: Test Teardown
# Usage: ./test-teardown.sh <PR_NUMBER>

if [ "$#" -lt 1 ]; then
    echo "Error: Missing Pull Request Number."
    echo "Usage: $0 <PR_NUMBER>"
    echo "Example: $0 101"
    exit 1
fi

PR_NUMBER="$1"
NAMESPACE="pr-${PR_NUMBER}"

echo "============================================================"
echo "🗑️ Tearing down KubePreview Environment for PR #${PR_NUMBER}"
echo "   Namespace to delete: ${NAMESPACE}"
echo "============================================================"

if kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    echo "🔥 Triggering namespace deletion: ${NAMESPACE}..."
    kubectl delete namespace "${NAMESPACE}" --wait=true
    echo "✅ Namespace ${NAMESPACE} and all associated resources successfully purged!"
else
    echo "⚠️ Namespace ${NAMESPACE} does not exist. Skipping deletion."
fi

echo "============================================================"
echo "✨ Teardown completed cleanly."
echo "============================================================"
