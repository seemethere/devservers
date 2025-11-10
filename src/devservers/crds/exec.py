from dataclasses import dataclass


@dataclass
class ExecResult:
    """
    ExecResult is a dataclass that holds the results of a command execution.
    It is similar to subprocess.CompletedProcess.
    """

    stdout: str
    stderr: str
    returncode: int
