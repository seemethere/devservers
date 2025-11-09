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

    # Since this test is not for the waiting logic, we can mock the main wait method.
    with patch.object(DevServer, "wait_for_ready") as mock_wait_ready:
        resource = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api)
        with resource as created:
            assert created.metadata.name == DEVSERVER_NAME
            assert created is not resource

    mock_k8s_api.create_namespaced_custom_object.assert_called_once()
    mock_wait_ready.assert_called_once()
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once_with(
        group=DevServer.group,
        version=DevServer.version,
        namespace=NAMESPACE,
        plural=DevServer.plural,
        name=DEVSERVER_NAME,
        body=unittest.mock.ANY,
    )


def test_devserver_context_manager_waits_for_running(mock_k8s_api):
    """Ensure the DevServer context manager waits for the resource to be ready."""
    metadata = ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE)
    spec = {"flavor": "cpu-small"}

    # Provide the nested attribute that the real method will call
    mock_k8s_api.api_client = unittest.mock.MagicMock()

    mock_k8s_api.create_namespaced_custom_object.return_value = {
        "metadata": {"name": DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": spec,
        "status": {"phase": "Pending"},
    }

    # This object is the one that will be returned by DevServer.create()
    created_devserver = DevServer(metadata, spec, {"phase": "Pending"}, mock_k8s_api)

    # Mock the classmethod `create` to return our controlled instance
    with patch.object(DevServer, "create", return_value=created_devserver) as mock_create, \
         patch("devservers.crds.devserver.client.CoreV1Api") as mock_core_v1_api:

        # Configure the CoreV1Api mock to return a ready pod
        mock_core_v1_instance = mock_core_v1_api.return_value
        pod_mock = unittest.mock.MagicMock()
        pod_mock.status.container_statuses = [unittest.mock.MagicMock(ready=True)]
        mock_core_v1_instance.read_namespaced_pod.return_value = pod_mock

        # Mock the watch stream for wait_for_status
        watch_events = [
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"name": DEVSERVER_NAME},
                    "status": {"phase": "Running", "extraData": "foobar"},
                },
            },
        ]

        # Mock refresh to update the status to Running when called inside wait_for_status
        def refresh_side_effect():
            if created_devserver.refresh.call_count > 1:
                created_devserver.status = {"phase": "Running", "extraData": "foobar"}
        created_devserver.refresh = unittest.mock.MagicMock(side_effect=refresh_side_effect)

        # The DevServer instance we are entering the context with
        devserver_instance = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api, wait_timeout=5)

        with patch.object(created_devserver, 'watch', return_value=watch_events):
            with devserver_instance as created:
                assert created.metadata.name == DEVSERVER_NAME
                assert created.status["phase"] == "Running"
                assert created is created_devserver

                mock_create.assert_called_once()
                assert created_devserver.watch.called
                mock_core_v1_instance.read_namespaced_pod.assert_called()


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

    # Mock the wait method since it's not the focus of this test.
    with patch.object(DevServer, "wait_for_ready"):
        resource = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api)
        with resource as created:
            assert created.metadata.name == DEVSERVER_NAME

    mock_k8s_api.create_namespaced_custom_object.assert_called_once()
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once()


def test_devserver_context_manager_preserves_wait_timeout(mock_k8s_api):
    """The created DevServer inherits the wait_timeout from the context manager."""
    metadata = ObjectMeta(name=DEVSERVER_NAME, namespace=NAMESPACE)
    spec = {"flavor": "cpu-small"}
    custom_timeout = 42

    created_devserver = DevServer(metadata=metadata, spec=spec, api=mock_k8s_api)
    created_devserver.wait_for_ready = unittest.mock.MagicMock()

    with patch.object(DevServer, "create", return_value=created_devserver) as mock_create:
        resource = DevServer(
            metadata=metadata,
            spec=spec,
            api=mock_k8s_api,
            wait_timeout=custom_timeout,
        )

        with resource as created:
            assert created is created_devserver

    mock_create.assert_called_once()
    assert created_devserver.wait_timeout == custom_timeout
    created_devserver.wait_for_ready.assert_called_once_with(timeout=custom_timeout)

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
