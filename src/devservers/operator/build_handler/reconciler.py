"""
Reconciliation logic for Build resources.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kubernetes import client

from ...queue.rabbitmq import BuildQueue, BuildMessage


class BuildReconciler:
    """
    Handles the reconciliation of Build resources.

    The Build controller doesn't create Kubernetes resources directly.
    Instead, it publishes build jobs to RabbitMQ for processing by workers.
    """

    def __init__(
        self,
        name: str,
        namespace: str,
        spec: Dict[str, Any],
    ):
        self.name = name
        self.namespace = namespace
        self.spec = spec

    async def queue_build(self, logger: logging.Logger) -> Dict[str, Any]:
        """
        Queue the build for processing.

        Args:
            logger: Logger instance

        Returns:
            Status update dictionary
        """
        priority = self.spec.get("priority", "normal")

        # Create build message
        message = BuildMessage(
            build_name=self.name,
            build_namespace=self.namespace,
            spec=self.spec,
            priority=priority,
        )

        # Publish to queue
        try:
            queue = BuildQueue()
            queue.connect()
            try:
                queue.publish(message)
            finally:
                queue.close()

            logger.info(
                f"Build '{self.namespace}/{self.name}' queued with priority '{priority}'"
            )

            return {
                "phase": "Queued",
                "message": f"Build queued with priority '{priority}'",
            }
        except Exception as e:
            logger.error(f"Failed to queue build: {e}")
            return {
                "phase": "Failed",
                "message": f"Failed to queue build: {e}",
            }


async def reconcile_build(
    name: str,
    namespace: str,
    spec: Dict[str, Any],
    status: Optional[Dict[str, Any]],
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Reconcile a Build resource.

    This function is called when a Build is created or updated.
    If the build hasn't been queued yet, it will be queued.

    Args:
        name: Build name
        namespace: Build namespace
        spec: Build spec
        status: Current status (may be None)
        logger: Logger instance

    Returns:
        Updated status dictionary
    """
    current_phase = (status or {}).get("phase", "Pending")

    # Only queue if not already queued or completed
    if current_phase == "Pending":
        reconciler = BuildReconciler(name, namespace, spec)
        return await reconciler.queue_build(logger)

    # If already queued/building/completed, return current status
    return status or {"phase": "Pending", "message": "Initializing"}


async def update_build_status(
    name: str,
    namespace: str,
    phase: str,
    message: str,
    digest: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Update the status of a Build resource.

    This is called by the build worker to update status during/after builds.

    Args:
        name: Build name
        namespace: Build namespace
        phase: New phase
        message: Status message
        digest: Image digest (for successful builds)
        logger: Logger instance
    """
    custom_objects_api = client.CustomObjectsApi()

    status_body: Dict[str, Any] = {
        "status": {
            "phase": phase,
            "message": message,
        }
    }

    if phase == "Building":
        status_body["status"]["startTime"] = datetime.now(timezone.utc).isoformat()
    elif phase in ["Succeeded", "Failed", "Cancelled"]:
        status_body["status"]["completionTime"] = datetime.now(timezone.utc).isoformat()

    if digest:
        status_body["status"]["digest"] = digest

    try:
        await asyncio.to_thread(
            custom_objects_api.patch_namespaced_custom_object_status,
            group="devserver.io",
            version="v1",
            namespace=namespace,
            plural="builds",
            name=name,
            body=status_body,
        )
        if logger:
            logger.info(f"Updated Build '{namespace}/{name}' status to '{phase}'")
    except client.ApiException as e:
        if logger:
            logger.error(f"Failed to update Build status: {e}")
        raise


async def get_build(
    name: str,
    namespace: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a Build resource.

    Args:
        name: Build name
        namespace: Build namespace

    Returns:
        Build resource dictionary or None if not found
    """
    custom_objects_api = client.CustomObjectsApi()

    try:
        return await asyncio.to_thread(
            custom_objects_api.get_namespaced_custom_object,
            group="devserver.io",
            version="v1",
            namespace=namespace,
            plural="builds",
            name=name,
        )
    except client.ApiException as e:
        if e.status == 404:
            return None
        raise
