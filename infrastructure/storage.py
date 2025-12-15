"""Storage resources (EFS) for DevServer infrastructure"""

from vpc import VPCResources


class StorageResources:
    """EFS and storage resources"""

    def __init__(self, vpc: VPCResources):
        self.vpc = vpc

        # Note: In the Terraform setup, EFS filesystems are created dynamically by Lambda
        # For this Pulumi setup, we're just creating the security group infrastructure
        # Actual EFS filesystems will be created by the operator as needed

        # The EFS security group is already created in vpc.py as vpc.efs_sg
        # We just need to export it for reference
        self.efs_sg = vpc.efs_sg

        # Optional: Create a shared EFS for common data if needed
        # Uncomment below if you want a shared EFS for all users

        # self.shared_efs = aws.efs.FileSystem(
        #     f"{PREFIX}-shared-efs",
        #     encrypted=True,
        #     performance_mode="generalPurpose",
        #     throughput_mode="bursting",
        #     tags={
        #         **COMMON_TAGS,
        #         "Name": f"{PREFIX}-shared-efs",
        #     },
        # )

        # # Create mount targets in all subnets
        # aws.efs.MountTarget(
        #     f"{PREFIX}-efs-mt-primary",
        #     file_system_id=self.shared_efs.id,
        #     subnet_id=vpc.primary_subnet.id,
        #     security_groups=[vpc.efs_sg.id],
        # )

        # aws.efs.MountTarget(
        #     f"{PREFIX}-efs-mt-secondary",
        #     file_system_id=self.shared_efs.id,
        #     subnet_id=vpc.secondary_subnet.id,
        #     security_groups=[vpc.efs_sg.id],
        # )

        # if vpc.tertiary_subnet:
        #     aws.efs.MountTarget(
        #         f"{PREFIX}-efs-mt-tertiary",
        #         file_system_id=self.shared_efs.id,
        #         subnet_id=vpc.tertiary_subnet.id,
        #         security_groups=[vpc.efs_sg.id],
        #     )
