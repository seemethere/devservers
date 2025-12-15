"""IAM roles and policies for DevServer infrastructure"""

import pulumi_aws as aws
import json
from config import PREFIX, COMMON_TAGS


class IAMResources:
    """IAM roles and policies"""

    def __init__(self):
        # EKS Cluster Role
        self.eks_cluster_role = aws.iam.Role(
            f"{PREFIX}-eks-cluster-role",
            assume_role_policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": "sts:AssumeRole",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "eks.amazonaws.com"
                    }
                }]
            }),
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-eks-cluster-role",
            },
        )

        # Attach AmazonEKSClusterPolicy to cluster role
        aws.iam.RolePolicyAttachment(
            f"{PREFIX}-eks-cluster-policy",
            role=self.eks_cluster_role.name,
            policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
        )

        # EKS Node Role
        self.eks_node_role = aws.iam.Role(
            f"{PREFIX}-eks-node-role",
            assume_role_policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": "sts:AssumeRole",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "ec2.amazonaws.com"
                    }
                }]
            }),
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-eks-node-role",
            },
        )

        # Attach required policies to node role
        aws.iam.RolePolicyAttachment(
            f"{PREFIX}-eks-node-worker-policy",
            role=self.eks_node_role.name,
            policy_arn="arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
        )

        aws.iam.RolePolicyAttachment(
            f"{PREFIX}-eks-node-cni-policy",
            role=self.eks_node_role.name,
            policy_arn="arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
        )

        aws.iam.RolePolicyAttachment(
            f"{PREFIX}-eks-node-ecr-policy",
            role=self.eks_node_role.name,
            policy_arn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
        )

        aws.iam.RolePolicyAttachment(
            f"{PREFIX}-eks-node-ebs-csi-policy",
            role=self.eks_node_role.name,
            policy_arn="arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy",
        )

        # Bedrock policy for Claude Code access
        self.bedrock_policy = aws.iam.RolePolicy(
            f"{PREFIX}-eks-node-bedrock-policy",
            role=self.eks_node_role.id,
            policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream"
                    ],
                    "Resource": [
                        "arn:aws:bedrock:*:*:foundation-model/anthropic.claude-*",
                        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-*"
                    ]
                }]
            }),
        )

        # Create Instance Profile for nodes
        self.node_instance_profile = aws.iam.InstanceProfile(
            f"{PREFIX}-node-instance-profile",
            role=self.eks_node_role.name,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-node-instance-profile",
            },
        )

    def create_oidc_provider(self, cluster):
        """Create OIDC provider for IRSA (must be called after cluster creation)"""
        # Get TLS certificate for OIDC provider
        oidc_issuer = cluster.identities[0].oidcs[0].issuer

        tls_cert = aws.get_tls_certificate_output(url=oidc_issuer)

        # Create OIDC Identity Provider
        self.oidc_provider = aws.iam.OpenIdConnectProvider(
            f"{PREFIX}-eks-oidc-provider",
            client_id_lists=["sts.amazonaws.com"],
            thumbprint_lists=[tls_cert.certificates[0].sha1_fingerprint],
            url=oidc_issuer,
            tags={
                **COMMON_TAGS,
                "Name": f"{PREFIX}-eks-oidc-provider",
            },
        )

        return self.oidc_provider
