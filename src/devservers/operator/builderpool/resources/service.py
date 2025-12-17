"""BuildKit daemon Service resource builders."""

from typing import Any, Dict


def build_headless_service(name: str) -> Dict[str, Any]:
    """
    Build a headless Service for the BuildKit StatefulSet.

    This service is used for StatefulSet DNS resolution.

    Args:
        name: Name of the BuilderPool

    Returns:
        Service resource dictionary
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"{name}-headless",
        },
        "spec": {
            "clusterIP": "None",
            "selector": {
                "app.kubernetes.io/name": "buildkit",
                "app.kubernetes.io/instance": name,
            },
            "ports": [
                {
                    "name": "grpc",
                    "port": 1234,
                    "targetPort": 1234,
                    "protocol": "TCP",
                },
            ],
        },
    }


def build_service(name: str) -> Dict[str, Any]:
    """
    Build a ClusterIP Service for the BuildKit daemon.

    This service exposes the BuildKit gRPC endpoint for builds.

    Args:
        name: Name of the BuilderPool

    Returns:
        Service resource dictionary
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {
                "app.kubernetes.io/name": "buildkit",
                "app.kubernetes.io/instance": name,
            },
            "ports": [
                {
                    "name": "grpc",
                    "port": 1234,
                    "targetPort": 1234,
                    "protocol": "TCP",
                },
            ],
        },
    }
