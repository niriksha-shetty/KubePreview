import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import yaml

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from config import settings

logger = logging.getLogger("kubepreview.k8s_manager")

_k8s_initialized = False


def init_k8s_client() -> bool:
    """Initialize Kubernetes SDK client configuration using a prioritized resolution strategy:
    1. Inspect KUBECONFIG environment variable path if set and file exists.
    2. Fall back to standard local kubeconfig (~/.kube/config).
    3. Fall back to project workspace kubeconfig files (e.g. kind-kubeconfig.yaml).
    4. Fall back to in-cluster configuration (ServiceAccount tokens).
    Returns True if initialized successfully, False otherwise.
    """
    global _k8s_initialized

    kubeconfig_env = os.getenv("KUBECONFIG")
    errors = []

    # 1. First check if KUBECONFIG environment variable is set and points to a valid file
    if kubeconfig_env:
        try:
            kubeconfig_path = Path(kubeconfig_env).expanduser().resolve()
            if kubeconfig_path.is_file():
                logger.info("Loading Kubernetes configuration from KUBECONFIG env path: %s", kubeconfig_path)
                config.load_kube_config(config_file=str(kubeconfig_path))
                _k8s_initialized = True
                logger.info("Successfully loaded Kubernetes configuration from KUBECONFIG path: %s", kubeconfig_path)
                return True
            else:
                logger.warning("KUBECONFIG env var is set to '%s', but file does not exist at resolved path: %s", kubeconfig_env, kubeconfig_path)
                errors.append(f"KUBECONFIG ({kubeconfig_env}): file does not exist at {kubeconfig_path}")
        except Exception as err:
            logger.warning("Failed to load kubeconfig from KUBECONFIG path '%s': %s", kubeconfig_env, err)
            errors.append(f"KUBECONFIG ({kubeconfig_env}): {err}")

    # 2. Fall back to default local kubeconfig (~/.kube/config)
    try:
        default_path = Path.home() / ".kube" / "config"
        if default_path.is_file():
            logger.info("Loading local default kubeconfig from: %s", default_path)
            config.load_kube_config(config_file=str(default_path))
            _k8s_initialized = True
            logger.info("Successfully loaded local default kubeconfig from: %s", default_path)
            return True
    except Exception as err:
        logger.warning("Could not load local default kubeconfig (~/.kube/config): %s", err)
        errors.append(f"Default kubeconfig (~/.kube/config): {err}")

    # 3. Fall back to project workspace kubeconfig files (e.g. kind-kubeconfig.yaml)
    workspace_dir = Path(__file__).resolve().parent.parent
    possible_project_configs = [
        workspace_dir / "kind-kubeconfig.yaml",
        workspace_dir / "kubeconfig.yaml",
        Path.cwd() / "kind-kubeconfig.yaml",
        Path.cwd() / "kubeconfig.yaml",
    ]
    for project_config in possible_project_configs:
        if project_config.is_file():
            try:
                logger.info("Loading project workspace kubeconfig from: %s", project_config)
                config.load_kube_config(config_file=str(project_config))
                _k8s_initialized = True
                logger.info("Successfully loaded project workspace kubeconfig from: %s", project_config)
                return True
            except Exception as err:
                logger.warning("Failed loading project workspace kubeconfig at %s: %s", project_config, err)
                errors.append(f"Project kubeconfig ({project_config}): {err}")

    # 4. Attempt in-cluster configuration fallback
    try:
        logger.info("Attempting in-cluster Kubernetes configuration fallback...")
        config.load_incluster_config()
        _k8s_initialized = True
        logger.info("Successfully loaded in-cluster Kubernetes configuration.")
        return True
    except Exception as err:
        logger.warning("Could not load in-cluster configuration: %s", err)
        errors.append(f"In-cluster config: {err}")

    # If all resolution sources fail, mark uninitialized and return False (allowing FastAPI to start)
    _k8s_initialized = False
    error_summary = "; ".join(errors)
    logger.warning(
        "Could not load Kubernetes configuration on startup (%s). "
        "Control plane started in standalone mode. K8s operations will auto-retry configuration loading when triggered.",
        error_summary,
    )
    return False


def _ensure_namespace_annotations_sync(
    namespace: str,
    pr_number: int,
    repo_full_name: str = "acme/sample-app",
    created_at_override: Optional[str] = None,
) -> None:
    """Ensure Kubernetes namespace metadata contains required KubePreview annotations and labels."""
    core_api = client.CoreV1Api()
    try:
        ns = core_api.read_namespace(name=namespace)
        metadata = ns.metadata or client.V1ObjectMeta()
        annotations = metadata.annotations or {}
        labels = metadata.labels or {}

        # Preserve existing created-at if present, unless override specified
        if created_at_override:
            annotations["kubepreview.io/created-at"] = created_at_override
        elif "kubepreview.io/created-at" not in annotations:
            annotations["kubepreview.io/created-at"] = datetime.now(timezone.utc).isoformat()

        annotations["kubepreview.io/ttl-hours"] = str(settings.TTL_HOURS)
        annotations["kubepreview.io/repo-full-name"] = repo_full_name

        labels["managed-by"] = "kubepreview"
        labels["pr-number"] = str(pr_number)

        patch_body = {
            "metadata": {
                "annotations": annotations,
                "labels": labels,
            }
        }
        core_api.patch_namespace(name=namespace, body=patch_body)
        logger.info("Stamped namespace '%s' metadata annotations and labels.", namespace)
    except ApiException as e:
        logger.error("Failed to update namespace metadata annotations for '%s': %s", namespace, e)


def _apply_resource_sync(doc: Dict[str, Any], namespace: str, repo_full_name: str = "acme/sample-app") -> None:
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

    # Ensure metadata dictionaries exist
    if "annotations" not in doc["metadata"] or doc["metadata"]["annotations"] is None:
        doc["metadata"]["annotations"] = {}
    if "labels" not in doc["metadata"] or doc["metadata"]["labels"] is None:
        doc["metadata"]["labels"] = {}

    if kind == "Namespace":
        doc["metadata"]["labels"]["managed-by"] = "kubepreview"
        doc["metadata"]["labels"]["pr-number"] = name.replace("pr-", "")
        if "kubepreview.io/created-at" not in doc["metadata"]["annotations"]:
            doc["metadata"]["annotations"]["kubepreview.io/created-at"] = datetime.now(timezone.utc).isoformat()
        doc["metadata"]["annotations"]["kubepreview.io/ttl-hours"] = str(settings.TTL_HOURS)
        doc["metadata"]["annotations"]["kubepreview.io/repo-full-name"] = repo_full_name

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
    """Poll deployment status synchronously until ready_replicas >= replicas or timeout."""
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


def _provision_preview_environment_sync(pr_number: int, image_tag: str = "latest", repo_full_name: str = "acme/sample-app") -> None:
    """Synchronous core provisioning logic executing in worker thread."""
    namespace = f"pr-{pr_number}"
    manifests_dir = settings.MANIFESTS_DIR

    logger.info("=== Starting Provisioning for PR #%d (Namespace: %s, Image Tag: %s, Repo: %s) ===", pr_number, namespace, image_tag, repo_full_name)

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

        replaced_text = raw_text.replace("__PR_NUMBER__", str(pr_number))
        replaced_text = replaced_text.replace("__NAMESPACE__", namespace)
        replaced_text = replaced_text.replace("__IMAGE_TAG__", image_tag)

        if settings.BASE_DOMAIN != "127.0.0.1.nip.io":
            replaced_text = replaced_text.replace("127.0.0.1.nip.io", settings.BASE_DOMAIN)

        docs = list(yaml.safe_load_all(replaced_text))
        for doc in docs:
            if doc:
                _apply_resource_sync(doc, namespace, repo_full_name)

    # Ensure annotations are stamped on namespace
    _ensure_namespace_annotations_sync(namespace, pr_number, repo_full_name)

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


def _list_managed_namespaces_sync() -> List[Dict[str, Any]]:
    """Query Kubernetes API for namespaces labeled managed-by=kubepreview."""
    if not _k8s_initialized:
        return []

    core_api = client.CoreV1Api()
    try:
        ns_list = core_api.list_namespace(label_selector="managed-by=kubepreview")
        result = []
        for ns in ns_list.items:
            metadata = ns.metadata
            labels = metadata.labels or {}
            annotations = metadata.annotations or {}

            pr_str = labels.get("pr-number")
            if not pr_str and metadata.name.startswith("pr-"):
                pr_str = metadata.name.replace("pr-", "")

            try:
                pr_num = int(pr_str)
            except (TypeError, ValueError):
                continue

            result.append({
                "name": metadata.name,
                "pr_number": pr_num,
                "created_at": annotations.get("kubepreview.io/created-at"),
                "ttl_hours": float(annotations.get("kubepreview.io/ttl-hours", settings.TTL_HOURS)),
                "repo_full_name": annotations.get("kubepreview.io/repo-full-name", "acme/sample-app"),
                "creation_timestamp": metadata.creation_timestamp,
            })
        return result
    except ApiException as e:
        logger.error("Failed to list managed Kubernetes namespaces: %s", e)
        return []


def _get_active_previews_telemetry_sync() -> List[Dict[str, Any]]:
    """Build telemetry data array for all active preview environments."""
    if not _k8s_initialized:
        return []

    namespaces_info = _list_managed_namespaces_sync()
    apps_api = client.AppsV1Api()
    now_utc = datetime.now(timezone.utc)
    telemetry = []

    for info in namespaces_info:
        pr_number = info["pr_number"]
        namespace_name = info["name"]
        ttl_hours = info["ttl_hours"]

        # Parse creation datetime
        created_at_str = info.get("created_at")
        created_dt: Optional[datetime] = None

        if created_at_str:
            try:
                clean_str = created_at_str.replace("Z", "+00:00")
                created_dt = datetime.fromisoformat(clean_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        if not created_dt and info.get("creation_timestamp"):
            ts = info["creation_timestamp"]
            if isinstance(ts, datetime):
                created_dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

        if not created_dt:
            created_dt = now_utc
            created_at_str = now_utc.isoformat()
        else:
            created_at_str = created_dt.isoformat()

        elapsed_seconds = (now_utc - created_dt).total_seconds()
        total_ttl_seconds = ttl_hours * 3600.0
        remaining_seconds = max(0.0, total_ttl_seconds - elapsed_seconds)
        remaining_minutes = int(remaining_seconds / 60.0)

        # Evaluate deployment status in namespace
        status_str = "Ready"
        try:
            deployments = apps_api.list_namespaced_deployment(namespace=namespace_name)
            if not deployments.items:
                status_str = "Provisioning"
            else:
                for dep in deployments.items:
                    replicas = dep.status.replicas or 1
                    ready = dep.status.ready_replicas or 0
                    if ready < replicas:
                        status_str = "Provisioning"
                        break
        except ApiException:
            status_str = "Provisioning"

        preview_url = f"http://pr-{pr_number}.{settings.BASE_DOMAIN}"

        telemetry.append({
            "pr_number": pr_number,
            "namespace": namespace_name,
            "created_at": created_at_str,
            "ttl_hours": ttl_hours,
            "remaining_minutes": remaining_minutes,
            "status": status_str,
            "preview_url": preview_url,
        })

    return telemetry


# --- Asynchronous Non-Blocking Public API ---

async def provision_preview_environment(
    pr_number: int,
    image_tag: str = "latest",
    repo_full_name: str = "acme/sample-app",
) -> None:
    """Asynchronous non-blocking wrapper to provision a preview environment."""
    await asyncio.to_thread(_provision_preview_environment_sync, pr_number, image_tag, repo_full_name)


async def teardown_preview_environment(pr_number: int) -> None:
    """Asynchronous non-blocking wrapper to teardown a preview environment."""
    await asyncio.to_thread(_teardown_preview_environment_sync, pr_number)


async def wait_for_deployment_ready(namespace: str, deployment_name: str, timeout_seconds: int = 90) -> bool:
    """Asynchronous non-blocking wrapper to check deployment status."""
    return await asyncio.to_thread(_wait_for_deployment_ready_sync, namespace, deployment_name, timeout_seconds)


async def list_managed_namespaces() -> List[Dict[str, Any]]:
    """Asynchronous non-blocking wrapper to list managed namespaces."""
    return await asyncio.to_thread(_list_managed_namespaces_sync)


async def get_active_previews_telemetry() -> List[Dict[str, Any]]:
    """Asynchronous non-blocking wrapper to get telemetry for active previews."""
    return await asyncio.to_thread(_get_active_previews_telemetry_sync)
