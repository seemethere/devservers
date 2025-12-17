# BuildKit Service

A Kubernetes-native container build service using BuildKit with job queuing via RabbitMQ.

## Overview

The BuildKit service provides:
- **CRD-based builds**: Create `Build` resources to trigger container image builds
- **BuilderPool management**: Configure pools of BuildKit daemons via `BuilderPool` CRD
- **Priority queuing**: RabbitMQ-based queue with high/normal/low priority support
- **Registry caching**: Layer caching via container registry for faster builds
- **Dedicated build nodes**: Optional node selectors and tolerations for build workloads

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│ Build CR     │───▶│ Build        │───▶│ RabbitMQ    │───▶│ Build Worker │
│ (user/CI)    │    │ Controller   │    │ Queue       │    │              │
└──────────────┘    └──────────────┘    └─────────────┘    └──────┬───────┘
                                                                  │
                                                           ┌──────▼───────┐
                                                           │ BuildKit     │
                                                           │ Daemon       │
                                                           └──────┬───────┘
                                                                  │
                                                           ┌──────▼───────┐
                                                           │ Registry     │
                                                           │ (images+cache)│
                                                           └──────────────┘
```

## Quick Start

### Deploy the BuildKit Service

```bash
# Full setup from scratch (creates k3d cluster + deploys everything)
make buildkit-full

# Or just deploy to existing cluster
make buildkit-deploy
```

### Development Setup (run worker locally)

```bash
# Deploy infrastructure and set up port-forwarding
make buildkit-dev

# In terminal 1: Start the operator
make run

# In terminal 2: Start the build worker locally
make buildkit-worker-run
```

### Create a Build

```yaml
apiVersion: devserver.io/v1
kind: Build
metadata:
  name: my-app-build
  namespace: default
spec:
  context:
    git:
      url: https://github.com/your-org/your-repo.git
      ref: main
  dockerfile: Dockerfile
  destination: your-registry.com/your-app:v1.0.0
  priority: normal
  timeout: 30m
```

Apply with:
```bash
kubectl apply -f build.yaml
```

Monitor build status:
```bash
kubectl get builds
kubectl describe build my-app-build
```

## CRDs

### Build

The `Build` CRD represents a single container image build job.

```yaml
apiVersion: devserver.io/v1
kind: Build
metadata:
  name: example-build
  namespace: default
spec:
  # Build context source (required) - either git or configMap
  context:
    git:
      url: https://github.com/org/repo.git
      ref: main                    # branch, tag, or commit
      subPath: docker              # optional subdirectory
    # OR
    configMap: my-dockerfile-cm    # ConfigMap containing Dockerfile

  # Path to Dockerfile within context
  dockerfile: Dockerfile           # default: Dockerfile

  # Destination image (required)
  destination: registry.example.com/my-app:v1.0.0

  # Build arguments
  buildArgs:
    - name: BUILD_ENV
      value: production

  # Secrets to mount during build
  secrets:
    - name: npm-registry-creds
      mountPath: /root/.npmrc

  # Cache configuration
  cache:
    enabled: true
    registry: registry.example.com/cache

  # Priority: low, normal, high
  priority: normal

  # Build timeout
  timeout: 30m

  # Which BuilderPool to use
  builderPool: default

status:
  phase: Pending|Queued|Building|Succeeded|Failed|Cancelled
  message: "Build completed successfully"
  startTime: "2024-01-15T10:00:00Z"
  completionTime: "2024-01-15T10:05:00Z"
  digest: sha256:abc123...
```

### BuilderPool

The `BuilderPool` CRD configures a pool of BuildKit daemons.

```yaml
apiVersion: devserver.io/v1
kind: BuilderPool
metadata:
  name: default
spec:
  # Number of BuildKit replicas
  replicas: 2

  # BuildKit image
  image: moby/buildkit:v0.12.4

  # Resource requirements
  resources:
    requests:
      cpu: "2"
      memory: 4Gi
    limits:
      cpu: "4"
      memory: 8Gi

  # Node placement (optional)
  nodeSelector:
    node-type: build
  tolerations:
    - key: "dedicated"
      value: "build"
      effect: "NoSchedule"

  # Cache configuration
  cache:
    type: registry
    registry: registry.example.com/buildkit-cache

  # Garbage collection
  gcPolicy:
    keepBytes: 50Gi
    keepDuration: 168h  # 7 days

  # Security (recommended)
  rootless: true

  # Registry credentials for pushing
  registrySecrets:
    - registry-creds

status:
  phase: Pending|Ready|Degraded|Failed
  readyReplicas: 2
  endpoint: default.buildkit-system.svc.cluster.local:1234
```

## Accessing the Build Service

### From Within the Cluster

Services within the cluster can trigger builds by creating `Build` CRs:

```python
from kubernetes import client, config

config.load_incluster_config()
api = client.CustomObjectsApi()

build = {
    "apiVersion": "devserver.io/v1",
    "kind": "Build",
    "metadata": {"name": "my-build", "namespace": "default"},
    "spec": {
        "context": {"git": {"url": "https://github.com/org/repo.git"}},
        "destination": "registry.example.com/app:latest",
    }
}

api.create_namespaced_custom_object(
    group="devserver.io",
    version="v1",
    namespace="default",
    plural="builds",
    body=build
)
```

Or use kubectl from any pod with appropriate RBAC:

```bash
kubectl apply -f - <<EOF
apiVersion: devserver.io/v1
kind: Build
metadata:
  name: my-build
spec:
  context:
    git:
      url: https://github.com/org/repo.git
  destination: registry.example.com/app:latest
EOF
```

### From Outside the Cluster

#### Using kubectl (with kubeconfig)

```bash
kubectl apply -f build.yaml
kubectl get builds --watch
```

#### Using the Kubernetes API directly

```bash
# Get API server URL
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')

# Get token (for service account auth)
TOKEN=$(kubectl get secret my-sa-token -o jsonpath='{.data.token}' | base64 -d)

# Create a build
curl -X POST "$APISERVER/apis/devserver.io/v1/namespaces/default/builds" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "apiVersion": "devserver.io/v1",
    "kind": "Build",
    "metadata": {"name": "api-build"},
    "spec": {
      "context": {"git": {"url": "https://github.com/org/repo.git"}},
      "destination": "registry.example.com/app:latest"
    }
  }'
```

#### Using CI/CD Pipelines

**GitHub Actions example:**

```yaml
- name: Trigger Kubernetes Build
  run: |
    kubectl apply -f - <<EOF
    apiVersion: devserver.io/v1
    kind: Build
    metadata:
      name: build-${{ github.sha }}
      namespace: default
    spec:
      context:
        git:
          url: ${{ github.server_url }}/${{ github.repository }}.git
          ref: ${{ github.sha }}
      destination: ghcr.io/${{ github.repository }}:${{ github.sha }}
      priority: high
    EOF

    # Wait for build to complete
    kubectl wait --for=jsonpath='{.status.phase}'=Succeeded \
      build/build-${{ github.sha }} --timeout=600s
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make buildkit-deploy` | Deploy CRDs and BuildKit infrastructure |
| `make buildkit-dev` | Deploy + set up port-forwarding for local development |
| `make buildkit-full` | Create k3d cluster + deploy everything |
| `make buildkit-status` | Show BuilderPools, Builds, and pod status |
| `make buildkit-logs` | Tail build worker logs |
| `make buildkit-worker-run` | Run build worker locally |
| `make buildkit-worker-build` | Build the worker Docker image |
| `make buildkit-worker-push` | Build and push worker image |
| `make buildkit-port-forward` | Port-forward RabbitMQ and BuildKit |
| `make buildkit-clean` | Delete all BuildKit resources |

## Configuration

### Environment Variables (Build Worker)

| Variable | Description | Default |
|----------|-------------|---------|
| `RABBITMQ_HOST` | RabbitMQ host | `localhost` |
| `RABBITMQ_PORT` | RabbitMQ port | `5672` |
| `RABBITMQ_USERNAME` | RabbitMQ username | `guest` |
| `RABBITMQ_PASSWORD` | RabbitMQ password | `guest` |
| `BUILDKIT_HOST` | BuildKit daemon address | `tcp://default.buildkit-system.svc.cluster.local:1234` |
| `LOG_LEVEL` | Log level | `INFO` |

### Registry Authentication

To push to private registries, create a secret with your credentials and reference it in the BuilderPool:

```bash
kubectl create secret docker-registry registry-creds \
  --docker-server=your-registry.com \
  --docker-username=your-user \
  --docker-password=your-password \
  -n buildkit-system
```

Then reference in BuilderPool:
```yaml
spec:
  registrySecrets:
    - registry-creds
```

## Troubleshooting

### Check build status
```bash
kubectl get builds -A
kubectl describe build <name>
```

### Check operator logs
```bash
kubectl logs -l app=devserver-operator -f
```

### Check build worker logs
```bash
kubectl logs -n buildkit-system -l app=buildworker -f
# Or locally: make buildkit-logs
```

### Check RabbitMQ
```bash
# Port-forward management UI
kubectl port-forward -n buildkit-system svc/rabbitmq 15672:15672
# Open http://localhost:15672 (user: buildqueue, pass: changeme-in-production)
```

### Check BuildKit daemon
```bash
kubectl logs -n buildkit-system -l app.kubernetes.io/name=buildkit
```
