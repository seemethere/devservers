import logging
import os

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "/etc/devserver-operator/config.yaml"
DEFAULT_PERSISTENT_HOME_SIZE = "10Gi"


class OperatorConfig:
    def __init__(self):
        self.config_path = os.environ.get(
            "DEVSERVER_OPERATOR_CONFIG_PATH", DEFAULT_CONFIG_PATH
        )
        self._config = self._load_config()
        self.default_persistent_home_size = self._config.get(
            "defaultPersistentHomeSize", DEFAULT_PERSISTENT_HOME_SIZE
        )

    def _load_config(self):
        try:
            with open(self.config_path, "r") as f:
                config_data = yaml.safe_load(f)
                logger.info(f"Loaded operator configuration from {self.config_path}")
                return config_data if config_data else {}
        except FileNotFoundError:
            logger.info(
                f"Operator config file not found at {self.config_path}, using default values."
            )
            return {}
        except Exception as e:
            logger.error(
                f"Error loading operator configuration from {self.config_path}: {e}"
            )
            return {}


# Global config instance to be used across the operator
config = OperatorConfig()
