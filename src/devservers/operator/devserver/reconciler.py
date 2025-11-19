"""
Kubernetes resource reconciliation for DevServer resources.
"""
import asyncio
import logging
import os
from typing import Any, Dict

import kopf
from kubernetes import client

from .resources.configmap import build_config_configmap
from .resources.deployment import build_deployment


class DevServerReconciler:
    """
    Handles the creation and management of Kubernetes resources for DevServer.
    """

    def __init__(
        self,
        name: str,
        namespace: str,
        spec: Dict[str, Any],
        flavor: Dict[str, Any],
        default_devserver_image: str,
        static_dependencies_image: str,
    ):
        self.name = name
        self.namespace = namespace
        self.spec = spec
        self.flavor = flavor
        self.default_devserver_image = default_devserver_image
        self.static_dependencies_image = static_dependencies_image
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def build_resources(self) -> Dict[str, Any]:
        """
        Build all Kubernetes resources required for the DevServer.

        Returns:
            Dictionary of resource objects keyed by resource type.
        """
        # Build Deployment
        deployment = build_deployment(
            self.name,
            self.namespace,
            self.spec,
            self.flavor,
            self.default_devserver_image,
            self.static_dependencies_image,
        )

        # Build ConfigMaps
        script_path = os.path.join(os.path.dirname(__file__), "resources", "startup.sh")
        with open(script_path, "r") as f:
            startup_script_content = f.read()

        script_path = os.path.join(os.path.dirname(__file__), "resources", "user_login.sh")
        with open(script_path, "r") as f:
            user_login_script_content = f.read()

        script_path = os.path.join(os.path.dirname(__file__), "resources", "sshd_config")
        with open(script_path, "r") as f:
            sshd_config_content = f.read()

        config_configmap = build_config_configmap(
            self.name,
            self.namespace,
            startup_script_content,
            user_login_script_content,
            sshd_config_content,
        )

        return {
            "deployment": deployment,
            "config_configmap": config_configmap,
        }

    def adopt_resources(self, resources: Dict[str, Any]) -> None:
        """
        Set owner references on all resources using kopf.adopt.

        Args:
            resources: Dictionary of resource objects from build_resources()
        """
        for resource in resources.values():
            kopf.adopt(resource)

    async def reconcile_resources(self, resources: Dict[str, Any], logger: logging.Logger) -> None:
        """
        Create or update all Kubernetes resources.

        Args:
            resources: Dictionary of resource objects from build_resources()
            logger: Logger instance
        """
        # Reconcile ConfigMaps
        await self._reconcile_configmap(resources["config_configmap"], logger)

        # Note: SSH access is via kubectl port-forward to the pod, no Service needed

        # Reconcile Deployment
        await self._reconcile_deployment(resources["deployment"], logger)

    async def _reconcile_configmap(self, configmap: Dict[str, Any], logger: logging.Logger) -> None:
        """Create or update a ConfigMap."""
        name = configmap["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespaced_config_map, name=name, namespace=self.namespace
            )
            # It exists, so we patch it
            await asyncio.to_thread(
                self.core_v1.patch_namespaced_config_map,
                name=name,
                namespace=self.namespace,
                body=configmap,
            )
            logger.info(f"ConfigMap '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                # It does not exist, so we create it
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_config_map,
                    namespace=self.namespace,
                    body=configmap,
                )
                logger.info(f"ConfigMap '{name}' created.")
            else:
                raise

    async def _reconcile_deployment(self, deployment: Dict[str, Any], logger: logging.Logger) -> None:
        """Create or update a Deployment."""
        name = deployment["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment, name=name, namespace=self.namespace
            )
            # It exists, so we patch it
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment,
                name=name,
                namespace=self.namespace,
                body=deployment,
            )
            logger.info(f"Deployment '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                # It does not exist, so we create it
                await asyncio.to_thread(
                    self.apps_v1.create_namespaced_deployment,
                    body=deployment,
                    namespace=self.namespace,
                )
                logger.info(f"Deployment '{name}' created for DevServer.")
            else:
                raise


async def reconcile_devserver(
    name: str,
    namespace: str,
    spec: Dict[str, Any],
    flavor: Dict[str, Any],
    logger: logging.Logger,
    default_devserver_image: str,
    static_dependencies_image: str,
) -> str:
    """
    Reconcile all Kubernetes resources for a DevServer.

    Args:
        name: Name of the DevServer
        namespace: Namespace of the DevServer
        spec: DevServer spec
        flavor: DevServerFlavor object
        logger: Logger instance

    Returns:
        Status message indicating success
    """
    reconciler = DevServerReconciler(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image,
        static_dependencies_image,
    )

    # Build all resources
    resources = reconciler.build_resources()

    # Set owner references
    reconciler.adopt_resources(resources)

    # Create or update resources
    await reconciler.reconcile_resources(resources, logger)

    return f"Deployment '{name}' reconciled successfully."
