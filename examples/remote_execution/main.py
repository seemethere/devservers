import os
import tempfile
import time
from contextlib import contextmanager

from devservers.crds.base import ObjectMeta
from devservers.crds.devserver import DevServer
from kubernetes import config


@contextmanager
def create_temp_workspace(num_files: int, file_size_kb: int, ignored_files: int):
    """Creates a temporary workspace with a number of files and a .gitignore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(num_files):
            with open(os.path.join(tmpdir, f"file_{i}.txt"), "w") as f:
                f.write("a" * file_size_kb * 1024)

        # Create some ignored files
        ignored_dir = os.path.join(tmpdir, ".venv")
        os.makedirs(ignored_dir)
        for i in range(ignored_files):
            with open(os.path.join(ignored_dir, f"ignored_file_{i}.txt"), "w") as f:
                f.write("ignored")

        yield tmpdir


def main():
    """
    This script demonstrates how to create a DevServer with a synchronized workspace,
    execute commands on it, and ensure it gets cleaned up.
    """
    # Load Kubernetes configuration from default location.
    config.load_kube_config()

    devserver_name = "remote-exec-benchmark"
    namespace = "default"
    # THIS SHOULD STAY AT cpu-small
    flavor = "cpu-small"
    disk_size = "256Gi"

    # --- Benchmark setup ---
    num_files = 10
    file_size_kb = 1024  # 1MB per file
    ignored_files = 5
    # -----------------------

    with create_temp_workspace(num_files, file_size_kb, ignored_files) as local_workspace:
        remote_workspace = "/workspace"
        print(f"Temporary workspace created at: {local_workspace}")
        print(f"Syncing {num_files} files ({file_size_kb}KB each) and {ignored_files} ignored files.")

        metadata = ObjectMeta(name=devserver_name, namespace=namespace)
        spec = {
            "flavor": flavor,
            "persistentHome": {"enabled": True, "size": disk_size},
            "ssh": {"publicKey": "ssh-rsa AAAA..."},
            "lifecycle": {"timeToLive": "8h"},
        }
        sync_workspace = {local_workspace: remote_workspace}

        start_time = time.time()
        with DevServer(metadata=metadata, spec=spec, sync_workspace=sync_workspace) as devserver:
            end_time = time.time()
            print(f"DevServer '{devserver.metadata.name}' is ready in namespace '{devserver.metadata.namespace}'.")
            print(f"Time to create and sync: {end_time - start_time:.2f} seconds")

            # Verify that ignored files were synced
            result = devserver.exec("ls -l /workspace/.venv")
            print("\nContents of /workspace/.venv (should be empty with .gitignore):")
            print(result.stdout)

    print(f"DevServer '{devserver_name}' has been deleted.")


if __name__ == "__main__":
    main()
