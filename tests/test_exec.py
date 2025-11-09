from devservers.crds.devserver import DevServer
from devservers.crds.base import ObjectMeta
from tests.conftest import TEST_NAMESPACE


def test_devserver_exec_success_string_arg(operator_running, test_ssh_public_key, test_flavor):
    name = "test-exec-success"
    spec = {
        "flavor": test_flavor,
        "image": "ubuntu:22.04",
        "ssh": {"publicKey": test_ssh_public_key},
        "lifecycle": {"timeToLive": "10m"},
    }
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec("echo 'hello world'")
        assert result.returncode == 0
        assert result.stdout == "hello world\n"
        assert result.stderr == ""


def test_devserver_exec_success_list_arg(operator_running, test_ssh_public_key, test_flavor):
    name = "test-exec-success-list"
    spec = {
        "flavor": test_flavor,
        "image": "ubuntu:22.04",
        "ssh": {"publicKey": test_ssh_public_key},
        "lifecycle": {"timeToLive": "10m"},
    }
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec(["echo", "hello", "world"])
        assert result.returncode == 0
        assert result.stdout == "hello world\n"
        assert result.stderr == ""


def test_devserver_exec_shell_true(operator_running, test_ssh_public_key, test_flavor):
    name = "test-exec-shell"
    spec = {
        "flavor": test_flavor,
        "image": "ubuntu:22.04",
        "ssh": {"publicKey": test_ssh_public_key},
        "lifecycle": {"timeToLive": "10m"},
    }
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec("echo 'hello' | cat", shell=True)
        assert result.returncode == 0
        assert result.stdout == "hello\n"
        assert result.stderr == ""


def test_devserver_exec_fail(operator_running, test_ssh_public_key, test_flavor):
    name = "test-exec-fail"
    spec = {
        "flavor": test_flavor,
        "image": "ubuntu:22.04",
        "ssh": {"publicKey": test_ssh_public_key},
        "lifecycle": {"timeToLive": "10m"},
    }
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec("exit 123", shell=True)
        assert result.returncode == 123
