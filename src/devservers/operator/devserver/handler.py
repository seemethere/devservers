import asyncio
import logging
from typing import Any, Dict

import kopf
from kubernetes import client

from .validation import validate_and_normalize_ttl, validate_volumes
from .host_keys import ensure_host_keys_secret
from .reconciler import reconcile_devserver
from ..config import config as operator_config
from ...crds.const import (
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL_DEVSERVER,
    CRD_PLURAL_DEVSERVERFLAVOR,
)


@kopf.on.create(CRD_GROUP, CRD_VERSION, CRD_PLURAL_DEVSERVER)
@kopf.on.update(CRD_GROUP, CRD_VERSION, CRD_PLURAL_DEVSERVER)
async def create_or_update_devserver(
    spec: Dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    patch: Dict[str, Any],
    meta: Dict[str, Any],
    **kwargs: Any,
) -> None:
    """
    Handle the creation or update of a DevServer resource.

    This handler orchestrates:
    1. TTL validation and normalization
    2. Flavor fetching
    3. SSH host key generation
    4. Kubernetes resource creation
    5. Status updates
    """
    logger.info(f"Reconciling DevServer '{name}' in namespace '{namespace}'...")

    # Step 1: Validate TTL
    ttl_str = spec.get("lifecycle", {}).get("timeToLive")
    validate_and_normalize_ttl(ttl_str, logger)

    # Step 1b: Validate volumes
    volumes = spec.get("volumes")
    validate_volumes(volumes, logger)

    # Step 2: Get the DevServerFlavor
    custom_objects_api = client.CustomObjectsApi()
    try:
        flavor = await asyncio.to_thread(
            custom_objects_api.get_cluster_custom_object,
            group=CRD_GROUP,
            version=CRD_VERSION,
            plural=CRD_PLURAL_DEVSERVERFLAVOR,
            name=spec["flavor"],
        )
    except client.ApiException as e:
        if e.status == 404:
            logger.error(f"DevServerFlavor '{spec['flavor']}' not found.")
            raise kopf.PermanentError(f"Flavor '{spec['flavor']}' not found.")
        raise

    # Step 3: Ensure SSH host keys exist
    # Build owner reference metadata for proper garbage collection
    owner_meta = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServer",
        "name": name,
        "uid": meta["uid"],
    }
    await ensure_host_keys_secret(name, namespace, owner_meta, logger)

    # Step 4: Reconcile all Kubernetes resources
    status_message = await reconcile_devserver(
        name,
        namespace,
        spec,
        flavor,
        logger,
        default_devserver_image=operator_config.default_devserver_image,
        static_dependencies_image=operator_config.static_dependencies_image,
    )

    # Step 5: Update status
    patch["status"] = {
        "phase": "Running",
        "message": status_message,
    }

@kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL_DEVSERVER)
async def delete_devserver(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    """
    Handle the deletion of a DevServer resource.

    The Deployment and Services are owned by the DevServer via owner
    references and will be garbage collected automatically.

    Note: User-managed PVCs are NOT automatically deleted. Users must
    manage their PVC lifecycle independently.
    """
    #TODO: Make a snapshot of the container
    logger.info(f"DevServer '{name}' in namespace '{namespace}' is being deleted.")
    logger.info("Associated Deployment and Services will be garbage collected.")
