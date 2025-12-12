#!/usr/bin/env python3

"""CLI entrypoint for running EKS experiments."""

from __future__ import annotations

import click
from rich.console import Console

from .cross_az_persistence import CrossAzPersistenceExperiment
from .snapshot_migration import SnapshotMigrationExperiment

EXPERIMENTS = {
    "cross-az-persistence": CrossAzPersistenceExperiment,
    "snapshot-migration": SnapshotMigrationExperiment,
}


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("experiment", type=click.Choice(list(EXPERIMENTS.keys())))
def main(experiment: str) -> None:
    """Run the selected EKS experiment."""
    console = Console()
    experiment_cls = EXPERIMENTS[experiment]
    experiment_instance = experiment_cls(console=console)
    experiment_instance.run()


if __name__ == "__main__":
    main()
