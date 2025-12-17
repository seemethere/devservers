"""
RabbitMQ client for build job queue management.
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel

logger = logging.getLogger(__name__)


# Queue names for different priorities
QUEUE_HIGH = "builds.high"
QUEUE_NORMAL = "builds.normal"
QUEUE_LOW = "builds.low"
EXCHANGE_NAME = "builds"
DLX_EXCHANGE = "builds.dlx"
DLQ_QUEUE = "builds.dead"


@dataclass
class BuildMessage:
    """Message structure for build jobs."""

    build_name: str
    build_namespace: str
    spec: Dict[str, Any]
    priority: str = "normal"
    attempt: int = 1
    max_attempts: int = 3

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "BuildMessage":
        """Deserialize from JSON string."""
        return cls(**json.loads(data))


class BuildQueue:
    """
    RabbitMQ client for managing build job queues.

    Supports priority queues (high, normal, low) and dead letter queue
    for failed builds.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        virtual_host: str = "/",
    ):
        """
        Initialize the BuildQueue client.

        Args:
            host: RabbitMQ host (default: from RABBITMQ_HOST env var)
            port: RabbitMQ port (default: from RABBITMQ_PORT env var or 5672)
            username: RabbitMQ username (default: from RABBITMQ_USERNAME env var)
            password: RabbitMQ password (default: from RABBITMQ_PASSWORD env var)
            virtual_host: RabbitMQ virtual host
        """
        self.host = host or os.environ.get("RABBITMQ_HOST", "localhost")
        self.port = port or int(os.environ.get("RABBITMQ_PORT", "5672"))
        self.username = username or os.environ.get("RABBITMQ_USERNAME", "guest")
        self.password = password or os.environ.get("RABBITMQ_PASSWORD", "guest")
        self.virtual_host = virtual_host

        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[BlockingChannel] = None

    def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(self.username, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            virtual_host=self.virtual_host,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._setup_queues()
        logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")

    def _setup_queues(self) -> None:
        """Set up exchanges and queues."""
        if not self._channel:
            raise RuntimeError("Not connected to RabbitMQ")

        # Declare dead letter exchange and queue
        self._channel.exchange_declare(
            exchange=DLX_EXCHANGE,
            exchange_type="direct",
            durable=True,
        )
        self._channel.queue_declare(
            queue=DLQ_QUEUE,
            durable=True,
        )
        self._channel.queue_bind(
            queue=DLQ_QUEUE,
            exchange=DLX_EXCHANGE,
            routing_key="dead",
        )

        # Declare main exchange
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="direct",
            durable=True,
        )

        # Declare priority queues with DLX
        for queue_name in [QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]:
            self._channel.queue_declare(
                queue=queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DLX_EXCHANGE,
                    "x-dead-letter-routing-key": "dead",
                },
            )
            # Bind with priority as routing key
            priority = queue_name.split(".")[-1]
            self._channel.queue_bind(
                queue=queue_name,
                exchange=EXCHANGE_NAME,
                routing_key=priority,
            )

        logger.info("RabbitMQ queues and exchanges set up")

    def close(self) -> None:
        """Close the RabbitMQ connection."""
        if self._connection and self._connection.is_open:
            self._connection.close()
            logger.info("RabbitMQ connection closed")

    def __enter__(self) -> "BuildQueue":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def publish(self, message: BuildMessage) -> None:
        """
        Publish a build message to the appropriate priority queue.

        Args:
            message: BuildMessage to publish
        """
        if not self._channel:
            raise RuntimeError("Not connected to RabbitMQ")

        routing_key = message.priority
        body = message.to_json()

        self._channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
            body=body.encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Persistent
                content_type="application/json",
            ),
        )
        logger.info(
            f"Published build job '{message.build_namespace}/{message.build_name}' "
            f"to queue with priority '{message.priority}'"
        )

    def consume(
        self,
        callback: Callable[[BuildMessage], bool],
        prefetch_count: int = 1,
    ) -> None:
        """
        Start consuming build messages from all priority queues.

        Consumes from high priority first, then normal, then low.

        Args:
            callback: Function to call with each message. Should return True
                     on success, False on failure.
            prefetch_count: Number of messages to prefetch.
        """
        if not self._channel:
            raise RuntimeError("Not connected to RabbitMQ")

        self._channel.basic_qos(prefetch_count=prefetch_count)

        def on_message(ch, method, properties, body):
            try:
                message = BuildMessage.from_json(body.decode("utf-8"))
                logger.info(
                    f"Received build job '{message.build_namespace}/{message.build_name}'"
                )

                success = callback(message)

                if success:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.info(
                        f"Build job '{message.build_namespace}/{message.build_name}' "
                        "completed successfully"
                    )
                else:
                    # Check if we should retry
                    if message.attempt < message.max_attempts:
                        # Republish with incremented attempt
                        message.attempt += 1
                        self.publish(message)
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        logger.warning(
                            f"Build job '{message.build_namespace}/{message.build_name}' "
                            f"failed, retrying (attempt {message.attempt})"
                        )
                    else:
                        # Send to DLQ by rejecting without requeue
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                        logger.error(
                            f"Build job '{message.build_namespace}/{message.build_name}' "
                            f"failed after {message.max_attempts} attempts, sent to DLQ"
                        )
            except Exception as e:
                logger.exception(f"Error processing message: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        # Consume from queues in priority order
        for queue_name in [QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]:
            self._channel.basic_consume(
                queue=queue_name,
                on_message_callback=on_message,
            )

        logger.info("Starting to consume build messages...")
        self._channel.start_consuming()

    def get_queue_depth(self, priority: str = "normal") -> int:
        """
        Get the number of messages in a queue.

        Args:
            priority: Queue priority (high, normal, low)

        Returns:
            Number of messages in the queue
        """
        if not self._channel:
            raise RuntimeError("Not connected to RabbitMQ")

        queue_name = f"builds.{priority}"
        result = self._channel.queue_declare(queue=queue_name, passive=True)
        return result.method.message_count
