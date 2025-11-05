#!/usr/bin/env python3

"""Base classes for EKS experiments."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from kubernetes import client, config
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from . import k8s_utils


@dataclass
class BaseExperimentConfig:
    """Base configuration for experiments."""

    poll_interval_seconds: int = 5
    poll_timeout_seconds: int = 180


class BaseExperiment(ABC):
    """Abstract base class for an EKS experiment."""

    def __init__(
        self,
        config: BaseExperimentConfig,
        console: Optional[Console] = None,
    ) -> None:
        self.config = config
        self.console = console or Console()

        # Clients initialized in `run`
        self.core_v1_api: Optional[client.CoreV1Api] = None
        self.apps_v1_api: Optional[client.AppsV1Api] = None
        self.storage_v1_api: Optional[client.StorageV1Api] = None
        self.custom_objects_api: Optional[client.CustomObjectsApi] = None
        self.api_client: Optional[client.ApiClient] = None

        # Runtime fields
        self.run_id: Optional[str] = None
        self.zone1: Optional[str] = None
        self.zone2: Optional[str] = None
        self.outcome_summary: Optional[Panel] = None
        self.error_occurred: bool = False

    @abstractmethod
    def run(self) -> None:
        """Run the experiment from start to finish."""
        raise NotImplementedError

    @abstractmethod
    def _print_experiment_overview(self) -> None:
        """Display a summary of the experiment's purpose and flow."""
        raise NotImplementedError

    def _initialize_clients(self) -> bool:
        """Initialize Kubernetes API clients."""
        try:
            config.load_kube_config()
        except config.ConfigException:
            self.console.print(
                "[bold red]Could not load kubeconfig. Is your environment configured correctly?[/bold red]"
            )
            return False

        self.core_v1_api = client.CoreV1Api()
        self.apps_v1_api = client.AppsV1Api()
        self.storage_v1_api = client.StorageV1Api()
        self.custom_objects_api = client.CustomObjectsApi()
        self.api_client = client.ApiClient()
        return True

    def _determine_zones(self) -> None:
        """Determine availability zones from cluster nodes."""
        assert self.core_v1_api
        cluster_region = k8s_utils.get_cluster_region(self.core_v1_api, self.console)
        if not cluster_region:
            self.console.print("[bold red]Exiting: Could not determine cluster region.[/bold red]")
            return

        self.zone1 = f"{cluster_region}a"
        self.zone2 = f"{cluster_region}b"
        self.console.print(
            f"\nTargeting zones: [bold magenta]{self.zone1}[/bold magenta] and "
            f"[bold magenta]{self.zone2}[/bold magenta]"
        )

    def _prepare_runtime_identifiers(self) -> None:
        """Prepare unique identifiers for this experiment run."""
        self.run_id = str(uuid.uuid4())[:8]

    def _wait_for(
        self,
        description: str,
        check_func: Callable[[], Optional[bool]],
        timeout: Optional[int] = None,
    ) -> None:
        """Generic timed wait with a spinner."""
        timeout = timeout or self.config.poll_timeout_seconds

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        )

        task_id = progress.add_task(f"Waiting for {description}...", total=None)

        with progress:
            start_time = time.time()
            while time.time() - start_time < timeout:
                result = check_func()
                if result is True:
                    progress.update(task_id, description=f"{description} - Done")
                    self.console.print(f"[green]✔[/green] {description} - Done")
                    return
                if result is False:
                    progress.stop()
                    raise RuntimeError(f"Check failed for '{description}'")

                time.sleep(self.config.poll_interval_seconds)

        raise TimeoutError(f"Timed out waiting for '{description}'")
