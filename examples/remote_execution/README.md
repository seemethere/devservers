# Remote Execution Example

This example demonstrates how to use the `devservers` Python library to create a `DevServer` with a synchronized local workspace, execute commands within it, and ensure proper cleanup.

## How it Works

The script `main.py` performs the following actions:

1.  **Loads Kubernetes Configuration**: It loads your local `kubeconfig` file to connect to your Kubernetes cluster.
2.  **Defines a DevServer**: It defines a `DevServer` with the following characteristics:
    *   Name: `remote-exec-example`
    *   Namespace: `default`
    *   Flavor: `gpu-small`
    *   Persistent Home Directory Size: `256Gi`
3.  **Workspace Synchronization**: It synchronizes your local project directory to the `/home/dev/workspace` directory inside the `DevServer`.
4.  **Context Manager**: It uses a context manager (`with ...:`) to create the `DevServer`. This is the recommended approach as it automatically handles the lifecycle of the `DevServer`:
    *   **`__enter__`**: When the `with` block is entered, the script creates the `DevServer` custom resource in Kubernetes, waits for it to become ready, and then syncs the workspace.
    *   **`__exit__`**: When the block is exited (either normally or due to an error), the script automatically deletes the `DevServer` resource, cleaning up all associated Kubernetes objects.
5.  **Remote Execution**: Inside the `with` block, there is a placeholder where you can add commands to be executed on the `DevServer` using the `devserver.exec()` method.

## Running the Example

To run this example, you need to have the `devservers` library installed and a configured Kubernetes environment.

1.  **Install dependencies**:
    ```bash
    uv sync
    ```

2.  **Run the script**:
    ```bash
    uv run python examples/remote_execution/main.py
    ```

You will see output indicating the creation of the `DevServer`, and after a few moments, a confirmation that it is ready. Once the script finishes, it will report that the `DevServer` has been deleted.
