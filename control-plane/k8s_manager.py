import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict
import yaml

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from config import settings

logger = logging.getLogger("kubepreview.k8s_manager")


import os

_k8s_initialized = False


def init_k8s_client() -> bool:
    """Initialize Kubernetes SDK client configuration."""
    global _k8s_initialized

    if settings.CLUSTER_IN_CLUSTER or "KUBERNETES_SERVICE_HOST" in os.environ:
        try:
            logger.info("Loading in-cluster Kubernetes configuration...")
            config.load_incluster_config()
            _k8s_initialized = True
            logger.info("Successfully loaded in-cluster Kubernetes configuration.")
            return True
        except Exception as err:
            logger.error("Failed to load in-cluster Kubernetes configuration: %s", err)
            _k8s_initialized = False
            return False

    try:
        logger.info("Loading local kubeconfig (~/.kube/config)...")
        config.load_kube_config()
        _k8s_initialized = True
        logger.info("Successfully loaded local kubeconfig.")
        return True
    except Exception as err:
        _k8s_initialized = False
        logger.warning(
            "Could not load local kubeconfig: %s. "
            "Please ensure your Kubernetes cluster (KinD/Minikube/Docker Desktop) is running and kubeconfig exists.",
            err,
        )
        return False



def _apply_resource_sync(doc: Dict[str, Any], namespace: str) -> None:
    """Apply a single Kubernetes resource dictionary synchronously.
    Handles HTTP 409 AlreadyExists by patching the existing resource.
    """
    if not doc or not isinstance(doc, dict):
        return

    kind = doc.get("kind")
    metadata = doc.get("metadata", {})
    name = metadata.get("name")

    if not kind or not name:
        return

    core_api = client.CoreV1Api()
    apps_api = client.AppsV1Api()
    net_api = client.NetworkingV1Api()

    logger.debug("Applying %s/%s in namespace %s", kind, name, namespace)

    try:
        if kind == "Namespace":
            try:
                core_api.create_namespace(body=doc)
                logger.info("Created Namespace/%s", name)
            except ApiException as e:
                if e.status == 409:
                    core_api.patch_namespace(name=name, body=doc)
                    logger.info("Patched existing Namespace/%s", name)
                else:
                    raise

        elif kind == "ResourceQuota":
            try:
                core_api.create_namespaced_resource_quota(namespace=namespace, body=doc)
                logger.info("Created ResourceQuota/%s in %s", name, namespace)
            except ApiException as e:
                if e.status == 409:
                    core_api.patch_namespaced_resource_quota(name=name, namespace=namespace, body=doc)
                    logger.info("Patched existing ResourceQuota/%s in %s", name, namespace)
                else:
                    raise

        elif kind == "ConfigMap":
            try:
                core_api.create_namespaced_config_map(namespace=namespace, body=doc)
                logger.info("Created ConfigMap/%s in %s", name, namespace)
            except ApiException as e:
                if e.status == 409:
                    core_api.patch_namespaced_config_map(name=name, namespace=namespace, body=doc)
                    logger.info("Patched existing ConfigMap/%s in %s", name, namespace)
                else:
                    raise

        elif kind == "Deployment":
            try:
                apps_api.create_namespaced_deployment(namespace=namespace, body=doc)
                logger.info("Created Deployment/%s in %s", name, namespace)
            except ApiException as e:
                if e.status == 409:
                    apps_api.patch_namespaced_deployment(name=name, namespace=namespace, body=doc)
                    logger.info("Patched existing Deployment/%s in %s", name, namespace)
                else:
                    raise

        elif kind == "Service":
            try:
                core_api.create_namespaced_service(namespace=namespace, body=doc)
                logger.info("Created Service/%s in %s", name, namespace)
            except ApiException as e:
                if e.status == 409:
                    core_api.patch_namespaced_service(name=name, namespace=namespace, body=doc)
                    logger.info("Patched existing Service/%s in %s", name, namespace)
                else:
                    raise

        elif kind == "Ingress":
            try:
                net_api.create_namespaced_ingress(namespace=namespace, body=doc)
                logger.info("Created Ingress/%s in %s", name, namespace)
            except ApiException as e:
                if e.status == 409:
                    net_api.patch_namespaced_ingress(name=name, namespace=namespace, body=doc)
                    logger.info("Patched existing Ingress/%s in %s", name, namespace)
                else:
                    raise
        else:
            logger.warning("Unsupported resource kind '%s' for resource '%s'", kind, name)

    except ApiException as e:
        logger.error(
            "Kubernetes API Exception for %s/%s: status=%s, reason=%s, body=%s",
            kind,
            name,
            e.status,
            e.reason,
            e.body,
        )
        raise


def _wait_for_deployment_ready_sync(namespace: str, deployment_name: str, timeout_seconds: int = 90) -> bool:
    """Poll deployment status synchronously until ready_replicas == replicas or timeout."""
    apps_api = client.AppsV1Api()
    start_time = time.time()
    logger.info("Waiting for Deployment '%s' in namespace '%s' to become ready (timeout: %ds)...", deployment_name, namespace, timeout_seconds)

    while time.time() - start_time < timeout_seconds:
        try:
            dep = apps_api.read_namespaced_deployment_status(name=deployment_name, namespace=namespace)
            replicas = dep.status.replicas or 1
            ready = dep.status.ready_replicas or 0
            updated = dep.status.updated_replicas or 0

            logger.debug("Deployment '%s' status: ready=%d/%d, updated=%d", deployment_name, ready, replicas, updated)
            if ready >= replicas and updated >= replicas:
                logger.info("Deployment '%s' in '%s' is READY (%d/%d replicas).", deployment_name, namespace, ready, replicas)
                return True
        except ApiException as e:
            if e.status == 404:
                logger.warning("Deployment '%s' in '%s' not found yet (404)...", deployment_name, namespace)
            else:
                logger.error("Error reading deployment status: %s", e)
        time.sleep(3)

    logger.warning("Timeout waiting for Deployment '%s' in '%s' to reach ready state (%ds).", deployment_name, namespace, timeout_seconds)
    return False


def _provision_preview_environment_sync(pr_number: int, image_tag: str = "latest") -> None:
    """Synchronous core provisioning logic executing in worker thread."""
    namespace = f"pr-{pr_number}"
    manifests_dir = settings.MANIFESTS_DIR

    logger.info("=== Starting Provisioning for PR #%d (Namespace: %s, Image Tag: %s) ===", pr_number, namespace, image_tag)

    if not manifests_dir.exists():
        logger.error("Manifests directory not found at %s", manifests_dir)
        raise FileNotFoundError(f"Manifests directory not found at {manifests_dir}")

    manifest_files = sorted([f for f in manifests_dir.glob("*.yaml") if f.is_file()])
    if not manifest_files:
        logger.error("No YAML manifest files found in %s", manifests_dir)
        raise FileNotFoundError(f"No manifest files in {manifests_dir}")

    for manifest_path in manifest_files:
        logger.info("Processing manifest file: %s", manifest_path.name)
        raw_text = manifest_path.read_text(encoding="utf-8")

        # Placeholders substitution across document text
        replaced_text = raw_text.replace("__PR_NUMBER__", str(pr_number))
        replaced_text = replaced_text.replace("__NAMESPACE__", namespace)
        replaced_text = replaced_text.replace("__IMAGE_TAG__", image_tag)

        if settings.BASE_DOMAIN != "127.0.0.1.nip.io":
            replaced_text = replaced_text.replace("127.0.0.1.nip.io", settings.BASE_DOMAIN)

        # Multi-document YAML parsing
        docs = list(yaml.safe_load_all(replaced_text))
        for doc in docs:
            if doc:
                _apply_resource_sync(doc, namespace)

    # Poll deployments for readiness
    _wait_for_deployment_ready_sync(namespace, "postgres", timeout_seconds=90)
    _wait_for_deployment_ready_sync(namespace, "sample-app", timeout_seconds=90)

    logger.info("=== Provisioning Completed Successfully for PR #%d ===", pr_number)


def _teardown_preview_environment_sync(pr_number: int) -> None:
    """Synchronous core teardown logic executing in worker thread."""
    namespace = f"pr-{pr_number}"
    core_api = client.CoreV1Api()
    logger.info("=== Starting Teardown for PR #%d (Namespace: %s) ===", pr_number, namespace)

    try:
        delete_options = client.V1DeleteOptions(propagation_policy="Foreground")
        core_api.delete_namespace(name=namespace, body=delete_options)
        logger.info("Initiated deletion for Namespace '%s' with Foreground propagation.", namespace)
    except ApiException as e:
        if e.status == 404:
            logger.info("Namespace '%s' already deleted or does not exist (404).", namespace)
        else:
            logger.error("Failed to delete namespace '%s': %s", namespace, e)
            raise

    logger.info("=== Teardown Completed for PR #%d ===", pr_number)


# --- Asynchronous Non-Blocking Public API ---

async def provision_preview_environment(pr_number: int, image_tag: str = "latest") -> None:
    """Asynchronous non-blocking wrapper to provision a preview environment."""
    await asyncio.to_thread(_provision_preview_environment_sync, pr_number, image_tag)


async def teardown_preview_environment(pr_number: int) -> None:
    """Asynchronous non-blocking wrapper to teardown a preview environment."""
    await asyncio.to_thread(_teardown_preview_environment_sync, pr_number)


async def wait_for_deployment_ready(namespace: str, deployment_name: str, timeout_seconds: int = 90) -> bool:
    """Asynchronous non-blocking wrapper to check deployment status."""
    return await asyncio.to_thread(_wait_for_deployment_ready_sync, namespace, deployment_name, timeout_seconds)
