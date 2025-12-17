#!/usr/bin/env python3
"""
Build worker entrypoint.

This process consumes build jobs from RabbitMQ and executes them using BuildKit.
"""

import logging
import os
import sys


def setup_logging() -> None:
    """Configure logging for the worker."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> None:
    """Main entrypoint for the build worker."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Build worker starting...")
    logger.info(f"BUILDKIT_HOST: {os.environ.get('BUILDKIT_HOST', 'not set')}")
    logger.info(f"RABBITMQ_HOST: {os.environ.get('RABBITMQ_HOST', 'not set')}")

    from .consumer import create_worker

    worker = create_worker()
    worker.run()


if __name__ == "__main__":
    main()
