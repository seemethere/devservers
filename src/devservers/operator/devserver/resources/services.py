"""
Service resource builders for DevServer.

Note: SSH access to DevServers is handled via `kubectl port-forward` to the pod
directly, so no SSH Service is required. The deployment exposes port 22 on the
container for the SSH daemon, but clients connect through port-forwarding.
"""
from typing import Any, Dict


def build_headless_service(name: str, namespace: str) -> Dict[str, Any]:
    """Builds the headless Service for the Deployment.

    Note: This function is currently unused but kept for potential future use
    cases like distributed training service discovery.
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": f"{name}-headless", "namespace": namespace},
        "spec": {
            "clusterIP": "None",
            "selector": {"app": name},
        },
    }
