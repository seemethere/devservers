"""VPC and networking components for DevServer infrastructure"""

import pulumi
import pulumi_aws as aws
from typing import List, Optional
from config import (
    PREFIX, VPC_CIDR, PRIMARY_SUBNET_CIDR, SECONDARY_SUBNET_CIDR,
    TERTIARY_SUBNET_CIDR, COMMON_TAGS
)


class VPCResources:
    """VPC and networking resources"""

    def __init__(self):
        # Get available availability zones
        self.azs = aws.get_availability_zones(state="available")

        # Create VPC
        self.vpc = aws.ec2.Vpc(
            f"{PREFIX}-vpc",
            cidr_block=VPC_CIDR,
            enable_dns_hostnames=True,
            enable_dns_support=True,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-vpc",
            },
        )

        # Create Internet Gateway
        self.igw = aws.ec2.InternetGateway(
            f"{PREFIX}-igw",
            vpc_id=self.vpc.id,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-igw",
            },
        )

        # Create Route Table
        self.route_table = aws.ec2.RouteTable(
            f"{PREFIX}-rt",
            vpc_id=self.vpc.id,
            routes=[
                aws.ec2.RouteTableRouteArgs(
                    cidr_block="0.0.0.0/0",
                    gateway_id=self.igw.id,
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-rt",
            },
        )

        # Create Primary Subnet (AZ 0)
        self.primary_subnet = aws.ec2.Subnet(
            f"{PREFIX}-subnet-primary",
            vpc_id=self.vpc.id,
            cidr_block=PRIMARY_SUBNET_CIDR,
            availability_zone=self.azs.names[0],
            map_public_ip_on_launch=True,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-subnet-primary",
                f"kubernetes.io/cluster/{PREFIX}-cluster": "shared",
                "kubernetes.io/role/elb": "1",
            },
        )

        # Create Secondary Subnet (AZ 1)
        self.secondary_subnet = aws.ec2.Subnet(
            f"{PREFIX}-subnet-secondary",
            vpc_id=self.vpc.id,
            cidr_block=SECONDARY_SUBNET_CIDR,
            availability_zone=self.azs.names[1],
            map_public_ip_on_launch=True,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-subnet-secondary",
                f"kubernetes.io/cluster/{PREFIX}-cluster": "shared",
                "kubernetes.io/role/elb": "1",
            },
        )

        # Create Tertiary Subnet (AZ 2) if available
        self.tertiary_subnet: Optional[aws.ec2.Subnet] = None
        if len(self.azs.names) >= 3:
            self.tertiary_subnet = aws.ec2.Subnet(
                f"{PREFIX}-subnet-tertiary",
                vpc_id=self.vpc.id,
                cidr_block=TERTIARY_SUBNET_CIDR,
                availability_zone=self.azs.names[2],
                map_public_ip_on_launch=True,
                tags={
                    **COMMON_TAGS,
                    "Name": f"{PREFIX}-subnet-tertiary",
                    f"kubernetes.io/cluster/{PREFIX}-cluster": "shared",
                    "kubernetes.io/role/elb": "1",
                },
            )

        # Associate Route Tables
        aws.ec2.RouteTableAssociation(
            f"{PREFIX}-rta-primary",
            subnet_id=self.primary_subnet.id,
            route_table_id=self.route_table.id,
        )

        aws.ec2.RouteTableAssociation(
            f"{PREFIX}-rta-secondary",
            subnet_id=self.secondary_subnet.id,
            route_table_id=self.route_table.id,
        )

        if self.tertiary_subnet:
            aws.ec2.RouteTableAssociation(
                f"{PREFIX}-rta-tertiary",
                subnet_id=self.tertiary_subnet.id,
                route_table_id=self.route_table.id,
            )

        # Create EKS Control Plane Security Group
        self.eks_control_plane_sg = aws.ec2.SecurityGroup(
            f"{PREFIX}-eks-control-plane-sg",
            vpc_id=self.vpc.id,
            description="Security group for EKS control plane",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=443,
                    to_port=443,
                    protocol="tcp",
                    cidr_blocks=[VPC_CIDR],
                    description="HTTPS from worker nodes",
                )
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    cidr_blocks=["0.0.0.0/0"],
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-eks-control-plane-sg",
            },
        )

        # Create Worker Nodes Security Group
        self.worker_sg = aws.ec2.SecurityGroup(
            f"{PREFIX}-worker-sg",
            vpc_id=self.vpc.id,
            description="Security group for EKS worker nodes",
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    cidr_blocks=["0.0.0.0/0"],
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-worker-sg",
            },
        )

        # Worker node ingress rules (added after SG creation to avoid circular dependencies)
        aws.ec2.SecurityGroupRule(
            f"{PREFIX}-worker-kubelet",
            type="ingress",
            from_port=10250,
            to_port=10250,
            protocol="tcp",
            cidr_blocks=[VPC_CIDR],
            security_group_id=self.worker_sg.id,
            description="Kubelet API",
        )

        aws.ec2.SecurityGroupRule(
            f"{PREFIX}-worker-https",
            type="ingress",
            from_port=443,
            to_port=443,
            protocol="tcp",
            cidr_blocks=[VPC_CIDR],
            security_group_id=self.worker_sg.id,
            description="HTTPS within VPC",
        )

        aws.ec2.SecurityGroupRule(
            f"{PREFIX}-worker-dns-tcp",
            type="ingress",
            from_port=53,
            to_port=53,
            protocol="tcp",
            cidr_blocks=[VPC_CIDR],
            security_group_id=self.worker_sg.id,
            description="DNS TCP",
        )

        aws.ec2.SecurityGroupRule(
            f"{PREFIX}-worker-dns-udp",
            type="ingress",
            from_port=53,
            to_port=53,
            protocol="udp",
            cidr_blocks=[VPC_CIDR],
            security_group_id=self.worker_sg.id,
            description="DNS UDP",
        )

        # Allow all traffic within the security group (for EFA and pod communication)
        aws.ec2.SecurityGroupRule(
            f"{PREFIX}-worker-self",
            type="ingress",
            from_port=0,
            to_port=65535,
            protocol="tcp",
            self=True,
            security_group_id=self.worker_sg.id,
            description="All TCP within security group",
        )

        # Create EFS Security Group
        self.efs_sg = aws.ec2.SecurityGroup(
            f"{PREFIX}-efs-sg",
            vpc_id=self.vpc.id,
            description="Security group for EFS shared storage",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=2049,
                    to_port=2049,
                    protocol="tcp",
                    security_groups=[self.worker_sg.id],
                    description="NFS from worker nodes",
                )
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    cidr_blocks=["0.0.0.0/0"],
                )
            ],
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-efs-sg",
            },
        )

    def get_all_subnet_ids(self) -> List[pulumi.Output]:
        """Get all subnet IDs (including tertiary if it exists)"""
        subnets = [self.primary_subnet.id, self.secondary_subnet.id]
        if self.tertiary_subnet:
            subnets.append(self.tertiary_subnet.id)
        return subnets

    def get_subnet_by_az(self, az_name: str) -> aws.ec2.Subnet:
        """Get subnet by AZ name (primary, secondary, or tertiary)"""
        if az_name == "secondary":
            return self.secondary_subnet
        elif az_name == "tertiary" and self.tertiary_subnet:
            return self.tertiary_subnet
        else:
            return self.primary_subnet
