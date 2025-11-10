from typing import Any, Dict


def build_statefulset(
    name: str,
    namespace: str,
    spec: Dict[str, Any],
    flavor: Dict[str, Any],
    default_persistent_home_size: str,
    default_devserver_image: str,
    static_dependencies_image: str,
) -> Dict[str, Any]:
    """Builds the StatefulSet for the DevServer."""
    image = spec.get("image", default_devserver_image)

    # Get the public key from the spec
    ssh_public_key = spec.get("ssh", {}).get("publicKey", "")

    persistent_home = spec.get("persistentHome", {})
    persistent_home_enabled = persistent_home.get("enabled", False)
    persistent_home_size = persistent_home.get("size", default_persistent_home_size)

    statefulset_spec = {
        "replicas": 1,
        "serviceName": f"{name}-headless",
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

    template = statefulset_spec["template"]
    assert isinstance(template, dict)
    pod_spec = template["spec"]
    assert isinstance(pod_spec, dict)
    volumes = pod_spec.get("volumes")
    assert isinstance(volumes, list)

    if persistent_home_enabled:
        statefulset_spec["volumeClaimTemplates"] = [
            {
                "metadata": {"name": "home"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": persistent_home_size}},
                },
            }
        ]
    else:
        volumes.append({"name": "home", "emptyDir": {}})

    # Remove nodeSelector if it is None
    if not pod_spec.get("nodeSelector"):
        pod_spec.pop("nodeSelector", None)

    # Remove tolerations if it is None
    if not pod_spec.get("tolerations"):
        pod_spec.pop("tolerations", None)

    # Add shared volume if specified
    if "sharedVolumeClaimName" in spec:
        pvc_name = spec["sharedVolumeClaimName"]

        volumes = pod_spec.get("volumes")
        assert isinstance(volumes, list)
        # Add the volume that points to the existing PVC
        volumes.append(
            {"name": "shared", "persistentVolumeClaim": {"claimName": pvc_name}}
        )

        containers = pod_spec.get("containers")
        assert isinstance(containers, list)
        container = containers[0]
        assert isinstance(container, dict)

        volume_mounts = container.get("volumeMounts")
        assert isinstance(volume_mounts, list)
        # Mount the volume into the container
        volume_mounts.append({"name": "shared", "mountPath": "/shared"})

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": statefulset_spec,
    }
