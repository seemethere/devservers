"""
Kopf handlers for Build custom resources.
"""

import logging
from typing import Any, Dict, Optional

import kopf

from .validation import validate_build_spec
from .reconciler import reconcile_build
from ...crds.const import CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILD


@kopf.on.create(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILD)
async def create_build(
    spec: Dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    patch: Dict[str, Any],
    status: Optional[Dict[str, Any]],
    **kwargs: Any,
) -> None:
    """
    Handle the creation of a Build resource.

    This handler:
    1. Validates the build spec
    2. Queues the build for processing
    3. Updates the status to 'Queued'
    """
    logger.info(f"Processing new Build '{namespace}/{name}'...")

    # Validate spec
    validate_build_spec(spec, logger)

    # Reconcile (queue the build)
    new_status = await reconcile_build(name, namespace, spec, status, logger)
    patch["status"] = new_status


@kopf.on.update(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILD)
async def update_build(
    spec: Dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    patch: Dict[str, Any],
    status: Optional[Dict[str, Any]],
    **kwargs: Any,
) -> None:
    """
    Handle updates to a Build resource.

    Builds are generally immutable once queued. Updates to the spec are ignored
    for builds that are already in progress.
    """
    current_phase = (status or {}).get("phase", "Pending")

    if current_phase in ["Building", "Succeeded", "Failed", "Cancelled"]:
        logger.info(
            f"Build '{namespace}/{name}' is in phase '{current_phase}', "
            "ignoring spec updates"
        )
        return

    # Re-validate and potentially re-queue if still pending
    if current_phase == "Pending":
        validate_build_spec(spec, logger)
        new_status = await reconcile_build(name, namespace, spec, status, logger)
        patch["status"] = new_status


@kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILD)
async def delete_build(
    name: str,
    namespace: str,
    logger: logging.Logger,
    status: Optional[Dict[str, Any]],
    **kwargs: Any,
) -> None:
    """
    Handle the deletion of a Build resource.

    If the build is in progress, we could potentially cancel it here.
    For now, we just log the deletion.
    """
    current_phase = (status or {}).get("phase", "Unknown")
    logger.info(
        f"Build '{namespace}/{name}' (phase: {current_phase}) is being deleted."
    )

    # TODO: If building, could send cancellation signal to worker
    # This would require additional infrastructure (e.g., Redis for signaling)


@kopf.on.field(CRD_GROUP, CRD_VERSION, CRD_PLURAL_BUILD, field="status.phase")
async def on_phase_change(
    name: str,
    namespace: str,
    old: Optional[str],
    new: Optional[str],
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    """
    React to Build phase changes.

    This can be used to trigger notifications, metrics, etc.
    """
    if old != new:
        logger.info(
            f"Build '{namespace}/{name}' phase changed: {old or 'None'} -> {new}"
        )

        # Could emit Kubernetes events here
        # Could update metrics here
        # Could send notifications here
