"""
Validation functions for Build resources.
"""

import logging
import re
from typing import Any, Dict, Optional

import kopf


def validate_build_spec(spec: Dict[str, Any], logger: logging.Logger) -> None:
    """
    Validate the Build spec.

    Raises:
        kopf.PermanentError: If validation fails
    """
    # Validate context
    context = spec.get("context", {})
    if not context:
        raise kopf.PermanentError("Build spec must include 'context'")

    has_git = "git" in context
    has_configmap = "configMap" in context

    if not has_git and not has_configmap:
        raise kopf.PermanentError(
            "Build context must specify either 'git' or 'configMap'"
        )

    if has_git and has_configmap:
        raise kopf.PermanentError(
            "Build context cannot specify both 'git' and 'configMap'"
        )

    # Validate git context
    if has_git:
        git = context["git"]
        if not git.get("url"):
            raise kopf.PermanentError("Git context must include 'url'")

        url = git["url"]
        if not (url.startswith("https://") or url.startswith("git@")):
            logger.warning(
                f"Git URL '{url}' does not start with https:// or git@. "
                "This may cause issues."
            )

    # Validate destination
    destination = spec.get("destination")
    if not destination:
        raise kopf.PermanentError("Build spec must include 'destination'")

    if not _is_valid_image_reference(destination):
        raise kopf.PermanentError(
            f"Invalid destination image reference: '{destination}'"
        )

    # Validate priority
    priority = spec.get("priority", "normal")
    if priority not in ["low", "normal", "high"]:
        raise kopf.PermanentError(
            f"Invalid priority '{priority}'. Must be one of: low, normal, high"
        )

    # Validate timeout
    timeout = spec.get("timeout", "30m")
    if not _is_valid_duration(timeout):
        raise kopf.PermanentError(
            f"Invalid timeout '{timeout}'. Must be a duration like '30m', '1h', '1h30m'"
        )

    logger.info("Build spec validation passed")


def _is_valid_image_reference(ref: str) -> bool:
    """
    Check if the string is a valid container image reference.

    Args:
        ref: Image reference string

    Returns:
        True if valid, False otherwise
    """
    # Basic validation - registry/repo:tag or registry/repo@digest
    # This is a simplified check, real validation would be more complex
    pattern = r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(/[a-zA-Z0-9._-]+)*(:[a-zA-Z0-9._-]+|@sha256:[a-f0-9]{64})?$"
    return bool(re.match(pattern, ref))


def _is_valid_duration(duration: str) -> bool:
    """
    Check if the string is a valid Go-style duration.

    Args:
        duration: Duration string like "30m", "1h", "1h30m"

    Returns:
        True if valid, False otherwise
    """
    pattern = r"^(\d+h)?(\d+m)?(\d+s)?$"
    return bool(re.match(pattern, duration)) and duration != ""


def parse_duration_seconds(duration: str) -> int:
    """
    Parse a duration string to seconds.

    Args:
        duration: Duration string like "30m", "1h", "1h30m"

    Returns:
        Duration in seconds
    """
    total_seconds = 0
    pattern = r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.match(pattern, duration)

    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        total_seconds = hours * 3600 + minutes * 60 + seconds

    return total_seconds
