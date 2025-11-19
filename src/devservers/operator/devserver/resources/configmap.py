from typing import Any, Dict


def build_config_configmap(
    name: str,
    namespace: str,
    startup_script: str,
    user_login_script: str,
    sshd_config: str,
) -> Dict[str, Any]:
    """Builds a single ConfigMap containing all configuration files."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{name}-config",
            "namespace": namespace,
        },
        "data": {
            "startup.sh": startup_script,
            "user_login.sh": user_login_script,
            "sshd_config": sshd_config,
        },
    }
