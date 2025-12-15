"""Helm charts for DevServer infrastructure"""

import pulumi
import pulumi_kubernetes as k8s
from eks import EKSResources


class HelmResources:
    """Helm charts (GPU Operator, etc.)"""

    def __init__(self, eks: EKSResources, k8s_provider: k8s.Provider):
        self.eks = eks
        self.k8s_provider = k8s_provider

        # Install NVIDIA GPU Operator
        # Note: This will wait for nodes to be available before installing
        self.gpu_operator = k8s.helm.v3.Release(
            "gpu-operator",
            name="gpu-operator",
            chart="gpu-operator",
            version="v25.3.3",
            namespace="gpu-operator",
            create_namespace=True,
            repository_opts=k8s.helm.v3.RepositoryOptsArgs(
                repo="https://helm.ngc.nvidia.com/nvidia",
            ),
            # Don't wait for resources to be ready - they need nodes first
            wait_for_jobs=False,
            skip_await=True,
            timeout=600,
            values={
                "operator": {
                    "defaultRuntime": "containerd",
                    "tolerations": [
                        {
                            "key": "nvidia.com/gpu",
                            "operator": "Exists",
                            "effect": "NoSchedule",
                        },
                        {
                            "key": "node-role",
                            "operator": "Equal",
                            "value": "cpu-only",
                            "effect": "NoSchedule",
                        },
                    ],
                    # Remove node selector so operator can run on any CPU node
                    # "nodeSelector": {
                    #     "NodeType": "cpu",
                    # },
                },
                "driver": {
                    "enabled": False,  # Drivers pre-installed via user-data
                },
                "toolkit": {
                    "enabled": True,
                    "runtimeClass": "",
                },
                "devicePlugin": {
                    "enabled": True,
                    "runtimeClass": "nvidia",
                },
                "dcgmExporter": {
                    "enabled": False,
                },
                "gfd": {
                    "enabled": True,
                    "runtimeClass": "nvidia",
                },
                "migManager": {
                    "enabled": True,
                    "config": {
                        "default": "all-disabled",
                    },
                },
                "mig": {
                    "strategy": "mixed",
                },
                "nodeStatusExporter": {
                    "enabled": True,
                },
            },
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[eks.cluster, eks.cpu_asg],
            ),
        )
