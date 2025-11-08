"""
Kubernetes resource reconciliation for DevServer resources.
"""
import asyncio
import logging
import os
from typing import Any, Dict

import kopf
from kubernetes import client

from .resources.configmap import build_configmap, build_startup_configmap, build_login_configmap
from .resources.services import build_headless_service, build_ssh_service
from .resources.statefulset import build_statefulset


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
        default_persistent_home_size: str,
    ):
        self.name = name
        self.namespace = namespace
        self.spec = spec
        self.flavor = flavor
        self.default_persistent_home_size = default_persistent_home_size
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def build_resources(self) -> Dict[str, Any]:
        """
        Build all Kubernetes resources required for the DevServer.

        Returns:
            Dictionary of resource objects keyed by resource type.
        """
        # Build services
        headless_service = build_headless_service(self.name, self.namespace)
        ssh_service = build_ssh_service(self.name, self.namespace)

        # Build StatefulSet
        statefulset = build_statefulset(
            self.name,
            self.namespace,
            self.spec,
            self.flavor,
            self.default_persistent_home_size,
        )

        # Build ConfigMaps
        sshd_configmap = build_configmap(self.name, self.namespace)

        script_path = os.path.join(os.path.dirname(__file__), "resources", "startup.sh")
        with open(script_path, "r") as f:
            startup_script_content = f.read()
        startup_script_configmap = build_startup_configmap(
            self.name, self.namespace, startup_script_content
        )
        script_path = os.path.join(os.path.dirname(__file__), "resources", "user_login.sh")
        with open(script_path, "r") as f:
            user_login_script_content = f.read()
        user_login_script_configmap = build_login_configmap(
            self.name, self.namespace, user_login_script_content
        )
        return {
            "headless_service": headless_service,
            "ssh_service": ssh_service,
            "statefulset": statefulset,
            "sshd_configmap": sshd_configmap,
            "startup_script_configmap": startup_script_configmap,
            "user_login_script_configmap": user_login_script_configmap,
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
        await self._reconcile_configmap(resources["sshd_configmap"], logger)
        await self._reconcile_configmap(resources["startup_script_configmap"], logger)
        await self._reconcile_configmap(resources["user_login_script_configmap"], logger)

        # Reconcile Services
        await self._reconcile_service(resources["headless_service"], logger)

        if self.spec.get("enableSSH", False):
            await self._reconcile_service(resources["ssh_service"], logger)
        else:
            # TODO: Handle disabling SSH on an existing DevServer by deleting the service
            pass

        # Reconcile StatefulSet
        await self._reconcile_statefulset(resources["statefulset"], logger)

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

    async def _reconcile_service(self, service: Dict[str, Any], logger: logging.Logger) -> None:
        """Create or update a Service."""
        name = service["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespaced_service, name=name, namespace=self.namespace
            )
            # It exists, so we patch it
            await asyncio.to_thread(
                self.core_v1.patch_namespaced_service,
                name=name,
                namespace=self.namespace,
                body=service,
            )
            logger.info(f"Service '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                # It does not exist, so we create it
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_service,
                    namespace=self.namespace,
                    body=service,
                )
                logger.info(f"Service '{name}' created.")
            else:
                raise

    async def _reconcile_statefulset(self, statefulset: Dict[str, Any], logger: logging.Logger) -> None:
        """Create or update a StatefulSet."""
        name = statefulset["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.apps_v1.read_namespaced_stateful_set, name=name, namespace=self.namespace
            )
            # It exists, so we patch it
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_stateful_set,
                name=name,
                namespace=self.namespace,
                body=statefulset,
            )
            logger.info(f"StatefulSet '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                # It does not exist, so we create it
                await asyncio.to_thread(
                    self.apps_v1.create_namespaced_stateful_set,
                    body=statefulset,
                    namespace=self.namespace,
                )
                logger.info(f"StatefulSet '{name}' created for DevServer.")
            else:
                raise


async def reconcile_devserver(
    name: str,
    namespace: str,
    spec: Dict[str, Any],
    flavor: Dict[str, Any],
    logger: logging.Logger,
    default_persistent_home_size: str,
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
        name, namespace, spec, flavor, default_persistent_home_size
    )

    # Build all resources
    resources = reconciler.build_resources()

    # Set owner references
    reconciler.adopt_resources(resources)

    # Create or update resources
    await reconciler.reconcile_resources(resources, logger)

    return f"StatefulSet '{name}' reconciled successfully."
