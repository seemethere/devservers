import subprocess
import sys
from pathlib import Path
from typing import Optional
import os

from kubernetes import client
from rich.console import Console

from ..ssh_config import (
    create_ssh_config_for_devserver,
    remove_ssh_config_for_devserver,
)
from ...utils.network import PortForwardError, kubernetes_port_forward
from ..config import Configuration
from ..utils import get_current_context
from ...crds.devserver import DevServer
from ...utils.kube import get_pod_by_labels


def warn_if_agent_forwarding_is_disabled(configuration: Configuration):
    if not configuration.ssh_forward_agent:
        console = Console()
        console.print("[yellow]⚠️ SSH agent forwarding is disabled. This may cause issues with tools that rely on SSH agent forwarding like git.[/yellow]")
        console.print("[yellow]   Modify the value ssh.forward_agent to true in your config file to enable it.[/yellow]")


def ssh_devserver(
    configuration: Configuration,
    name: str,
    ssh_private_key_file: Optional[str],
    remote_command: tuple[str, ...],
    assume_yes: bool = False,
    namespace: Optional[str] = None,
    no_proxy: bool = False,
) -> None:
    """SSH into a DevServer."""
    console = Console()

    user, target_namespace = get_current_context()
    if namespace:
        target_namespace = namespace
    key_path_str = ssh_private_key_file or configuration.ssh_private_key_file

    assert target_namespace is not None

    try:
        # Check if DevServer exists
        DevServer.get(name=name, namespace=target_namespace)

        # Get pod by label selector
        core_v1_api = client.CoreV1Api()
        pod = get_pod_by_labels(core_v1_api, target_namespace, {"app": name})
        if not pod:
            console.print(f"[red]Error: No pod found for DevServer '{name}'[/red]")
            sys.exit(1)

        assert pod.metadata is not None
        pod_name = pod.metadata.name

        if not no_proxy:
            kubeconfig_path = os.environ.get("KUBECONFIG")
            _, use_include, hostname = create_ssh_config_for_devserver(
                configuration.ssh_config_dir,
                name,
                key_path_str,
                user=user,
                namespace=target_namespace,
                kubeconfig_path=kubeconfig_path,
                ssh_forward_agent=configuration.ssh_forward_agent,
                assume_yes=assume_yes,
            )
            if use_include:
                console.print(f"Connecting to devserver '{name}' via SSH config...")
                ssh_command = ["ssh", hostname]
                warn_if_agent_forwarding_is_disabled(configuration)
                if remote_command:
                    ssh_command.extend(remote_command)
                subprocess.run(ssh_command, check=False)
                return
            else:
                console.print("SSH Include not enabled. Using port-forward to connect.")
                console.print("Run 'devctl config ssh-include enable' to simplify this.")

        with kubernetes_port_forward(
            pod_name=pod_name, namespace=target_namespace, pod_port=22
        ) as local_port:
            # Interactive port-forward flow
            console.print(
                f"Connecting to devserver '{name}' via port-forward on localhost:{local_port}..."
            )
            key_path = Path(key_path_str).expanduser()
            if not key_path.is_file():
                console.print(
                    f"[red]Error: SSH private key file not found at '{key_path}'[/red]"
                )
                sys.exit(1)

            ssh_command = [
                "ssh",
                "-A" if configuration.ssh_forward_agent else "",
                "-i", str(key_path),
                "-p", str(local_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "dev@localhost",
            ]
            warn_if_agent_forwarding_is_disabled(configuration)
            if remote_command:
                ssh_command.extend(remote_command)
            subprocess.run(ssh_command, check=False)

    except client.ApiException as e:
        if e.status == 404:
            console.print(f"[yellow]DevServer '{name}' not found. It may have expired.[/yellow]")
            remove_ssh_config_for_devserver(
                configuration.ssh_config_dir, name, user=user
            )
        else:
            console.print(f"Error connecting to Kubernetes: {e.reason}")
        sys.exit(1)
    except PortForwardError as e:
        console.print(
            f"Error: Could not start port-forwarding for DevServer '{name}'. Pod may not be ready."
        )
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]An unexpected error occurred: {e}[/red]")
        sys.exit(1)
    finally:
        console.print("\n[green]SSH session ended. Closing port-forward.[/green]")
