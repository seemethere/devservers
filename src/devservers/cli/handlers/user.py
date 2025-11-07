from kubernetes import client, config
from rich.console import Console
from rich.table import Table
import sys
import yaml
from ...crds.const import (
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL_DEVSERVERUSER,
)
import re


class KubeConfig:
    def __init__(self, config_dict):
        self._config = config_dict

    def get_cluster(self, name):
        for cluster in self._config["clusters"]:
            if cluster["name"] == name:
                return cluster
        return None


def create_user(username: str) -> None:
    """Creates a new DevServerUser resource."""
    custom_objects_api = client.CustomObjectsApi()
    console = Console()

    manifest = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "DevServerUser",
        "metadata": {"name": username},
        "spec": {"username": username},
    }

    try:
        custom_objects_api.create_cluster_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            plural=CRD_PLURAL_DEVSERVERUSER,
            body=manifest,
        )
        console.print(f"✅ User '{username}' created successfully.")
    except client.ApiException as e:
        if e.status == 409:
            console.print(f"Error: User '{username}' already exists.")
        else:
            console.print(f"Error creating user: {e.reason}")


def delete_user(username: str) -> None:
    """Deletes a DevServerUser resource."""
    custom_objects_api = client.CustomObjectsApi()
    console = Console()

    try:
        custom_objects_api.delete_cluster_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            plural=CRD_PLURAL_DEVSERVERUSER,
            name=username,
        )
        console.print(f"✅ User '{username}' deleted successfully.")
    except client.ApiException as e:
        if e.status == 404:
            console.print(f"Error: User '{username}' not found.")
        else:
            console.print(f"Error deleting user: {e.reason}")


def list_users() -> None:
    """Lists all DevServerUser resources."""
    custom_objects_api = client.CustomObjectsApi()
    console = Console()

    try:
        users = custom_objects_api.list_cluster_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            plural=CRD_PLURAL_DEVSERVERUSER,
        )

        table = Table(title="DevServer Users")
        table.add_column("Name", style="cyan")
        table.add_column("Username", style="magenta")
        table.add_column("Namespace", style="green")
        table.add_column("Status", style="yellow")

        for user in users["items"]:
            status = user.get("status", {})
            table.add_row(
                user["metadata"]["name"],
                user["spec"]["username"],
                status.get("namespace", "N/A"),
                status.get("phase", "Unknown"),
            )

        if not users["items"]:
            console.print("No users found.")
        else:
            console.print(table)

    except client.ApiException as e:
        console.print(f"Error listing users: {e.reason}")


def generate_user_kubeconfig(username: str) -> None:
    """Generates a kubeconfig file for a DevServerUser."""
    custom_objects_api = client.CustomObjectsApi()
    core_v1_api = client.CoreV1Api()
    console = Console()

    try:
        # 1. Get User's Namespace
        user_obj = custom_objects_api.get_cluster_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            plural=CRD_PLURAL_DEVSERVERUSER,
            name=username,
        )
        namespace = user_obj.get("status", {}).get("namespace")
        if not namespace:
            console.print(
                f"❌ Error: Could not find namespace in DevServerUser '{username}'."
            )
            sys.exit(1)

        # 2. Get Cluster Info
        # Load the current kubeconfig to extract cluster details
        api_client_config = client.Configuration.get_default_copy()

        contexts, active_context = config.list_kube_config_contexts()
        cluster_name_from_context = active_context["context"]["cluster"]

        cluster_obj = {
            "server": api_client_config.host,
            "certificate-authority-data": None,  # This will be handled below
        }

        # The Python client library can be tricky with certs. We need to handle
        # both file paths and inline data.
        if api_client_config.ssl_ca_cert:
            with open(api_client_config.ssl_ca_cert, "rb") as f:
                import base64

                cluster_obj["certificate-authority-data"] = base64.b64encode(
                    f.read()
                ).decode("utf-8")
        else:
            # If no CA cert file is specified, the client might be using a
            # different auth method or insecure connection. For this tool, we
            # assume we need the CA data. A more robust implementation might
            # handle insecure-skip-tls-verify.
            pass

        # 3. Assemble Kubeconfig
        user_config = {}

        is_eks = False
        try:
            core_v1_api.read_namespaced_config_map("aws-auth", "kube-system")
            is_eks = True
        except Exception as e:
            # The k8s client's ApiException doesn't inherit from BaseException,
            # so we catch a broad Exception and check its type.
            if "ApiException" in str(type(e)) and getattr(e, "status", None) == 404:
                is_eks = False  # ConfigMap not found, not an EKS cluster
            else:
                # For other errors (like permissions), assume not EKS and warn
                console.print(
                    f"[yellow]Warning: Could not check for 'aws-auth' ConfigMap: {e}. "
                    "Assuming non-EKS cluster.[/yellow]"
                )
                is_eks = False

        if is_eks:
            cluster_name = ""
            region = ""
            # For EKS, we parse the cluster ARN to get the region and short name
            match_arn = re.match(
                r"arn:aws:eks:([^:]+):[^:]+:cluster/(.+)", cluster_name_from_context
            )
            if match_arn:
                region = match_arn.group(1)
                cluster_name = match_arn.group(2)
            else:
                # Try to parse as FQDN (eksctl naming convention)
                match_fqdn = re.match(
                    r"(.+)\.([^.]+)\.eksctl\.io", cluster_name_from_context
                )
                if match_fqdn:
                    cluster_name = match_fqdn.group(1)
                    region = match_fqdn.group(2)
                else:
                    console.print(
                        f"❌ Error: Could not parse EKS cluster name '{cluster_name_from_context}'. "
                        "Expected ARN (arn:aws:eks:...) or eksctl FQDN (...eksctl.io) format."
                    )
                    sys.exit(1)

            user_config = {
                "exec": {
                    "apiVersion": "client.authentication.k8s.io/v1beta1",
                    "command": "aws",
                    "args": [
                        "--region",
                        region,
                        "eks",
                        "get-token",
                        "--cluster-name",
                        cluster_name,
                        "--output",
                        "json",
                    ],
                    "env": None,
                    "interactiveMode": "IfAvailable",
                    "provideClusterInfo": False,
                }
            }
        else:
            sa_name = f"{username}-sa"
            token = core_v1_api.create_namespaced_service_account_token(
                sa_name, namespace, {}
            ).status.token
            user_config = {"token": token}

        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": username,
            "clusters": [
                {
                    "name": cluster_name_from_context,
                    "cluster": cluster_obj,
                }
            ],
            "contexts": [
                {
                    "name": username,
                    "context": {
                        "cluster": cluster_name_from_context,
                        "namespace": namespace,
                        "user": username,
                    },
                }
            ],
            "users": [
                {
                    "name": username,
                    "user": user_config,
                }
            ],
        }

        # Use a dumper that prefers literal block style for multiline strings
        class MyDumper(yaml.SafeDumper):
            def represent_scalar(self, tag, value, style=None):
                if "\n" in value:
                    style = "|"
                return super().represent_scalar(tag, value, style)

        # When printing to stdout for piping, we don't want Rich's markup
        print(yaml.dump(kubeconfig, Dumper=MyDumper))

    except Exception as e:
        if "ApiException" in str(type(e)):
            if getattr(e, "status", None) == 404:
                console.print(f"❌ Error: DevServerUser '{username}' not found.")
            else:
                reason = getattr(e, "reason", "Unknown")
                console.print(f"❌ Error: An API error occurred: {reason}")
        else:
            console.print(f"❌ An unexpected error occurred: {e}")
        sys.exit(1)
