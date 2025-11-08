import os
from unittest.mock import mock_open, patch

import yaml

from devservers.operator.config import DEFAULT_PERSISTENT_HOME_SIZE, OperatorConfig


def test_config_defaults_when_no_file():
    """Verify config uses defaults when the config file is not found."""
    with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
        config = OperatorConfig()
        assert config.default_persistent_home_size == DEFAULT_PERSISTENT_HOME_SIZE
        mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_loads_from_file():
    """Verify config correctly loads from a YAML file."""
    config_data = {"defaultPersistentHomeSize": "20Gi"}
    mock_content = yaml.dump(config_data)

    with patch("builtins.open", mock_open(read_data=mock_content)) as mock_file:
        config = OperatorConfig()
        assert config.default_persistent_home_size == "20Gi"
        mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_loads_from_env_var_path():
    """Verify config respects DEVSERVER_OPERATOR_CONFIG_PATH env var."""
    config_data = {"defaultPersistentHomeSize": "30Gi"}
    mock_content = yaml.dump(config_data)
    custom_path = "/tmp/custom_config.yaml"

    with patch.dict(os.environ, {"DEVSERVER_OPERATOR_CONFIG_PATH": custom_path}):
        with patch("builtins.open", mock_open(read_data=mock_content)) as mock_file:
            config = OperatorConfig()
            assert config.default_persistent_home_size == "30Gi"
            mock_file.assert_called_once_with(custom_path, "r")


def test_config_falls_back_with_empty_file():
    """Verify config uses defaults when the config file is empty."""
    with patch("builtins.open", mock_open(read_data="")) as mock_file:
        config = OperatorConfig()
        assert config.default_persistent_home_size == DEFAULT_PERSISTENT_HOME_SIZE
        mock_file.assert_called_once_with("/etc/devserver-operator/config.yaml", "r")


def test_config_falls_back_with_partial_config():
    """Verify config uses defaults for missing keys."""
    config_data = {"anotherKey": "someValue"}
    mock_content = yaml.dump(config_data)
    with patch("builtins.open", mock_open(read_data=mock_content)):
        config = OperatorConfig()
        assert config.default_persistent_home_size == DEFAULT_PERSISTENT_HOME_SIZE
