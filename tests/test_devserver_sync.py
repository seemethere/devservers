import tempfile
import os
import shutil


def test_devserver_workspace_sync(
    operator_running, devserver_factory, devserver_user
):
    """
    Tests that the workspace sync functionality correctly copies files into the
    DevServer pod on creation.
    """
    local_tmp_dir = tempfile.mkdtemp(prefix="devserver-sync-test-")
    try:
        test_file_path = os.path.join(local_tmp_dir, "hello.txt")
        with open(test_file_path, "w") as f:
            f.write("hello from sync test")

        remote_path = "/workspace"
        sync_map = {local_tmp_dir: remote_path}

        devserver_spec = {
            "flavor": "cpu-small",
            "image": "ubuntu:22.04",
            "user": devserver_user,
            "ssh": {"publicKey": "ssh-rsa AAAA..."},
            "lifecycle": {"timeToLive": "10m"},
        }

        devserver_instance = devserver_factory(
            "sync-test", spec=devserver_spec, sync_workspace=sync_map
        )

        with devserver_instance as devserver:
            devserver.sync()

            remote_file_path = f"{remote_path}/hello.txt"
            exec_result = devserver.exec(f"cat {remote_file_path}")

            assert exec_result.returncode == 0
            assert "hello from sync test" in exec_result.stdout

            # Verify that the file is owned by the correct user.
            # The entrypoint script should chown the workspace directory.
            stat_result = devserver.exec(f"stat -c '%U:%G' {remote_file_path}")
            assert stat_result.returncode == 0
            assert "dev:dev" in stat_result.stdout

    finally:
        shutil.rmtree(local_tmp_dir)
