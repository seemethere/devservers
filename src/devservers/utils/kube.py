"""
Shared helpers for configuring the Kubernetes Python client.
"""
from __future__ import annotations

import logging
from typing import Dict, Literal, Optional

from kubernetes import client, config as kube_config


class KubernetesConfigurationError(RuntimeError):
    """Raised when the Kubernetes client cannot be configured."""


def configure_kube_client(
    logger: Optional[logging.Logger] = None,
    *,
    kubeconfig_path: Optional[str] = None,
) -> Literal["in-cluster", "kubeconfig"]:
    """
    Configure the Kubernetes client, preferring in-cluster credentials when available.

    Args:
        logger: Logger used to emit informational/error messages. If omitted a
            module-level logger will be used.
        kubeconfig_path: Explicit path to a kubeconfig file. When provided the
            function will only attempt to configure the client from this path.

    Returns:
        A string describing the configuration source used.

    Raises:
        KubernetesConfigurationError: If the client could not be configured.
    """

    effective_logger = logger or logging.getLogger(__name__)

    if kubeconfig_path:
        try:
            kube_config.load_kube_config(config_file=kubeconfig_path)
        except kube_config.ConfigException as exc:
            message = (
                "Could not configure Kubernetes client "
                f"from kubeconfig '{kubeconfig_path}'."
            )
            effective_logger.error("%s %s", message, exc)
            raise KubernetesConfigurationError(message) from exc

        effective_logger.info("Using kubeconfig at '%s'.", kubeconfig_path)
        return "kubeconfig"

    try:
        kube_config.load_incluster_config()
        effective_logger.info("Using in-cluster Kubernetes configuration.")
        return "in-cluster"
    except kube_config.ConfigException as incluster_error:
        try:
            kube_config.load_kube_config()
            effective_logger.info("Using local kubeconfig.")
            return "kubeconfig"
        except kube_config.ConfigException as kubeconfig_error:
            message = (
                "Unable to configure Kubernetes client using either "
                "in-cluster credentials or the default kubeconfig."
            )
            effective_logger.error(message)
            effective_logger.debug(
                "In-cluster configuration error: %s",
                incluster_error,
            )
            effective_logger.debug(
                "Default kubeconfig error: %s",
                kubeconfig_error,
            )
            raise KubernetesConfigurationError(message) from kubeconfig_error


def get_pod_by_labels(
    core_v1: client.CoreV1Api,
    namespace: str,
    labels: Dict[str, str],
) -> Optional[client.V1Pod]:
    """
    Find first pod matching label selector.

    Args:
        core_v1: Kubernetes CoreV1Api client
        namespace: Namespace to search in
        labels: Dictionary of labels to match (e.g., {"app": "my-devserver"})

    Returns:
        First matching pod, or None if no pods found
    """
    label_selector = ",".join(f"{k}={v}" for k, v in labels.items())
    pods = core_v1.list_namespaced_pod(
        namespace=namespace,
        label_selector=label_selector
    )

    if pods.items:
        return pods.items[0]
    return None
