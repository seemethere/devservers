#!/usr/bin/env python3

"""Reusable Kubernetes utility functions for EKS experiments."""

from __future__ import annotations

from typing import Optional

from kubernetes import client
from kubernetes.stream import stream
from rich.console import Console


def get_cluster_region(core_v1_api: client.CoreV1Api, console: Console) -> Optional[str]:
    """Get the cluster region from node labels."""
    console.print("Determining cluster region from node labels...")
    try:
        nodes = core_v1_api.list_node(limit=1)
    except client.ApiException as exc:
        console.print(f"[bold red]Error listing nodes: {exc}[/bold red]")
        return None

    if not nodes.items:
        console.print("[bold red]Could not list any nodes in the cluster.[/bold red]")
        return None

    labels = nodes.items[0].metadata.labels or {}
    region = labels.get("topology.kubernetes.io/region")
    if region:
        console.print(
            f"[green]✔[/green] Detected cluster region: [bold cyan]{region}[/bold cyan]"
        )
        return region
    console.print(
        "[bold red]Could not determine cluster region. "
        "Label 'topology.kubernetes.io/region' not found on node.[/bold red]"
    )
    return None


def get_pod_zone(
    core_v1_api: client.CoreV1Api, pod_name: str, namespace: str, console: Console
) -> str:
    """Get the availability zone where a pod is running."""
    try:
        pod = core_v1_api.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )
        node_name = pod.spec.node_name
        node = core_v1_api.read_node(name=node_name)
        zone = node.metadata.labels.get("topology.kubernetes.io/zone")
        if not zone:
            return "unknown"
        return zone
    except client.ApiException as exc:
        console.print(
            f"[bold red]Error getting pod zone for '{pod_name}': {exc}[/bold red]"
        )
        return "unknown"


def exec_in_pod(
    core_v1_api: client.CoreV1Api,
    pod_name: str,
    namespace: str,
    command: list[str],
    console: Console,
    stdin_data: Optional[str] = None,
) -> str:
    """Execute a command in a pod and return output."""
    try:
        response = stream(
            core_v1_api.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=command,
            stderr=True,
            stdin=stdin_data is not None,
            stdout=True,
            tty=False,
            _preload_content=False,
        )

        if stdin_data:
            response.write_stdin(stdin_data)
            response.close()

        # The default stream() method has issues with closing/reading stdout
        # So we read it manually until the stream is closed.
        output = ""
        while response.is_open():
            response.update(timeout=1)
            if response.peek_stdout():
                output += response.read_stdout()
            if response.peek_stderr():
                console.print(f"[dim]  stderr: {response.read_stderr()}[/dim]")

        return output

    except client.ApiException as exc:
        console.print(f"[bold red]Error executing command in pod: {exc}[/bold red]")
        raise


def wait_for_pod_deleted(
    core_v1_api: client.CoreV1Api,
    pod_name: str,
    namespace: str,
    wait_for_func,
) -> None:
    """Wait for a pod to be deleted."""

    def check_deleted():
        try:
            core_v1_api.read_namespaced_pod(name=pod_name, namespace=namespace)
            return None  # Still exists
        except client.ApiException as exc:
            if exc.status == 404:
                return True  # Deleted
            raise

    wait_for_func(
        description=f"Pod '{pod_name}' to be deleted",
        check_func=check_deleted,
        timeout=60,
    )


def delete_pod(
    core_v1_api: client.CoreV1Api,
    pod_name: str,
    namespace: str,
    console: Console,
    wait_for_func,
) -> None:
    """Delete a pod."""
    try:
        console.print(f"Deleting pod '[bold cyan]{pod_name}[/bold cyan]'...")
        core_v1_api.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )
        wait_for_pod_deleted(core_v1_api, pod_name, namespace, wait_for_func)
        console.print(f"[green]✔[/green] Pod '{pod_name}' deleted.")
    except client.ApiException as exc:
        if exc.status == 404:
            console.print(f"[yellow]ℹ[/yellow] Pod '{pod_name}' already deleted.")
        else:
            raise
