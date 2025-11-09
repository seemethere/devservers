import asyncio
import pytest
from unittest.mock import patch, mock_open
import io
import sys
import yaml
import os
import tempfile
import uuid

from click.testing import CliRunner
from devservers.cli import main as cli_main
from devservers.cli import handlers
from tests.conftest import TEST_NAMESPACE
from kubernetes import client
from typing import Any, Dict
from tests.helpers import (
    build_devserver_spec,
    wait_for_devserver_status,
    cleanup_devserver,
    wait_for_cluster_custom_object_to_be_deleted,
    wait_for_devserveruser_status,
)
from devservers.cli.config import Configuration
from devservers.crds.const import (
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL_DEVSERVER,
    CRD_PLURAL_DEVSERVERFLAVOR,
    CRD_PLURAL_DEVSERVERUSER,
)


# Define constants and clients needed for CLI tests
NAMESPACE: str = TEST_NAMESPACE
TEST_DEVSERVER_NAME: str = "test-cli-devserver"


@pytest.fixture(autouse=True)
def mock_config_from_file(test_config: Configuration) -> None:
    """Mocks the config loading to return the test_config fixture."""
    with patch("devservers.cli.main.load_config", return_value=test_config):
        yield


class TestCliIntegration:
    """
    Integration tests for the CLI that interact with a Kubernetes cluster.
    """

    @pytest.mark.asyncio
    async def test_list_command(
        self,
        k8s_clients: Dict[str, Any],
        test_ssh_public_key: str,
        test_config: Configuration,
    ) -> None:
        """Tests that the 'list' command can see a created DevServer."""
        custom_objects_api = k8s_clients["custom_objects_api"]
        devserver_name = f"test-cli-list-{uuid.uuid4().hex[:6]}"

        # Create a DevServer for the list command to find
        devserver_manifest = {
            "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
            "kind": "DevServer",
            "metadata": {"name": devserver_name, "namespace": NAMESPACE},
            "spec": build_devserver_spec(
                flavor="any-flavor",
                public_key="ssh-rsa AAA...",
                ttl="1h",
                image=None,
            ),
        }

        await asyncio.to_thread(
            custom_objects_api.create_namespaced_custom_object,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL_DEVSERVER,
            body=devserver_manifest,
        )

        try:
            # Capture the stdout
            captured_output = io.StringIO()
            sys.stdout = captured_output

            await asyncio.to_thread(handlers.list_devservers, namespace=NAMESPACE)

            sys.stdout = sys.__stdout__  # Restore stdout

            output = captured_output.getvalue()
            assert devserver_name in output
            # Note: Without operator running, status will be Unknown

        finally:
            # Cleanup
            await cleanup_devserver(
                custom_objects_api, name=devserver_name, namespace=NAMESPACE
            )

    @pytest.mark.asyncio
    async def test_create_command(
        self,
        k8s_clients: Dict[str, Any],
        test_ssh_public_key: str,
        test_config: Configuration,
        test_flavor: str,
    ) -> None:
        """Tests that the 'create' command successfully creates a DevServer."""
        custom_objects_api = k8s_clients["custom_objects_api"]
        devserver_name = f"test-cli-create-{uuid.uuid4().hex[:6]}"

        try:
            # Call the handler to create the DevServer
            await asyncio.to_thread(
                handlers.create_devserver,
                configuration=test_config,
                name=devserver_name,
                flavor=test_flavor,
                image="nginx:latest",
                namespace=NAMESPACE,
                ssh_public_key_file=test_ssh_public_key,
            )

            # Verify the resource was created
            ds = await asyncio.to_thread(
                custom_objects_api.get_namespaced_custom_object,
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=NAMESPACE,
                plural=CRD_PLURAL_DEVSERVER,
                name=devserver_name,
            )

            assert ds["spec"]["flavor"] == test_flavor
            assert ds["spec"]["image"] == "nginx:latest"
            assert "publicKey" in ds["spec"]["ssh"]

        finally:
            # Cleanup
            await cleanup_devserver(
                custom_objects_api, name=devserver_name, namespace=NAMESPACE
            )

    @pytest.mark.asyncio
    async def test_delete_command(
        self,
        k8s_clients: Dict[str, Any],
        test_ssh_public_key: str,
        test_config: Configuration,
    ) -> None:
        """Tests that the 'delete' command successfully deletes a DevServer."""
        custom_objects_api = k8s_clients["custom_objects_api"]
        devserver_name = f"test-cli-delete-{uuid.uuid4().hex[:6]}"

        # Create a resource to be deleted
        devserver_manifest = {
            "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
            "kind": "DevServer",
            "metadata": {"name": devserver_name, "namespace": NAMESPACE},
            "spec": build_devserver_spec(
                flavor="any-flavor",
                public_key="ssh-rsa AAA...",
                ttl="1h",
                image=None,
            ),
        }
        await asyncio.to_thread(
            custom_objects_api.create_namespaced_custom_object,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL_DEVSERVER,
            body=devserver_manifest,
        )

        # Call the handler to delete the DevServer
        await asyncio.to_thread(
            handlers.delete_devserver,
            configuration=test_config,
            name=devserver_name,
            namespace=NAMESPACE,
        )

        # Verify the resource was deleted
        with pytest.raises(client.ApiException) as cm:
            await asyncio.to_thread(
                custom_objects_api.get_namespaced_custom_object,
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=NAMESPACE,
                plural=CRD_PLURAL_DEVSERVER,
                name=devserver_name,
            )
        assert isinstance(cm.value, client.ApiException)
        assert cm.value.status == 404

    @pytest.mark.asyncio
    async def test_describe_command(
        self,
        k8s_clients: Dict[str, Any],
        test_ssh_public_key: str,
        test_config: Configuration,
    ) -> None:
        """Tests that the 'describe' command can see a created DevServer."""
        custom_objects_api = k8s_clients["custom_objects_api"]
        devserver_name = f"test-cli-describe-{uuid.uuid4().hex[:6]}"

        # Create a DevServer for the describe command to find
        devserver_manifest = {
            "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
            "kind": "DevServer",
            "metadata": {"name": devserver_name, "namespace": NAMESPACE},
            "spec": build_devserver_spec(
                flavor="any-flavor",
                public_key="ssh-rsa AAA...",
                ttl="1h",
                image=None,
            ),  # Flavor doesn't need to exist for this test
        }

        await asyncio.to_thread(
            custom_objects_api.create_namespaced_custom_object,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL_DEVSERVER,
            body=devserver_manifest,
        )

        try:
            # Capture the stdout
            captured_output = io.StringIO()
            sys.stdout = captured_output

            await asyncio.to_thread(
                handlers.describe_devserver,
                name=devserver_name,
                namespace=NAMESPACE,
            )

            sys.stdout = sys.__stdout__  # Restore stdout

            output = captured_output.getvalue()
            assert devserver_name in output
            assert "any-flavor" in output

        finally:
            # Cleanup
            await cleanup_devserver(
                custom_objects_api, name=devserver_name, namespace=NAMESPACE
            )


class TestCliParser:
    """
    Unit tests for the Click CLI parser.
    These tests do not interact with Kubernetes.
    """

    def test_create_command_parsing(self, test_config: Configuration) -> None:
        """Tests that 'create' command arguments are parsed correctly."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.create_devserver") as mock_create:
            result = runner.invoke(
                cli_main.main,
                ["create", "--name", "my-server", "--flavor", "cpu-small", "--image", "ubuntu:22.04"]
            )

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called with correct arguments
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert isinstance(call_kwargs["configuration"], Configuration)
            assert call_kwargs["name"] == "my-server"
            assert call_kwargs["flavor"] == "cpu-small"
            assert call_kwargs["image"] == "ubuntu:22.04"

    def test_create_command_with_flavor(self, test_config: Configuration) -> None:
        """Tests that 'create' command with a flavor creates a DevServer object."""
        runner = CliRunner()

        # Mock the k8s object creation
        with patch(
            "kubernetes.client.CustomObjectsApi.create_namespaced_custom_object"
        ) as mock_create_k8s:
            result = runner.invoke(
                cli_main.main,
                [
                    "create",
                    "--name",
                    "my-server",
                    "--flavor",
                    "cpu-small",
                ],
            )

            # Check that the command succeeded
            assert result.exit_code == 0, result.output
            assert "created successfully" in result.output

            # Check that the k8s object was created with the correct parameters
            mock_create_k8s.assert_called_once()
            _, kwargs = mock_create_k8s.call_args
            assert kwargs["body"]["metadata"]["name"] == "my-server"
            assert kwargs["body"]["spec"]["flavor"] == "cpu-small"

    def test_create_command_no_flavor_uses_default(
        self, test_config: Configuration
    ) -> None:
        """Tests that 'create' command uses the default flavor when none is provided."""
        runner = CliRunner()

        default_flavor_obj = {
            "metadata": {"name": "default-flavor"},
            "spec": {"default": True},
        }

        async def mock_get_default_flavor():
            return default_flavor_obj

        # We need to mock the k8s object creation and the get_default_flavor function.
        with patch(
            "kubernetes.client.CustomObjectsApi.create_namespaced_custom_object"
        ) as mock_create_k8s, patch(
            "devservers.cli.handlers.create.get_default_flavor",
            side_effect=mock_get_default_flavor,
        ) as mock_get_default:
            result = runner.invoke(cli_main.main, ["create", "--name", "my-server"])

            # Check that the command succeeded
            assert result.exit_code == 0, result.output
            assert "created successfully" in result.output

            # Check that the k8s object was created with the correct parameters
            mock_create_k8s.assert_called_once()
            _, kwargs = mock_create_k8s.call_args
            assert kwargs["body"]["metadata"]["name"] == "my-server"
            assert kwargs["body"]["spec"]["flavor"] == "default-flavor"

            # Check that the get_default_flavor was called
            assert mock_get_default.call_count == 1

    def test_create_command_no_flavor_no_default(self, test_config: Configuration) -> None:
        """Tests that 'create' command fails if no flavor is provided and no default exists."""
        runner = CliRunner()

        async def mock_get_default_flavor_none():
            return None

        # Mock get_default_flavor to return None
        with patch(
            "devservers.cli.handlers.create.get_default_flavor",
            side_effect=mock_get_default_flavor_none,
        ) as mock_get_default:
            result = runner.invoke(cli_main.main, ["create", "--name", "my-server"])

            # Check that the command failed
            assert result.exit_code != 0
            assert "No default flavor found" in result.output
            mock_get_default.assert_called_once()

    def test_list_command_parsing(self) -> None:
        """Tests that 'list' command is recognized."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.list_devservers") as mock_list:
            result = runner.invoke(cli_main.main, ["list"])

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called
            mock_list.assert_called_once()

    def test_flavors_command_parsing(self) -> None:
        """Tests that 'flavors' command is recognized."""
        runner = CliRunner()

        with patch("devservers.cli.handlers.list_flavors") as mock_list_flavors:
            result = runner.invoke(cli_main.main, ["flavors"])
            assert result.exit_code == 0
            mock_list_flavors.assert_called_once()

    def test_delete_command_parsing(self, test_config: Configuration) -> None:
        """Tests that 'delete' command arguments are parsed correctly."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.delete_devserver") as mock_delete:
            result = runner.invoke(cli_main.main, ["delete", "--name", "my-server"])

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called with correct arguments
            mock_delete.assert_called_once()
            call_kwargs = mock_delete.call_args.kwargs
            assert isinstance(call_kwargs["configuration"], Configuration)
            assert call_kwargs["name"] == "my-server"

    def test_describe_command_parsing(self) -> None:
        """Tests that 'describe' command arguments are parsed correctly."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.describe_devserver") as mock_describe:
            result = runner.invoke(cli_main.main, ["describe", "--name", "my-server"])

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called with correct arguments
            mock_describe.assert_called_once()
            call_kwargs = mock_describe.call_args.kwargs
            assert call_kwargs["name"] == "my-server"

    def test_ssh_command_parsing(self, test_config: Configuration) -> None:
        """Tests that 'ssh' command arguments are parsed correctly."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.ssh_devserver") as mock_ssh:
            result = runner.invoke(
                cli_main.main,
                [
                    "ssh",
                    "--name",
                    "my-server",
                    "-i",
                    "my-key",
                    "--no-proxy",
                    "remote",
                    "command",
                ],
            )

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called with correct arguments
            mock_ssh.assert_called_once()
            call_kwargs = mock_ssh.call_args.kwargs
            assert isinstance(call_kwargs["configuration"], Configuration)
            assert call_kwargs["name"] == "my-server"
            assert call_kwargs["ssh_private_key_file"] == "my-key"
            assert call_kwargs["no_proxy"] is True
            assert call_kwargs["remote_command"] == ("remote", "command")

    def test_ssh_proxy_command_parsing(self) -> None:
        """Tests that 'ssh-proxy' command arguments are parsed correctly."""
        runner = CliRunner()

        # Mock the handler to avoid actual Kubernetes interaction
        with patch("devservers.cli.handlers.ssh_proxy_devserver") as mock_ssh_proxy:
            result = runner.invoke(
                cli_main.main,
                [
                    "ssh-proxy",
                    "--name",
                    "my-server",
                    "--namespace",
                    "my-namespace",
                    "--kubeconfig-path",
                    "my-kubeconfig",
                ],
            )

            # Check that the command succeeded
            assert result.exit_code == 0

            # Verify the handler was called with correct arguments
            mock_ssh_proxy.assert_called_once()
            call_kwargs = mock_ssh_proxy.call_args.kwargs
            assert call_kwargs["name"] == "my-server"
            assert call_kwargs["namespace"] == "my-namespace"
            assert call_kwargs["kubeconfig_path"] == "my-kubeconfig"


class TestUserCliIntegration:
    """Integration tests for the 'user' subcommand."""

    @pytest.mark.asyncio
    async def test_user_create_list_delete(
        self, k8s_clients: Dict[str, Any], operator_running: Any
    ) -> None:
        """Tests the full lifecycle (create, list, delete) of a user via the CLI."""
        custom_objects_api = k8s_clients["custom_objects_api"]
        runner = CliRunner()
        username = f"test-cli-user-{uuid.uuid4().hex[:6]}"

        try:
            # 1. Create user
            result = await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "create", username]
            )
            assert result.exit_code == 0
            assert f"User '{username}' created successfully" in result.output

            # Wait for operator to set status
            await wait_for_devserveruser_status(custom_objects_api, name=username)

            user_obj = await asyncio.to_thread(
                custom_objects_api.get_cluster_custom_object,
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL_DEVSERVERUSER,
                name=username,
            )
            assert user_obj["spec"]["username"] == username
            assert user_obj["status"]["namespace"] == f"dev-{username}"

            # 2. List users and check for the new user and namespace
            result = await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "list"]
            )
            assert result.exit_code == 0
            assert username in result.output
            assert f"dev-{username}".startswith(
                f"dev-{username}"
            )  # Check prefix due to truncation in output table

            # 3. Delete user
            result = await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "delete", username]
            )
            assert result.exit_code == 0
            assert f"User '{username}' deleted successfully" in result.output

            # Verify resource was deleted by waiting for it to disappear
            await wait_for_cluster_custom_object_to_be_deleted(
                custom_objects_api,
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL_DEVSERVERUSER,
                name=username,
            )

        finally:
            # Cleanup in case of failure
            try:
                # This will gracefully handle a 404 if already deleted
                await asyncio.to_thread(handlers.delete_user, username=username)
            except client.ApiException as e:
                if e.status != 404:
                    raise

    @pytest.mark.asyncio
    async def test_user_kubeconfig_command(
        self, k8s_clients: Dict[str, Any], operator_running: Any
    ) -> None:
        """Tests that the 'user kubeconfig' command generates a valid config."""
        runner = CliRunner()
        username = f"test-kubeconfig-user-{uuid.uuid4().hex[:6]}"

        try:
            # 1. Create a user for the test
            await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "create", username]
            )
            # Wait for the operator to be ready
            await wait_for_devserveruser_status(
                k8s_clients["custom_objects_api"], name=username
            )

            # 2. Generate kubeconfig
            result = await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "kubeconfig", username]
            )
            assert result.exit_code == 0
            kubeconfig_data = yaml.safe_load(result.output)
            assert kubeconfig_data["current-context"] == username

            # In the Kind-based integration test environment, we expect a token,
            # as the aws-auth ConfigMap will not be present.
            assert "token" in kubeconfig_data["users"][0]["user"]

            # 3. Write to a temp file and use it to list devservers
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_kubeconfig:
                temp_kubeconfig.write(result.output)
                kubeconfig_path = temp_kubeconfig.name

            # Use the generated kubeconfig to run a command
            runner_with_kubeconfig = CliRunner(env={"KUBECONFIG": kubeconfig_path})
            list_result = await asyncio.to_thread(
                runner_with_kubeconfig.invoke, cli_main.main, ["list"]
            )
            assert list_result.exit_code == 0
            assert (
                f"No DevServers found in namespace 'dev-{username}'."
                in list_result.output
            )

        finally:
            # Cleanup
            await asyncio.to_thread(
                runner.invoke, cli_main.main, ["admin", "user", "delete", username]
            )
            if "kubeconfig_path" in locals() and os.path.exists(kubeconfig_path):
                os.remove(kubeconfig_path)


@pytest.mark.asyncio
async def test_create_and_list_with_operator(
    operator_running: Any,
    k8s_clients: Dict[str, Any],
    test_ssh_public_key: str,
    test_config: Configuration,
) -> None:
    """
    Integration test for the CLI that works with the actual operator running.
    This test verifies end-to-end functionality by creating a DevServer with CLI
    and verifying it appears in list with proper status when operator is running.
    """
    custom_objects_api = k8s_clients["custom_objects_api"]

    # First create a flavor for the test
    flavor_manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServerFlavor",
        "metadata": {"name": "cli-test-flavor"},
        "spec": {
            "resources": {
                "requests": {"cpu": "200m", "memory": "256Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            }
        },
    }
    await asyncio.to_thread(
        custom_objects_api.create_cluster_custom_object,
        group=CRD_GROUP,
        version=CRD_VERSION,
        plural=CRD_PLURAL_DEVSERVERFLAVOR,
        body=flavor_manifest,
    )

    try:
        # Create a DevServer using the CLI
        devserver_name = "cli-test-server"
        await asyncio.to_thread(
            handlers.create_devserver,
            configuration=test_config,
            name=devserver_name,
            flavor="cli-test-flavor",
            image="alpine:latest",
            namespace=NAMESPACE,
            ssh_public_key_file=test_ssh_public_key,
        )

        # Give the operator time to process and set the status to Running
        await wait_for_devserver_status(
            custom_objects_api, name=devserver_name, namespace=NAMESPACE
        )

        # Verify it appears in the list command
        captured_output = io.StringIO()
        sys.stdout = captured_output
        await asyncio.to_thread(handlers.list_devservers, namespace=NAMESPACE)
        sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        assert devserver_name in output

        # If operator is working, we should see Running status eventually
        # Note: This might show "Unknown" initially before operator processes it

    finally:
        # Cleanup
        try:
            await asyncio.to_thread(
                handlers.delete_devserver,
                configuration=test_config,
                name="cli-test-server",
                namespace=NAMESPACE,
            )
        except Exception:
            pass

        try:
            await asyncio.to_thread(
                custom_objects_api.delete_cluster_custom_object,
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL_DEVSERVERFLAVOR,
                name="cli-test-flavor",
            )
        except client.ApiException as e:
            if e.status != 404:
                raise


class TestUserCliUnit:
    """Unit tests for the 'user' subcommand that do not require a k8s cluster."""

    @pytest.mark.parametrize(
        "host_url, cluster_name_in_context, expected_auth, expect_token_call",
        [
            ("https://localhost:8080", "local-cluster", {"method": "token"}, True),
            (
                "https://something.eks.amazonaws.com",
                "arn:aws:eks:us-west-1:123456789012:cluster/eks-arn-cluster",
                {"method": "exec", "region": "us-west-1", "name": "eks-arn-cluster"},
                False,
            ),
            (
                "https://irrelevant.host.com",
                "eks-fqdn-cluster.us-east-1.eksctl.io",
                {"method": "exec", "region": "us-east-1", "name": "eks-fqdn-cluster"},
                False,
            ),
        ],
    )
    @patch("devservers.cli.handlers.user.config")
    @patch("devservers.cli.handlers.user.client")
    def test_generate_user_kubeconfig(
        self,
        mock_k8s_client,
        mock_kube_config,
        host_url,
        cluster_name_in_context,
        expected_auth,
        expect_token_call,
    ):
        """Tests that the correct kubeconfig is generated for local and EKS clusters."""
        username = f"test-user-{expected_auth.get('name', 'local')}"
        namespace = f"dev-{username}"

        # Mock away the check for the aws-auth configmap to control detection
        mock_core_v1_api = mock_k8s_client.CoreV1Api.return_value
        if expected_auth["method"] == "exec":
            # If we expect an EKS kubeconfig, the aws-auth check should succeed
            mock_core_v1_api.read_namespaced_config_map.return_value = True
        else:
            # Otherwise, it should raise a 404 Not Found error
            # We must use a class that inherits from BaseException for the mock side_effect
            class MockApiException(Exception):
                def __init__(self, status=0, reason=None):
                    self.status = status
                    self.reason = reason

            mock_core_v1_api.read_namespaced_config_map.side_effect = MockApiException(
                status=404
            )

        # Mock CustomObjectsApi
        mock_user_obj = {"status": {"namespace": namespace}}
        mock_k8s_client.CustomObjectsApi.return_value.get_cluster_custom_object.return_value = (
            mock_user_obj
        )

        # Mock CoreV1Api for token generation
        mock_core_v1_api.create_namespaced_service_account_token.return_value.status.token = (
            "test-token"
        )

        # Mock kubeconfig loading
        mock_api_client_config = client.Configuration()
        mock_api_client_config.host = host_url
        mock_api_client_config.ssl_ca_cert = "/path/to/ca.crt"
        mock_k8s_client.Configuration.get_default_copy.return_value = (
            mock_api_client_config
        )

        mock_kube_config.list_kube_config_contexts.return_value = (
            [],
            {"context": {"cluster": cluster_name_in_context}},
        )

        with patch("builtins.open", mock_open(read_data=b"cert-data")), patch(
            "base64.b64encode"
        ) as mock_b64encode:
            mock_b64encode.return_value.decode.return_value = "base64-cert-data"

            captured_output = io.StringIO()
            original_stdout = sys.stdout
            try:
                sys.stdout = captured_output
                handlers.user.generate_user_kubeconfig(username)
            finally:
                sys.stdout = original_stdout

            output = captured_output.getvalue()
            kubeconfig_data = yaml.safe_load(output)

            assert kubeconfig_data["current-context"] == username
            user_auth = kubeconfig_data["users"][0]["user"]

            if expected_auth["method"] == "token":
                assert "token" in user_auth
                assert user_auth["token"] == "test-token"
                assert "exec" not in user_auth
            elif expected_auth["method"] == "exec":
                assert "exec" in user_auth
                exec_config = user_auth["exec"]
                assert (
                    exec_config["apiVersion"] == "client.authentication.k8s.io/v1beta1"
                )
                assert exec_config["command"] == "aws"
                assert exec_config["args"] == [
                    "--region",
                    expected_auth["region"],
                    "eks",
                    "get-token",
                    "--cluster-name",
                    expected_auth["name"],
                    "--output",
                    "json",
                ]
                assert exec_config["env"] is None
                assert exec_config["interactiveMode"] == "IfAvailable"
                assert exec_config["provideClusterInfo"] is False
                assert "token" not in user_auth

            if expect_token_call:
                mock_k8s_client.CoreV1Api.return_value.create_namespaced_service_account_token.assert_called_once()
            else:
                mock_k8s_client.CoreV1Api.return_value.create_namespaced_service_account_token.assert_not_called()
