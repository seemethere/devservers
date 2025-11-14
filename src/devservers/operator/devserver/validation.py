"""
Validation and normalization for DevServer resources.
"""
import logging
from datetime import timedelta
from typing import Any, Dict, List

import kopf

from devservers.utils.time import parse_duration


def validate_and_normalize_ttl(
    ttl_str: str | None,
    logger: logging.Logger,
) -> None:
    """
    Validate the TTL string and normalize it to a consistent format.
    Raises a PermanentError if the TTL is invalid.
    """
    if not ttl_str:
        return

    try:
        duration = parse_duration(ttl_str)
        if duration <= timedelta(minutes=0):
            raise ValueError("TTL must be a positive duration.")
        if duration > timedelta(days=7):
            raise ValueError("TTL cannot exceed 7 days.")

    except ValueError as e:
        logger.error(f"Invalid timeToLive value '{ttl_str}': {e}")
        raise kopf.PermanentError(f"Invalid timeToLive: {e}")


def validate_volumes(
    volumes: List[Dict[str, Any]] | None,
    logger: logging.Logger,
) -> None:
    """
    Validate volume configuration for duplicate mount paths.
    Raises a PermanentError if validation fails.
    """
    if not volumes:
        return

    mount_paths = []
    for idx, volume in enumerate(volumes):
        if not isinstance(volume, dict):
            logger.error(f"Volume at index {idx} is not a dictionary.")
            raise kopf.PermanentError(f"Volume at index {idx} must be a dictionary.")

        mount_path = volume.get("mountPath")
        if not mount_path:
            logger.error(f"Volume at index {idx} is missing required field 'mountPath'.")
            raise kopf.PermanentError(f"Volume at index {idx} is missing required field 'mountPath'.")

        if mount_path in mount_paths:
            logger.error(f"Duplicate mount path '{mount_path}' found in volumes.")
            raise kopf.PermanentError(f"Duplicate mount path '{mount_path}' is not allowed. Each volume must have a unique mount path.")

        mount_paths.append(mount_path)
