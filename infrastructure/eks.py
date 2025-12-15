"""EKS cluster and node groups for DevServer infrastructure"""

import pulumi
import pulumi_aws as aws
import base64
from typing import Dict, Any
from config import PREFIX, EKS_VERSION, KEY_PAIR_NAME, COMMON_TAGS, SUPPORTED_GPU_TYPES, REGION
from vpc import VPCResources
from iam import IAMResources
from user_data import get_gpu_user_data, get_cpu_user_data


class EKSResources:
    """EKS cluster and node groups"""

    def __init__(self, vpc: VPCResources, iam: IAMResources):
        self.vpc = vpc
        self.iam = iam

        # Create EKS Cluster
        self.cluster = aws.eks.Cluster(
            f"{PREFIX}-cluster",
            name=f"{PREFIX}-cluster",
            version=EKS_VERSION,
            role_arn=iam.eks_cluster_role.arn,
            vpc_config=aws.eks.ClusterVpcConfigArgs(
                subnet_ids=vpc.get_all_subnet_ids(),
                security_group_ids=[vpc.eks_control_plane_sg.id],
                endpoint_private_access=True,
                endpoint_public_access=True,
            ),
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-cluster",
            },
        )

        # Get AMIs for different architectures
        self.x86_64_ami = aws.ec2.get_ami(
            most_recent=True,
            owners=["amazon"],
            filters=[
                aws.ec2.GetAmiFilterArgs(
                    name="name",
                    values=["amazon-eks-node-al2023-x86_64-standard-1.34-*"],
                ),
                aws.ec2.GetAmiFilterArgs(
                    name="architecture",
                    values=["x86_64"],
                ),
            ],
        )

        self.arm64_ami = aws.ec2.get_ami(
            most_recent=True,
            owners=["amazon"],
            filters=[
                aws.ec2.GetAmiFilterArgs(
                    name="name",
                    values=["amazon-eks-node-al2023-arm64-standard-1.34-*"],
                ),
                aws.ec2.GetAmiFilterArgs(
                    name="architecture",
                    values=["arm64"],
                ),
            ],
        )

        # Create CPU management nodes FIRST (so addons have nodes to deploy to)
        self._create_cpu_node_group()

        # Install EKS addons (after CPU nodes so they have nodes to deploy to)
        self.vpc_cni_addon = aws.eks.Addon(
            f"{PREFIX}-vpc-cni",
            cluster_name=self.cluster.name,
            addon_name="vpc-cni",
            resolve_conflicts_on_create="OVERWRITE",
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-vpc-cni",
            },
            opts=pulumi.ResourceOptions(
                depends_on=[self.cluster, self.cpu_asg],
            ),
        )

        self.ebs_csi_addon = aws.eks.Addon(
            f"{PREFIX}-ebs-csi-driver",
            cluster_name=self.cluster.name,
            addon_name="aws-ebs-csi-driver",
            resolve_conflicts_on_create="OVERWRITE",
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-ebs-csi-driver",
            },
            opts=pulumi.ResourceOptions(
                depends_on=[self.cluster, self.cpu_asg],
            ),
        )

        # Create placement groups for GPU types that need them
        self.placement_groups = {}
        for gpu_type, config in SUPPORTED_GPU_TYPES.items():
            if config.get("use_placement_group", False):
                self.placement_groups[gpu_type] = aws.ec2.PlacementGroup(
                    f"{PREFIX}-pg-{gpu_type}",
                    name=f"{PREFIX}-gpu-{gpu_type}-cluster",
                    strategy="cluster",
                    tags={
                        **COMMON_TAGS,
                        "Name": f"{PREFIX}-gpu-{gpu_type}-cluster",
                        "GpuType": gpu_type,
                    },
                )

        # Create GPU node groups (after addons)
        self.gpu_asgs = {}
        self.gpu_launch_templates = {}

        for gpu_type, config in SUPPORTED_GPU_TYPES.items():
            if config["gpus_per_instance"] > 0:  # Only for GPU nodes
                self._create_gpu_node_group(gpu_type, config)

    def _create_gpu_node_group(self, gpu_type: str, config: Dict[str, Any]):
        """Create a GPU node group with launch template and ASG"""

        # Get the appropriate AMI based on architecture
        ami_id = self.x86_64_ami.id if config.get("architecture", "x86_64") == "x86_64" else self.arm64_ami.id

        # Determine subnet based on GPU type
        # For simplicity, we'll put all nodes in primary subnet for now
        # In production, you'd implement the complex subnet logic from Terraform
        subnet = self.vpc.primary_subnet

        # Create launch template
        user_data_script = pulumi.Output.all(
            self.cluster.name,
            self.cluster.endpoint,
            self.cluster.certificate_authority.data,
        ).apply(lambda args: get_gpu_user_data(
            cluster_name=args[0],
            cluster_endpoint=args[1],
            cluster_ca=args[2],
            cluster_cidr="10.0.0.0/16",
            region=REGION,
            gpu_type=gpu_type,
        ))

        launch_template = aws.ec2.LaunchTemplate(
            f"{PREFIX}-lt-{gpu_type}",
            name_prefix=f"{PREFIX}-gpu-{gpu_type}-",
            image_id=ami_id,
            instance_type=config["instance_type"],
            key_name=KEY_PAIR_NAME,
            iam_instance_profile=aws.ec2.LaunchTemplateIamInstanceProfileArgs(
                name=self.iam.node_instance_profile.name,
            ),
            block_device_mappings=[
                aws.ec2.LaunchTemplateBlockDeviceMappingArgs(
                    device_name="/dev/xvda",
                    ebs=aws.ec2.LaunchTemplateBlockDeviceMappingEbsArgs(
                        volume_size=4096,  # 4TB
                        volume_type="gp3",
                        delete_on_termination=True,
                        encrypted=True,
                    ),
                )
            ],
            network_interfaces=[
                aws.ec2.LaunchTemplateNetworkInterfaceArgs(
                    associate_public_ip_address=True,
                    security_groups=[self.vpc.worker_sg.id],
                    delete_on_termination=True,
                    # EFA for GPU instances (except t4-small)
                    interface_type="efa" if gpu_type != "t4-small" else "interface",
                )
            ],
            placement=aws.ec2.LaunchTemplatePlacementArgs(
                group_name=self.placement_groups[gpu_type].name,
            ) if config.get("use_placement_group", False) else None,
            user_data=user_data_script.apply(lambda s: base64.b64encode(s.encode()).decode()),
            tag_specifications=[
                aws.ec2.LaunchTemplateTagSpecificationArgs(
                    resource_type="instance",
                    tags={
                        **COMMON_TAGS,
                        "Name": f"{PREFIX}-gpu-instance-{gpu_type}",
                        "GpuType": gpu_type,
                    },
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-gpu-launch-template-{gpu_type}",
                "GpuType": gpu_type,
            },
        )

        self.gpu_launch_templates[gpu_type] = launch_template

        # Create Auto Scaling Group
        asg = aws.autoscaling.Group(
            f"{PREFIX}-asg-{gpu_type}",
            name=f"{PREFIX}-gpu-nodes-{gpu_type}",
            vpc_zone_identifiers=[subnet.id],  # Note: plural in Pulumi
            min_size=config["instance_count"],
            max_size=config["instance_count"],
            desired_capacity=config["instance_count"],
            health_check_type="EC2",
            health_check_grace_period=300,
            launch_template=aws.autoscaling.GroupLaunchTemplateArgs(
                id=launch_template.id,
                version="$Latest",
            ),
            tags=[
                aws.autoscaling.GroupTagArgs(
                    key="Name",
                    value=f"{PREFIX}-gpu-node-{gpu_type}",
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key=f"kubernetes.io/cluster/{PREFIX}-cluster",
                    value="owned",
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key="Environment",
                    value=COMMON_TAGS["Environment"],
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key="GpuType",
                    value=gpu_type,
                    propagate_at_launch=True,
                ),
            ],
        )

        self.gpu_asgs[gpu_type] = asg

    def _create_cpu_node_group(self):
        """Create CPU management node group"""

        user_data_script = pulumi.Output.all(
            self.cluster.name,
            self.cluster.endpoint,
            self.cluster.certificate_authority.data,
        ).apply(lambda args: get_cpu_user_data(
            cluster_name=args[0],
            cluster_endpoint=args[1],
            cluster_ca=args[2],
            cluster_cidr="10.0.0.0/16",
            region=REGION,
        ))

        # Create CPU launch template
        cpu_launch_template = aws.ec2.LaunchTemplate(
            f"{PREFIX}-lt-cpu",
            name_prefix=f"{PREFIX}-cpu-",
            image_id=self.x86_64_ami.id,
            instance_type="c5.4xlarge",
            key_name=KEY_PAIR_NAME,
            iam_instance_profile=aws.ec2.LaunchTemplateIamInstanceProfileArgs(
                name=self.iam.node_instance_profile.name,
            ),
            block_device_mappings=[
                aws.ec2.LaunchTemplateBlockDeviceMappingArgs(
                    device_name="/dev/xvda",
                    ebs=aws.ec2.LaunchTemplateBlockDeviceMappingEbsArgs(
                        volume_size=4096,
                        volume_type="gp3",
                        delete_on_termination=True,
                        encrypted=True,
                    ),
                )
            ],
            network_interfaces=[
                aws.ec2.LaunchTemplateNetworkInterfaceArgs(
                    associate_public_ip_address=True,
                    security_groups=[self.vpc.worker_sg.id],
                    delete_on_termination=True,
                )
            ],
            user_data=user_data_script.apply(lambda s: base64.b64encode(s.encode()).decode()),
            tag_specifications=[
                aws.ec2.LaunchTemplateTagSpecificationArgs(
                    resource_type="instance",
                    tags={
                        **COMMON_TAGS,
                        "Name": f"{PREFIX}-cpu-mgmt-node",
                        "NodeType": "cpu-management",
                    },
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-cpu-launch-template",
            },
        )

        # Create CPU Auto Scaling Group
        self.cpu_asg = aws.autoscaling.Group(
            f"{PREFIX}-asg-cpu",
            name=f"{PREFIX}-cpu-nodes",
            vpc_zone_identifiers=[self.vpc.primary_subnet.id, self.vpc.secondary_subnet.id],
            min_size=1,
            max_size=4,
            desired_capacity=2,
            health_check_type="EC2",
            health_check_grace_period=300,
            launch_template=aws.autoscaling.GroupLaunchTemplateArgs(
                id=cpu_launch_template.id,
                version="$Latest",
            ),
            tags=[
                aws.autoscaling.GroupTagArgs(
                    key="Name",
                    value=f"{PREFIX}-cpu-mgmt-node",
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key=f"kubernetes.io/cluster/{PREFIX}-cluster",
                    value="owned",
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key="Environment",
                    value=COMMON_TAGS["Environment"],
                    propagate_at_launch=True,
                ),
                aws.autoscaling.GroupTagArgs(
                    key="NodeType",
                    value="cpu-management",
                    propagate_at_launch=True,
                ),
            ],
        )
