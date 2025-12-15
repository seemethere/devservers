"""Configuration management for DevServer infrastructure"""

import pulumi

# Get the current stack and config
config = pulumi.Config()
stack = pulumi.get_stack()

# Common configuration
PREFIX = "devserver"
VPC_CIDR = "10.0.0.0/16"
PRIMARY_SUBNET_CIDR = "10.0.0.0/20"
SECONDARY_SUBNET_CIDR = "10.0.16.0/20"
TERTIARY_SUBNET_CIDR = "10.0.32.0/20"

# EKS Configuration
EKS_VERSION = "1.34"
KEY_PAIR_NAME = config.get("keyPairName") or "pet-instances-skeleton-key-v2"

# Environment-specific configurations
ENVIRONMENT_CONFIGS = {
    "dev": {
        "region": "us-west-1",
        "environment": "test",
        "gpu_instance_count": 2,
        "supported_gpu_types": {
            "t4": {
                "instance_type": "g4dn.12xlarge",
                "instance_count": 2,
                "gpus_per_instance": 4,
                "use_placement_group": True,
                "architecture": "x86_64",
            },
            "t4-small": {
                "instance_type": "g4dn.2xlarge",
                "instance_count": 1,
                "gpus_per_instance": 1,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
            "cpu-x86": {
                "instance_type": "c7i.4xlarge",
                "instance_count": 1,
                "gpus_per_instance": 0,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
        },
    },
    "prod": {
        "region": "us-east-2",
        "environment": "prod",
        "gpu_instance_count": 2,
        "supported_gpu_types": {
            "h200": {
                "instance_type": "p5e.48xlarge",
                "instance_count": 2,
                "gpus_per_instance": 8,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
            "h100": {
                "instance_type": "p5.48xlarge",
                "instance_count": 2,
                "gpus_per_instance": 8,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
            "a100": {
                "instance_type": "p4d.24xlarge",
                "instance_count": 2,
                "gpus_per_instance": 8,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
            "t4": {
                "instance_type": "g4dn.12xlarge",
                "instance_count": 2,
                "gpus_per_instance": 4,
                "use_placement_group": True,
                "architecture": "x86_64",
            },
            "l4": {
                "instance_type": "g6.12xlarge",
                "instance_count": 2,
                "gpus_per_instance": 4,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
            "cpu-x86": {
                "instance_type": "c7i.8xlarge",
                "instance_count": 2,
                "gpus_per_instance": 0,
                "use_placement_group": False,
                "architecture": "x86_64",
            },
        },
    },
}

# Get current environment config
CURRENT_CONFIG = ENVIRONMENT_CONFIGS.get(stack, ENVIRONMENT_CONFIGS["dev"])
REGION = config.get("aws:region") or CURRENT_CONFIG["region"]
ENVIRONMENT = CURRENT_CONFIG["environment"]
SUPPORTED_GPU_TYPES = CURRENT_CONFIG["supported_gpu_types"]

# Tags
COMMON_TAGS = {
    "Project": "devserver",
    "Environment": ENVIRONMENT,
    "ManagedBy": "Pulumi",
}
