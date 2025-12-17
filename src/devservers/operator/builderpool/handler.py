"""
Kopf handlers for BuilderPool custom resources.
"""

import logging
from typing import Any, Dict

import kopf

from .reconciler import reconcile_builderpool, delete_builderpool_resources
from ...crds.const import CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILDERPOOL


@kopf.on.create(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILDERPOOL)
@kopf.on.update(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILDERPOOL)
async def create_or_update_builderpool(
    spec: Dict[str, Any],
    name: str,
    logger: logging.Logger,
    patch: Dict[str, Any],
    **kwargs: Any,
) -> None:
    """
    Handle the creation or update of a BuilderPool resource.

    This handler orchestrates:
    1. BuildKit daemon StatefulSet creation
    2. Service creation for internal access
    3. ConfigMap creation for buildkitd configuration
    4. Status updates
    """
    logger.info(f"Reconciling BuilderPool '{name}'...")

    # Reconcile all Kubernetes resources
    status = await reconcile_builderpool(name, spec, logger)

    # Update status
    patch["status"] = status


@kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILDERPOOL)
async def delete_builderpool(
    name: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    """
    Handle the deletion of a BuilderPool resource.

    Cleans up all associated resources (StatefulSet, Services, ConfigMap).
    """
    logger.info(f"BuilderPool '{name}' is being deleted.")
    await delete_builderpool_resources(name, logger)
    logger.info(f"BuilderPool '{name}' resources cleaned up.")


@kopf.timer(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILDERPOOL, interval=30.0)
async def monitor_builderpool(
    spec: Dict[str, Any],
    name: str,
    logger: logging.Logger,
    patch: Dict[str, Any],
    **kwargs: Any,
) -> None:
    """
    Periodically monitor the BuilderPool status.

    Updates the status based on the current state of the StatefulSet.
    """
    from .reconciler import BuilderPoolReconciler

    reconciler = BuilderPoolReconciler(name, spec)
    status = await reconciler.get_status(logger)
    patch["status"] = status
