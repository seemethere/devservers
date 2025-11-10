from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Type, TypeVar, Generator
import time
from kubernetes import client, watch

from ..utils.kube import KubernetesConfigurationError, configure_kube_client

from .errors import KubeConfigError

# A generic type for BaseCustomResource subclasses
T = TypeVar("T", bound="BaseCustomResource")


def _is_status_subset(subset: Dict[str, Any], superset: Dict[str, Any]) -> bool:
    """
    Checks if the `subset` dictionary is a subset of the `superset` dictionary.
    """
    if not superset:
        return False
    for key, value in subset.items():
        if key not in superset or superset[key] != value:
            return False
    return True


def _get_k8s_api() -> client.CustomObjectsApi:
    """
    Initializes and returns the Kubernetes CustomObjectsApi client.

    This function will raise a RuntimeError with a helpful message if the
    Kubernetes configuration cannot be loaded.
    """
    try:
        configure_kube_client()
    except KubernetesConfigurationError as exc:
        raise KubeConfigError(
            "Kubernetes configuration not found. Please ensure you have a valid "
            "kubeconfig file or are running in-cluster."
        ) from exc

    return client.CustomObjectsApi()


@dataclass
class ObjectMeta:
    name: str
    namespace: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ObjectMeta":
        """
        Constructs an ObjectMeta from a dictionary, ignoring unknown fields.
        This makes it robust to extra metadata from the Kubernetes API.
        """
        known_field_names = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in known_field_names}
        return cls(**filtered_data)


class BaseCustomResource:
    group: str
    version: str
    plural: str
    namespaced: bool

    # These attributes are expected to be defined by subclasses, but are declared
    # here for type-hinting purposes so that generic methods can be type-checked.
    metadata: ObjectMeta
    spec: Dict[str, Any]
    status: Dict[str, Any]

    def __init__(self, api: Optional[client.CustomObjectsApi] = None) -> None:
        self.api = api or _get_k8s_api()

    @classmethod
    def get(
        cls,
        name: str,
        *,
        namespace: Optional[str] = None,
        api: Optional[client.CustomObjectsApi] = None,
    ) -> "BaseCustomResource":

        api_instance = api or _get_k8s_api()
        if cls.namespaced:
            if not namespace:
                raise ValueError("Namespace is required for namespaced resources")
            data = api_instance.get_namespaced_custom_object(
                group=cls.group,
                version=cls.version,
                namespace=namespace,
                plural=cls.plural,
                name=name,
            )
        else:
            if namespace:
                raise ValueError("Cluster-scoped resources must not receive a namespace")
            data = api_instance.get_cluster_custom_object(
                group=cls.group,
                version=cls.version,
                plural=cls.plural,
                name=name,
            )

        meta = ObjectMeta.from_dict(data["metadata"])
        return cls(
            metadata=meta, spec=data["spec"], status=data.get("status", {}), api=api
        )

    @classmethod
    def create(
        cls: Type[T],
        metadata: ObjectMeta,
        spec: Dict[str, Any],
        api: Optional[client.CustomObjectsApi] = None,
    ) -> T:
        """Creates a custom resource in the cluster."""
        api_instance = api or _get_k8s_api()
        resource = cls(metadata=metadata, spec=spec, api=api_instance)

        if cls.namespaced:
            if not metadata.namespace:
                raise ValueError("Namespace is required for namespaced resources")
            created_obj = api_instance.create_namespaced_custom_object(
                group=cls.group,
                version=cls.version,
                namespace=metadata.namespace,
                plural=cls.plural,
                body=resource.to_dict(),
            )
        else:
            if metadata.namespace:
                raise ValueError("Namespace must not be set for cluster-scoped resources")
            created_obj = api_instance.create_cluster_custom_object(
                group=cls.group,
                version=cls.version,
                plural=cls.plural,
                body=resource.to_dict(),
            )

        resource.status = created_obj.get("status", {})
        return resource

    @classmethod
    def list(
        cls: Type[T],
        namespace: Optional[str] = None,
        api: Optional[client.CustomObjectsApi] = None,
    ) -> List[T]:
        """Lists all custom resources."""
        api_instance = api or _get_k8s_api()

        if cls.namespaced:
            if not namespace:
                raise ValueError("Namespace is required for namespaced resources")
            result = api_instance.list_namespaced_custom_object(
                group=cls.group,
                version=cls.version,
                namespace=namespace,
                plural=cls.plural,
            )
        else:
            if namespace:
                raise ValueError("Namespace must not be set for cluster-scoped resources")
            result = api_instance.list_cluster_custom_object(
                group=cls.group,
                version=cls.version,
                plural=cls.plural,
            )

        return [
            cls(
                metadata=ObjectMeta.from_dict(item["metadata"]),
                spec=item["spec"],
                status=item.get("status", {}),
                api=api_instance,
            )
            for item in result["items"]
        ]

    def update(self: T) -> T:
        """Replaces the custom resource in the cluster with the current object's state."""
        if self.namespaced:
            if not self.metadata.namespace:
                raise ValueError("Namespace is required for namespaced resources")
            updated_obj = self.api.replace_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.metadata.namespace,
                plural=self.plural,
                name=self.metadata.name,
                body=self.to_dict(),
            )
        else:
            if self.metadata.namespace:
                raise ValueError("Namespace must not be set for cluster-scoped resources")
            updated_obj = self.api.replace_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.plural,
                name=self.metadata.name,
                body=self.to_dict(),
            )

        self.spec = updated_obj["spec"]
        self.status = updated_obj.get("status", {})
        return self

    def patch(self: T, patch_body: Dict[str, Any]) -> T:
        """Patches the custom resource in the cluster."""
        if self.namespaced:
            if not self.metadata.namespace:
                raise ValueError("Namespace is required for namespaced resources")
            patched_obj = self.api.patch_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.metadata.namespace,
                plural=self.plural,
                name=self.metadata.name,
                body=patch_body,
            )
        else:
            if self.metadata.namespace:
                raise ValueError("Namespace must not be set for cluster-scoped resources")
            patched_obj = self.api.patch_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.plural,
                name=self.metadata.name,
                body=patch_body,
            )

        self.spec = patched_obj["spec"]
        self.status = patched_obj.get("status", {})
        return self

    def delete(self) -> None:
        """Deletes the custom resource from the cluster."""
        if self.namespaced:
            if not self.metadata.namespace:
                raise ValueError("Namespace is required for namespaced resources")
            self.api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.metadata.namespace,
                plural=self.plural,
                name=self.metadata.name,
                body=client.V1DeleteOptions(),
            )
        else:
            if self.metadata.namespace:
                raise ValueError("Namespace must not be set for cluster-scoped resources")
            self.api.delete_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.plural,
                name=self.metadata.name,
                body=client.V1DeleteOptions(),
            )

    def refresh(self) -> None:
        """Refreshes the object from the cluster, updating spec and status."""
        obj = self.get(
            name=self.metadata.name,
            namespace=self.metadata.namespace,
            api=self.api,
        )
        self.spec = obj.spec
        self.status = obj.status

    def watch(self: T, timeout_seconds: Optional[int] = None):
        """
        Watches the custom resource for events.

        Returns:
            A watch object that can be iterated to get events.
        """
        if self.namespaced:
            if not self.metadata.namespace:
                raise ValueError("Namespace is required for namespaced resources")
            return watch.Watch().stream(
                self.api.list_namespaced_custom_object,
                group=self.group,
                version=self.version,
                namespace=self.metadata.namespace,
                plural=self.plural,
                field_selector=f"metadata.name={self.metadata.name}",
                timeout_seconds=timeout_seconds,
            )
        else:
            raise NotImplementedError("Watching cluster-scoped resources is not yet implemented.")

    def to_dict(self) -> Dict[str, Any]:
        # Clean up metadata from asdict, removing None values and empty collections
        metadata_dict = {
            k: v for k, v in asdict(self.metadata).items() if v is not None and v
        }

        body = {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": self.__class__.__name__,
            "metadata": metadata_dict,
            "spec": self.spec,
        }
        # The status should not be sent on create/update operations, but is present for completeness.
        # The API server will ignore it for create/replace.
        if self.status:
            body["status"] = self.status

        return body

    def wait_for_status(self: T, status: Dict[str, Any], timeout: int = 30) -> Generator[Dict[str, Any], None, None]:
        """Waits for the custom resource to reach the desired status, yielding events along the way."""
        start_time = time.time()

        # First, check the current state of the object. It might already be in the desired state.
        self.refresh()
        if _is_status_subset(status, self.status):
            return

        while time.time() - start_time < timeout:
            remaining_timeout = int(timeout - (time.time() - start_time))
            if remaining_timeout <= 0:
                break

            # The watch will time out and the for loop will complete.
            # The outer while loop will then re-establish the watch if there's time remaining.
            watch_had_events = False
            for event in self.watch(timeout_seconds=remaining_timeout):
                watch_had_events = True
                yield event
                obj = event["object"]
                if "status" in obj and _is_status_subset(status, obj["status"]):
                    # The event indicates we might be in the desired state.
                    # Refresh the object to get the absolute latest state and confirm.
                    self.refresh()
                    if _is_status_subset(status, self.status):
                        return

            # If the watch stream was empty, it may have timed out.
            # We should refresh and check the status before potentially re-watching.
            if not watch_had_events:
                self.refresh()
                if _is_status_subset(status, self.status):
                    return

        # After the while loop (due to timeout), do one last refresh and check.
        self.refresh()
        if _is_status_subset(status, self.status):
            return

        raise TimeoutError(
            f"Custom resource {self.metadata.name} did not reach status {status} within {timeout} seconds."
        )
