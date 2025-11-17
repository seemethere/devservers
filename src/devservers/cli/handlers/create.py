import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from kubernetes import client, watch
from rich.console import Console
from rich.status import Status

from ..config import Configuration
from ..utils import get_current_context
from ...crds.devserver import DevServer
from ...crds.base import ObjectMeta
from ...utils.flavors import get_default_flavor


def _wait_for_crd_running(devserver: DevServer, status: Status) -> None:
    """Watches the DevServer CR until its phase is 'Running'."""
    for event in devserver.watch():
        devserver_obj = event["object"]
        if "status" in devserver_obj and "phase" in devserver_obj["status"]:
            phase = devserver_obj["status"]["phase"]
            if phase == "Running":
                return
            status.update(f"DevServer '{devserver.metadata.name}' is in phase: {phase}")


def _get_pod_status_message(pod_name: str, pod_status: client.V1PodStatus) -> str:
    """Generates a human-readable status message from a pod's status."""
    if pod_status.container_statuses:
        for container in pod_status.container_statuses:
            if container.state.waiting:
                return f"Pod '{pod_name}': Container '{container.name}' is {container.state.waiting.reason}..."
            if container.state.terminated:
                reason = (
                    f" ({container.state.terminated.reason})"
                    if container.state.terminated.reason
                    else ""
                )
                return f"Pod '{pod_name}': Container '{container.name}' terminated{reason}."
    if pod_status.phase:
        return f"Pod '{pod_name}' is in phase: {pod_status.phase}"
    return f"Pod '{pod_name}' is in an unknown state."


def _wait_for_pod_ready(devserver_name: str, namespace: str, status: Status) -> None:
    """Watches the DevServer pod until it is running and ready."""
    core_v1_api = client.CoreV1Api()
    w = watch.Watch()
    for event in w.stream(
        core_v1_api.list_namespaced_pod,
        namespace=namespace,
        label_selector=f"app={devserver_name}",
    ):
        pod = event["object"]
        pod_status = pod.status
        pod_name = pod.metadata.name

        # Check for readiness
        if (
            pod_status.phase == "Running"
            and pod_status.container_statuses
            and all(c.ready for c in pod_status.container_statuses)
        ):
            w.stop()
            return

        # Update status message
        message = _get_pod_status_message(pod_name, pod_status)
        status.update(message)


def _wait_for_devserver_ready(devserver: DevServer, console: Console) -> None:
    """Waits for the DevServer to become ready by watching the CRD and the pod."""
    with Status(
        f"Waiting for DevServer '{devserver.metadata.name}' to be provisioned...", console=console
    ) as status:
        _wait_for_crd_running(devserver, status)

        status.update(
            f"DevServer '{devserver.metadata.name}' is running. Waiting for pod to be ready..."
        )
        assert devserver.metadata.namespace is not None
        _wait_for_pod_ready(devserver.metadata.name, devserver.metadata.namespace, status)

    console.print(f"✅ DevServer '{devserver.metadata.name}' is ready.")


def create_devserver(
    configuration: Configuration,
    name: str,
    flavor: Optional[str] = None,
    image: Optional[str] = None,
    ssh_public_key_file: Optional[str] = None,
    namespace: Optional[str] = None,
    time_to_live: str = "4h",
    wait: bool = False,
    volumes: tuple[str, ...] = (),
) -> None:
    """Creates a new DevServer resource."""
    console = Console()

    _, target_namespace = get_current_context()
    if namespace:
        target_namespace = namespace

    # If flavor is not specified, try to find the default flavor
    if not flavor:
        console.print("No flavor specified, searching for a default flavor...")
        default_flavor = asyncio.run(get_default_flavor())
        if default_flavor:
            flavor = default_flavor["metadata"]["name"]
            console.print(f"Using default flavor: '{flavor}'")
        else:
            console.print(
                "Error: No default flavor found. Please specify a flavor with --flavor."
            )
            sys.exit(1)

    key_path_str = ssh_public_key_file or configuration.ssh_public_key_file
    try:
        key_path = Path(key_path_str).expanduser()
        with open(key_path, "r") as f:
            ssh_public_key = f.read().strip()
    except FileNotFoundError:
        console.print(f"Error: SSH public key file not found at '{key_path}'")
        sys.exit(1)
    except Exception as e:
        console.print(f"Error reading SSH public key file: {e}")
        sys.exit(1)

    # Construct the DevServer manifest
    spec: Dict[str, Any] = {
        "flavor": flavor,
        "ssh": {"publicKey": ssh_public_key},
        "lifecycle": {"timeToLive": time_to_live},
    }

    # Parse and add volumes if provided
    if volumes:
        parsed_volumes = []
        for vol_str in volumes:
            parts = vol_str.split(":")
            if len(parts) < 2 or len(parts) > 3:
                console.print(
                    f"[red]Error: Invalid volume format '{vol_str}'. "
                    f"Expected format: PVC_NAME:/path or PVC_NAME:/path:ro[/red]"
                )
                sys.exit(1)

            claim_name = parts[0]
            mount_path = parts[1]
            read_only = len(parts) == 3 and parts[2] == "ro"

            parsed_volumes.append({
                "claimName": claim_name,
                "mountPath": mount_path,
                "readOnly": read_only
            })

        spec["volumes"] = parsed_volumes

    # If an image is provided, use it, otherwise use the default from the operator
    if image:
        spec["image"] = image

    try:
        metadata = ObjectMeta(name=name, namespace=target_namespace)
        devserver = DevServer.create(metadata=metadata, spec=spec)
        console.print(f"DevServer '{name}' created successfully in namespace '{target_namespace}'.")
        if wait:
            assert target_namespace is not None
            _wait_for_devserver_ready(devserver, console)
    except client.ApiException as e:
        if e.status == 409:  # Conflict
            console.print(f"Error: DevServer '{name}' already exists.")
        else:
            console.print(f"Error creating DevServer: {e.reason}")
