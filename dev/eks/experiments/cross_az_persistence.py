#!/usr/bin/env python3

"""Reusable experiment module for validating cross-AZ persistence behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from kubernetes import client, watch
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from . import k8s_utils
from .base import BaseExperiment, BaseExperimentConfig

# Kubernetes constants
NAMESPACE = "default"
DEVSERVER_GROUP = "devserver.io"
DEVSERVER_VERSION = "v1"
DEVSERVER_PLURAL = "devservers"
FLAVOR_PLURAL = "devserverflavors"


@dataclass
class ExperimentConfig(BaseExperimentConfig):
    """Configuration parameters for the experiment."""

    namespace: str = NAMESPACE
    flavor_cpu_request: str = "500m"
    flavor_memory_request: str = "1Gi"
    flavor_cpu_limit: str = "1"
    flavor_memory_limit: str = "2Gi"
    persistent_home_size: str = "1Gi"
    ssh_public_key: str = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCq ... dummy key ... fgq"
    )
    lifecycle_ttl: str = "1h"


class CrossAzPersistenceExperiment(BaseExperiment):
    """Encapsulates the logic for the cross-AZ persistence experiment."""

    def __init__(
        self,
        config: ExperimentConfig | None = None,
        console: Optional[Console] = None,
    ) -> None:
        super().__init__(config or ExperimentConfig(), console)

        self.devserver_name: Optional[str] = None
        self.flavor_name_az1: Optional[str] = None
        self.flavor_name_az2: Optional[str] = None
        self.pvc_name: Optional[str] = None
        self.pv_zone: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Run the experiment from start to finish."""

        self._print_experiment_overview()

        if not self._initialize_clients():
            return

        self._determine_zones()
        if not self.zone1 or not self.zone2:
            return

        self._prepare_runtime_identifiers()

        try:
            self._phase_create_flavors()
            pod_name_az1 = self._phase_create_devserver_in_zone(self.zone1)
            if not pod_name_az1:
                return

            test_file_path, test_data = self._phase_populate_volume(pod_name_az1)
            self._phase_delete_devserver()
            pv_zone = self._phase_attempt_cross_az_creation()
            self._phase_verify_results(
                pod_name_az1=pod_name_az1,
                pv_zone=pv_zone,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.console.print(f"\n[bold red]An unexpected error occurred: {exc}[/bold red]")
        finally:
            self._phase_cleanup()

        if self.outcome_summary:
            self.console.print(self.outcome_summary)

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------
    def _phase_create_flavors(self) -> None:
        self.console.print(
            Rule("[bold yellow]Phase 1: Create Flavors for Each Zone[/bold yellow]")
        )
        assert self.custom_objects_api
        assert self.flavor_name_az1
        assert self.flavor_name_az2
        assert self.zone1
        assert self.zone2
        self._create_devserver_flavor(self.flavor_name_az1, self.zone1)
        self._create_devserver_flavor(self.flavor_name_az2, self.zone2)

    def _phase_create_devserver_in_zone(self, zone: str) -> Optional[str]:
        assert self.devserver_name
        assert self.custom_objects_api
        assert self.core_v1_api

        self.console.print(
            Rule(f"[bold yellow]Phase 2: Create DevServer in Zone '{zone}'[/bold yellow]")
        )
        flavor = self.flavor_name_az1 if zone == self.zone1 else self.flavor_name_az2
        assert flavor
        self._create_devserver(flavor)
        pod_name = self._wait_for_pod_running(label_selector=f"app={self.devserver_name}")
        if not pod_name:
            return None
        zone_of_pod = k8s_utils.get_pod_zone(
            self.core_v1_api, pod_name, self.config.namespace, self.console
        )
        self.console.print(
            f"  [cyan]↳ Pod '[bold]{pod_name}[/bold]' is running in zone: "
            f"[bold magenta]{zone_of_pod}[/bold magenta][/cyan]"
        )
        return pod_name

    def _phase_populate_volume(self, pod_name: str) -> tuple[str, str]:
        assert self.core_v1_api

        self.console.print("\nWriting test file to persistent volume...")
        test_file_path = "/home/dev/test-file.txt"
        test_data = f"Data from run {self.run_id}"
        k8s_utils.exec_in_pod(
            self.core_v1_api,
            pod_name,
            self.config.namespace,
            ["/bin/bash", "-c", f"echo '{test_data}' > {test_file_path}"],
            self.console,
        )
        return test_file_path, test_data

    def _phase_delete_devserver(self) -> None:
        assert self.devserver_name
        assert self.custom_objects_api
        assert self.apps_v1_api
        assert self.core_v1_api
        assert self.pvc_name

        self.console.print(
            Rule(
                "[bold yellow]Phase 3: Delete DevServer and Verify Volume Persistence[/bold yellow]"
            )
        )
        self._delete_devserver()
        self._wait_for_statefulset_deleted()
        # Pod is deleted as part of StatefulSet deletion, no need to wait explicitly
        self._verify_pvc_exists()
        self.pv_zone = self._get_pv_zone(self.pvc_name)

    def _phase_attempt_cross_az_creation(self) -> Optional[str]:
        assert self.devserver_name
        assert self.custom_objects_api
        assert self.zone2

        self.console.print(
            Rule(
                f"[bold yellow]Phase 4: Attempt to Create DevServer in Different Zone '{self.zone2}'[/bold yellow]"
            )
        )
        self._create_devserver(self.flavor_name_az2)
        return getattr(self, "pv_zone", None)

    def _phase_verify_results(
        self,
        pod_name_az1: str,
        pv_zone: Optional[str],
    ) -> None:
        assert self.zone2

        self.console.print(Rule("[bold yellow]Phase 5: Verification & Results[/bold yellow]"))
        final_pod_name = pod_name_az1  # StatefulSet will reuse the name
        timeout = self.config.poll_timeout_seconds
        start_time = time.time()

        self.console.print(
            f"Polling for outcome of pod '[bold cyan]{final_pod_name}[/bold cyan]' "
            f"for up to {timeout}s..."
        )

        while time.time() - start_time < timeout:
            pod_phase = self._read_pod_phase(final_pod_name)
            if pod_phase == "Running":
                self._handle_unexpected_success(final_pod_name)
                return

            if self._inspect_failure_events(final_pod_name, pv_zone):
                return

            time.sleep(self.config.poll_interval_seconds)

        self.console.print(
            f"\n[bold red]FAILURE:[/bold red] Timed out after {timeout}s waiting for a "
            f"definitive outcome for pod '{final_pod_name}'."
        )

    def _phase_cleanup(self) -> None:
        self.console.print(Rule("[bold yellow]Phase 6: Cleanup[/bold yellow]"))
        self._delete_devserver()
        self._delete_devserver_flavor(self.flavor_name_az1)
        self._delete_devserver_flavor(self.flavor_name_az2)

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def _print_experiment_overview(self) -> None:  # noqa: D102
        self.console.print(
            Panel(
                "[bold]EKS Cross-AZ PVC Attachment Experiment[/bold]\n\n"
                "This experiment checks whether a standard Persistent Volume (backed by AWS EBS)\n"
                "can be detached from a pod in one Availability Zone and re-attached to a new pod\n"
                "in a different AZ.\n\n"
                "[bold]Hypothesis:[/] This should fail because EBS volumes are zone-locked.",
                title="[bold blue]Experiment Overview[/bold blue]",
                border_style="blue",
            )
        )

    def _prepare_runtime_identifiers(self) -> None:  # noqa: D102
        super()._prepare_runtime_identifiers()
        assert self.zone1 and self.zone2
        self.devserver_name = f"persistent-test-{self.run_id}"
        self.flavor_name_az1 = f"test-{self.zone1.replace('-', '')}-{self.run_id}"
        self.flavor_name_az2 = f"test-{self.zone2.replace('-', '')}-{self.run_id}"
        self.pvc_name = f"home-{self.devserver_name}-0"

    # ------------------------------------------------------------------
    # Kubernetes helpers
    # ------------------------------------------------------------------
    def _create_devserver_flavor(self, flavor_name: str, zone: str) -> None:
        assert self.custom_objects_api

        body = {
            "apiVersion": f"{DEVSERVER_GROUP}/{DEVSERVER_VERSION}",
            "kind": "DevServerFlavor",
            "metadata": {"name": flavor_name},
            "spec": {
                "nodeSelector": {
                    "topology.kubernetes.io/zone": zone,
                    "kubernetes.io/arch": "amd64",
                },
                "resources": {
                    "requests": {
                        "cpu": self.config.flavor_cpu_request,
                        "memory": self.config.flavor_memory_request,
                    },
                    "limits": {
                        "cpu": self.config.flavor_cpu_limit,
                        "memory": self.config.flavor_memory_limit,
                    },
                },
            },
        }
        self.console.print(
            f"Creating DevServerFlavor '[bold cyan]{flavor_name}[/bold cyan]' for zone "
            f"'[bold magenta]{zone}[/bold magenta]'..."
        )
        self.custom_objects_api.create_cluster_custom_object(
            group=DEVSERVER_GROUP,
            version=DEVSERVER_VERSION,
            plural=FLAVOR_PLURAL,
            body=body,
        )
        self.console.print(
            f"[green]✔[/green] DevServerFlavor '[bold cyan]{flavor_name}[/bold cyan]' created."
        )

    def _delete_devserver_flavor(self, flavor_name: Optional[str]) -> None:
        if not flavor_name or not self.custom_objects_api:
            return

        try:
            self.console.print(
                f"Deleting DevServerFlavor '[bold cyan]{flavor_name}[/bold cyan]'..."
            )
            self.custom_objects_api.delete_cluster_custom_object(
                group=DEVSERVER_GROUP,
                version=DEVSERVER_VERSION,
                plural=FLAVOR_PLURAL,
                name=flavor_name,
                body=client.V1DeleteOptions(),
            )
            self.console.print(
                f"[green]✔[/green] DevServerFlavor '[bold cyan]{flavor_name}[/bold cyan]' deleted."
            )
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(
                    f"[yellow]i[/yellow] DevServerFlavor '[bold cyan]{flavor_name}[/bold cyan]' "
                    "not found, already deleted."
                )
            else:
                raise

    def _create_devserver(self, flavor_name: Optional[str]) -> None:
        assert self.custom_objects_api
        assert self.devserver_name
        assert flavor_name

        body = {
            "apiVersion": f"{DEVSERVER_GROUP}/{DEVSERVER_VERSION}",
            "kind": "DevServer",
            "metadata": {
                "name": self.devserver_name,
                "namespace": self.config.namespace,
            },
            "spec": {
                "flavor": flavor_name,
                "persistentHomeSize": self.config.persistent_home_size,
                "ssh": {"publicKey": self.config.ssh_public_key},
                "lifecycle": {"timeToLive": self.config.lifecycle_ttl},
            },
        }
        self.console.print(
            f"Creating DevServer '[bold cyan]{self.devserver_name}[/bold cyan]' with flavor "
            f"'[bold cyan]{flavor_name}[/bold cyan]'..."
        )
        self.custom_objects_api.create_namespaced_custom_object(
            group=DEVSERVER_GROUP,
            version=DEVSERVER_VERSION,
            namespace=self.config.namespace,
            plural=DEVSERVER_PLURAL,
            body=body,
        )
        self.console.print(
            f"[green]✔[/green] DevServer '[bold cyan]{self.devserver_name}[/bold cyan]' created."
        )

    def _delete_devserver(self) -> None:
        if not self.devserver_name or not self.custom_objects_api:
            return

        try:
            self.console.print(
                f"Deleting DevServer '[bold cyan]{self.devserver_name}[/bold cyan]'..."
            )
            self.custom_objects_api.delete_namespaced_custom_object(
                group=DEVSERVER_GROUP,
                version=DEVSERVER_VERSION,
                namespace=self.config.namespace,
                plural=DEVSERVER_PLURAL,
                name=self.devserver_name,
                body=client.V1DeleteOptions(),
            )
            self.console.print(
                f"[green]✔[/green] DevServer '[bold cyan]{self.devserver_name}[/bold cyan]' deleted."
            )
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(
                    f"[yellow]i[/yellow] DevServer '[bold cyan]{self.devserver_name}[/bold cyan]' "
                    "not found, already deleted."
                )
            else:
                raise

    def _wait_for_pod_running(self, label_selector: str, timeout: int = 180) -> Optional[str]:
        assert self.core_v1_api
        watcher = watch.Watch()
        with self.console.status(
            f"Waiting for pod with label '[bold cyan]{label_selector}[/bold cyan]' to become Running...",
            spinner="dots",
        ):
            for event in watcher.stream(
                self.core_v1_api.list_namespaced_pod,
                namespace=self.config.namespace,
                label_selector=label_selector,
                timeout_seconds=timeout,
            ):
                pod = event["object"]
                phase = pod.status.phase
                if phase == "Running":
                    watcher.stop()
                    self.console.print(
                        f"[green]✔[/green] Pod '[bold cyan]{pod.metadata.name}[/bold cyan]' is Running."
                    )
                    return pod.metadata.name
                if phase in {"Failed", "Unknown"}:
                    watcher.stop()
                    self.console.print(
                        f"[bold red]Pod '{pod.metadata.name}' entered a failed state: {phase}[/bold red]"
                    )
                    raise RuntimeError(f"Pod failed to start. Status: {phase}")
        raise TimeoutError(
            f"Pod with label '{label_selector}' did not become Running within {timeout}s."
        )

    def _wait_for_statefulset_deleted(self) -> None:
        assert self.apps_v1_api
        assert self.devserver_name

        def check() -> Optional[bool]:
            try:
                self.apps_v1_api.read_namespaced_stateful_set(
                    name=self.devserver_name,
                    namespace=self.config.namespace,
                )
                return None
            except client.ApiException as exc:
                if exc.status == 404:
                    return True
                raise

        self._wait_for(
            f"StatefulSet '{self.devserver_name}' to be deleted",
            check,
        )

    def _verify_pvc_exists(self) -> bool:
        assert self.core_v1_api
        assert self.pvc_name
        self.console.print(
            f"Verifying PVC '[bold cyan]{self.pvc_name}[/bold cyan]' exists..."
        )
        try:
            self.core_v1_api.read_namespaced_persistent_volume_claim(
                name=self.pvc_name,
                namespace=self.config.namespace,
            )
            self.console.print(
                f"[green]✔[/green] PVC '[bold cyan]{self.pvc_name}[/bold cyan]' still exists."
            )
            return True
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(
                    f"[bold red]Error: PVC '[bold cyan]{self.pvc_name}[/bold cyan]' does not exist when it should.[/bold red]"
                )
                return False
            raise

    def _get_pv_zone(self, pvc_name: str) -> Optional[str]:
        assert self.core_v1_api
        try:
            pvc = self.core_v1_api.read_namespaced_persistent_volume_claim(
                name=pvc_name,
                namespace=self.config.namespace,
            )
        except client.ApiException as exc:
            self.console.print(
                f"[bold red]Error inspecting PV for '{pvc_name}': {exc}[/bold red]"
            )
            return None

        pv_name = pvc.spec.volume_name
        if not pv_name:
            self.console.print(
                f"[bold red]Could not find PersistentVolume name for PVC '{pvc_name}'.[/bold red]"
            )
            return None

        self.console.print(
            f"Inspecting PersistentVolume '[bold cyan]{pv_name}[/bold cyan]' for zone affinity..."
        )
        try:
            pv = self.core_v1_api.read_persistent_volume(name=pv_name)
        except client.ApiException as exc:
            self.console.print(
                f"[bold red]Error inspecting PV '{pv_name}': {exc}[/bold red]"
            )
            return None

        affinity = pv.spec.node_affinity
        if not affinity or not affinity.required or not affinity.required.node_selector_terms:
            self.console.print(
                f"[bold red]No required node affinity found on PV '{pv_name}'.[/bold red]"
            )
            return None

        for term in affinity.required.node_selector_terms:
            for expr in term.match_expressions or []:
                if expr.key == "topology.kubernetes.io/zone" and expr.values:
                    zone = expr.values[0]
                    self.console.print(
                        f"[green]✔[/green] PV '[bold cyan]{pv_name}[/bold cyan]' is permanently bound to zone: "
                        f"[bold magenta]{zone}[/bold magenta]"
                    )
                    return zone

        self.console.print(
            f"[bold red]Could not find zone label in node affinity for PV '{pv_name}'.[/bold red]"
        )
        return None

    def _read_pod_phase(self, pod_name: str) -> Optional[str]:
        assert self.core_v1_api
        try:
            pod = self.core_v1_api.read_namespaced_pod(
                name=pod_name,
                namespace=self.config.namespace,
            )
            return pod.status.phase
        except client.ApiException as exc:
            if exc.status == 404:
                return None
            self.console.print(
                f"[bold red]An unexpected API error occurred when reading pod phase: {exc}[/bold red]"
            )
            return None

    def _inspect_failure_events(self, pod_name: str, pv_zone: Optional[str]) -> bool:
        assert self.core_v1_api
        assert self.zone2
        events = self.core_v1_api.list_namespaced_event(
            namespace=self.config.namespace,
            field_selector=f"involvedObject.name={pod_name}",
        )

        for event in events.items:
            if event.reason in {"FailedScheduling", "FailedAttachVolume"}:
                self.outcome_summary = Panel(
                    "[bold green]Experiment Conclusion: Success[/bold green]\n\n"
                    f"The experiment behaved as expected. The second pod, targeted for zone "
                    f"[bold magenta]{self.zone2}[/bold magenta], failed to start because it could not "
                    "attach the Persistent Volume.\n\n"
                    f"The PV is permanently bound to zone [bold magenta]{pv_zone or 'unknown'}[/bold magenta], "
                    "confirming that standard EBS-backed Persistent Volumes are zone-locked.",
                    title="[bold green]Result[/bold green]",
                    border_style="green",
                )
                self.console.print("\n[bold green]SUCCESS (Expected Failure):[/bold green]")
                self.console.print(
                    f"Pod failed to start in '{self.zone2}' as expected."
                )
                self.console.print(
                    "  [cyan]↳ This is because the pod is required to use the persistent volume "
                    f"bound to [bold magenta]{pv_zone or 'unknown'}[/bold magenta].[/cyan]"
                )
                self.console.print(
                    f"  [yellow]↳ Found event: {event.reason}: {event.message}[/yellow]"
                )
                return True
        return False

    def _handle_unexpected_success(self, pod_name: str) -> None:
        zone_of_pod = k8s_utils.get_pod_zone(
            self.core_v1_api, pod_name, self.config.namespace, self.console
        )
        self.outcome_summary = Panel(
            "[bold yellow]Experiment Conclusion: Unexpected Success[/bold yellow]\n\n"
            f"The second pod, targeted for zone [bold magenta]{self.zone2}[/bold magenta], "
            f"successfully started in zone [bold magenta]{zone_of_pod}[/bold magenta] and re-attached the Persistent Volume.\n\n"
            "This behavior is highly unusual for standard EBS volumes and may indicate a "
            "multi-zone storage solution or a configuration issue.",
            title="[bold yellow]Result[/bold yellow]",
            border_style="yellow",
        )


__all__ = ["CrossAzPersistenceExperiment", "ExperimentConfig"]
