# DevServer Operator

The DevServer Operator is a Kubernetes operator built with the [Kopf](https://kopf.readthedocs.io/) framework. It manages the lifecycle of `DevServer` and `DevServerFlavor` custom resources.

## Custom Resources

The operator introduces two Custom Resource Definitions (CRDs):

-   `DevServer`: Represents an individual development server instance.
-   `DevServerFlavor`: Defines reusable templates for `DevServer` configurations.
-   `DevServerUser`: Manages user access and public SSH keys.

### DevServer

When a `DevServer` resource is created or updated, the operator provisions the necessary Kubernetes objects to run the development environment, including:

-   A `Deployment` to manage the pod.
-   `Services` for network access (including SSH).
-   A `Secret` for SSH host keys. The operator will automatically generate this secret if it doesn't exist.
-   A `ConfigMap` for the SSH daemon configuration, which includes a custom message of the day (motd) and allows SSH agent forwarding.

The operator watches for changes to `DevServer` resources and will automatically apply updates. For example, changing the `image` in a `DevServer`'s `spec` will cause the operator to update the `Deployment` to roll out a new pod with the new image.

### Container Startup Script

The operator injects a `startup.sh` script into the `DevServer` container. This script is responsible for:

-   **User Creation**: It creates a non-root `dev` user with UID/GID `1000`. The script is designed to be idempotent and work across different Linux distributions (e.g., Debian-based and Red Hat-based) by handling cases where a user or group with that ID already exists.
-   **Privilege Escalation**: The environment includes `doas` as a lightweight `sudo` replacement (if sudo is not already available). The `dev` user is configured with passwordless access to run commands as root (e.g., `doas apt-get update`).
-   **SSH Setup**: It configures the `dev` user's `authorized_keys` with the public key from the `DevServer` spec.
-   **SSHD Execution**: It starts the SSH daemon (`sshd`) as the final step, allowing the user to connect.

**Example `DevServer`:**

```yaml
apiVersion: devserver.io/v1
kind: DevServer
metadata:
  name: my-dev-server
  namespace: default
spec:
  owner: user@example.com
  flavor: cpu-small
  image: ubuntu:22.04
  ssh:
    publicKey: "ssh-rsa AAAA..."
  lifecycle:
    timeToLive: "8h"
```

### DevServerFlavor

`DevServerFlavor` resources are used to define "t-shirt sizes" for DevServers, specifying resource requests, limits, and node selectors.

Tolerations can also be specified to allow DevServers to be scheduled on nodes with matching taints, such as GPU nodes.

In addition to compute resources, flavors can specify a list of `volumes` to be mounted into the DevServer. This is useful for providing shared storage, datasets, or pre-configured environments. Volumes specified directly in a `DevServer` will override flavor volumes with the same `mountPath`.

Cluster administrators can mark a flavor as the default by setting `spec.default: true`. When a default flavor is configured, users can create DevServers without explicitly specifying a flavor. Only one flavor can be marked as default at a time.

**Example `DevServerFlavor`:**

```yaml
apiVersion: devserver.io/v1
kind: DevServerFlavor
metadata:
  name: cpu-small
spec:
  default: true  # Optional: mark this as the default flavor
  defaultImage: "ubuntu:22.04"
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
  nodeSelector:
    kubernetes.io/arch: amd64
  tolerations:
    - key: "nvidia.com/gpu"
      operator: "Exists"
      effect: "NoSchedule"
  volumes:
    - claimName: "shared-data"
      mountPath: "/data"
      readOnly: true
status:
  schedulable: "Yes"
```

The operator will periodically update the `status.schedulable` field to indicate if a flavor can likely be scheduled on the cluster. This status is used by `devctl` to provide users with scheduling hints.

### Adding New Flavors

To add a new flavor, create a YAML file with your `DevServerFlavor` definition and apply it to your cluster:

```bash
kubectl apply -f your-flavor-file.yaml
```

You can use the example above as a template for your own flavors.

### DevServerUser

`DevServerUser` resources manage users and their associated permissions within the cluster. The operator sets up RBAC roles and resource quotas based on the spec. This CRD does not manage SSH keys directly; instead, SSH access is handled by the `devctl` CLI when creating or managing a `DevServer`.

**Example `DevServerUser`:**

```yaml
apiVersion: devserver.io/v1
kind: DevServerUser
metadata:
  name: test-user
spec:
  username: test-user
```
## Lifecycle Management

The operator automatically handles the expiration of `DevServer` resources based on the `spec.lifecycle.timeToLive` field. When a DevServer expires, the operator deletes the corresponding `DevServer` resource, and Kubernetes garbage collection removes the associated objects.

## Development

The operator is written in Python using the [Kopf](https://kopf.readthedocs.io/) framework and requires Python 3.9+.

### Architecture

The operator is now fully asynchronous to improve performance and scalability. All Kubernetes API calls and other blocking operations are executed in a non-blocking manner.

The codebase is structured to separate concerns for each Custom Resource Definition (CRD) it manages. The logic for each CRD is contained within its own directory:

-   `src/devservers/operator/devserver/`: Contains the handlers and reconciliation logic for the `DevServer` CRD.
-   `src/devservers/operator/devserveruser/`: Contains the handlers and reconciliation logic for the `DevServerUser` CRD.
-   `src/devservers/operator/devserverflavor/`: Contains the handlers for the `DevServerFlavor` CRD, including support for default flavors.

This structure makes it easier to extend the operator with new CRDs in the future.

The DevServer Operator is configured via a ConfigMap, which is mounted into the operator's pod as a volume. This allows for runtime configuration without requiring changes to the operator's code or deployment manifest for common adjustments.

### Configuration Options

-   `defaultPersistentHomeSize`: Sets the default size for persistent home directories (`persistentHome.size`) when it is not explicitly specified in a `DevServer` resource. The value should be a string representing a Kubernetes quantity (e.g., `10Gi`, `500Mi`). Can be overridden by the `DEVSERVER_DEFAULT_PERSISTENT_HOME_SIZE` environment variable.
-   `expirationInterval`: Interval in seconds for checking for expired DevServers. Defaults to `60`. Can be overridden by the `DEVSERVER_EXPIRATION_INTERVAL` environment variable.
-   `flavorReconciliationInterval`: Interval in seconds for reconciling `DevServerFlavor` statuses. Defaults to `60`. Can be overridden by the `DEVSERVER_FLAVOR_RECONCILIATION_INTERVAL` environment variable.
-   `workerLimit`: The maximum number of concurrent reconciliations. This helps to prevent overwhelming the Kubernetes API server. Defaults to `1`. Can be overridden by the `DEVSERVER_WORKER_LIMIT` environment variable.
-   `postingEnabled`: Whether to post reconciliation logs as Kubernetes events. It is recommended to keep this `false` to reduce API server load. Defaults to `false`. Can be overridden by the `DEVSERVER_POSTING_ENABLED` environment variable.
-   `defaultDevserverImage`: The default container image to use for `
