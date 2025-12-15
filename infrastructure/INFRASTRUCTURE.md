# DevServer Infrastructure

This directory contains the Pulumi infrastructure-as-code for the DevServer Kubernetes operator.

## Overview

The infrastructure is organized into modular Python files:

- **`config.py`**: Configuration management for different environments (dev/prod)
- **`vpc.py`**: VPC, subnets, security groups, and networking
- **`iam.py`**: IAM roles and policies for EKS cluster and nodes
- **`eks.py`**: EKS 1.34 cluster with GPU and CPU node groups
- **`storage.py`**: EFS storage configuration
- **`kubernetes.py`**: Kubernetes resources (namespaces, RBAC, device plugins)
- **`helm.py`**: Helm charts (NVIDIA GPU Operator)
- **`user_data.py`**: User data templates for node bootstrapping
- **`__main__.py`**: Main entry point that ties everything together

## Environments

### Dev (us-west-1)
- Test environment with T4 GPUs
- 2x g4dn.12xlarge instances (4 T4 GPUs each)
- Configured for development and testing

### Prod (us-east-2)
- Production environment with H200/H100/A100/T4/L4 GPUs
- Higher capacity and more GPU types
- Configured for production workloads

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Pulumi CLI** installed ([installation guide](https://www.pulumi.com/docs/install/))
3. **Python 3.8+** with pip
4. **kubectl** for cluster management

## Setup

1. **Install Python dependencies**:
   ```bash
   cd infrastructure
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure Pulumi backend** (if not already done):
   ```bash
   pulumi login  # Or: pulumi login --local for local state
   ```

## Deployment

### Deploy to Dev Environment (us-west-1)

```bash
cd infrastructure
pulumi stack select dev  # Or: pulumi stack init dev
pulumi up
```

### Deploy to Prod Environment (us-east-2)

```bash
cd infrastructure
pulumi stack select prod  # Or: pulumi stack init prod
pulumi up
```

## Configuration

### Environment-Specific Settings

Configuration is managed in `config.py` with environment-specific settings:

```python
ENVIRONMENT_CONFIGS = {
    "dev": {
        "region": "us-west-1",
        "supported_gpu_types": {
            "t4": {...},
            "t4-small": {...},
            "cpu-x86": {...},
        },
    },
    "prod": {
        "region": "us-east-2",
        "supported_gpu_types": {
            "h200": {...},
            "h100": {...},
            "a100": {...},
            "t4": {...},
            "l4": {...},
            "cpu-x86": {...},
        },
    },
}
```

### Stack Configuration

Per-stack configuration can be set via Pulumi config:

```bash
# Set AWS region
pulumi config set aws:region us-west-1

# Set key pair name for SSH access
pulumi config set keyPairName your-key-pair-name
```

## Accessing the Cluster

After deployment, get the kubeconfig:

```bash
# Export kubeconfig
pulumi stack output kubeconfig --show-secrets > kubeconfig.json
export KUBECONFIG=$(pwd)/kubeconfig.json

# Verify cluster access
kubectl get nodes
kubectl get pods -n gpu-operator
kubectl get pods -n devserver
```

## Infrastructure Components

### VPC and Networking
- VPC with 10.0.0.0/16 CIDR
- 3 subnets across multiple AZs (primary, secondary, tertiary)
- Internet Gateway for public access
- Security groups for control plane, worker nodes, and EFS

### EKS Cluster
- Kubernetes version 1.34
- EBS CSI driver addon for persistent volumes
- VPC CNI addon for pod networking
- Self-managed node groups via Auto Scaling Groups

### Node Groups

#### GPU Nodes
- Per GPU type (T4, H200, H100, A100, L4, etc.)
- EFA-enabled for high-performance networking
- NVIDIA drivers pre-installed via user data
- 4TB root volumes
- Placement groups for low-latency communication

#### CPU Management Nodes
- c5.4xlarge instances
- Used for control plane components and management tasks
- 2 nodes for high availability

### Storage
- EBS volumes for persistent storage (via EBS CSI driver)
- EFS security group configured for shared storage
- Individual EFS filesystems created dynamically by operator

### GPU Support
- NVIDIA GPU Operator (v25.3.3) via Helm
- NVIDIA device plugin for GPU allocation
- EFA device plugin for high-performance networking
- MIG support (configurable)

## Outputs

Key outputs exported by the stack:

- `vpc_id`: VPC ID
- `cluster_name`: EKS cluster name
- `cluster_endpoint`: EKS API endpoint
- `kubeconfig`: Kubernetes configuration
- `worker_security_group_id`: Worker node security group ID
- `efs_security_group_id`: EFS security group ID
- `eks_node_role_arn`: Node IAM role ARN
- `devserver_namespace`: DevServer namespace name

## Cleanup

To destroy the infrastructure:

```bash
# Make sure you're on the right stack!
pulumi stack select dev  # or prod

# Preview what will be destroyed
pulumi destroy --preview

# Destroy the infrastructure
pulumi destroy
```

## Comparison with Terraform

This Pulumi infrastructure is equivalent to the Terraform code in `../osdc/terraform-gpu-devservers/`, with the following differences:

### What's Included
- ✅ VPC and networking (subnets, security groups, route tables)
- ✅ IAM roles and policies (EKS cluster, nodes, Bedrock access)
- ✅ EKS 1.34 cluster
- ✅ EBS CSI driver addon
- ✅ VPC CNI addon
- ✅ GPU node groups via Auto Scaling Groups
- ✅ CPU management node groups
- ✅ NVIDIA GPU Operator (Helm)
- ✅ EFA device plugin
- ✅ Kubernetes resources (namespaces, RBAC, aws-auth)
- ✅ EFS security group infrastructure

### What's Not Included (as requested)
- ❌ Lambda functions (expiry, availability checking)
- ❌ SQS queues
- ❌ DynamoDB tables
- ❌ ALB / Route53 / domain name configuration
- ❌ SSH proxy infrastructure

### Differences
1. **Simplified user data**: The user data scripts have been simplified for Amazon Linux 2023
2. **Configuration approach**: Uses Python dictionaries instead of Terraform locals
3. **Module structure**: Uses Python classes instead of Terraform modules
4. **State management**: Uses Pulumi state instead of Terraform state

## Troubleshooting

### Node not joining cluster
- Check CloudWatch logs for the EC2 instance
- Verify the aws-auth ConfigMap is correctly configured
- Ensure IAM roles have proper trust relationships

### GPU not detected
- Check if NVIDIA drivers are installed: `kubectl exec -it <pod> -- nvidia-smi`
- Verify GPU operator pods are running: `kubectl get pods -n gpu-operator`
- Check device plugin logs: `kubectl logs -n gpu-operator <device-plugin-pod>`

### EFA not working
- Verify EFA device plugin is running: `kubectl get ds -n kube-system aws-efa-k8s-device-plugin-daemonset`
- Check if EFA is available on the instance: `fi_info -p efa`

## Support

For issues or questions:
1. Check the Pulumi logs: `pulumi logs`
2. Review AWS CloudWatch logs for the EKS cluster
3. Check Kubernetes events: `kubectl get events -A`

## References

- [Pulumi AWS Provider Documentation](https://www.pulumi.com/registry/packages/aws/)
- [Pulumi EKS Provider Documentation](https://www.pulumi.com/registry/packages/eks/)
- [AWS EKS Documentation](https://docs.aws.amazon.com/eks/)
- [NVIDIA GPU Operator Documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/)
