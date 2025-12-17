"""
BuildKit client for executing container builds.
"""

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Result of a container build."""

    success: bool
    digest: Optional[str] = None
    error: Optional[str] = None
    logs: str = ""


class BuildKitBuilder:
    """
    Client for executing builds via BuildKit.

    Uses buildctl CLI to communicate with BuildKit daemon.
    """

    def __init__(
        self,
        buildkit_addr: Optional[str] = None,
    ):
        """
        Initialize the BuildKit builder.

        Args:
            buildkit_addr: BuildKit daemon address (default: from BUILDKIT_HOST env var)
        """
        self.buildkit_addr = buildkit_addr or os.environ.get(
            "BUILDKIT_HOST", "tcp://default.buildkit-system.svc.cluster.local:1234"
        )

    async def build(
        self,
        build_name: str,
        build_namespace: str,
        spec: Dict[str, Any],
        status_callback: Optional[callable] = None,
    ) -> BuildResult:
        """
        Execute a container build.

        Args:
            build_name: Name of the Build resource
            build_namespace: Namespace of the Build resource
            spec: Build spec from the Build CR
            status_callback: Optional callback for status updates

        Returns:
            BuildResult with success status, digest, and logs
        """
        context = spec.get("context", {})
        dockerfile = spec.get("dockerfile", "Dockerfile")
        destination = spec["destination"]
        build_args = spec.get("buildArgs", [])
        cache_config = spec.get("cache", {})

        try:
            # Prepare build context
            context_path = await self._prepare_context(context)

            # Build command
            cmd = self._build_command(
                context_path=context_path,
                dockerfile=dockerfile,
                destination=destination,
                build_args=build_args,
                cache_config=cache_config,
            )

            logger.info(f"Starting build: {' '.join(cmd)}")

            if status_callback:
                await status_callback("Building", "Build in progress")

            # Execute build
            result = await self._execute_build(cmd)

            if result.success:
                logger.info(
                    f"Build '{build_namespace}/{build_name}' succeeded: {result.digest}"
                )
            else:
                logger.error(
                    f"Build '{build_namespace}/{build_name}' failed: {result.error}"
                )

            return result

        except Exception as e:
            logger.exception(f"Build failed with exception: {e}")
            return BuildResult(
                success=False,
                error=str(e),
            )

    async def _prepare_context(self, context: Dict[str, Any]) -> str:
        """
        Prepare the build context.

        For git contexts, clones the repository.
        For configMap contexts, extracts files from the ConfigMap.

        Args:
            context: Context configuration from Build spec

        Returns:
            Path to the build context directory
        """
        if "git" in context:
            return await self._clone_git_context(context["git"])
        elif "configMap" in context:
            return await self._extract_configmap_context(context["configMap"])
        else:
            raise ValueError("No valid context source specified")

    async def _clone_git_context(self, git_config: Dict[str, Any]) -> str:
        """Clone a git repository as build context."""
        url = git_config["url"]
        ref = git_config.get("ref", "main")
        sub_path = git_config.get("subPath", "")

        # Create temporary directory
        tmpdir = tempfile.mkdtemp(prefix="build-context-")

        # Clone repository
        clone_cmd = ["git", "clone", "--depth=1", "--branch", ref, url, tmpdir]

        process = await asyncio.create_subprocess_exec(
            *clone_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Git clone failed: {stderr.decode()}")

        context_path = tmpdir
        if sub_path:
            context_path = os.path.join(tmpdir, sub_path)
            if not os.path.exists(context_path):
                raise RuntimeError(f"SubPath '{sub_path}' does not exist in repository")

        return context_path

    async def _extract_configmap_context(self, configmap_name: str) -> str:
        """Extract build context from a ConfigMap."""
        # This would use the Kubernetes API to fetch the ConfigMap
        # and extract its contents to a temporary directory
        # For simplicity, we'll implement a basic version
        from kubernetes import client

        tmpdir = tempfile.mkdtemp(prefix="build-context-")

        core_v1 = client.CoreV1Api()
        # Assume configmap is in the same namespace as we're running
        namespace = os.environ.get("POD_NAMESPACE", "default")

        configmap = await asyncio.to_thread(
            core_v1.read_namespaced_config_map,
            name=configmap_name,
            namespace=namespace,
        )

        # Write each key as a file
        for key, value in (configmap.data or {}).items():
            file_path = os.path.join(tmpdir, key)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(value)

        # Handle binary data
        for key, value in (configmap.binary_data or {}).items():
            file_path = os.path.join(tmpdir, key)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                import base64
                f.write(base64.b64decode(value))

        return tmpdir

    def _build_command(
        self,
        context_path: str,
        dockerfile: str,
        destination: str,
        build_args: List[Dict[str, str]],
        cache_config: Dict[str, Any],
    ) -> List[str]:
        """Build the buildctl command."""
        cmd = [
            "buildctl",
            "--addr", self.buildkit_addr,
            "build",
            "--frontend", "dockerfile.v0",
            "--local", f"context={context_path}",
            "--local", f"dockerfile={context_path}",
            "--opt", f"filename={dockerfile}",
            "--output", f"type=image,name={destination},push=true",
        ]

        # Add build args
        for arg in build_args:
            cmd.extend(["--opt", f"build-arg:{arg['name']}={arg['value']}"])

        # Add cache configuration
        if cache_config.get("enabled", True):
            cache_registry = cache_config.get("registry")
            if cache_registry:
                cmd.extend([
                    "--export-cache", f"type=registry,ref={cache_registry},mode=max",
                    "--import-cache", f"type=registry,ref={cache_registry}",
                ])

        return cmd

    async def _execute_build(self, cmd: List[str]) -> BuildResult:
        """Execute the build command and parse results."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout, _ = await process.communicate()
        logs = stdout.decode()

        if process.returncode == 0:
            # Try to extract digest from logs
            digest = self._extract_digest(logs)
            return BuildResult(
                success=True,
                digest=digest,
                logs=logs,
            )
        else:
            return BuildResult(
                success=False,
                error=f"Build failed with exit code {process.returncode}",
                logs=logs,
            )

    def _extract_digest(self, logs: str) -> Optional[str]:
        """Extract image digest from build logs."""
        import re

        # Look for digest in output
        # BuildKit typically outputs: pushing manifest for xxx@sha256:xxx
        pattern = r"@(sha256:[a-f0-9]{64})"
        match = re.search(pattern, logs)
        if match:
            return match.group(1)

        return None
