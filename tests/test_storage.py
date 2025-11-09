import asyncio
import pytest
from kubernetes import client
from tests.conftest import TEST_NAMESPACE
from tests.helpers import (
    build_devserver_spec,
    wait_for_devserver_status,
    wait_for_pvc_to_exist,
    wait_for_statefulset_to_exist,
    wait_for_statefulset_to_be_deleted,
)

# Constants from the main test file
NAMESPACE = TEST_NAMESPACE


@pytest.mark.asyncio
async def test_persistent_storage_retains_on_recreation(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that a DevServer with persistentHomeSize correctly creates a
    StatefulSet with a volumeClaimTemplate and a corresponding PVC. It also
    tests that the PVC is retained when a DevServer is deleted and then
    re-attached when the same DevServer is recreated.
    """
    apps_v1 = k8s_clients["apps_v1"]
    core_v1 = k8s_clients["core_v1"]
    devserver_name = "test-recreation"
    storage_size = "1Gi"
    pvc_name = f"home-{devserver_name}-0"

    devserver_spec = build_devserver_spec(
        flavor=test_flavor,
        public_key="ssh-rsa AAAA...",
        ttl="1h",
        image=None,
        overrides={"persistentHome": {"enabled": True, "size": storage_size}},
    )

    # 1. Initial Creation
    print("PHASE 1: Creating DevServer and PVC...")
    async with async_devserver(
        devserver_name,
        spec=devserver_spec,
    ):
        # 1a. Verify the StatefulSet's volumeClaimTemplate has the correct size
        statefulset = await wait_for_statefulset_to_exist(
            apps_v1, name=devserver_name, namespace=NAMESPACE
        )

        assert statefulset is not None
        vct = statefulset.spec.volume_claim_templates[0]
        assert vct.spec.resources.requests["storage"] == storage_size

        # 1b. Verify the PVC is created by the StatefulSet controller
        pvc = await wait_for_pvc_to_exist(core_v1, name=pvc_name, namespace=NAMESPACE)

        assert pvc is not None, f"PVC '{pvc_name}' was not created."
        assert pvc.spec.resources.requests["storage"] == storage_size
        print(f"✅ PVC '{pvc_name}' created.")

    # Wait for StatefulSet to be deleted
    await wait_for_statefulset_to_be_deleted(
        apps_v1, name=devserver_name, namespace=NAMESPACE
    )
    print(f"✅ StatefulSet '{devserver_name}' deleted.")

    # Assert that the PVC still exists
    try:
        await asyncio.to_thread(
            core_v1.read_namespaced_persistent_volume_claim,
            name=pvc_name,
            namespace=NAMESPACE,
        )
        print(f"✅ PVC '{pvc_name}' correctly retained after deletion.")
    except client.ApiException as e:
        if e.status == 404:
            pytest.fail(
                f"PVC '{pvc_name}' was deleted, but should have been retained."
            )
        raise

    # 3. Re-creation
    print("PHASE 3: Re-creating DevServer, verifying it re-attaches...")
    async with async_devserver(
        devserver_name,
        spec=devserver_spec,
    ):
        # Wait for StatefulSet to be re-created and become ready
        await wait_for_statefulset_to_exist(
            apps_v1, name=devserver_name, namespace=NAMESPACE
        )
        await wait_for_devserver_status(
            k8s_clients["custom_objects_api"],
            name=devserver_name,
            namespace=NAMESPACE,
            expected_status="Running",
        )

    await wait_for_statefulset_to_be_deleted(
        apps_v1, name=devserver_name, namespace=NAMESPACE
    )
