# Developer Scripts

This directory contains scripts to aid in the development and testing of the `devserver-operator`.

## Remote Development Bootstrap (`bootstrap_operator.py`)

For a faster and more realistic development loop, you can run the operator directly inside your Kubernetes cluster and sync your local code changes to it in real-time.

### Purpose

Instead of running the operator locally with `make run`, which might not perfectly replicate the in-cluster environment, this script deploys the operator to your current Kubernetes context. It then uses `kubectl cp` to sync your local `src/` directory into the running pod and restarts the process, allowing for rapid iteration without rebuilding a container image for every change.

### Prerequisites

You must have `kubectl` installed and configured to connect to a Kubernetes cluster.

### Usage

The easiest way to use the script is through the Makefile target:

```bash
make dev-bootstrap
```

This command will:
1.  Target your currently active `kubectl` context and namespace.
2.  Create the namespace if it doesn't exist.
3.  Set up the necessary RBAC (ServiceAccount, Role, RoleBinding) for the operator.
4.  Create or update a `devserver-operator-dev` Deployment, pulling the `:main` image from GHCR.
5.  Wait for the operator pod to be running.
6.  Sync your local source code into the pod at `/app`.
7.  Restart the `kopf` process inside the pod to apply your changes.
8.  Generate a `./devctl` executable script in the project root.

### The `./devctl` Wrapper

After a successful bootstrap, a `devctl` script is created in your project root. This is a convenience wrapper around the main `devctl` CLI (`uv run python -m devservers.cli.main`) that automatically targets the namespace you bootstrapped into.

You can use it like the normal CLI, but without needing to specify the namespace:

```bash
./devctl list
./devctl describe my-devserver
```

This script is ignored by Git.

### Viewing Logs

You can stream the logs from the remote operator with:

```bash
kubectl logs -f -l app=devserver-operator-dev -n <your-namespace>
```
