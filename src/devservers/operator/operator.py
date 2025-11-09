"""
Kubernetes operator for DevServer custom resources.

This module contains the main Kopf handlers for the DevServer and DevServerUser CRDs.
The handlers are kept thin and delegate to specialized modules for:
- Validation (validation.py)
- Host key generation (host_keys.py)
- Resource reconciliation (reconciler.py)
- Lifecycle management (lifecycle.py)
"""
import asyncio
import logging
import os
from typing import Any

import kopf
from kubernetes import client

from ..utils.kube import KubernetesConfigurationError, configure_kube_client
from .devserver.lifecycle import cleanup_expired_devservers
from .devserverflavor.lifecycle import reconcile_flavors_periodically
# NOTE: This is what registers our operator's function with kopf so that
#       `kopf.run -m devservers.operator` can work. If you add more functions
#       to the operator, you must add them here.
# ruff: noqa: F401
from . import devserver
from . import devserveruser
from . import devserverflavor
from .config import config as operator_config
from ..crds.const import CRD_GROUP


# Kubernetes client configuration is set up lazily per handler so that unit
# tests can monkeypatch client objects without triggering a real kube-config
# load at import time.

# Constants
FINALIZER = f"finalizer.{CRD_GROUP}"

# Operator settings
EXPIRATION_INTERVAL = operator_config.expiration_interval
FLAVOR_RECONCILIATION_INTERVAL = operator_config.flavor_reconciliation_interval


@kopf.on.startup()
async def on_startup(
    settings: kopf.OperatorSettings, logger: logging.Logger, **kwargs: Any
) -> None:
    """
    Handle the startup of the operator.

    This sets operator-wide settings and starts background tasks.
    """
    try:
        configure_kube_client(logger)
    except KubernetesConfigurationError as exc:
        raise kopf.PermanentError(str(exc)) from exc

    logger.info("Operator started.")
    logger.info(
        f"Default persistent home size: {operator_config.default_persistent_home_size}"
    )

    # The default worker limit is unbounded which means you can EASILY flood
    # your API server on restart unless you limit it. 1-5 are the generally
    # accepted common sense defaults. This is intentionally conservative and
    # can be tuned based on your cluster's capabilities.
    # TODO: Make this configurable via environment variable
    settings.batching.worker_limit = operator_config.worker_limit

    # All logs by default go to the k8s event api making api server flooding
    # even more likely. Disable event posting to reduce API load.
    settings.posting.enabled = operator_config.posting_enabled

    # Start the background cleanup task for TTL expiration
    loop = asyncio.get_running_loop()
    custom_objects_api = client.CustomObjectsApi()
    loop.create_task(
        cleanup_expired_devservers(
            custom_objects_api=custom_objects_api,
            logger=logger,
            interval_seconds=EXPIRATION_INTERVAL,
        )
    )

    # Start the background task for flavor status reconciliation
    loop.create_task(
        reconcile_flavors_periodically(
            logger=logger,
            interval_seconds=FLAVOR_RECONCILIATION_INTERVAL,
        )
    )
