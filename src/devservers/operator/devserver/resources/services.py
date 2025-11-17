from typing import Any, Dict


def build_headless_service(name: str, namespace: str) -> Dict[str, Any]:
    """Builds the headless Service for the Deployment."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": f"{name}-headless", "namespace": namespace},
        "spec": {
            "clusterIP": "None",
            "selector": {"app": name},
        },
    }


def build_ssh_service(name: str, namespace: str) -> Dict[str, Any]:
    """Builds the NodePort Service for SSH access."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": f"{name}-ssh", "namespace": namespace},
        "spec": {
            "type": "NodePort",
            "selector": {"app": name},
            "ports": [{"port": 22, "targetPort": 22, "protocol": "TCP"}],
        },
    }
