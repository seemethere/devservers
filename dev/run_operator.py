#!/usr/bin/env python3
"""
Development script to install CRDs, launch the operator, and stream logs.

Usage:
    python dev/run_operator.py [--namespace NAMESPACE]
"""

import argparse
import asyncio
import sys
from pathlib import Path

import kopf
from kubernetes import client, utils

from devservers.utils.kube import (
    KubernetesConfigurationError,
    configure_kube_client,
)


def install_crds():
    """Install the DevServer CRDs into the cluster."""
    print("🔧 Installing DevServer CRDs...")

    try:
        configure_kube_client()
    except KubernetesConfigurationError as exc:
        print(f"❌ Failed to configure Kubernetes client: {exc}")
        print("ℹ️  Make sure you have kubectl configured and can access your cluster")
        sys.exit(1)

    k8s_client = client.ApiClient()
    api_extensions_v1 = client.ApiextensionsV1Api()

    # Get the project root directory (parent of dev/)
    project_root = Path(__file__).parent.parent
    crd_files = [
        project_root / "crds" / "devserver.io_devservers.yaml",
        project_root / "crds" / "devserver.io_devserverflavors.yaml",
    ]

    # Check if CRDs exist and their status
    crd_names = ["devservers.devserver.io", "devserverflavors.devserver.io"]
    for crd_name in crd_names:
        try:
            crd = api_extensions_v1.read_custom_resource_definition(name=crd_name)
            if crd.metadata.deletion_timestamp:
                print(f"⚠️  CRD {crd_name} is currently terminating")
                print(
                    "ℹ️  You may need to wait for it to fully delete before proceeding"
                )
            else:
                print(f"✅ CRD {crd_name} already exists")
        except client.ApiException as e:
            if e.status == 404:
                print(f"📝 CRD {crd_name} will be created")
            else:
                print(f"⚠️  Error checking CRD {crd_name}: {e}")

    # Apply CRDs
    for crd_file in crd_files:
        if not crd_file.exists():
            print(f"❌ CRD file not found: {crd_file}")
            sys.exit(1)

        try:
            print(f"📄 Applying {crd_file.name}...")
            utils.create_from_yaml(k8s_client, str(crd_file), apply=True)
        except Exception as e:
            print(f"⚠️  Warning: {e}")
            # Continue anyway - might be a race condition or already exists

    print("✅ CRDs installed successfully\n")


async def run_operator(namespaces=None):
    """Run the operator and stream logs."""
    print("🚀 Starting DevServer Operator...")

    # Import the operator module to register handlers
    import devservers.operator.operator  # noqa: F401

    if namespaces:
        print(f"👀 Watching namespace(s): {', '.join(namespaces)}")
    else:
        print("👀 Watching all namespaces")

    print("📡 Streaming logs (Ctrl+C to stop)...\n")
    print("=" * 80)

    try:
        await kopf.run(
            registry=kopf.get_default_registry(),
            priority=0,
            namespaces=namespaces,
            cluster_wide=not namespaces,
        )
    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print("🛑 Operator stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Operator error: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Install CRDs, launch the DevServer operator, and stream logs"
    )
    parser.add_argument(
        "--namespace",
        "-n",
        action="append",
        help="Namespace to watch (can be specified multiple times, default: all namespaces)",
    )
    parser.add_argument(
        "--skip-crds",
        action="store_true",
        help="Skip CRD installation (useful if CRDs are already installed)",
    )

    args = parser.parse_args()

    # Install CRDs unless skipped
    if not args.skip_crds:
        install_crds()
    else:
        print("⏭️  Skipping CRD installation\n")

    # Run the operator
    try:
        asyncio.run(run_operator(namespaces=args.namespace))
    except KeyboardInterrupt:
        print("\n🛑 Interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
