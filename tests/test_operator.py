import pytest
from devservers.operator.devserver.resources.deployment import build_deployment
from devservers.operator.devserveruser.reconciler import DevServerUserReconciler
from unittest.mock import MagicMock
from kubernetes.client.rest import ApiException

def test_build_deployment_with_node_selector():
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

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    assert "nodeSelector" in deployment["spec"]["template"]["spec"]
    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {
        "disktype": "ssd",
        "team": "backend"
    }

def test_build_deployment_without_node_selector():
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

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    assert "nodeSelector" not in deployment["spec"]["template"]["spec"]


def test_build_deployment_with_no_volumes():
    """Test that no volumes specified results in emptyDir at /home/dev"""
    name = "test-server"
    namespace = "test-ns"
    spec = {}
    flavor = {"spec": {"resources": {}}}

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    # Should have emptyDir volume named "home"
    volumes = deployment["spec"]["template"]["spec"]["volumes"]
    home_volume = next((v for v in volumes if v.get("name") == "home"), None)
    assert home_volume is not None, "home volume not found"
    assert "emptyDir" in home_volume, "home volume should be emptyDir"

    # Should have mount at /home/dev
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    home_mount = next(
        (vm for vm in container["volumeMounts"] if vm.get("name") == "home"),
        None
    )
    assert home_mount is not None, "home mount not found"
    assert home_mount["mountPath"] == "/home/dev"


def test_build_deployment_with_single_volume():
    """Test that a single volume is mounted correctly"""
    name = "test-server"
    namespace = "test-ns"
    spec = {
        "volumes": [
            {
                "claimName": "my-pvc",
                "mountPath": "/home/dev",
                "readOnly": False
            }
        ]
    }
    flavor = {"spec": {"resources": {}}}

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    # Should NOT have emptyDir home volume
    volumes = deployment["spec"]["template"]["spec"]["volumes"]
    home_volume = next((v for v in volumes if v.get("name") == "home"), None)
    assert home_volume is None, "home emptyDir volume should not exist when volumes are specified"

    # Should have user volume
    user_volume = next((v for v in volumes if v.get("name", "").startswith("vol-")), None)
    assert user_volume is not None, "user volume not found"
    assert "persistentVolumeClaim" in user_volume
    assert user_volume["persistentVolumeClaim"]["claimName"] == "my-pvc"

    # Should have mount at /home/dev
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    user_mount = next(
        (vm for vm in container["volumeMounts"] if vm.get("name", "").startswith("vol-")),
        None
    )
    assert user_mount is not None, "user mount not found"
    assert user_mount["mountPath"] == "/home/dev"
    assert not user_mount["readOnly"]


def test_build_deployment_with_multiple_volumes():
    """Test that multiple volumes are mounted correctly"""
    name = "test-server"
    namespace = "test-ns"
    spec = {
        "volumes": [
            {
                "claimName": "home-pvc",
                "mountPath": "/home/dev",
                "readOnly": False
            },
            {
                "claimName": "data-pvc",
                "mountPath": "/data",
                "readOnly": True
            },
            {
                "claimName": "output-pvc",
                "mountPath": "/outputs",
                "readOnly": False
            }
        ]
    }
    flavor = {"spec": {"resources": {}}}

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    # Should have 3 user volumes
    volumes = deployment["spec"]["template"]["spec"]["volumes"]
    user_volumes = [v for v in volumes if v.get("name", "").startswith("vol-")]
    assert len(user_volumes) == 3, f"Expected 3 user volumes, got {len(user_volumes)}"

    # Verify PVC claim names
    claim_names = {v["persistentVolumeClaim"]["claimName"] for v in user_volumes}
    assert claim_names == {"home-pvc", "data-pvc", "output-pvc"}

    # Should have 3 user mounts
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    user_mounts = [
        vm for vm in container["volumeMounts"]
        if vm.get("name", "").startswith("vol-")
    ]
    assert len(user_mounts) == 3, f"Expected 3 user mounts, got {len(user_mounts)}"

    # Verify mount paths and read-only flags
    mount_paths = {vm["mountPath"]: vm for vm in user_mounts}
    assert "/home/dev" in mount_paths
    assert "/data" in mount_paths
    assert "/outputs" in mount_paths
    assert mount_paths["/data"]["readOnly"]
    assert not mount_paths["/home/dev"]["readOnly"]
    assert not mount_paths["/outputs"]["readOnly"]


def test_build_deployment_kind_is_deployment():
    """Test that the resource kind is Deployment, not StatefulSet"""
    name = "test-server"
    namespace = "test-ns"
    spec = {}
    flavor = {"spec": {"resources": {}}}

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    assert deployment["kind"] == "Deployment"
    assert deployment["apiVersion"] == "apps/v1"
    # Should NOT have serviceName field (that's StatefulSet-specific)
    assert "serviceName" not in deployment["spec"]
    # Should NOT have volumeClaimTemplates (that's StatefulSet-specific)
    assert "volumeClaimTemplates" not in deployment["spec"]


def test_build_deployment_uses_recreate_strategy():
    """Deployment should use Recreate strategy for RWO volumes"""
    name = "test-server"
    namespace = "test-ns"
    spec = {}
    flavor = {"spec": {"resources": {}}}

    deployment = build_deployment(
        name,
        namespace,
        spec,
        flavor,
        default_devserver_image="default-image",
        static_dependencies_image="static-image",
    )

    assert deployment["spec"].get("strategy") == {"type": "Recreate"}


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
