# Kubernetes Operator for PyTorch Development Servers (Python Edition)

This document provides a high-level overview and reference for the Python-based Kubernetes operator for managing PyTorch development servers.

## Project Overview
The goal is to build a lightweight, easy-to-manage Kubernetes operator to manage development servers for developers on AWS EKS (and other Kubernetes platforms).

This project is built with the following principles:
*   **Python First**: The operator is built using the `kopf` framework in Python for rapid development and ease of maintenance.
*   **Unified Codebase**: The operator and the `devctl` command-line tool are managed in a single codebase to streamline development, testing, and deployment.

---

## Custom Resource Definitions (CRDs)

### DevServer CRD
This is the core resource that represents a user's development server.

```yaml
apiVersion: devservers.io/v1
kind: DevServer
metadata:
  name: <server-name>
  namespace: <user-namespace>
spec:
  owner: <user>@company.com
  flavor: gpu-large  # References DevServerFlavor
  image: company/pytorch-dev:latest
  mode: standalone  # or distributed

  # For distributed training only
  distributed:
    worldSize: 4
    nprocsPerNode: 1
    backend: nccl
    ncclSettings:
      NCCL_DEBUG: INFO
      NCCL_SOCKET_IFNAME: eth0

  persistentHomeSize: 100Gi
  sharedVolumeClaimName: <username>-shared-efs

  lifecycle:
    idleTimeout: 3600
    autoShutdown: true
    expirationTime: "2024-01-15T18:00:00Z"  # Auto-expire at specific time
    timeToLive: "4h"                        # Human-readable expiration from creation
```

### DevServerFlavor CRD
This resource defines a "t-shirt size" for a `DevServer`, specifying its resource requests and limits.

```yaml
apiVersion: devservers.io/v1
kind: DevServerFlavor
metadata:
  name: gpu-large
spec:
  resources:
    requests:
      memory: 32Gi
      cpu: 8
      nvidia.com/gpu: 1
    limits:
      memory: 64Gi
      cpu: 16
      nvidia.com/gpu: 1
  nodeSelector:
    instance-type: g4dn.xlarge
  tolerations:
    - key: "nvidia.com/gpu"
      operator: "Exists"
      effect: "NoSchedule"
```

---

## CLI Commands (`devctl`)

The `devctl` CLI provides a user-friendly way to interact with `DevServer` resources. It uses the user's active `kubeconfig` context for authentication.

### Core Commands
```bash
# List available resource flavors (cpu-small, cpu-medium, cpu-large, etc.)
devctl flavors

# Create a new development server
devctl create mydev --flavor cpu-small --wait

# List your running development servers
devctl list

# Show detailed information about a DevServer
devctl describe mydev

# Get an interactive shell inside the development server
devctl shell mydev

# Execute a specific command inside the development server
devctl shell mydev -- python train.py

# Delete a development server and its resources
devctl delete mydev
```

### Advanced Usage Examples
```bash
# Create a server with a custom image and home directory size
devctl create large-dev --flavor cpu-large --image pytorch/pytorch:latest --home-size 50Gi

# Create a server that will automatically be deleted after a set time
devctl create quick-test --flavor cpu-small --time 30m

# Extend the lifetime of a running DevServer
devctl extend mydev --time 2h

# Update the flavor of a DevServer to scale its resources up or down
devctl update mydev --flavor cpu-large
```

---

## Future Enhancements
- Web UI dashboard
- VS Code remote development integration
- Jupyter notebook support
- Automated checkpoint management
- Multi-GPU per pod support
- Spot instance support for cost optimization
- Integration with MLflow/Weights & Biases
