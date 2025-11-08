import pytest
from devservers.operator.devserver.resources.statefulset import build_statefulset
from devservers.operator.devserveruser.reconciler import DevServerUserReconciler
from unittest.mock import MagicMock
from kubernetes.client.rest import ApiException

def test_build_statefulset_with_node_selector():
    name = "test-server"
    namespace = "test-ns"
    spec = {
        "ssh": {
            "publicKey": "ssh-rsa AAA..."
        }
    }
    flavor = {
        "spec": {
            "resources": {
                "requests": {"cpu": "1", "memory": "1Gi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            },
            "nodeSelector": {
                "disktype": "ssd",
                "team": "backend"
            }
        }
    }

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "nodeSelector" in statefulset["spec"]["template"]["spec"]
    assert statefulset["spec"]["template"]["spec"]["nodeSelector"] == {
        "disktype": "ssd",
        "team": "backend"
    }

def test_build_statefulset_without_node_selector():
    name = "test-server"
    namespace = "test-ns"
    spec = {
        "ssh": {
            "publicKey": "ssh-rsa AAA..."
        }
    }
    flavor = {
        "spec": {
            "resources": {
                "requests": {"cpu": "1", "memory": "1Gi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            }
        }
    }

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "nodeSelector" not in statefulset["spec"]["template"]["spec"]


def test_build_statefulset_with_persistent_home_enabled():
    name = "test-server"
    namespace = "test-ns"
    spec = {"persistentHome": {"enabled": True}}
    flavor = {"spec": {"resources": {}}}

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "volumeClaimTemplates" in statefulset["spec"]
    vct = statefulset["spec"]["volumeClaimTemplates"][0]
    assert vct["metadata"]["name"] == "home"
    assert vct["spec"]["resources"]["requests"]["storage"] == "10Gi"

    volumes = statefulset["spec"]["template"]["spec"]["volumes"]
    assert not any(v.get("name") == "home" and "emptyDir" in v for v in volumes)


def test_build_statefulset_with_persistent_home_enabled_and_size():
    name = "test-server"
    namespace = "test-ns"
    spec = {"persistentHome": {"enabled": True, "size": "20Gi"}}
    flavor = {"spec": {"resources": {}}}

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "volumeClaimTemplates" in statefulset["spec"]
    vct = statefulset["spec"]["volumeClaimTemplates"][0]
    assert vct["spec"]["resources"]["requests"]["storage"] == "20Gi"


def test_build_statefulset_with_persistent_home_disabled():
    name = "test-server"
    namespace = "test-ns"
    spec = {"persistentHome": {"enabled": False}}
    flavor = {"spec": {"resources": {}}}

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "volumeClaimTemplates" not in statefulset["spec"]
    volumes = statefulset["spec"]["template"]["spec"]["volumes"]
    assert any(v.get("name") == "home" and "emptyDir" in v for v in volumes)


def test_build_statefulset_with_persistent_home_unspecified():
    name = "test-server"
    namespace = "test-ns"
    spec = {}
    flavor = {"spec": {"resources": {}}}

    statefulset = build_statefulset(
        name, namespace, spec, flavor, default_persistent_home_size="10Gi"
    )

    assert "volumeClaimTemplates" not in statefulset["spec"]
    volumes = statefulset["spec"]["template"]["spec"]["volumes"]
    assert any(v.get("name") == "home" and "emptyDir" in v for v in volumes)


def test_compute_user_namespace_default():
    spec = {"username": "alice"}
    reconciler = DevServerUserReconciler(spec=spec, metadata={})
    assert reconciler._desired_namespace_name() == "dev-alice"


@pytest.mark.asyncio
async def test_devserver_user_reconciler_creates_namespace(monkeypatch):
    spec = {"username": "bob"}
    reconciler = DevServerUserReconciler(spec=spec, metadata={})

    # Mock the k8s clients
    namespace_api = MagicMock()
    rbac_api = MagicMock()

    monkeypatch.setattr(reconciler, "core_v1", namespace_api)
    monkeypatch.setattr(reconciler, "rbac_v1", rbac_api)

    # Mock the methods called within the reconciler
    namespace_api.create_namespace = MagicMock()
    namespace_api.create_namespaced_service_account = MagicMock()
    # For roles and rolebindings, we need to mock the read calls to raise a 404
    # to trigger the create path.
    rbac_api.read_namespaced_role = MagicMock(side_effect=ApiException(status=404))
    rbac_api.create_namespaced_role = MagicMock()
    rbac_api.read_namespaced_role_binding = MagicMock(side_effect=ApiException(status=404))
    rbac_api.create_namespaced_role_binding = MagicMock()

    # The reconciler calls the k8s client methods via `asyncio.to_thread`.
    # We can patch `asyncio.to_thread` to just call the function directly
    # since our mocks are not actually blocking.
    async def to_thread_mock(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", to_thread_mock)

    logger = MagicMock()
    result = await reconciler.reconcile(logger)

    assert result.namespace == "dev-bob"
    namespace_api.create_namespace.assert_called_once()
    namespace_api.create_namespaced_service_account.assert_called_once()
    rbac_api.create_namespaced_role.assert_called_once()
    rbac_api.create_namespaced_role_binding.assert_called_once()

    # Verify the rolebinding includes both the user and the service account
    rolebinding_body = rbac_api.create_namespaced_role_binding.call_args.kwargs["body"]
    subjects = rolebinding_body["subjects"]
    assert len(subjects) == 2
    assert {"kind": "User", "name": "bob"} in subjects
    assert {
        "kind": "ServiceAccount",
        "name": "bob-sa",
        "namespace": "dev-bob",
    } in subjects
