"""
RabbitMQ consumer for processing build jobs.
"""

import asyncio
import logging
import signal
import sys
from typing import Any, Dict, Optional

from kubernetes import config as k8s_config

from ..queue.rabbitmq import BuildQueue, BuildMessage
from ..operator.build.reconciler import update_build_status
from .builder import BuildKitBuilder, BuildResult

logger = logging.getLogger(__name__)


class BuildWorker:
    """
    Worker that consumes build jobs from RabbitMQ and executes them.
    """

    def __init__(
        self,
        builder: Optional[BuildKitBuilder] = None,
    ):
        """
        Initialize the build worker.

        Args:
            builder: BuildKitBuilder instance (default: creates new instance)
        """
        self.builder = builder or BuildKitBuilder()
        self.queue: Optional[BuildQueue] = None
        self._shutdown = False

    def setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown = True
            if self.queue:
                self.queue.close()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    def process_build(self, message: BuildMessage) -> bool:
        """
        Process a single build message.

        Args:
            message: BuildMessage from the queue

        Returns:
            True if build succeeded, False otherwise
        """
        build_name = message.build_name
        build_namespace = message.build_namespace
        spec = message.spec

        logger.info(f"Processing build '{build_namespace}/{build_name}'")

        # Run the async build in the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                self._process_build_async(build_name, build_namespace, spec)
            )
            return result
        finally:
            loop.close()

    async def _process_build_async(
        self,
        build_name: str,
        build_namespace: str,
        spec: Dict[str, Any],
    ) -> bool:
        """
        Async implementation of build processing.

        Args:
            build_name: Build resource name
            build_namespace: Build resource namespace
            spec: Build spec

        Returns:
            True if build succeeded, False otherwise
        """
        try:
            # Update status to Building
            await update_build_status(
                build_name,
                build_namespace,
                phase="Building",
                message="Build started",
                logger=logger,
            )

            # Execute the build
            result = await self.builder.build(
                build_name=build_name,
                build_namespace=build_namespace,
                spec=spec,
            )

            # Update status based on result
            if result.success:
                await update_build_status(
                    build_name,
                    build_namespace,
                    phase="Succeeded",
                    message="Build completed successfully",
                    digest=result.digest,
                    logger=logger,
                )
                return True
            else:
                await update_build_status(
                    build_name,
                    build_namespace,
                    phase="Failed",
                    message=result.error or "Build failed",
                    logger=logger,
                )
                return False

        except Exception as e:
            logger.exception(f"Build processing failed: {e}")
            try:
                await update_build_status(
                    build_name,
                    build_namespace,
                    phase="Failed",
                    message=f"Build processing error: {e}",
                    logger=logger,
                )
            except Exception:
                logger.exception("Failed to update build status after error")
            return False

    def run(self) -> None:
        """
        Start the worker and begin consuming messages.

        This method blocks until shutdown.
        """
        logger.info("Starting build worker...")

        # Set up signal handlers
        self.setup_signal_handlers()

        # Load Kubernetes config
        try:
            k8s_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
            logger.info("Loaded local Kubernetes config")

        # Connect to RabbitMQ and start consuming
        self.queue = BuildQueue()
        self.queue.connect()

        try:
            logger.info("Starting to consume build messages...")
            self.queue.consume(
                callback=self.process_build,
                prefetch_count=1,
            )
        except KeyboardInterrupt:
            logger.info("Worker interrupted, shutting down...")
        finally:
            if self.queue:
                self.queue.close()

        logger.info("Build worker stopped")


def create_worker() -> BuildWorker:
    """
    Factory function to create a BuildWorker instance.

    Returns:
        Configured BuildWorker instance
    """
    return BuildWorker()
