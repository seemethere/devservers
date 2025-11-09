import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes import client

from devservers.crds.const import CRD_GROUP, CRD_PLURAL_DEVSERVER, CRD_VERSION
from devservers.operator.devserver import lifecycle
from devservers.operator.devserver.resources.statefulset import DEFAULT_DEVSERVER_IMAGE
from tests.conftest import TEST_NAMESPACE
from tests.helpers import (
    wait_for_devserver_status,
    wait_for_statefulset_to_be_deleted,
    wait_for_statefulset_to_exist,
)

# Constants from the main test file
NAMESPACE = TEST_NAMESPACE
TEST_DEVSERVER_NAME = "test-devserver"


@pytest.mark.asyncio
async def test_devserver_creates_statefulset(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests if creating a DevServer resource leads to the creation of a
    corresponding StatefulSet. This is the core reconciliation test with
    the actual operator running.
    """
    apps_v1 = k8s_clients["apps_v1"]
    custom_objects_api = k8s_clients["custom_objects_api"]

    print(f"🧪 Starting test_devserver_creates_statefulset in namespace: {NAMESPACE}")

    # 1. Create a DevServer custom resource
    devserver_manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServer",
        "metadata": {"name": TEST_DEVSERVER_NAME, "namespace": NAMESPACE},
        "spec": {
            "flavor": test_flavor,
            "image": "ubuntu:22.04",
            "ssh": {"publicKey": "ssh-rsa AAAA..."},
            "lifecycle": {"timeToLive": "1h"},
        },
    }

    async with async_devserver(
        TEST_DEVSERVER_NAME,
        spec=devserver_manifest["spec"],
    ):
        # 2. Wait and check for the corresponding StatefulSet
        statefulset = await wait_for_statefulset_to_exist(
            apps_v1, name=TEST_DEVSERVER_NAME, namespace=NAMESPACE
        )

        # 3. Assert that the statefulset was found and has correct properties
        assert statefulset is not None, (
            f"StatefulSet '{TEST_DEVSERVER_NAME}' not created by operator."
        )
        assert statefulset.spec.template.spec.containers[0].image == "ubuntu:22.04"

        container = statefulset.spec.template.spec.containers[0]
        assert container.resources.requests["cpu"] == "100m"
        assert "/devserver/startup.sh" in container.args[0]

        # 3a. Wait and check for the status update on the DevServer
        await wait_for_devserver_status(
            custom_objects_api,
            name=TEST_DEVSERVER_NAME,
            namespace=NAMESPACE,
            expected_status="Running",
        )

    # 4. Wait and check for the corresponding StatefulSet to be deleted
    await wait_for_statefulset_to_be_deleted(
        apps_v1, name=TEST_DEVSERVER_NAME, namespace=NAMESPACE
    )


@pytest.mark.asyncio
async def test_devserver_update_changes_image(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests if updating a DevServer's spec.image triggers the operator to
    update the underlying StatefulSet's container image.
    """
    apps_v1 = k8s_clients["apps_v1"]
    devserver_name = f"test-update-{uuid.uuid4().hex[:6]}"

    initial_image = "ubuntu:22.04"
    updated_image = "fedora:latest"

    # 1. Create a DevServer manifest
    manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServer",
        "metadata": {"name": devserver_name, "namespace": NAMESPACE},
        "spec": {
            "flavor": test_flavor,
            "image": initial_image,
            "ssh": {"publicKey": "ssh-rsa AAAA..."},
            "lifecycle": {"timeToLive": "5m"},
        },
    }

    async with async_devserver(
        devserver_name,
        spec=manifest["spec"],
    ) as devserver:
        # 3. Wait for the StatefulSet and verify the initial image
        statefulset = await wait_for_statefulset_to_exist(
            apps_v1, name=devserver_name, namespace=NAMESPACE
        )
        assert statefulset.spec.template.spec.containers[0].image == initial_image

        # 4. Update the spec via the DevServer helper (use patch to avoid resourceVersion issues).
        await asyncio.to_thread(devserver.patch, {"spec": {"image": updated_image}})

        # 5. Poll the StatefulSet until the image is updated
        for _ in range(30):  # Poll for up to 60 seconds
            await asyncio.sleep(2)
            updated_sts = await asyncio.to_thread(
                apps_v1.read_namespaced_stateful_set,
                name=devserver_name,
                namespace=NAMESPACE,
            )
            if updated_sts.spec.template.spec.containers[0].image == updated_image:
                break
        else:
            pytest.fail("StatefulSet image was not updated in time.")

        # 6. Final assertion to be sure
        final_sts = await asyncio.to_thread(
            apps_v1.read_namespaced_stateful_set, name=devserver_name, namespace=NAMESPACE
        )
        assert final_sts.spec.template.spec.containers[0].image == updated_image

    # 7. Ensure StatefulSet cleanup
    await wait_for_statefulset_to_be_deleted(
        apps_v1, name=devserver_name, namespace=NAMESPACE
    )


@pytest.mark.asyncio
async def test_multiple_devservers(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that the operator can handle multiple DevServer resources simultaneously,
    and that creating a DevServer without specifying an image uses the default.
    """
    apps_v1 = k8s_clients["apps_v1"]

    devserver_names = ["test-multi-1", "test-multi-2-default-image"]

    manifests = [
        {
            "metadata": {"name": devserver_names[0], "namespace": NAMESPACE},
            "spec": {
                "flavor": test_flavor,
                "image": "fedora:38",
                "ssh": {"publicKey": "ssh-rsa AAAA..."},
                "lifecycle": {"timeToLive": "1h"},
            },
        },
        {
            "metadata": {"name": devserver_names[1], "namespace": NAMESPACE},
            "spec": {
                "flavor": test_flavor,
                # No image specified, should use default
                "ssh": {"publicKey": "ssh-rsa AAAA..."},
                "lifecycle": {"timeToLive": "1h"},
            },
        },
    ]

    async with AsyncExitStack() as stack:
        for manifest in manifests:
            ctx = async_devserver(
                manifest["metadata"]["name"],
                namespace=manifest["metadata"]["namespace"],
                spec=manifest["spec"],
            )
            await stack.enter_async_context(ctx)

        # Wait for all statefulsets to be created and verify images
        for _ in range(30):
            await asyncio.sleep(1)
            try:
                sts1 = await asyncio.to_thread(
                    apps_v1.read_namespaced_stateful_set,
                    name=devserver_names[0],
                    namespace=NAMESPACE,
                )
                sts2 = await asyncio.to_thread(
                    apps_v1.read_namespaced_stateful_set,
                    name=devserver_names[1],
                    namespace=NAMESPACE,
                )

                # Once both are found, verify images and break
                assert sts1.spec.template.spec.containers[0].image == "fedora:38"
                assert (
                    sts2.spec.template.spec.containers[0].image
                    == DEFAULT_DEVSERVER_IMAGE
                )  # Verify default
                break
            except client.ApiException as e:
                if e.status != 404:
                    raise
        else:
            pytest.fail("Not all StatefulSets were created and ready in time.")

    for name in devserver_names:
        await wait_for_statefulset_to_be_deleted(
            apps_v1, name=name, namespace=NAMESPACE
        )


@pytest.mark.asyncio
async def test_devserver_expires_after_ttl(
    test_flavor, operator_running, k8s_clients, async_devserver
):
    """
    Tests that a DevServer with a short TTL is automatically deleted
    by the operator's cleanup process.
    """
    apps_v1 = k8s_clients["apps_v1"]
    custom_objects_api = k8s_clients["custom_objects_api"]
    devserver_name = f"test-ttl-expiry-{uuid.uuid4().hex[:6]}"
    ttl_seconds = 2  # Keep TTL short, test is now deterministic

    devserver_manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServer",
        "metadata": {"name": devserver_name, "namespace": NAMESPACE},
        "spec": {
            "flavor": test_flavor,
            "ssh": {"publicKey": "ssh-rsa AAAA..."},
            "lifecycle": {"timeToLive": f"{ttl_seconds}s"},
        },
    }

    async with async_devserver(
        devserver_name,
        spec=devserver_manifest["spec"],
    ):
        # 1. Verify StatefulSet is created
        await wait_for_statefulset_to_exist(
            apps_v1, name=devserver_name, namespace=NAMESPACE
        )

        # 2. Wait for TTL to pass
        await asyncio.sleep(ttl_seconds + 1)

        # 3. Manually trigger the cleanup logic
        print("⚡️ Manually triggering expiration check...")
        deleted_count = await lifecycle.check_and_expire_devservers(
            custom_objects_api, logging.getLogger(__name__)
        )
        assert deleted_count == 1


@pytest.mark.asyncio
async def test_cleanup_expired_devservers_unit():
    """
    Unit test for the cleanup_expired_devservers background task.
    This test uses mocks to simulate the Kubernetes API and time.
    """
    custom_objects_api = MagicMock()
    # The method is now called via to_thread, so we mock the underlying sync method
    custom_objects_api.list_cluster_custom_object = MagicMock()
    custom_objects_api.delete_namespaced_custom_object = MagicMock()
    logger = logging.getLogger(__name__)

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    devservers = {
        "items": [
            # Expired DevServer (created 1h ago with 30m TTL)
            {
                "metadata": {
                    "name": "expired-server",
                    "namespace": "default",
                    "creationTimestamp": one_hour_ago.isoformat(),
                },
                "spec": {"lifecycle": {"timeToLive": "30m"}},
            },
            # Active DevServer (created now with 1h TTL)
            {
                "metadata": {
                    "name": "active-server",
                    "namespace": "default",
                    "creationTimestamp": now.isoformat(),
                },
                "spec": {"lifecycle": {"timeToLive": "1h"}},
            },
        ]
    }
    custom_objects_api.list_cluster_custom_object.return_value = devservers

    # Patch asyncio.sleep to break the infinite loop after one iteration.
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # We use a side effect to raise an exception that breaks the loop.
        mock_sleep.side_effect = asyncio.CancelledError

        # We also need to mock to_thread to call our sync mocks
        async def to_thread_mock(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("asyncio.to_thread", to_thread_mock):
            # The function will now exit with CancelledError after one loop.
            with pytest.raises(asyncio.CancelledError):
                await lifecycle.cleanup_expired_devservers(custom_objects_api, logger, 0)

    # Assert that delete was called ONLY for the expired server
    custom_objects_api.delete_namespaced_custom_object.assert_called_once_with(
        group=CRD_GROUP,
        version=CRD_VERSION,
        plural=CRD_PLURAL_DEVSERVER,
        name="expired-server",
        namespace="default",
        body=client.V1DeleteOptions(),
    )
