#!/usr/bin/env python3

"""Experiment to validate VolumeSnapshot-based cross-AZ data migration."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any, Optional

from kubernetes import client
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule

from . import k8s_utils
from .base import BaseExperiment, BaseExperimentConfig

# Kubernetes constants
SNAPSHOT_API_GROUP = "snapshot.storage.k8s.io"
SNAPSHOT_API_VERSION = "v1"


@dataclass
class ExperimentConfig(BaseExperimentConfig):
    """Configuration parameters for the snapshot migration experiment."""

    pvc_size: str = "1Gi"
    storage_class_name: str = "auto-ebs-sc"
    snapshot_class_name: str = "ebs-csi-snapshot-class"
    poll_timeout_seconds: int = 300


class SnapshotMigrationExperiment(BaseExperiment):
    """Validates VolumeSnapshot-based cross-AZ migration."""

    def __init__(
        self,
        config: ExperimentConfig | None = None,
        console: Optional[Console] = None,
    ) -> None:
        super().__init__(config or ExperimentConfig(), console)

        self.namespace: Optional[str] = None
        self.source_pvc_name: Optional[str] = None
        self.snapshot_name: Optional[str] = None
        self.target_pvc_name: Optional[str] = None
        self.writer_pod_name: Optional[str] = None
        self.reader_pod_name: Optional[str] = None
        self.snapshot_class_created: bool = False
        self.snapshot_crds_installed: bool = False
        self.snapshot_controller_installed: bool = False
        self.test_data: Optional[str] = None
        self.outcome_summary: Optional[Panel] = None
        self.error_occurred: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Run the experiment from start to finish."""
        self._print_experiment_overview()

        if not self._initialize_clients():
            return

        try:
            if not self._phase_check_prerequisites():
                return

            self._determine_zones()
            if not self.zone1 or not self.zone2:
                return

            self._prepare_runtime_identifiers()
            self._phase_setup_namespace()

            try:
                self._phase_create_source_pvc()
                self._phase_write_test_data()
                self._phase_create_snapshot()
                self._phase_restore_to_different_zone()
                self._phase_verify_data_integrity()
            except KeyboardInterrupt:
                self.console.print("\n\n[bold yellow]⚠ Experiment interrupted by user[/bold yellow]")
                self.error_occurred = True
                # Don't re-raise, allow cleanup to run
            except Exception as exc:
                self.error_occurred = True
                self.console.print(f"\n[bold red]An unexpected error occurred: {exc}[/bold red]")
                import traceback
                self.console.print(f"[dim]{traceback.format_exc()}[/dim]")
        finally:
            # Always cleanup, even on interrupt
            if self.error_occurred:
                self.console.print(
                    Panel(
                        "An error occurred. The experiment is paused to allow for manual inspection of resources.\n"
                        "Press [bold]Enter[/bold] to continue with cleanup.",
                        title="[yellow]Experiment Paused[/yellow]",
                        border_style="yellow",
                    )
                )
                input()

            self._phase_cleanup()

        if self.outcome_summary:
            self.console.print(self.outcome_summary)

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------
    def _phase_setup_namespace(self) -> None:
        """Create a temporary namespace for the experiment."""
        assert self.core_v1_api
        assert self.namespace
        self.console.print(Rule("[bold yellow]Phase 1: Setup Namespace[/bold yellow]"))

        namespace_body = client.V1Namespace(
            metadata=client.V1ObjectMeta(name=self.namespace)
        )
        self.core_v1_api.create_namespace(body=namespace_body)
        self.console.print(f"Created namespace '[bold cyan]{self.namespace}[/bold cyan]'.")

    def _phase_check_prerequisites(self) -> bool:
        """Check if VolumeSnapshot CRDs and classes exist, install if missing."""
        self.console.print(Rule("[bold yellow]Phase 0: Prerequisites Check[/bold yellow]"))

        # Check for VolumeSnapshot CRDs
        required_crds = [
            "volumesnapshots.snapshot.storage.k8s.io",
            "volumesnapshotclasses.snapshot.storage.k8s.io",
            "volumesnapshotcontents.snapshot.storage.k8s.io",
        ]

        missing_crds = []
        for crd_name in required_crds:
            if not self._check_crd_exists(crd_name):
                missing_crds.append(crd_name)

        if missing_crds:
            self.console.print(
                "\n[yellow]⚠[/yellow] VolumeSnapshot CRDs not found. Installing..."
            )
            for crd in missing_crds:
                self.console.print(f"  - {crd}")

            if not self._install_snapshot_crds():
                return False

            self.snapshot_crds_installed = True
            self.console.print("[green]✔[/green] VolumeSnapshot CRDs installed successfully.")
        else:
            self.console.print("[green]✔[/green] All required CRDs are already installed.")

        # Check for snapshot controller
        if not self._check_snapshot_controller_exists():
            self.console.print("\n[yellow]⚠[/yellow] Snapshot controller not found. Installing...")
            if not self._install_snapshot_controller():
                return False

            self.snapshot_controller_installed = True
            self.console.print("[green]✔[/green] Snapshot controller installed successfully.")
        else:
            self.console.print("[green]✔[/green] Snapshot controller is already running.")

        # Check for VolumeSnapshotClass
        if not self._check_snapshot_class_exists():
            self.console.print(
                f"[yellow]ℹ[/yellow] VolumeSnapshotClass '{self.config.snapshot_class_name}' not found. "
                "Creating temporary one for experiment..."
            )
            self._create_snapshot_class()
            self.snapshot_class_created = True
        else:
            self.console.print(
                f"[green]✔[/green] VolumeSnapshotClass '{self.config.snapshot_class_name}' exists."
            )

        return True

    def _phase_create_source_pvc(self) -> None:
        """Create a PVC in zone1."""
        assert self.zone1
        assert self.source_pvc_name

        self.console.print(
            Rule(f"[bold yellow]Phase 1: Create Source PVC in Zone '{self.zone1}'[/bold yellow]")
        )

        self._create_pvc(self.source_pvc_name, zone=self.zone1)

    def _phase_write_test_data(self) -> None:
        """Create a pod to write test data to the source PVC."""
        assert self.source_pvc_name
        assert self.run_id

        self.console.print("\nWriting test data to source PVC...")

        self.test_data = f"Snapshot test data from run {self.run_id}"
        self.writer_pod_name = f"test-writer-{self.run_id}"

        self._create_writer_pod(self.writer_pod_name, self.source_pvc_name, self.zone1)
        self._wait_for_pod_running(self.writer_pod_name)

        # Ensure the mount point directory exists
        test_file = "/data/test-file.txt"
        k8s_utils.exec_in_pod(
            self.core_v1_api,
            self.writer_pod_name,
            self.namespace,
            ["mkdir", "-p", "/data"],
            self.console,
        )

        # Write test file
        k8s_utils.exec_in_pod(
            self.core_v1_api,
            self.writer_pod_name,
            self.namespace,
            command=["/bin/sh", "-c", f"tee {test_file}"],
            console=self.console,
            stdin_data=self.test_data,
        )

        # Verify write
        output = k8s_utils.exec_in_pod(
            self.core_v1_api,
            self.writer_pod_name,
            self.namespace,
            ["cat", test_file],
            self.console,
        )
        if output.strip() == self.test_data:
            self.console.print("[green]✔[/green] Test data written successfully.")
        else:
            raise RuntimeError("Failed to verify test data write.")

        # We do NOT delete the pod or PVC yet. The snapshot controller needs them.

    def _phase_create_snapshot(self) -> None:
        """Create a VolumeSnapshot from the source PVC."""
        assert self.snapshot_name
        assert self.source_pvc_name

        self.console.print(Rule("[bold yellow]Phase 2: Create VolumeSnapshot[/bold yellow]"))

        self._create_volume_snapshot(self.snapshot_name, self.source_pvc_name)
        self._wait_for_snapshot_ready(self.snapshot_name)

        # Now that the snapshot is ready, we can clean up the source pod and PVC
        self.console.print("\n[dim]Snapshot is ready. Cleaning up source pod and PVC...[/dim]")
        if self.writer_pod_name:
            k8s_utils.delete_pod(
                self.core_v1_api,
                self.writer_pod_name,
                self.namespace,
                self.console,
                self._wait_for,
            )
        self._delete_pvc(self.source_pvc_name)

    def _phase_restore_to_different_zone(self) -> None:
        """Restore the snapshot to a new PVC in zone2."""
        assert self.zone2
        assert self.target_pvc_name
        assert self.snapshot_name

        self.console.print(
            Rule(f"[bold yellow]Phase 3: Restore to PVC in Zone '{self.zone2}'[/bold yellow]")
        )

        self._create_pvc_from_snapshot(
            self.target_pvc_name,
            self.snapshot_name,
            zone=self.zone2
        )

    def _phase_verify_data_integrity(self) -> None:
        """Create a pod in zone2 to verify the data."""
        assert self.target_pvc_name
        assert self.test_data
        assert self.run_id

        self.console.print(Rule("[bold yellow]Phase 4: Verify Data Integrity[/bold yellow]"))

        self.reader_pod_name = f"test-reader-{self.run_id}"
        self._create_writer_pod(self.reader_pod_name, self.target_pvc_name, self.zone2)
        self._wait_for_pod_running(self.reader_pod_name)

        # Verify the pod is in the correct zone
        actual_zone = k8s_utils.get_pod_zone(
            self.core_v1_api, self.reader_pod_name, self.namespace, self.console
        )
        self.console.print(
            f"  [cyan]↳ Reader pod is running in zone: [bold magenta]{actual_zone}[/bold magenta][/cyan]"
        )

        # Read the test file
        test_file = "/data/test-file.txt"
        try:
            output = k8s_utils.exec_in_pod(
                self.core_v1_api,
                self.reader_pod_name,
                self.namespace,
                ["cat", test_file],
                self.console,
            )
            restored_data = output.strip()

            if restored_data == self.test_data:
                self.console.print(
                    "\n[bold green]✔ SUCCESS:[/bold green] Data integrity verified!"
                )
                self.console.print(
                    f"  [cyan]↳ Original data: '{self.test_data}'[/cyan]"
                )
                self.console.print(
                    f"  [cyan]↳ Restored data: '{restored_data}'[/cyan]"
                )

                self.outcome_summary = Panel(
                    "[bold green]Experiment Conclusion: Success[/bold green]\n\n"
                    f"VolumeSnapshot successfully migrated data from zone [bold magenta]{self.zone1}[/bold magenta] to zone [bold magenta]{self.zone2}[/bold magenta].\n\n"
                    "✓ Snapshot created successfully\n"
                    "✓ PVC restored in different zone\n"
                    "✓ Data integrity verified\n\n"
                    "[bold]Conclusion:[/bold] VolumeSnapshots can be used for cross-AZ migration of DevServer data.",
                    title="[bold green]Result[/bold green]",
                    border_style="green",
                )
            else:
                raise RuntimeError(
                    f"Data mismatch! Expected '{self.test_data}', got '{restored_data}'"
                )
        finally:
            k8s_utils.delete_pod(
                self.core_v1_api,
                self.reader_pod_name,
                self.namespace,
                self.console,
                self._wait_for,
            )

    def _phase_cleanup(self) -> None:
        """Clean up all resources created during the experiment."""
        self.console.print(Rule("[bold yellow]Phase 5: Cleanup[/bold yellow]"))

        # The primary cleanup is deleting the namespace, which cleans everything else.
        if self.namespace:
            try:
                self.console.print(f"Deleting namespace '[bold cyan]{self.namespace}[/bold cyan]'...")
                self.core_v1_api.delete_namespace(name=self.namespace)
                # We don't wait here to speed up exit, cluster will handle it.
                self.console.print(f"[green]✔[/green] Namespace '{self.namespace}' deletion initiated.")
            except Exception as exc:
                self.console.print(f"[yellow]⚠[/yellow] Failed to delete namespace: {exc}")

        # We no longer clean up CRDs and the controller by default,
        # as they are useful to keep around.

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------
    def _print_experiment_overview(self) -> None:  # noqa: D102
        self.console.print(
            Panel(
                "[bold]VolumeSnapshot Cross-AZ Migration Experiment[/bold]\n\n"
                "This experiment validates whether VolumeSnapshots can be used to migrate\n"
                "persistent data between availability zones.\n\n"
                "[bold]Test Flow:[/bold]\n"
                "0. Check for VolumeSnapshot CRDs (auto-install if missing)\n"
                "1. Create a PVC in Zone A and write test data\n"
                "2. Create a VolumeSnapshot\n"
                "3. Restore snapshot to a new PVC in Zone B\n"
                "4. Verify data integrity in Zone B\n"
                "5. Cleanup (remove CRDs if we installed them)\n\n"
                "[bold]Hypothesis:[/] Snapshots should enable seamless cross-AZ data migration.",
                title="[bold blue]Experiment Overview[/bold blue]",
                border_style="blue",
            )
        )

    def _determine_zones(self) -> None:
        """Determine availability zones from cluster nodes."""
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

    def _prepare_runtime_identifiers(self) -> None:  # noqa: D102
        super()._prepare_runtime_identifiers()
        self.namespace = f"snapshot-exp-{self.run_id}"
        self.source_pvc_name = "snapshot-test-source"
        self.snapshot_name = "snapshot-test-snap"
        self.target_pvc_name = "snapshot-test-target"

    def _wait_for_crd_deletion(self, crd_name: str, timeout: int = 60):
        """Wait for a CRD to be fully deleted."""
        self.console.print(
            f"[yellow]  - CRD '{crd_name}' is terminating. Waiting up to {timeout}s for it to be removed..."
        )
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                api = client.ApiextensionsV1Api()
                api.read_custom_resource_definition(crd_name)
                time.sleep(5)
            except client.ApiException as exc:
                if exc.status == 404:
                    self.console.print(f"[green]  - CRD '{crd_name}' has been deleted.[/green]")
                    return
                raise
        raise TimeoutError(f"CRD '{crd_name}' was not deleted within {timeout}s.")

    def _check_crd_exists(self, crd_name: str) -> bool:
        """Check if a CRD exists and is not terminating."""
        try:
            api = client.ApiextensionsV1Api()
            crd = api.read_custom_resource_definition(crd_name)
            if crd.metadata.deletion_timestamp:
                self._wait_for_crd_deletion(crd_name)
                return False
            return True
        except client.ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def _check_snapshot_class_exists(self) -> bool:
        """Check if the VolumeSnapshotClass exists."""
        assert self.custom_objects_api
        try:
            self.custom_objects_api.get_cluster_custom_object(
                group=SNAPSHOT_API_GROUP,
                version=SNAPSHOT_API_VERSION,
                plural="volumesnapshotclasses",
                name=self.config.snapshot_class_name,
            )
            return True
        except client.ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def _create_snapshot_class(self) -> None:
        """Create a temporary VolumeSnapshotClass for testing."""
        assert self.custom_objects_api

        body = {
            "apiVersion": f"{SNAPSHOT_API_GROUP}/{SNAPSHOT_API_VERSION}",
            "kind": "VolumeSnapshotClass",
            "metadata": {"name": self.config.snapshot_class_name},
            "driver": "ebs.csi.aws.amazon.com",
            "deletionPolicy": "Delete",
        }

        self.custom_objects_api.create_cluster_custom_object(
            group=SNAPSHOT_API_GROUP,
            version=SNAPSHOT_API_VERSION,
            plural="volumesnapshotclasses",
            body=body,
        )
        self.console.print(
            f"[green]✔[/green] Created VolumeSnapshotClass '{self.config.snapshot_class_name}'."
        )

    def _delete_snapshot_class(self) -> None:
        """Delete the temporary VolumeSnapshotClass."""
        assert self.custom_objects_api
        try:
            self.console.print(
                f"Deleting VolumeSnapshotClass '{self.config.snapshot_class_name}'..."
            )
            self.custom_objects_api.delete_cluster_custom_object(
                group=SNAPSHOT_API_GROUP,
                version=SNAPSHOT_API_VERSION,
                plural="volumesnapshotclasses",
                name=self.config.snapshot_class_name,
            )
            self.console.print(
                f"[green]✔[/green] VolumeSnapshotClass '{self.config.snapshot_class_name}' deleted."
            )
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(
                    "[yellow]ℹ[/yellow] VolumeSnapshotClass already deleted."
                )
            else:
                raise

    def _install_snapshot_crds(self) -> bool:
        """Install VolumeSnapshot CRDs using kubectl."""
        crd_urls = [
            "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/master/client/config/crd/snapshot.storage.k8s.io_volumesnapshotclasses.yaml",
            "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/master/client/config/crd/snapshot.storage.k8s.io_volumesnapshotcontents.yaml",
            "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/master/client/config/crd/snapshot.storage.k8s.io_volumesnapshots.yaml",
        ]

        for url in crd_urls:
            try:
                subprocess.run(
                    ["kubectl", "apply", "-f", url],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.console.print(f"  [dim]Applied {url.split('/')[-1]}[/dim]")
            except subprocess.CalledProcessError as exc:
                self.console.print(
                    f"[bold red]Failed to install CRD from {url}[/bold red]\n"
                    f"Error: {exc.stderr}"
                )
                if "forbidden" in exc.stderr.lower() or "unauthorized" in exc.stderr.lower():
                    self.console.print(
                        "\n[bold red]Permission denied. You need cluster-admin permissions "
                        "to install CRDs.[/bold red]"
                    )
                return False
            except FileNotFoundError:
                self.console.print(
                    "[bold red]kubectl command not found. Please install kubectl.[/bold red]"
                )
                return False

        return True

    def _uninstall_snapshot_crds(self) -> None:
        """Uninstall VolumeSnapshot CRDs."""
        self.console.print("\nUninstalling VolumeSnapshot CRDs...")
        crd_names = [
            "volumesnapshotclasses.snapshot.storage.k8s.io",
            "volumesnapshotcontents.snapshot.storage.k8s.io",
            "volumesnapshots.snapshot.storage.k8s.io",
        ]

        for crd_name in crd_names:
            try:
                subprocess.run(
                    ["kubectl", "delete", "crd", crd_name],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.console.print(f"  [dim]Deleted {crd_name}[/dim]")
            except subprocess.CalledProcessError as exc:
                if "not found" not in exc.stderr.lower():
                    self.console.print(
                        f"[yellow]⚠[/yellow] Warning: Failed to delete CRD {crd_name}: {exc.stderr}"
                    )

        self.console.print("[green]✔[/green] VolumeSnapshot CRDs uninstalled.")

    def _install_snapshot_controller(self) -> bool:
        """Install snapshot-controller using kubectl."""
        controller_urls = [
            "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/master/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml",
            "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/master/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml",
        ]

        for url in controller_urls:
            try:
                subprocess.run(
                    ["kubectl", "apply", "-f", url],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.console.print(f"  [dim]Applied {url.split('/')[-1]}[/dim]")
            except subprocess.CalledProcessError as exc:
                self.console.print(
                    f"[bold red]Failed to install snapshot-controller from {url}[/bold red]\n"
                    f"Error: {exc.stderr}"
                )
                return False

        # Wait for controller to be ready
        self.console.print("  Waiting for snapshot-controller to be ready...")
        if not self._wait_for_snapshot_controller_ready():
            self.console.print(
                "[bold red]Snapshot controller failed to become ready within timeout.[/bold red]"
            )
            return False

        return True

    def _wait_for_snapshot_controller_ready(self, timeout: int = 120) -> bool:
        """Wait for snapshot-controller deployment to be ready."""
        assert self.apps_v1_api

        start_time = time.time()
        last_reason = None

        spinner_columns = (
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}[/bold cyan]"),
            TimeElapsedColumn(),
        )

        with self.console.status(
            spinner_columns, description="Waiting for snapshot-controller..."
        ) as status:
            while time.time() - start_time < timeout:
                try:
                    deployment = self.apps_v1_api.read_namespaced_deployment(
                        name="snapshot-controller",
                        namespace="kube-system",
                    )

                    is_ready = False
                    reason = "Initializing"

                    if deployment.status and deployment.status.conditions:
                        for condition in deployment.status.conditions:
                            if condition.type == "Available":
                                if condition.status == "True":
                                    is_ready = True
                                    break
                                reason = condition.reason or "Unknown"

                    if is_ready:
                        return True

                    if reason != last_reason:
                        status.update(
                            description=(
                                f"Waiting for snapshot-controller... (Reason: {reason})"
                            )
                        )
                        last_reason = reason

                except client.ApiException as exc:
                    if exc.status == 404:
                        status.update(
                            description="Waiting for deployment to be created..."
                        )
                    else:
                        self.console.print(
                            f"\n[yellow]⚠[/yellow] Error checking deployment: {exc}"
                        )

                time.sleep(self.config.poll_interval_seconds)

        # Timeout diagnostics
        self.console.print("\n[bold red]Timeout waiting for snapshot-controller.[/bold red]")
        self._diagnose_deployment_failure("snapshot-controller", "kube-system")
        return False

    def _wait_for_pod_deleted(self, pod_name: str) -> None:
        """Wait for a pod to be deleted."""
        assert self.core_v1_api

        def check_deleted():
            try:
                self.core_v1_api.read_namespaced_pod(
                    name=pod_name, namespace=self.namespace
                )
                return None  # Still exists
            except client.ApiException as exc:
                if exc.status == 404:
                    return True  # Deleted
                raise

        self._wait_for(
            description=f"Pod '{pod_name}' to be deleted",
            check_func=check_deleted,
            timeout=60,
        )

    def _wait_for_pvc_bound(self, pvc_name: str) -> None:
        """Wait for a PVC to be bound."""
        assert self.core_v1_api

        def check_pvc_status():
            try:
                pvc = self.core_v1_api.read_namespaced_persistent_volume_claim(
                    name=pvc_name,
                    namespace=self.namespace,
                )
                if pvc.status.phase == "Bound":
                    return True
                elif pvc.status.phase == "Lost":
                    return False
                return None
            except client.ApiException:
                return None

        self._wait_for(
            description=f"PVC '{pvc_name}' to be bound",
            check_func=check_pvc_status,
        )

    def _wait_for_pod_running(self, pod_name: str) -> None:
        """Wait for a pod to be in Running state."""
        assert self.core_v1_api

        def check_pod_status():
            try:
                pod = self.core_v1_api.read_namespaced_pod(
                    name=pod_name,
                    namespace=self.namespace,
                )
                if pod.status.phase == "Running":
                    return True
                elif pod.status.phase in {"Failed", "Unknown"}:
                    return False
                return None
            except client.ApiException as exc:
                if exc.status == 404:
                    return None
                raise

        self._wait_for(
            description=f"Pod '{pod_name}' to be running",
            check_func=check_pod_status,
        )

    def _wait_for_snapshot_ready(self, snapshot_name: str) -> None:
        """Wait for a VolumeSnapshot to be ready to use."""
        assert self.custom_objects_api

        def check_snapshot_status():
            try:
                snapshot = self.custom_objects_api.get_namespaced_custom_object(
                    group=SNAPSHOT_API_GROUP,
                    version=SNAPSHOT_API_VERSION,
                    namespace=self.namespace,
                    plural="volumesnapshots",
                    name=snapshot_name,
                )
                status = snapshot.get("status", {})
                if status.get("readyToUse"):
                    return True
                if status.get("error"):
                    return False
                return None
            except client.ApiException:
                return None

        self._wait_for(
            description=f"VolumeSnapshot '{snapshot_name}' to be ready",
            check_func=check_snapshot_status,
        )

    def _delete_pod(self, pod_name: str) -> None:
        """Delete a pod."""
        assert self.core_v1_api
        try:
            self.console.print(f"Deleting pod '[bold cyan]{pod_name}[/bold cyan]'...")
            self.core_v1_api.delete_namespaced_pod(
                name=pod_name,
                namespace=self.namespace,
            )
            self._wait_for_pod_deleted(pod_name)
            self.console.print(f"[green]✔[/green] Pod '{pod_name}' deleted.")
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(f"[yellow]ℹ[/yellow] Pod '{pod_name}' already deleted.")
            else:
                raise

    def _create_writer_pod(self, pod_name: str, pvc_name: str, zone: Optional[str]) -> None:
        """Create a simple pod for writing/reading data."""
        assert self.core_v1_api

        pod_spec = {
            "restart_policy": "Never",
            "containers": [
                {
                    "name": "writer",
                    "image": "alpine:latest",
                    "command": ["/bin/sh", "-c", "sleep 3600"],
                    "volume_mounts": [{"name": "data", "mountPath": "/data"}],
                }
            ],
            "volumes": [
                {"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}
            ],
        }

        if zone:
            pod_spec["node_selector"] = {"topology.kubernetes.io/zone": zone}

        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(name=pod_name),
            spec=client.V1PodSpec(**pod_spec),
        )

        self.console.print(f"Creating pod '[bold cyan]{pod_name}[/bold cyan]'...")
        self.core_v1_api.create_namespaced_pod(
            namespace=self.namespace,
            body=pod,
        )

    def _create_pvc(self, pvc_name: str, zone: str, data_source: Optional[dict] = None) -> None:
        """Create a PersistentVolumeClaim."""
        assert self.core_v1_api

        pvc_spec: dict[str, Any] = {
            "access_modes": ["ReadWriteOnce"],
            "storage_class_name": self.config.storage_class_name,
            "resources": client.V1ResourceRequirements(
                requests={"storage": self.config.pvc_size}
            ),
        }

        if data_source:
            pvc_spec["data_source"] = client.V1TypedLocalObjectReference(
                api_group=data_source.get("apiGroup"),
                kind=data_source["kind"],
                name=data_source["name"],
            )

        pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(name=pvc_name),
            spec=client.V1PersistentVolumeClaimSpec(**pvc_spec),
        )

        self.console.print(f"Creating PVC '[bold cyan]{pvc_name}[/bold cyan]' in zone '{zone}'...")
        self.core_v1_api.create_namespaced_persistent_volume_claim(
            namespace=self.namespace,
            body=pvc,
        )

    def _create_pvc_from_snapshot(self, pvc_name: str, snapshot_name: str, zone: str) -> None:
        """Create a PVC from a VolumeSnapshot."""
        data_source = {
            "name": snapshot_name,
            "kind": "VolumeSnapshot",
            "apiGroup": SNAPSHOT_API_GROUP,
        }
        self._create_pvc(pvc_name, zone, data_source=data_source)

    def _delete_pvc(self, pvc_name: str) -> None:
        """Delete a PersistentVolumeClaim."""
        assert self.core_v1_api
        try:
            self.console.print(f"Deleting PVC '[bold cyan]{pvc_name}[/bold cyan]'...")
            self.core_v1_api.delete_namespaced_persistent_volume_claim(
                name=pvc_name,
                namespace=self.namespace,
            )
            self.console.print(f"[green]✔[/green] PVC '{pvc_name}' deleted.")
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print(f"[yellow]ℹ[/yellow] PVC '{pvc_name}' already deleted.")
            else:
                raise

    def _create_volume_snapshot(self, snapshot_name: str, pvc_name: str) -> None:
        """Create a VolumeSnapshot from a PVC."""
        assert self.custom_objects_api

        body = {
            "apiVersion": f"{SNAPSHOT_API_GROUP}/{SNAPSHOT_API_VERSION}",
            "kind": "VolumeSnapshot",
            "metadata": {
                "name": snapshot_name,
                "namespace": self.namespace,
            },
            "spec": {
                "volumeSnapshotClassName": self.config.snapshot_class_name,
                "source": {"persistentVolumeClaimName": pvc_name},
            },
        }

        self.console.print(
            f"Creating VolumeSnapshot '[bold cyan]{snapshot_name}[/bold cyan]' from PVC '{pvc_name}'..."
        )
        self.custom_objects_api.create_namespaced_custom_object(
            group=SNAPSHOT_API_GROUP,
            version=SNAPSHOT_API_VERSION,
            namespace=self.namespace,
            plural="volumesnapshots",
            body=body,
        )
        self.console.print(f"[green]✔[/green] VolumeSnapshot '{snapshot_name}' created.")

    def _delete_volume_snapshot(self, snapshot_name: str) -> None:
        """Delete a VolumeSnapshot."""
        assert self.custom_objects_api
        try:
            self.console.print(f"Deleting VolumeSnapshot '[bold cyan]{snapshot_name}[/bold cyan]'...")
            self.custom_objects_api.delete_namespaced_custom_object(
                group=SNAPSHOT_API_GROUP,
                version=SNAPSHOT_API_VERSION,
                namespace=self.namespace,
                plural="volumesnapshots",
                name=snapshot_name,
            )
            self.console.print(f"[green]✔[/green] VolumeSnapshot '{snapshot_name}' deleted.")
        except client.ApiException as exc:
            if exc.status == 404:
                self.console.print("[yellow]ℹ[/yellow] VolumeSnapshot already deleted.")
            else:
                raise

    def _diagnose_deployment_failure(self, name: str, namespace: str):
        """Prints diagnostic information for a failed deployment."""
        self.console.print(
            Panel(
                f"[bold red]Deployment '{name}' in namespace '{namespace}' failed to become ready.[/bold red]\n\n"
                "This could be due to: \n"
                "1. Insufficient permissions for the snapshot-controller deployment.\n"
                "2. The deployment might be stuck in a pending state.\n"
                "3. The cluster might be under heavy load.\n\n"
                "Please check the following:\n"
                "  - The snapshot-controller pod logs for errors.\n"
                "  - The cluster's node status and resource availability.\n"
                "  - The snapshot-controller deployment's status conditions.\n\n"
                "You might need to reinstall the snapshot-controller or check its logs.",
                title="[bold red]Deployment Diagnosis[/bold red]",
                border_style="red",
            )
        )

__all__ = ["SnapshotMigrationExperiment", "ExperimentConfig"]
