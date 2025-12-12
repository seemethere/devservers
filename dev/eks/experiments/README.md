# EKS Experiments

This package collects self-contained experiments for exercising and validating EKS
infrastructure behaviour. Each experiment encapsulates its setup, execution flow and
cleanup so it can be run repeatedly and safely.

## Running experiments

Use the package entrypoint to run any experiment:

```bash
uv run -m dev.eks.experiments <experiment-name>
```

### Available experiments

- `cross-az-persistence` — creates a DevServer in one availability zone, writes a marker
  file to its persistent volume, tears it down, and attempts to recreate it in a different
  zone. The experiment confirms that AWS EBS-based PVCs cannot be reattached across zones.

- `snapshot-migration` — validates that VolumeSnapshots can be used to migrate data
  between availability zones. Creates a PVC in one zone, snapshots it, restores to a
  new PVC in a different zone, and verifies data integrity.

## Adding a new experiment

1. Create a new module inside this directory (for example `my_experiment.py`) and expose
   a class with a `run()` method following the pattern established in
   `cross_az_persistence.py`.
2. Register the experiment in `__main__.py` by adding it to the `EXPERIMENTS` mapping.
3. Document the experiment here under **Available experiments**.

Experiments are designed to be development aides—they may assume access to an existing
cluster, credentials, or other prerequisites. Keep each experiment focused on a single
question so it remains easy to understand and re-run.
