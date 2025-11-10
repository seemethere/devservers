import logging
import os
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.prompt import Confirm

from ..utils.kube import KubernetesConfigurationError, configure_kube_client
from . import handlers
from .config import create_default_config, get_default_config_path, load_config
from .ssh_config import ensure_ssh_config_include, set_ssh_config_permission


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the devserver config file.",
)
@click.option(
    "--assume-yes", is_flag=True, help="Automatically answer yes to all prompts."
)
@click.pass_context
def main(ctx, config_path, assume_yes) -> None:
    """A CLI to manage DevServers."""
    ctx.ensure_object(dict)
    console = Console()

    default_config_path = get_default_config_path()
    effective_config_path = config_path if config_path else default_config_path

    # Do not attempt to create a config file during tests
    is_testing = "PYTEST_CURRENT_TEST" in os.environ

    if (
        not is_testing
        and not effective_config_path.exists()
        and effective_config_path == default_config_path
    ):
        console.print(f"Configuration file not found at [cyan]{effective_config_path}[/cyan].")
        if assume_yes or Confirm.ask("Would you like to create a default one?", default=True):
            create_default_config(effective_config_path)

    ctx.obj["CONFIG"] = load_config(effective_config_path)
    ctx.obj["ASSUME_YES"] = assume_yes
    try:
        configure_kube_client(logging.getLogger(__name__))
    except KubernetesConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command(help="Create a new DevServer.")
@click.option("--name", type=str, default="dev", help="The name of the DevServer.")
@click.option("--flavor", type=str, required=False, help="The flavor of the DevServer.")
@click.option("--image", type=str, help="The container image to use.")
@click.option(
    "--ssh-public-key-file",
    type=str,
    default=None,
    help="Path to the SSH public key file.",
)
@click.option(
    "--time",
    "--ttl",
    "time_to_live",
    type=str,
    default="4h",
    help="The time to live for the DevServer.",
)
@click.option(
    "--wait",
    is_flag=True,
    help="Wait for the DevServer to be ready.",
)
@click.option(
    "--persistent-home-size",
    type=str,
    default="10Gi",
    help="The size of the persistent home directory.",
)
@click.pass_context
def create(
    ctx,
    name: str,
    flavor: str,
    image: str,
    ssh_public_key_file: str,
    time_to_live: str,
    wait: bool,
    persistent_home_size: str,
) -> None:
    """Create a new DevServer."""
    handlers.create_devserver(
        configuration=ctx.obj["CONFIG"],
        name=name,
        flavor=flavor,
        image=image,
        ssh_public_key_file=ssh_public_key_file,
        time_to_live=time_to_live,
        wait=wait,
        persistent_home_size=persistent_home_size,
    )


@main.command(help="Delete a DevServer.")
@click.option("--name", type=str, default="dev", help="The name of the DevServer.")
@click.pass_context
def delete(ctx, name: str) -> None:
    """Delete a DevServer."""
    handlers.delete_devserver(configuration=ctx.obj["CONFIG"], name=name)


@main.command(help="Describe a DevServer.")
@click.option("--name", type=str, default="dev", help="The name of the DevServer.")
def describe(name: str) -> None:
    """Describe a DevServer."""
    handlers.describe_devserver(name=name)


@main.command(name="list", help="List all DevServers.")
def list_command() -> None:
    """List all DevServers."""
    handlers.list_devservers()


@main.command(name="flavors", help="List all DevServer flavors.")
def flavors() -> None:
    """List all DevServer flavors."""
    handlers.list_flavors()


@main.command(help="SSH into a DevServer.")
@click.option("--name", type=str, default="dev", help="The name of the DevServer.")
@click.option(
    "-i",
    "--identity-file",
    "ssh_private_key_file",
    type=str,
    default=None,
    help="Path to the SSH private key file.",
)
@click.option(
    "-n",
    "--namespace",
    type=str,
    default=None,
    help="The namespace to use.",
    hidden=True,
)  # Hidden from user help
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Connect directly to the DevServer without using SSH config.",
)
@click.argument("remote_command", nargs=-1)
@click.pass_context
def ssh(
    ctx,
    name: str,
    ssh_private_key_file: str,
    namespace: Optional[str],
    no_proxy: bool,
    remote_command: tuple[str, ...],
) -> None:
    """SSH into a DevServer."""
    handlers.ssh_devserver(
        configuration=ctx.obj["CONFIG"],
        name=name,
        ssh_private_key_file=ssh_private_key_file,
        namespace=namespace,
        no_proxy=no_proxy,
        remote_command=remote_command,
        assume_yes=ctx.obj["ASSUME_YES"],
    )


@main.command(name="ssh-proxy", help="Run in proxy mode for SSH ProxyCommand.", hidden=True)
@click.option("--name", type=str, default="dev", help="The name of the DevServer.")
@click.option(
    "-n",
    "--namespace",
    type=str,
    default=None,
    help="The namespace to use.",
    hidden=True,
)
@click.option(
    "--kubeconfig-path",
    type=str,
    default=None,
    help="Path to the kubeconfig file.",
    hidden=True,
)
def ssh_proxy(name: str, namespace: Optional[str], kubeconfig_path: Optional[str]) -> None:
    """Run in proxy mode for SSH ProxyCommand."""
    handlers.ssh_proxy_devserver(name=name, namespace=namespace, kubeconfig_path=kubeconfig_path)


@main.group()
def admin() -> None:
    """Administrative commands for managing DevServers."""
    pass


@admin.group()
def user() -> None:
    """Manage DevServer users."""
    pass


@user.command(name="create", help="Create a new DevServer user.")
@click.argument("username", type=str)
def user_create(username: str) -> None:
    """Create a new DevServer user."""
    handlers.create_user(username=username)


@user.command(name="delete", help="Delete a DevServer user.")
@click.argument("username", type=str)
def user_delete(username: str) -> None:
    """Delete a DevServer user."""
    handlers.delete_user(username=username)


@user.command(name="list", help="List all DevServer users.")
def user_list() -> None:
    """List all DevServer users."""
    handlers.list_users()


@user.command(name="kubeconfig", help="Generate a kubeconfig for a DevServer user.")
@click.argument("username", type=str)
def user_kubeconfig(username: str) -> None:
    """Generate a kubeconfig for a DevServer user."""
    handlers.generate_user_kubeconfig(username=username)


@main.group()
def config() -> None:
    """Manage devctl configuration."""
    pass


@config.command(name="ssh-include")
@click.argument("action", type=click.Choice(["enable", "disable"]))
@click.pass_context
def ssh_include(ctx, action: str):
    """Enable or disable SSH config Include directive."""
    console = Console()
    config = ctx.obj["CONFIG"]
    assume_yes = ctx.obj["ASSUME_YES"]

    if action.lower() == "enable":
        set_ssh_config_permission(config.ssh_config_dir, True)
        if ensure_ssh_config_include(
            config.ssh_config_dir, assume_yes=assume_yes
        ):
            console.print(
                "[green]✅ Enabled SSH config Include directive.[/green]")
            console.print(
                f"[cyan]Added 'Include {config.ssh_config_dir}/*.sshconfig' to ~/.ssh/config[/cyan]"
            )
        else:
            console.print(
                "[yellow]SSH config Include was not enabled.[/yellow]")
    elif action.lower() == "disable":
        set_ssh_config_permission(config.ssh_config_dir, False)
        console.print(
            "[yellow]✅ Disabled automatic SSH config Include.[/yellow]")
        console.print(
            "[dim]Note: Existing Include directive in ~/.ssh/config not removed.[/dim]")
        console.print(
            "[dim]You can manually remove the 'Include ~/.config/devserver/*.sshconfig' line if desired.[/dim]"
        )


if __name__ == "__main__":
    main()
