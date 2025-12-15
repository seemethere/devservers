"""Kubernetes resources for DevServer infrastructure"""

import pulumi
import pulumi_kubernetes as k8s
import json
import yaml
from config import PREFIX, REGION
from eks import EKSResources
from iam import IAMResources


class KubernetesResources:
    """Kubernetes resources (ConfigMaps, Namespaces, DaemonSets, etc.)"""

    def __init__(self, eks: EKSResources, iam: IAMResources):
        self.eks = eks
        self.iam = iam

        # Create kubeconfig for the cluster
        kubeconfig = pulumi.Output.all(
            eks.cluster.endpoint,
            eks.cluster.certificate_authority.data,
            eks.cluster.name
        ).apply(lambda args: json.dumps({
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{
                "cluster": {
                    "server": args[0],
                    "certificate-authority-data": args[1],
                },
                "name": "kubernetes",
            }],
            "contexts": [{
                "context": {
                    "cluster": "kubernetes",
                    "user": "aws",
                },
                "name": "aws",
            }],
            "current-context": "aws",
            "users": [{
                "name": "aws",
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "aws",
                        "args": [
                            "eks",
                            "get-token",
                            "--cluster-name",
                            args[2],
                            "--region",
                            REGION,
                        ],
                    },
                },
            }],
        }))

        # Create Kubernetes provider
        self.k8s_provider = k8s.Provider(
            f"{PREFIX}-k8s-provider",
            kubeconfig=kubeconfig,
        )

        # Create aws-auth ConfigMap to allow nodes to join the cluster
        self.aws_auth = k8s.core.v1.ConfigMap(
            "aws-auth",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="aws-auth",
                namespace="kube-system",
            ),
            data={
                "mapRoles": pulumi.Output.all(iam.eks_node_role.arn).apply(
                    lambda args: yaml.dump([
                        {
                            "rolearn": args[0],
                            "username": "system:node:{{EC2PrivateDNSName}}",
                            "groups": [
                                "system:bootstrappers",
                                "system:nodes",
                            ]
                        }
                    ])
                )
            },
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[eks.cluster],
            ),
        )

        # Create devserver namespace
        self.namespace = k8s.core.v1.Namespace(
            "devserver-ns",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="devserver",
                labels={
                    "name": "devserver",
                    "purpose": "development-servers",
                },
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[eks.cluster],
            ),
        )

        # Create service account for dev pods
        self.service_account = k8s.core.v1.ServiceAccount(
            "devserver-sa",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="devserver-service-account",
                namespace=self.namespace.metadata.name,
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[self.namespace],
            ),
        )

        # Create role for dev pods
        self.role = k8s.rbac.v1.Role(
            "devserver-role",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="devserver-role",
                namespace=self.namespace.metadata.name,
            ),
            rules=[
                k8s.rbac.v1.PolicyRuleArgs(
                    api_groups=[""],
                    resources=["pods", "pods/log", "pods/exec"],
                    verbs=["get", "list", "create", "update", "patch", "watch"],
                )
            ],
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[self.namespace],
            ),
        )

        # Create role binding
        self.role_binding = k8s.rbac.v1.RoleBinding(
            "devserver-role-binding",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="devserver-role-binding",
                namespace=self.namespace.metadata.name,
            ),
            role_ref=k8s.rbac.v1.RoleRefArgs(
                api_group="rbac.authorization.k8s.io",
                kind="Role",
                name=self.role.metadata.name,
            ),
            subjects=[
                k8s.rbac.v1.SubjectArgs(
                    kind="ServiceAccount",
                    name=self.service_account.metadata.name,
                    namespace=self.namespace.metadata.name,
                )
            ],
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[self.role, self.service_account],
            ),
        )

        # Create EFA device plugin
        self._create_efa_device_plugin()

    def _create_efa_device_plugin(self):
        """Create AWS EFA device plugin DaemonSet"""

        # Create service account for EFA device plugin
        efa_sa = k8s.core.v1.ServiceAccount(
            "efa-device-plugin-sa",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="aws-efa-k8s-device-plugin",
                namespace="kube-system",
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[self.eks.cluster],
            ),
        )

        # Create EFA device plugin DaemonSet
        self.efa_daemonset = k8s.apps.v1.DaemonSet(
            "efa-device-plugin-daemonset",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="aws-efa-k8s-device-plugin-daemonset",
                namespace="kube-system",
            ),
            spec=k8s.apps.v1.DaemonSetSpecArgs(
                selector=k8s.meta.v1.LabelSelectorArgs(
                    match_labels={
                        "name": "aws-efa-k8s-device-plugin",
                    },
                ),
                template=k8s.core.v1.PodTemplateSpecArgs(
                    metadata=k8s.meta.v1.ObjectMetaArgs(
                        labels={
                            "name": "aws-efa-k8s-device-plugin",
                        },
                    ),
                    spec=k8s.core.v1.PodSpecArgs(
                        service_account_name=efa_sa.metadata.name,
                        host_network=True,
                        node_selector={
                            "kubernetes.io/arch": "amd64",
                        },
                        tolerations=[
                            k8s.core.v1.TolerationArgs(
                                key="CriticalAddonsOnly",
                                operator="Exists",
                            ),
                            k8s.core.v1.TolerationArgs(
                                key="aws.amazon.com/efa",
                                operator="Exists",
                                effect="NoSchedule",
                            ),
                        ],
                        containers=[
                            k8s.core.v1.ContainerArgs(
                                name="aws-efa-k8s-device-plugin",
                                image="602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/aws-efa-k8s-device-plugin:v0.3.3",
                                image_pull_policy="Always",
                                security_context=k8s.core.v1.SecurityContextArgs(
                                    allow_privilege_escalation=False,
                                    capabilities=k8s.core.v1.CapabilitiesArgs(
                                        drop=["ALL"],
                                    ),
                                ),
                                resources=k8s.core.v1.ResourceRequirementsArgs(
                                    requests={
                                        "cpu": "10m",
                                        "memory": "10Mi",
                                    },
                                    limits={
                                        "cpu": "10m",
                                        "memory": "10Mi",
                                    },
                                ),
                                volume_mounts=[
                                    k8s.core.v1.VolumeMountArgs(
                                        name="device-plugin",
                                        mount_path="/var/lib/kubelet/device-plugins",
                                    ),
                                    k8s.core.v1.VolumeMountArgs(
                                        name="proc",
                                        mount_path="/host/proc",
                                    ),
                                    k8s.core.v1.VolumeMountArgs(
                                        name="sys",
                                        mount_path="/host/sys",
                                    ),
                                ],
                            ),
                        ],
                        volumes=[
                            k8s.core.v1.VolumeArgs(
                                name="device-plugin",
                                host_path=k8s.core.v1.HostPathVolumeSourceArgs(
                                    path="/var/lib/kubelet/device-plugins",
                                ),
                            ),
                            k8s.core.v1.VolumeArgs(
                                name="proc",
                                host_path=k8s.core.v1.HostPathVolumeSourceArgs(
                                    path="/proc",
                                ),
                            ),
                            k8s.core.v1.VolumeArgs(
                                name="sys",
                                host_path=k8s.core.v1.HostPathVolumeSourceArgs(
                                    path="/sys",
                                ),
                            ),
                        ],
                    ),
                ),
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[efa_sa, self.eks.cluster],
            ),
        )
