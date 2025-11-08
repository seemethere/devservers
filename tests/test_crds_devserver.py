import unittest.mock
from unittest.mock import patch

import pytest
from kubernetes.config import ConfigException
from kubernetes.client import ApiException

from devservers.crds.base import ObjectMeta, _get_k8s_api
from devservers.crds.devserver import DevServer
from devservers.crds.errors import KubeConfigError

NAMESPACE = "test-namespace"
DEVSERVER_NAME = "test-devserver"


def test_devserver_create(mock_k8s_api):
    """Test the DevServer.create classmethod."""
    metadata = ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE)
    spec = {"flavor": "cpu-small", "image": "ubuntu:22.04"}

    mock_k8s_api.create_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": spec,
        "status": {"phase": "Pending"},
    }

    devserver = DevServer.create(metadata=metadata, spec=spec, api=mock_k8s_api)

    assert devserver.metadata.name == DEVSERVER_NAME
    assert devserver.spec["flavor"] == "cpu-small"
    assert devserver.status["phase"] == "Pending"

    mock_k8s_api.create_namespaced_custom_object.assert_called_once()
    call_args = mock_k8s_api.create_namespaced_custom_object.call_args
    assert call_args.kwargs["namespace"] == NAMESPACE
    assert call_args.kwargs["body"]["metadata"]["name"] == DEVSERVER_NAME
    assert call_args.kwargs["body"]["kind"] == "DevServer"


def test_devserver_get(mock_k8s_api):
    """Test the DevServer.get classmethod (from BaseCustomResource)."""
    mock_k8s_api.get_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": {"flavor": "cpu-small"},
        "status": {"phase": "Running"},
    }

    devserver = DevServer.get(name=DEVSERVER_NAME, namespace=NAMESPACE, api=mock_k8s_api)

    assert devserver.metadata.name == DEVSERVER_NAME
    assert devserver.status["phase"] == "Running"
    mock_k8s_api.get_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
        name=DEVSERVER_NAME,
    )


def test_devserver_list(mock_k8s_api):
    """Test the DevServer.list classmethod."""
    mock_k8s_api.list_namespaced_custom_object.return_value = {
        "items": [
            {
                "metadata": {"name": "devserver-1", "namespace": NAMESPACE},
                "spec": {},
                "status": {"phase": "Running"},
            },
            {
                "metadata": {"name": "devserver-2", "namespace": NAMESPACE},
                "spec": {},
                "status": {"phase": "Pending"},
            },
        ]
    }

    devservers = DevServer.list(namespace=NAMESPACE, api=mock_k8s_api)

    assert len(devservers) == 2
    assert devservers[0].metadata.name == "devserver-1"
    assert devservers[1].status["phase"] == "Pending"
    mock_k8s_api.list_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
    )


def test_devserver_update(mock_k8s_api):
    """Test the DevServer.update instance method."""
    devserver = DevServer(
        metadata=ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE),
        spec={"image": "old-image"},
        api=mock_k8s_api,
    )
    devserver.spec["image"] = "new-image"

    mock_k8s_api.replace_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": {"image": "new-image"},
        "status": {"phase": "Updating"},
    }

    devserver.update()

    assert devserver.spec["image"] == "new-image"
    assert devserver.status["phase"] == "Updating"
    mock_k8s_api.replace_namespaced_custom_object.assert_called_once()
    call_args = mock_k8s_api.replace_namespaced_custom_object.call_args
    assert call_args.kwargs["body"]["spec"]["image"] == "new-image"


def test_devserver_patch(mock_k8s_api):
    """Test the DevServer.patch instance method."""
    devserver = DevServer(
        metadata=ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE),
        spec={"image": "ubuntu"},
        api=mock_k8s_api,
    )

    patch_body = {"spec": {"image": "fedora"}}
    mock_k8s_api.patch_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": {"image": "fedora"},
        "status": {},
    }

    devserver.patch(patch_body)

    assert devserver.spec["image"] == "fedora"
    mock_k8s_api.patch_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
        name=DEVSERVER_NAME,
        body=patch_body,
    )


def test_devserver_delete(mock_k8s_api):
    """Test the DevServer.delete instance method."""
    devserver = DevServer(
        metadata=ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE),
        spec={},
        api=mock_k8s_api,
    )
    devserver.delete()
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
        name=DEVSERVER_NAME,
        body=unittest.mock.ANY,
    )


def test_devserver_context_manager_creates_and_cleans_up(mock_k8s_api):
    """Ensure the DevServer context manager creates and deletes resources."""
    metadata = ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE)
    spec = {"flavor": "cpu-small"}

    mock_k8s_api.create_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": spec,
        "status": {"phase": "Pending"},
    }

    resource = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api)

    with resource as created:
        assert created.metadata.name == DEVSERVER_NAME
        assert created is not resource

    mock_k8s_api.create_namespaced_custom_object.assert_called_once()
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
        name=DEVSERVER_NAME,
        body=unittest.mock.ANY,
    )


def test_devserver_context_manager_ignores_404_on_delete(mock_k8s_api):
    """A missing resource during cleanup should not raise an error."""
    metadata = ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE)
    spec = {"flavor": "cpu-small"}

    mock_k8s_api.create_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": spec,
        "status": {},
    }
    mock_k8s_api.delete_namespaced_custom_object.side_effect = ApiException(
        status=404, reason="Not Found"
    )

    resource = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api)

    with resource as created:
        assert created.metadata.name == DEVSERVER_NAME

    mock_k8s_api.create_namespaced_custom_object.assert_called_once()
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once()

def test_devserver_refresh(mock_k8s_api):
    """Test the DevServer.refresh instance method."""
    devserver = DevServer(
        metadata=ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE),
        spec={"image": "old-image"},
        status={"phase": "Old"},
        api=mock_k8s_api
    )

    mock_k8s_api.get_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": {"image": "refreshed-image"},
        "status": {"phase": "Refreshed"},
    }

    devserver.refresh()

    assert devserver.spec["image"] == "refreshed-image"
    assert devserver.status["phase"] == "Refreshed"
    mock_k8s_api.get_namespaced_custom_object.assert_called_once()

def test_get_k8s_api_raises_runtime_error_on_config_exception():
    """
    Test that our helper function provides a user-friendly error when
    kubeconfig is not found.
    """
    with patch("devservers.crds.base.config.load_kube_config") as mock_load:
        mock_load.side_effect = ConfigException("Kube config not found")

        with pytest.raises(KubeConfigError) as excinfo:
            _get_k8s_api()

        assert "Kubernetes configuration not found" in str(excinfo.value)
