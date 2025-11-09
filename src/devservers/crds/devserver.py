from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, Type
from types import TracebackType
import time

from kubernetes import client
from kubernetes.client import ApiException
from .base import BaseCustomResource, ObjectMeta
from .const import CRD_GROUP, CRD_VERSION, CRD_PLURAL_DEVSERVER


@dataclass
class PersistentHomeSpec:
    """A dataclass to represent the persistentHome field in the DevServer spec."""

    enabled: bool
    size: str = "10Gi"


@dataclass
class DevServer(BaseCustomResource):
    group = CRD_GROUP
    version = CRD_VERSION
    plural = CRD_PLURAL_DEVSERVER
    namespaced = True

    metadata: ObjectMeta
    spec: Dict[str, Any]
    status: Dict[str, Any] = field(default_factory=dict, init=False)

    def __init__(
        self,
        metadata: ObjectMeta,
        spec: Dict[str, Any],
        status: Optional[Dict[str, Any]] = None,
        api: Optional[client.CustomObjectsApi] = None,
        wait_timeout: int = 300,
    ) -> None:
        super().__init__(api)
        self.metadata = metadata
        self.spec = spec
        self.status = status or {}
        self.wait_timeout = wait_timeout
        self._context_resource: Optional["DevServer"] = None

    def wait_for_ready(self, timeout: int = 60) -> None:
        """Waits for the underlying pod's containers to be ready."""
        start = time.time()
        now = start
        for _ in self.wait_for_status(
            status={"phase": "Running"}, timeout=timeout
        ):
            now = time.time()
            if now - start > timeout:
                raise TimeoutError(
                    f"DevServer {self.metadata.name} did not become ready within {timeout} seconds."
                )
        core_v1 = client.CoreV1Api(self.api.api_client)
        pod_name = f"{self.metadata.name}-0"

        while time.time() - start < timeout:
            try:
                pod = core_v1.read_namespaced_pod(
                    name=pod_name, namespace=self.metadata.namespace
                )
                if pod.status.container_statuses and all(
                    cs.ready for cs in pod.status.container_statuses
                ):
                    return  # All containers are ready
            except ApiException as e:
                if e.status != 404:
                    raise
            time.sleep(1)

        raise TimeoutError(
            f"Pod {pod_name} did not become ready within {timeout} seconds."
        )

    @property
    def persistent_home(self) -> Optional[PersistentHomeSpec]:
        """
        Provides typed access to the persistentHome spec.
        Returns:
            A PersistentHomeSpec object if persistentHome is defined in the spec,
            otherwise None.
        """
        persistent_home_data = self.spec.get("persistentHome")
        if persistent_home_data:
            return PersistentHomeSpec(**persistent_home_data)
        return None

    @persistent_home.setter
    def persistent_home(self, value: Optional[PersistentHomeSpec]) -> None:
        """
        Sets the persistentHome spec from a PersistentHomeSpec object.
        """
        if value:
            self.spec["persistentHome"] = asdict(value)
        elif "persistentHome" in self.spec:
            del self.spec["persistentHome"]

    def __enter__(self) -> "DevServer":
        """
        Creates the DevServer resource when entering the context manager and
        returns the freshly created resource instance.
        """
        if self._context_resource is not None:
            raise RuntimeError("DevServer context manager already active")

        created = self.__class__.create(
            metadata=self.metadata,
            spec=self.spec,
            api=self.api,
        )


        created.wait_for_ready(timeout=self.wait_timeout)

        self._context_resource = created
        return created

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        """
        Deletes the DevServer resource when exiting the context manager.
        """
        resource = self._context_resource
        self._context_resource = None

        if resource is None:
            return False

        try:
            resource.delete()
        except ApiException as api_exc:
            if api_exc.status != 404 and exc_type is None:
                raise
        except Exception:
            if exc_type is None:
                raise

        return False
