import hashlib
import re
from typing import Any, Dict


def build_deployment(
    name: str,
    namespace: str,
    spec: Dict[str, Any],
    flavor: Dict[str, Any],
    default_devserver_image: str,
    static_dependencies_image: str,
) -> Dict[str, Any]:
    """Builds the Deployment for the DevServer."""
    image = spec.get("image", default_devserver_image)

    # Get the public key from the spec
    ssh_public_key = spec.get("ssh", {}).get("publicKey", "")

    deployment_spec = {
        "replicas": 1,
        "strategy": {"type": "Recreate"},
        "selector": {"matchLabels": {"app": name}},
        "template": {
            "metadata": {"labels": {"app": name}},
            "spec": {
                "nodeSelector": flavor["spec"].get("nodeSelector"),
                "tolerations": flavor["spec"].get("tolerations"),
                "initContainers": [
                    {
                        "name": "install-sshd",
                        "image": static_dependencies_image,
                        "imagePullPolicy": "Always",
                        "command": ["/bin/sh", "-c"],
                        "args": [
                            """
                            set -ex
                            echo "[INIT] Copying portable binaries..."
                            cp /usr/local/bin/sshd /opt/bin/
                            cp /usr/local/bin/scp /opt/bin/
                            cp /usr/local/bin/sftp-server /opt/bin/
                            cp /usr/local/bin/ssh-keygen /opt/bin/
                            cp /usr/local/bin/doas /opt/bin/
                            chmod +x /opt/bin/sshd
                            chmod u+s /opt/bin/doas
                            chmod +x /opt/bin/doas
                            echo "[INIT] Binaries copied."
                            """
                        ],
                        "volumeMounts": [{"name": "bin", "mountPath": "/opt/bin"}],
                    },
                ],
                "containers": [
                    {
                        "name": "devserver",
                        "image": image,
                        "imagePullPolicy": "Always",
                        "command": ["/bin/sh", "-c"],
                        "args": ["/devserver/startup.sh"],
                        "ports": [{"containerPort": 22}],
                        "volumeMounts": [
                            {"name": "home", "mountPath": "/home/dev"},
                            {"name": "bin", "mountPath": "/opt/bin"},
                            {
                                "name": "startup-script",
                                "mountPath": "/devserver",
                                "readOnly": True,
                            },
                            {
                                "name": "login-script",
                                "mountPath": "/devserver-login/user_login.sh",
                                "mode": 0o755,
                                "subPath": "user_login.sh",
                                "readOnly": True,
                            },
                            {
                                "name": "sshd-config",
                                "mountPath": "/opt/ssh/sshd_config",
                                "subPath": "sshd_config",
                                "readOnly": True,
                            },
                            {
                                "name": "host-keys",
                                "mountPath": "/opt/ssh/hostkeys",
                                "readOnly": True,
                            },
                        ],
                        "resources": flavor["spec"]["resources"],
                        "env": [
                            {
                                "name": "SSH_PUBLIC_KEY",
                                "value": ssh_public_key,
                            },
                        ],
                    }
                ],
                "volumes": [
                    {"name": "bin", "emptyDir": {}},
                    {
                        "name": "startup-script",
                        "configMap": {
                            "name": f"{name}-startup-script",
                            "defaultMode": 0o755,
                        },
                    },
                    {
                        "name": "login-script",
                        "configMap": {
                            "name": f"{name}-login-script",
                            "defaultMode": 0o755,
                        },
                    },
                    {
                        "name": "sshd-config",
                        "configMap": {"name": f"{name}-sshd-config"},
                    },
                    {
                        "name": "host-keys",
                        "secret": {
                            "secretName": f"{name}-host-keys",
                            "defaultMode": 0o600,
                        },
                    },
                ],
            },
        },
    }

    template = deployment_spec["template"]
    assert isinstance(template, dict)
    pod_spec = template["spec"]
    assert isinstance(pod_spec, dict)
    volumes = pod_spec.get("volumes")
    assert isinstance(volumes, list)

    def _sanitize(value: str) -> str:
        sanitized = re.sub(r"[^a-z0-9-]", "-", value.lower())
        return re.sub(r"-+", "-", sanitized).strip("-")

    def _stable_volume_name(claim_name: str, mount_path: str) -> str:
        sanitized_path = re.sub(r"[^a-z0-9-]", "-", mount_path.lower().strip("/"))
        sanitized_path = re.sub(r"-+", "-", sanitized_path).strip("-")
        raw_name = f"vol-{claim_name}"
        if sanitized_path:
            raw_name = f"{raw_name}-{sanitized_path}"

        sanitized = _sanitize(raw_name) or "vol"
        if len(sanitized) <= 63:
            return sanitized

        hash_suffix = hashlib.sha1(raw_name.encode()).hexdigest()[:6]
        trim_len = max(1, 63 - len(hash_suffix) - 1)
        prefix = sanitized[:trim_len].rstrip("-")
        if not prefix:
            prefix = sanitized[:trim_len]
        return f"{prefix}-{hash_suffix}"

    flavor_volumes = flavor["spec"].get("volumes", [])
    user_volumes = spec.get("volumes", [])

    # Merge volumes, user_volumes override flavor_volumes on mountPath conflict
    merged_volumes = {v["mountPath"]: v for v in flavor_volumes}
    merged_volumes.update({v["mountPath"]: v for v in user_volumes})
    final_volumes = list(merged_volumes.values())

    home_mount_path = "/home/dev"
    home_volume_specified = any(
        v.get("mountPath") == home_mount_path for v in final_volumes
    )

    if not final_volumes or not home_volume_specified:
        # Ensure there's always writable storage at /home/dev unless overridden.
        volumes.append({"name": "home", "emptyDir": {}})

    if final_volumes:
        # User specified volumes: mount each PVC
        containers = pod_spec.get("containers")
        assert isinstance(containers, list)
        container = containers[0]
        assert isinstance(container, dict)
        volume_mounts = container.get("volumeMounts")
        assert isinstance(volume_mounts, list)

        if home_volume_specified:
            # Remove the default home mount since a PVC will replace it.
            volume_mounts[:] = [
                vm for vm in volume_mounts if vm.get("name") != "home"
            ]

        for volume in final_volumes:
            claim_name = volume["claimName"]
            mount_path = volume["mountPath"]
            read_only = volume.get("readOnly", False)
            volume_name = _stable_volume_name(claim_name, mount_path)

            # Add to volumes list
            volumes.append({
                "name": volume_name,
                "persistentVolumeClaim": {"claimName": claim_name}
            })

            # Add to volumeMounts list
            volume_mounts.append({
                "name": volume_name,
                "mountPath": mount_path,
                "readOnly": read_only
            })

    # Remove nodeSelector if it is None
    if not pod_spec.get("nodeSelector"):
        pod_spec.pop("nodeSelector", None)

    # Remove tolerations if it is None
    if not pod_spec.get("tolerations"):
        pod_spec.pop("tolerations", None)

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": deployment_spec,
    }
