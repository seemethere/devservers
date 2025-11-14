import logging
import os

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "/etc/devserver-operator/config.yaml"
DEFAULT_EXPIRATION_INTERVAL = 60
DEFAULT_FLAVOR_RECONCILIATION_INTERVAL = 60
DEFAULT_WORKER_LIMIT = 1
DEFAULT_POSTING_ENABLED = False
DEFAULT_DEVSERVER_IMAGE = "seemethere/devserver-base:latest"
DEFAULT_STATIC_DEPENDENCIES_IMAGE = "seemethere/devserver-static-dependencies:latest"


class OperatorConfig:
    def __init__(self):
        self.config_path = os.environ.get(
            "DEVSERVER_OPERATOR_CONFIG_PATH", DEFAULT_CONFIG_PATH
        )
        self._config = self._load_config()

        def get_bool(value):
            return str(value).lower() in ("true", "1", "t")

        self.expiration_interval = self._get_value(
            "DEVSERVER_EXPIRATION_INTERVAL",
            "expirationInterval",
            DEFAULT_EXPIRATION_INTERVAL,
            caster=int,
        )
        self.flavor_reconciliation_interval = self._get_value(
            "DEVSERVER_FLAVOR_RECONCILIATION_INTERVAL",
            "flavorReconciliationInterval",
            DEFAULT_FLAVOR_RECONCILIATION_INTERVAL,
            caster=int,
        )
        self.worker_limit = self._get_value(
            "DEVSERVER_WORKER_LIMIT",
            "workerLimit",
            DEFAULT_WORKER_LIMIT,
            caster=int,
        )
        self.posting_enabled = self._get_value(
            "DEVSERVER_POSTING_ENABLED",
            "postingEnabled",
            DEFAULT_POSTING_ENABLED,
            caster=get_bool,
        )
        self.default_devserver_image = self._get_value(
            "DEVSERVER_DEFAULT_DEVSERVER_IMAGE",
            "defaultDevserverImage",
            DEFAULT_DEVSERVER_IMAGE,
        )
        self.static_dependencies_image = self._get_value(
            "DEVSERVER_STATIC_DEPENDENCIES_IMAGE",
            "staticDependenciesImage",
            DEFAULT_STATIC_DEPENDENCIES_IMAGE,
        )

    def _get_value(self, env_key, yaml_key, default, caster=None):
        val = os.environ.get(env_key, self._config.get(yaml_key, default))
        if caster:
            return caster(val)
        return val

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
