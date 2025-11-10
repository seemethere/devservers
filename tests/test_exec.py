from dataclasses import dataclass
from typing import Iterable, Union

import pytest

from devservers.crds.base import ObjectMeta
from devservers.crds.devserver import DevServer
from tests.conftest import TEST_NAMESPACE


@dataclass(frozen=True)
class ExecCommandExpectation:
    command: Union[str, Iterable[str]]
    shell: bool
    expected_stdout: str


def _make_devserver_spec(flavor: str, public_key: str, image: str = "ubuntu:22.04") -> dict[str, object]:
    return {
        "flavor": flavor,
        "image": image,
        "ssh": {"publicKey": public_key},
        "lifecycle": {"timeToLive": "10m"},
    }


@pytest.mark.parametrize(
    "name_suffix, expectation",
    [
        (
            "success",
            ExecCommandExpectation(
                command="echo 'hello world'",
                shell=False,
                expected_stdout="hello world\n",
            ),
        ),
        (
            "success-list",
            ExecCommandExpectation(
                command=["echo", "hello", "world"],
                shell=False,
                expected_stdout="hello world\n",
            ),
        ),
        (
            "shell",
            ExecCommandExpectation(
                command="echo 'hello' | cat",
                shell=True,
                expected_stdout="hello\n",
            ),
        ),
    ],
)
def test_devserver_exec_success(
    operator_running,
    test_ssh_public_key,
    test_flavor,
    name_suffix: str,
    expectation: ExecCommandExpectation,
) -> None:
    name = f"test-exec-{name_suffix}"
    spec = _make_devserver_spec(test_flavor, test_ssh_public_key)
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec(expectation.command, shell=expectation.shell)
        assert result.returncode == 0
        assert result.stdout == expectation.expected_stdout
        assert result.stderr == ""


def test_devserver_exec_fail(operator_running, test_ssh_public_key, test_flavor):
    name = "test-exec-fail"
    spec = _make_devserver_spec(test_flavor, test_ssh_public_key)
    metadata = ObjectMeta(name=name, namespace=TEST_NAMESPACE)
    with DevServer(metadata=metadata, spec=spec) as devserver:
        result = devserver.exec("exit 123", shell=True)
        assert result.returncode == 123
