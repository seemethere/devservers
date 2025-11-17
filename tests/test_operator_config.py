import os
from unittest.mock import mock_open, patch

import yaml

from devservers.operator.config import (
    DEFAULT_EXPIRATION_INTERVAL,
    DEFAULT_FLAVOR_RECONCILIATION_INTERVAL,
    DEFAULT_WORKER_LIMIT,
    DEFAULT_POSTING_ENABLED,
    DEFAULT_DEVSERVER_IMAGE,
    DEFAULT_STATIC_DEPENDENCIES_IMAGE,
    OperatorConfig,
)


def test_config_defaults_when_no_file():
    """Verify config uses defaults when the config file is not found."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
            config = OperatorConfig()
            assert config.expiration_interval == DEFAULT_EXPIRATION_INTERVAL
            assert (
                config.flavor_reconciliation_interval
                == DEFAULT_FLAVOR_RECONCILIATION_INTERVAL
            )
            assert config.worker_limit == DEFAULT_WORKER_LIMIT
            assert config.posting_enabled == DEFAULT_POSTING_ENABLED
            assert config.default_devserver_image == DEFAULT_DEVSERVER_IMAGE
            assert config.static_dependencies_image == DEFAULT_STATIC_DEPENDENCIES_IMAGE
            mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_loads_from_file():
    """Verify config correctly loads from a YAML file."""
    config_data = {
        "expirationInterval": 120,
        "flavorReconciliationInterval": 180,
        "workerLimit": 5,
        "postingEnabled": True,
        "defaultDevserverImage": "my-custom-image:latest",
        "staticDependenciesImage": "my-custom-static-image:latest",
    }
    mock_content = yaml.dump(config_data)

    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=mock_content)) as mock_file:
            config = OperatorConfig()
            assert config.expiration_interval == 120
            assert config.flavor_reconciliation_interval == 180
            assert config.worker_limit == 5
            assert config.posting_enabled is True
            assert config.default_devserver_image == "my-custom-image:latest"
            assert config.static_dependencies_image == "my-custom-static-image:latest"
            mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_loads_from_env_var_path():
    """Verify config respects DEVSERVER_OPERATOR_CONFIG_PATH env var."""
    config_data = {"expirationInterval": 90}
    mock_content = yaml.dump(config_data)
    custom_path = "/tmp/custom_config.yaml"

    with patch.dict(os.environ, {"DEVSERVER_OPERATOR_CONFIG_PATH": custom_path}, clear=True):
        with patch("builtins.open", mock_open(read_data=mock_content)) as mock_file:
            config = OperatorConfig()
            assert config.expiration_interval == 90
            mock_file.assert_called_once_with(custom_path, "r")


def test_config_env_var_overrides():
    """Verify environment variables override config file values."""
    config_data = {
        "expirationInterval": 120,
        "workerLimit": 5,
        "postingEnabled": False,
    }
    mock_content = yaml.dump(config_data)

    with patch.dict(
        os.environ,
        {
            "DEVSERVER_EXPIRATION_INTERVAL": "300",
            "DEVSERVER_WORKER_LIMIT": "10",
            "DEVSERVER_POSTING_ENABLED": "true",
            "DEVSERVER_DEFAULT_DEVSERVER_IMAGE": "env-image:latest",
            "DEVSERVER_STATIC_DEPENDENCIES_IMAGE": "env-static-image:latest",
        },
    ):
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = OperatorConfig()
            assert config.expiration_interval == 300
            assert config.worker_limit == 10
            assert config.posting_enabled is True
            assert config.default_devserver_image == "env-image:latest"
            assert config.static_dependencies_image == "env-static-image:latest"


def test_config_falls_back_with_empty_file():
    """Verify config uses defaults when the config file is empty."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data="")) as mock_file:
            config = OperatorConfig()
            assert config.expiration_interval == DEFAULT_EXPIRATION_INTERVAL
            mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_falls_back_with_partial_config():
    """Verify config uses defaults for missing keys."""
    config_data = {"anotherKey": "someValue"}
    mock_content = yaml.dump(config_data)
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = OperatorConfig()
            assert config.expiration_interval == DEFAULT_EXPIRATION_INTERVAL
