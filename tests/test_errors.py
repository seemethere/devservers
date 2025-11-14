import time
import pytest
from kubernetes import client
from tests.conftest import TEST_NAMESPACE
from typing import Any, Dict
from devservers.crds.const import CRD_GROUP, CRD_VERSION, CRD_PLURAL_DEVSERVER
from tests.helpers import build_devserver_spec

# Constants from the main test file
NAMESPACE: str = TEST_NAMESPACE


def test_devserver_missing_flavor_error(
    operator_running: Any, k8s_clients: Dict[str, Any], test_ssh_public_key: str
) -> None:
    """
    Tests that creating a DevServer with a non-existent flavor
    properly handles the error condition.
    """
    apps_v1 = k8s_clients["apps_v1"]
    custom_objects_api = k8s_clients["custom_objects_api"]

    devserver_name = "test-missing-flavor"
    devserver_manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServer",
        "metadata": {"name": devserver_name, "namespace": NAMESPACE},
        "spec": build_devserver_spec(
            flavor="non-existent-flavor",
            public_key="ssh-rsa AAA...",
            ttl="1h",
            image="ubuntu:22.04",
        ),
    }

    try:
        custom_objects_api.create_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL_DEVSERVER,
            body=devserver_manifest,
        )

        time.sleep(2)  # Give operator time to process

        # Verify that no deployment was created due to the error
        with pytest.raises(client.ApiException) as exc_info:
            apps_v1.read_namespaced_deployment(
                name=devserver_name, namespace=NAMESPACE
            )
        assert isinstance(exc_info.value, client.ApiException)
        assert exc_info.value.status == 404, (
            "Deployment should not exist for invalid flavor"
        )

    finally:
        # Cleanup
        try:
            custom_objects_api.delete_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=NAMESPACE,
                plural=CRD_PLURAL_DEVSERVER,
                name=devserver_name,
            )
        except client.ApiException as e:
            if e.status != 404:
                raise
