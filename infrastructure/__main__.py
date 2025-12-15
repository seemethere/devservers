"""DevServer Infrastructure - Main Entry Point

This module sets up the complete infrastructure for the DevServer Kubernetes operator:
- VPC and networking (subnets, security groups, etc.)
- IAM roles and policies for EKS
- EKS 1.34 cluster with GPU and CPU node groups
- EBS CSI driver and EFS storage
- Kubernetes resources (namespaces, service accounts, etc.)
- Helm charts (NVIDIA GPU Operator)

Usage:
    pulumi up                    # Deploy to dev environment (us-west-1)
    pulumi up --stack prod       # Deploy to prod environment (us-east-2)
"""

import pulumi
from vpc import VPCResources
from iam import IAMResources
from eks import EKSResources
from storage import StorageResources
from kubernetes import KubernetesResources
from helm import HelmResources
from config import PREFIX, ENVIRONMENT

# Create VPC and networking resources
vpc = VPCResources()

# Create IAM roles and policies
iam = IAMResources()

# Create EKS cluster and node groups
eks = EKSResources(vpc, iam)

# Create OIDC provider for IRSA (after cluster exists)
oidc_provider = iam.create_oidc_provider(eks.cluster)

# Create storage resources (EFS)
storage = StorageResources(vpc)

# Create Kubernetes resources
k8s_resources = KubernetesResources(eks, iam)

# Install Helm charts
helm = HelmResources(eks, k8s_resources.k8s_provider)

# Export important outputs
pulumi.export("vpc_id", vpc.vpc.id)
pulumi.export("cluster_name", eks.cluster.name)
pulumi.export("cluster_endpoint", eks.cluster.endpoint)
pulumi.export("cluster_security_group_id", vpc.eks_control_plane_sg.id)
pulumi.export("kubeconfig", k8s_resources.k8s_provider.kubeconfig)
pulumi.export("region", pulumi.Config("aws").get("region"))
pulumi.export("environment", ENVIRONMENT)

# Export subnet IDs for reference
pulumi.export("primary_subnet_id", vpc.primary_subnet.id)
pulumi.export("secondary_subnet_id", vpc.secondary_subnet.id)
if vpc.tertiary_subnet:
    pulumi.export("tertiary_subnet_id", vpc.tertiary_subnet.id)

# Export security group IDs for reference
pulumi.export("worker_security_group_id", vpc.worker_sg.id)
pulumi.export("efs_security_group_id", vpc.efs_sg.id)

# Export IAM role ARNs
pulumi.export("eks_cluster_role_arn", iam.eks_cluster_role.arn)
pulumi.export("eks_node_role_arn", iam.eks_node_role.arn)
pulumi.export("node_instance_profile_name", iam.node_instance_profile.name)
pulumi.export("oidc_provider_arn", oidc_provider.arn)

# Export namespace
pulumi.export("devserver_namespace", k8s_resources.namespace.metadata.name)

# Export deployment commands
pulumi.export("deploy_operator_commands", pulumi.Output.concat(
    "# 1. Install CRDs\n",
    "kubectl apply -f ../crds/\n\n",
    "# 2. Apply sample flavors\n",
    "kubectl apply -f ../examples/flavors/\n\n",
    "# 3. Build and push operator image (optional - for local development)\n",
    "# cd .. && make docker-build docker-push\n\n",
    "# 4. Or run operator locally for development:\n",
    "# cd .. && make run\n\n",
    "# 5. To create a test DevServer:\n",
    "# kubectl apply -f ../examples/devserver-sample.yaml\n"
))

print("\n✓ DevServer infrastructure deployment complete!")
print(f"  Environment: {ENVIRONMENT}")
print(f"  Cluster: {PREFIX}-cluster")
print("\n📋 Next steps:")
print("  1. Configure kubectl:")
print("     pulumi stack output kubeconfig --show-secrets > kubeconfig.json")
print("     export KUBECONFIG=kubeconfig.json")
print("  2. Verify nodes:")
print("     kubectl get nodes")
print("  3. Install CRDs and flavors:")
print("     kubectl apply -f ../crds/")
print("     kubectl apply -f ../examples/flavors/")
print("  4. Run operator (for development):")
print("     cd .. && make run")
print("  5. Or see deployment commands:")
print("     pulumi stack output deploy_operator_commands")
