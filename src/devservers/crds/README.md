# Custom Resource Definition (CRD) Clients

This module provides high-level, object-oriented clients for interacting with the `devserver.io` custom resources in a Kubernetes cluster. These classes act as a Pythonic SDK, abstracting away the raw Kubernetes API calls into a more intuitive model.

## `BaseCustomResource`

This is the foundation for all CRD clients. It provides a generic, reusable implementation of all standard CRUD (Create, Read, Update, Delete) operations, and handles the distinction between namespaced and cluster-scoped resources automatically.

## `DevServer` Client

The `DevServer` class inherits from `BaseCustomResource` and is the primary interface for managing `DevServer` custom resources.

### Example Usage

Below are examples of how to use the `DevServer` client to manage resources programmatically.

#### Prerequisites

The client will automatically attempt to load your Kubernetes configuration from a standard `kubeconfig` file or from the in-cluster service account environment.

If the configuration cannot be loaded, the client will raise a `KubeConfigError` with a helpful message.

#### Creating a DevServer

To create a new `DevServer`, you define its `ObjectMeta` and `spec`, then call the `create` classmethod. It's best practice to wrap client calls in a `try...except` block to handle potential configuration or API errors.

```python
from devservers.crds.devserver import DevServer
from devservers.crds.base import ObjectMeta
from devservers.crds.errors import KubeConfigError

# 1. Define the metadata and spec
metadata = ObjectMeta(name="my-test-server", namespace="default")
spec = {
    "flavor": "cpu-small",
    "image": "ubuntu:22.04",
    "ssh": {"publicKey": "ssh-rsa AAAA..."},
    "lifecycle": {"timeToLive": "1h"},
    "persistentHome": {"enabled": True, "size": "20Gi"},
}

# 2. Create the resource on the cluster
try:
    devserver = DevServer.create(metadata=metadata, spec=spec)
    print(f"Successfully created '{devserver.metadata.name}' with status: {devserver.status}")
except KubeConfigError as e:
    print(f"Error: {e}")
except Exception as e:
    # Handle other potential Kubernetes API errors
    print(f"An API error occurred: {e}")

```

#### Managing a DevServer Lifecycle with a Context Manager

You can let the SDK handle creation **and** automatic cleanup by using the `DevServer` object as a context manager. When the `with` block exits—whether normally or via an exception—the resource is deleted.

```python
from devservers.crds.devserver import DevServer
from devservers.crds.base import ObjectMeta

metadata = ObjectMeta(name="cm-test-server", namespace="default")
spec = {"flavor": "cpu-small", "image": "ubuntu:22.04"}

# Automatically creates on enter and deletes on exit
with DevServer(metadata=metadata, spec=spec) as server:
    print(f"DevServer {server.metadata.name} is ready")
    # perform work with the server here

# At this point the DevServer has been deleted
```

#### Typed Spec Access

For fields that have a defined structure, like `persistentHome`, the `DevServer` class provides typed properties for easier access and modification.

```python
from devservers.crds.devserver import PersistentHomeSpec

# Get the DevServer object
server = DevServer.get(name="my-test-server", namespace="default")

# Read persistent home settings
if server.persistent_home and server.persistent_home.enabled:
    print(f"Persistent home is enabled with size: {server.persistent_home.size}")

# Disable persistence using the typed property
server.persistent_home = None
server.update()
```

#### Getting and Listing DevServers

You can retrieve a single `DevServer` by name or list all servers in a namespace.

```python
# Get a specific DevServer by name
server = DevServer.get(name="my-test-server", namespace="default")
print(f"Found server: {server.metadata.name}")

# List all DevServers in the 'default' namespace
servers = DevServer.list(namespace="default")
print("Available servers:")
for s in servers:
    print(f"- {s.metadata.name}")
```

#### Updating a DevServer

You can modify a `DevServer`'s `spec` and apply the changes with the `update()` or `patch()` methods.

```python
# Get the object first
server = DevServer.get(name="my-test-server", namespace="default")

# Option 1: Replace the entire object with a full update
print(f"Old image: {server.spec.get('image')}")
server.spec["image"] = "fedora:latest"
server.update()
print(f"New image: {server.spec.get('image')}")


# Option 2: Patch a single field
server.patch({"spec": {"lifecycle": {"timeToLive": "8h"}}})
print(f"New TTL: {server.spec['lifecycle']['timeToLive']}")

```

#### Deleting a DevServer

To clean up a resource, simply call the `delete()` method.

```python
server = DevServer.get(name="my-test-server", namespace="default")
server.delete()
print(f"DevServer '{server.metadata.name}' deleted.")
```

#### Refreshing Local State

If the resource is modified on the cluster by another process (e.g., the operator updates its status), you can sync your local Python object with the `refresh()` method.

```python
server = DevServer.get(name="my-test-server", namespace="default")
# ...some time passes, and the operator changes the status...
server.refresh()
print(f"Current status phase is: {server.status.get('phase')}")
```

#### Waiting for a Specific Status

The `wait_for_status` method provides a robust way to block program execution until a resource reaches a desired state. It now functions as a generator, streaming events from the Kubernetes API as they occur.

This is useful when you need to wait for an operator to finish processing a resource, such as waiting for a `DevServer` to become "Ready".

##### Example: Streaming Status Events

You can iterate over the generator to process events in real-time while you wait. The loop will exit once the desired status is reached or a timeout occurs.

```python
server = DevServer.get(name="my-test-server", namespace="default")
desired_status = {"phase": "Running"}

print(f"Waiting for '{server.metadata.name}' to reach phase: Running...")
try:
    for event in server.wait_for_status(status=desired_status, timeout=180):
        phase = event.get("object", {}).get("status", {}).get("phase", "Unknown")
        print(f" -> Received event: {event['type']}, current phase: {phase}")

    print(f"Server is now running.")
except TimeoutError:
    print("Timed out waiting for the server to become running.")
```

##### Example: Blocking Until Ready

If you don't need to process the intermediate events and simply want to block until the status is met, you can consume the generator with an empty loop or by converting it to a list.

```python
# This will block until the server is 'Running' or timeout is reached
try:
    for _ in server.wait_for_status(status={"phase": "Running"}, timeout=180):
        pass # The events are ignored, we just wait for completion
    print("Server is ready to be used.")
except TimeoutError:
    print("Timed out waiting for the server to become ready.")
```
