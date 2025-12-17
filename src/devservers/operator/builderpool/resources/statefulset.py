"""BuildKit daemon StatefulSet resource builder."""

from typing import Any, Dict, List, Optional


def build_statefulset(
    name: str,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a StatefulSet for the BuildKit daemon.

    Args:
        name: Name of the BuilderPool
        spec: BuilderPool spec

    Returns:
        StatefulSet resource dictionary
    """
    replicas = spec.get("replicas", 1)
    image = spec.get("image", "moby/buildkit:latest")
    rootless = spec.get("rootless", True)
    resources = spec.get("resources", {})
    node_selector = spec.get("nodeSelector")
    tolerations = spec.get("tolerations")
    cache_config = spec.get("cache", {})
    gc_policy = spec.get("gcPolicy", {})
    registry_secrets = spec.get("registrySecrets", [])

    # Build buildkitd.toml config
    buildkitd_config = _build_buildkitd_config(cache_config, gc_policy)

    # Build container args
    container_args = ["--addr", "tcp://0.0.0.0:1234"]
    if rootless:
        container_args.extend(["--oci-worker-no-process-sandbox"])

    # Build security context
    security_context: Dict[str, Any] = {}
    if rootless:
        security_context = {
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "seccompProfile": {"type": "Unconfined"},
        }
    else:
        security_context = {"privileged": True}

    # Build volumes and volume mounts
    volumes: List[Dict[str, Any]] = [
        {
            "name": "buildkitd-config",
            "configMap": {"name": f"{name}-buildkitd-config"},
        },
    ]
    volume_mounts: List[Dict[str, Any]] = [
        {
            "name": "buildkitd-config",
            "mountPath": "/etc/buildkit/buildkitd.toml",
            "subPath": "buildkitd.toml",
            "readOnly": True,
        },
        {
            "name": "buildkit-cache",
            "mountPath": "/var/lib/buildkit",
        },
    ]

    # Add registry secrets if specified
    if registry_secrets:
        volumes.append({
            "name": "docker-config",
            "secret": {
                "secretName": registry_secrets[0],  # Use first secret for now
                "items": [{"key": ".dockerconfigjson", "path": "config.json"}],
            },
        })
        volume_mounts.append({
            "name": "docker-config",
            "mountPath": "/root/.docker",
            "readOnly": True,
        })

    pod_spec: Dict[str, Any] = {
        "containers": [
            {
                "name": "buildkitd",
                "image": image,
                "args": container_args,
                "ports": [
                    {"name": "grpc", "containerPort": 1234, "protocol": "TCP"},
                ],
                "securityContext": security_context,
                "volumeMounts": volume_mounts,
                "readinessProbe": {
                    "exec": {
                        "command": ["buildctl", "debug", "workers"],
                    },
                    "initialDelaySeconds": 5,
                    "periodSeconds": 10,
                },
                "livenessProbe": {
                    "exec": {
                        "command": ["buildctl", "debug", "workers"],
                    },
                    "initialDelaySeconds": 15,
                    "periodSeconds": 30,
                },
            }
        ],
        "volumes": volumes,
    }

    # Add resources if specified
    if resources:
        pod_spec["containers"][0]["resources"] = resources

    # Add node selector if specified
    if node_selector:
        pod_spec["nodeSelector"] = node_selector

    # Add tolerations if specified
    if tolerations:
        pod_spec["tolerations"] = tolerations

    # Build VolumeClaimTemplate for cache storage
    volume_claim_templates = [
        {
            "metadata": {"name": "buildkit-cache"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {
                    "requests": {
                        "storage": gc_policy.get("keepBytes", "50Gi"),
                    }
                },
            },
        }
    ]

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
        },
        "spec": {
            "serviceName": f"{name}-headless",
            "replicas": replicas,
            "selector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "buildkit",
                    "app.kubernetes.io/instance": name,
                },
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "buildkit",
                        "app.kubernetes.io/instance": name,
                    },
                },
                "spec": pod_spec,
            },
            "volumeClaimTemplates": volume_claim_templates,
        },
    }


def _build_buildkitd_config(
    cache_config: Dict[str, Any],
    gc_policy: Dict[str, Any],
) -> str:
    """Build buildkitd.toml configuration."""
    config_lines = [
        "[worker.oci]",
        "  gc = true",
    ]

    # Add GC policy
    keep_bytes = gc_policy.get("keepBytes", "50Gi")
    keep_duration = gc_policy.get("keepDuration", "168h")

    # Convert keepBytes to bytes for buildkit config
    config_lines.extend([
        "",
        "[[worker.oci.gcpolicy]]",
        f'  keepDuration = "{keep_duration}"',
        "  keepBytes = 53687091200",  # 50Gi default
        '  filters = ["type==source.local", "type==exec.cachemount", "type==source.git.checkout"]',
        "",
        "[[worker.oci.gcpolicy]]",
        "  all = true",
        f'  keepDuration = "{keep_duration}"',
    ])

    return "\n".join(config_lines)


def build_buildkitd_configmap(
    name: str,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a ConfigMap containing buildkitd.toml.

    Args:
        name: Name of the BuilderPool
        spec: BuilderPool spec

    Returns:
        ConfigMap resource dictionary
    """
    cache_config = spec.get("cache", {})
    gc_policy = spec.get("gcPolicy", {})
    config_content = _build_buildkitd_config(cache_config, gc_policy)

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{name}-buildkitd-config",
        },
        "data": {
            "buildkitd.toml": config_content,
        },
    }
