import asyncio
import pytest
from kubernetes import client
from tests.conftest import TEST_NAMESPACE
from tests.helpers import (
    build_devserver_spec,
    wait_for_devserver_status,
    wait_for_deployment_to_exist,
)

# Constants from the main test file
NAMESPACE = TEST_NAMESPACE


@pytest.mark.asyncio
async def test_ephemeral_storage_with_no_volumes(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that a DevServer with no volumes specified gets an emptyDir
    mounted at /home/dev (ephemeral storage).
    """
    apps_v1 = k8s_clients["apps_v1"]
    devserver_name = "test-ephemeral"

    devserver_spec = build_devserver_spec(
        flavor=test_flavor,
        public_key="ssh-rsa AAAA...",
        ttl="1h",
        image=None,
    )

    async with async_devserver(
        devserver_name,
        spec=devserver_spec,
    ):
        # Verify the Deployment has an emptyDir volume at /home/dev
        deployment = await wait_for_deployment_to_exist(
            apps_v1, name=devserver_name, namespace=NAMESPACE
        )

        assert deployment is not None

        # Check volumes
        volumes = deployment.spec.template.spec.volumes
        home_volume = next((v for v in volumes if v.name == "home"), None)
        assert home_volume is not None, "home volume not found"
        assert home_volume.empty_dir is not None, "home volume should be emptyDir"

        # Check volume mounts
        container = deployment.spec.template.spec.containers[0]
        home_mount = next((vm for vm in container.volume_mounts if vm.name == "home"), None)
        assert home_mount is not None, "home mount not found"
        assert home_mount.mount_path == "/home/dev"

        print("✅ Ephemeral storage (emptyDir) correctly configured at /home/dev")


@pytest.mark.asyncio
async def test_single_volume_mount(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that a DevServer with a single volume mounts it correctly.
    """
    apps_v1 = k8s_clients["apps_v1"]
    core_v1 = k8s_clients["core_v1"]
    devserver_name = "test-single-volume"
    pvc_name = "test-pvc-home"

    # Create a PVC for testing
    pvc_manifest = client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(name=pvc_name, namespace=NAMESPACE),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=client.V1ResourceRequirements(requests={"storage": "1Gi"}),
        ),
    )

    try:
        await asyncio.to_thread(
            core_v1.create_namespaced_persistent_volume_claim,
            namespace=NAMESPACE,
            body=pvc_manifest,
        )
        print(f"✅ PVC '{pvc_name}' created for testing")

        devserver_spec = build_devserver_spec(
            flavor=test_flavor,
            public_key="ssh-rsa AAAA...",
            ttl="1h",
            image=None,
            volumes=[
                {
                    "claimName": pvc_name,
                    "mountPath": "/home/dev",
                    "readOnly": False,
                }
            ],
        )

        async with async_devserver(
            devserver_name,
            spec=devserver_spec,
        ):
            # Verify the Deployment mounts the PVC
            deployment = await wait_for_deployment_to_exist(
                apps_v1, name=devserver_name, namespace=NAMESPACE
            )

            assert deployment is not None

            # Check volumes
            volumes = deployment.spec.template.spec.volumes
            user_volume = next((v for v in volumes if v.name.startswith("user-volume-")), None)
            assert user_volume is not None, "user volume not found"
            assert user_volume.persistent_volume_claim is not None
            assert user_volume.persistent_volume_claim.claim_name == pvc_name

            # Check volume mounts
            container = deployment.spec.template.spec.containers[0]
            user_mount = next(
                (vm for vm in container.volume_mounts if vm.name.startswith("user-volume-")),
                None
            )
            assert user_mount is not None, "user mount not found"
            assert user_mount.mount_path == "/home/dev"
            assert not user_mount.read_only

            print(f"✅ Single volume '{pvc_name}' correctly mounted at /home/dev")

    finally:
        # Cleanup PVC
        try:
            await asyncio.to_thread(
                core_v1.delete_namespaced_persistent_volume_claim,
                name=pvc_name,
                namespace=NAMESPACE,
            )
            print(f"🧹 PVC '{pvc_name}' deleted")
        except client.ApiException as e:
            if e.status != 404:
                print(f"⚠️ Error deleting PVC '{pvc_name}': {e}")


@pytest.mark.asyncio
async def test_multiple_volume_mounts(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that a DevServer can mount multiple PVCs at different paths.
    """
    apps_v1 = k8s_clients["apps_v1"]
    core_v1 = k8s_clients["core_v1"]
    devserver_name = "test-multi-volumes"
    pvc_home = "test-pvc-multi-home"
    pvc_data = "test-pvc-multi-data"

    # Create PVCs for testing
    pvcs_to_create = [
        (pvc_home, "/home/dev"),
        (pvc_data, "/data"),
    ]

    created_pvcs = []

    try:
        for pvc_name, _ in pvcs_to_create:
            pvc_manifest = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(name=pvc_name, namespace=NAMESPACE),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    resources=client.V1ResourceRequirements(requests={"storage": "1Gi"}),
                ),
            )
            await asyncio.to_thread(
                core_v1.create_namespaced_persistent_volume_claim,
                namespace=NAMESPACE,
                body=pvc_manifest,
            )
            created_pvcs.append(pvc_name)
            print(f"✅ PVC '{pvc_name}' created for testing")

        devserver_spec = build_devserver_spec(
            flavor=test_flavor,
            public_key="ssh-rsa AAAA...",
            ttl="1h",
            image=None,
            volumes=[
                {
                    "claimName": pvc_home,
                    "mountPath": "/home/dev",
                    "readOnly": False,
                },
                {
                    "claimName": pvc_data,
                    "mountPath": "/data",
                    "readOnly": True,
                },
            ],
        )

        async with async_devserver(
            devserver_name,
            spec=devserver_spec,
        ):
            # Verify the Deployment mounts both PVCs
            deployment = await wait_for_deployment_to_exist(
                apps_v1, name=devserver_name, namespace=NAMESPACE
            )

            assert deployment is not None

            # Check volumes
            volumes = deployment.spec.template.spec.volumes
            user_volumes = [v for v in volumes if v.name.startswith("user-volume-")]
            assert len(user_volumes) == 2, f"Expected 2 user volumes, got {len(user_volumes)}"

            # Check volume mounts
            container = deployment.spec.template.spec.containers[0]
            user_mounts = [
                vm for vm in container.volume_mounts
                if vm.name.startswith("user-volume-")
            ]
            assert len(user_mounts) == 2, f"Expected 2 user mounts, got {len(user_mounts)}"

            # Verify specific mounts
            mount_paths = {vm.mount_path: vm for vm in user_mounts}
            assert "/home/dev" in mount_paths, "/home/dev mount not found"
            assert "/data" in mount_paths, "/data mount not found"
            assert mount_paths["/data"].read_only, "/data should be read-only"

            print("✅ Multiple volumes correctly mounted")

    finally:
        # Cleanup PVCs
        for pvc_name in created_pvcs:
            try:
                await asyncio.to_thread(
                    core_v1.delete_namespaced_persistent_volume_claim,
                    name=pvc_name,
                    namespace=NAMESPACE,
                )
                print(f"🧹 PVC '{pvc_name}' deleted")
            except client.ApiException as e:
                if e.status != 404:
                    print(f"⚠️ Error deleting PVC '{pvc_name}': {e}")


@pytest.mark.asyncio
async def test_pvc_persists_after_devserver_deletion(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that user-managed PVCs are NOT deleted when a DevServer is deleted.
    """
    core_v1 = k8s_clients["core_v1"]
    devserver_name = "test-pvc-persistence"
    pvc_name = "test-pvc-persistent"

    # Create a PVC for testing
    pvc_manifest = client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(name=pvc_name, namespace=NAMESPACE),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=client.V1ResourceRequirements(requests={"storage": "1Gi"}),
        ),
    )

    try:
        await asyncio.to_thread(
            core_v1.create_namespaced_persistent_volume_claim,
            namespace=NAMESPACE,
            body=pvc_manifest,
        )
        print(f"✅ PVC '{pvc_name}' created for testing")

        devserver_spec = build_devserver_spec(
            flavor=test_flavor,
            public_key="ssh-rsa AAAA...",
            ttl="1h",
            image=None,
            volumes=[
                {
                    "claimName": pvc_name,
                    "mountPath": "/home/dev",
                    "readOnly": False,
                }
            ],
        )

        async with async_devserver(
            devserver_name,
            spec=devserver_spec,
        ):
            await wait_for_devserver_status(
                k8s_clients["custom_objects_api"],
                name=devserver_name,
                namespace=NAMESPACE,
                expected_status="Running",
            )
            print(f"✅ DevServer '{devserver_name}' running")

        # DevServer is now deleted (context manager exit)
        # Verify PVC still exists
        pvc = await asyncio.to_thread(
            core_v1.read_namespaced_persistent_volume_claim,
            name=pvc_name,
            namespace=NAMESPACE,
        )
        assert pvc is not None, f"PVC '{pvc_name}' should still exist after DevServer deletion"
        print(f"✅ PVC '{pvc_name}' correctly persisted after DevServer deletion")

    finally:
        # Cleanup PVC
        try:
            await asyncio.to_thread(
                core_v1.delete_namespaced_persistent_volume_claim,
                name=pvc_name,
                namespace=NAMESPACE,
            )
            print(f"🧹 PVC '{pvc_name}' deleted")
        except client.ApiException as e:
            if e.status != 404:
                print(f"⚠️ Error deleting PVC '{pvc_name}': {e}")
