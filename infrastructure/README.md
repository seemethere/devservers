# DevServer Infrastructure

This directory contains the Pulumi infrastructure code for deploying the DevServer Kubernetes operator to AWS EKS Auto Mode.

## Prerequisites

- Python 3.12+
- Pulumi CLI (installed via brew)
- AWS CLI configured with appropriate credentials
- kubectl installed

## Setup

### 1. Set up Python Virtual Environment

```bash
cd infrastructure
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Pulumi

The project uses an S3 backend for state management with the following configuration:

```bash
# Set the passphrase for encryption
export PULUMI_CONFIG_PASSPHRASE="devserver-local-dev"

# Set AWS region for S3 backend
export AWS_REGION=us-west-1

# Login to S3 backend
pulumi login s3://devserver-pulumi-state-308535385114

# Verify configuration
pulumi config list
```

### 3. AWS Configuration

Ensure your AWS credentials are configured for the target account:

```bash
aws sts get-caller-identity
```

The stack is configured to deploy to **us-west-1** region.

## Usage

### Development Workflow

Always activate the virtual environment and set required environment variables:

```bash
source venv/bin/activate
export PULUMI_CONFIG_PASSPHRASE="devserver-local-dev"
export AWS_REGION=us-west-1
```

### Deploy Infrastructure

```bash
# Preview changes
pulumi preview

# Deploy
pulumi up

# Check stack status
pulumi stack

# View outputs
pulumi stack output
```

### Configure kubectl for EKS Cluster

After successful deployment, configure kubectl to connect to the EKS cluster:

```bash
# Configure kubectl context for the devserver cluster
aws eks update-kubeconfig --region us-west-1 --name devserver

# Verify connection
kubectl cluster-info

# Check current context
kubectl config current-context
```

For k9s users, you can now use k9s directly after the kubectl configuration is complete.

### Cleanup

```bash
# Destroy all resources
pulumi destroy

# Remove stack
pulumi stack rm dev
```

## Project Structure

- `__main__.py` - Main Pulumi program
- `requirements.txt` - Python dependencies
- `Pulumi.yaml` - Project configuration
- `Pulumi.dev.yaml` - Stack-specific configuration
- `venv/` - Python virtual environment (gitignored)

## Important Notes

- **S3 Backend**: This project uses Pulumi's S3 backend for state management (s3://devserver-pulumi-state-308535385114)
- **Passphrase**: Required for encryption of sensitive values
- **EKS Auto Mode**: Using AWS EKS Auto Mode for simplified node management
- **Latest Providers**: Using pulumi-aws 7.9.0 with latest features
- **2 Availability Zones**: us-west-1 only has 2 AZs (us-west-1a, us-west-1c)

## Troubleshooting

### Dependency Conflicts

If you encounter dependency conflicts, ensure you're using the correct versions:
- pulumi-aws: 7.9.0+ (latest)
- pulumi-kubernetes: 4.23.0+
- Note: pulumi-eks not used due to compatibility issues with latest pulumi-aws

### Passphrase Issues

If you get passphrase errors:
```bash
export PULUMI_CONFIG_PASSPHRASE="devserver-local-dev"
```

### Permission Issues

Ensure your AWS credentials have the necessary permissions for:
- VPC and networking resources
- EKS cluster creation and management
- IAM role creation and management
- ECR repository access
