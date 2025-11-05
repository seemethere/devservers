# eks dev setup

1. Create a cluster with auto-mode enabled
```bash
eksctl create cluster --name=<MY_NAME> --enable-auto-mode --region <REGION>
```

2. Apply the default storage class and GPU nodepool for EKS auto mode

```bash
# assuming from the root directory
kubectl apply -f dev/eks/
```

## Experiments

We maintain repeatable EKS infrastructure experiments under `dev/eks/experiments/`. Each
experiment is exposed through a simple CLI.

Run an experiment with:

```bash
uv run -m dev.eks.experiments <experiment-name>
```

Currently available experiments:

- `cross-az-persistence` — provisions a DevServer in one availability zone, writes data
  to its PVC, tears it down, and then attempts to recreate it in a different zone to
  demonstrate that standard EBS-backed volumes are zone-locked.

See `dev/eks/experiments/README.md` for details on the experiment flow and how to add new
experiments.

## GPU Nodepool
The `gpu-nodepool.yml` configures a GPU-accelerated nodepool using Karpenter with:
- NVIDIA GPU instance types (g6e and g6 families)
- Taint `nvidia.com/gpu:NoSchedule` to ensure only GPU workloads schedule on these nodes

To use GPU nodes with DevServer, you can create a `DevServerFlavor` that includes the necessary tolerations and resource limits.

**Example `gpu-small.yaml` flavor:**
```yaml
apiVersion: devserver.io/v1
kind: DevServerFlavor
metadata:
  name: gpu-small
spec:
  resources:
    requests:
      cpu: "1"
      memory: "4Gi"
    limits:
      cpu: "4"
      memory: "16Gi"
      nvidia.com/gpu: "1"
  nodeSelector:
    kubernetes.io/arch: amd64
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
```

You can then create a DevServer with this flavor:
```bash
# First apply the flavor
kubectl apply -f examples/flavors/gpu-small.yaml

# Then create the devserver
devctl create --name fedora-gpu --image fedora:latest --flavor gpu-small --ttl 4h

# Once created, you can ssh in and verify GPU access
devctl ssh fedora-gpu -- nvidia-smi
```

## ARM64 CPU Nodepool

The `cpu-arm64-nodepool.yml` configures a nodepool for ARM64 CPU instances using Karpenter, enabling you to run ARM-based workloads on your cluster. This is particularly useful for cost-effective development environments or for testing ARM-specific code.

## TODO
- [ ] Add some sample EFS storage to this setup for shared folders
