"""
Kubernetes resource reconciliation for BuilderPool resources.
"""

import asyncio
import logging
from typing import Any, Dict

import kopf
from kubernetes import client

from .resources.statefulset import build_statefulset, build_buildkitd_configmap
from .resources.service import build_headless_service, build_service


class BuilderPoolReconciler:
    """
    Handles the creation and management of Kubernetes resources for BuilderPool.
    """

    def __init__(self, name: str, spec: Dict[str, Any]):
        self.name = name
        self.spec = spec
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        # BuilderPool is cluster-scoped, resources go in a dedicated namespace
        self.namespace = "buildkit-system"

    def build_resources(self) -> Dict[str, Any]:
        """
        Build all Kubernetes resources required for the BuilderPool.

        Returns:
            Dictionary of resource objects keyed by resource type.
        """
        return {
            "configmap": build_buildkitd_configmap(self.name, self.spec),
            "statefulset": build_statefulset(self.name, self.spec),
            "headless_service": build_headless_service(self.name),
            "service": build_service(self.name),
        }

    def adopt_resources(self, resources: Dict[str, Any]) -> None:
        """
        Set owner references on all resources using kopf.adopt.

        Note: Since BuilderPool is cluster-scoped, we don't set owner references
        on namespaced resources. We use labels for tracking instead.

        Args:
            resources: Dictionary of resource objects from build_resources()
        """
        # Add labels to track ownership since we can't use owner references
        # across cluster/namespace boundary
        for resource in resources.values():
            metadata = resource.setdefault("metadata", {})
            labels = metadata.setdefault("labels", {})
            labels["devserver.io/builderpool"] = self.name

    async def reconcile_resources(
        self, resources: Dict[str, Any], logger: logging.Logger
    ) -> None:
        """
        Create or update all Kubernetes resources.

        Args:
            resources: Dictionary of resource objects from build_resources()
            logger: Logger instance
        """
        # Ensure namespace exists
        await self._ensure_namespace(logger)

        # Reconcile ConfigMap first (needed by StatefulSet)
        await self._reconcile_configmap(resources["configmap"], logger)

        # Reconcile Services
        await self._reconcile_service(resources["headless_service"], logger)
        await self._reconcile_service(resources["service"], logger)

        # Reconcile StatefulSet
        await self._reconcile_statefulset(resources["statefulset"], logger)

    async def _ensure_namespace(self, logger: logging.Logger) -> None:
        """Ensure the buildkit-system namespace exists."""
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespace, name=self.namespace
            )
        except client.ApiException as e:
            if e.status == 404:
                namespace = {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": self.namespace,
                        "labels": {"app.kubernetes.io/managed-by": "devserver-operator"},
                    },
                }
                await asyncio.to_thread(self.core_v1.create_namespace, body=namespace)
                logger.info(f"Namespace '{self.namespace}' created.")
            else:
                raise

    async def _reconcile_configmap(
        self, configmap: Dict[str, Any], logger: logging.Logger
    ) -> None:
        """Create or update a ConfigMap."""
        name = configmap["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespaced_config_map,
                name=name,
                namespace=self.namespace,
            )
            await asyncio.to_thread(
                self.core_v1.patch_namespaced_config_map,
                name=name,
                namespace=self.namespace,
                body=configmap,
            )
            logger.info(f"ConfigMap '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                configmap["metadata"]["namespace"] = self.namespace
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_config_map,
                    namespace=self.namespace,
                    body=configmap,
                )
                logger.info(f"ConfigMap '{name}' created.")
            else:
                raise

    async def _reconcile_service(
        self, service: Dict[str, Any], logger: logging.Logger
    ) -> None:
        """Create or update a Service."""
        name = service["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespaced_service,
                name=name,
                namespace=self.namespace,
            )
            await asyncio.to_thread(
                self.core_v1.patch_namespaced_service,
                name=name,
                namespace=self.namespace,
                body=service,
            )
            logger.info(f"Service '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                service["metadata"]["namespace"] = self.namespace
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_service,
                    namespace=self.namespace,
                    body=service,
                )
                logger.info(f"Service '{name}' created.")
            else:
                raise

    async def _reconcile_statefulset(
        self, statefulset: Dict[str, Any], logger: logging.Logger
    ) -> None:
        """Create or update a StatefulSet."""
        name = statefulset["metadata"]["name"]
        try:
            await asyncio.to_thread(
                self.apps_v1.read_namespaced_stateful_set,
                name=name,
                namespace=self.namespace,
            )
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_stateful_set,
                name=name,
                namespace=self.namespace,
                body=statefulset,
            )
            logger.info(f"StatefulSet '{name}' patched.")
        except client.ApiException as e:
            if e.status == 404:
                statefulset["metadata"]["namespace"] = self.namespace
                await asyncio.to_thread(
                    self.apps_v1.create_namespaced_stateful_set,
                    namespace=self.namespace,
                    body=statefulset,
                )
                logger.info(f"StatefulSet '{name}' created.")
            else:
                raise

    async def get_status(self, logger: logging.Logger) -> Dict[str, Any]:
        """
        Get the current status of the BuilderPool resources.

        Returns:
            Status dictionary with phase, readyReplicas, and endpoint.
        """
        try:
            statefulset = await asyncio.to_thread(
                self.apps_v1.read_namespaced_stateful_set,
                name=self.name,
                namespace=self.namespace,
            )

            ready_replicas = statefulset.status.ready_replicas or 0
            desired_replicas = statefulset.spec.replicas or 1

            if ready_replicas == desired_replicas:
                phase = "Ready"
                message = f"All {ready_replicas} replicas are ready"
            elif ready_replicas > 0:
                phase = "Degraded"
                message = f"{ready_replicas}/{desired_replicas} replicas ready"
            else:
                phase = "Pending"
                message = "Waiting for replicas to become ready"

            return {
                "phase": phase,
                "readyReplicas": ready_replicas,
                "message": message,
                "endpoint": f"{self.name}.{self.namespace}.svc.cluster.local:1234",
            }
        except client.ApiException as e:
            if e.status == 404:
                return {
                    "phase": "Pending",
                    "readyReplicas": 0,
                    "message": "StatefulSet not yet created",
                }
            raise


async def reconcile_builderpool(
    name: str,
    spec: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Reconcile all Kubernetes resources for a BuilderPool.

    Args:
        name: Name of the BuilderPool
        spec: BuilderPool spec
        logger: Logger instance

    Returns:
        Status dictionary
    """
    reconciler = BuilderPoolReconciler(name, spec)

    # Build all resources
    resources = reconciler.build_resources()

    # Add labels for tracking
    reconciler.adopt_resources(resources)

    # Create or update resources
    await reconciler.reconcile_resources(resources, logger)

    # Get current status
    status = await reconciler.get_status(logger)

    return status


async def delete_builderpool_resources(
    name: str,
    logger: logging.Logger,
) -> None:
    """
    Delete all Kubernetes resources for a BuilderPool.

    Args:
        name: Name of the BuilderPool
        logger: Logger instance
    """
    namespace = "buildkit-system"
    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # Delete StatefulSet
    try:
        await asyncio.to_thread(
            apps_v1.delete_namespaced_stateful_set,
            name=name,
            namespace=namespace,
        )
        logger.info(f"StatefulSet '{name}' deleted.")
    except client.ApiException as e:
        if e.status != 404:
            raise

    # Delete Services
    for service_name in [name, f"{name}-headless"]:
        try:
            await asyncio.to_thread(
                core_v1.delete_namespaced_service,
                name=service_name,
                namespace=namespace,
            )
            logger.info(f"Service '{service_name}' deleted.")
        except client.ApiException as e:
            if e.status != 404:
                raise

    # Delete ConfigMap
    try:
        await asyncio.to_thread(
            core_v1.delete_namespaced_config_map,
            name=f"{name}-buildkitd-config",
            namespace=namespace,
        )
        logger.info(f"ConfigMap '{name}-buildkitd-config' deleted.")
    except client.ApiException as e:
        if e.status != 404:
            raise
