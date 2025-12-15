# DevServer Kubernetes Operator Deployment Plan

**Target**: Deploy to AWS EKS Auto Mode in us-west-1 region
**Cluster Name**: devserver
**IaC Tool**: Pulumi with Python
**Status Legend**: TODO | IN_PROGRESS | DEPLOYED | AGENT_TESTED | USER_TESTED

---

## Phase 1: Infrastructure Foundation

### 1.1 Create claude_iac_plan.md Documentation - DEPLOYED
- **Status**: DEPLOYED
- **Description**: Document deployment plan with status tracking system
- **Agent Testing**: N/A
- **User Testing**: N/A
- **Notes**: Documentation file created with comprehensive status tracking

### 1.2 Initialize Pulumi Project - AGENT_TESTED
- **Status**: AGENT_TESTED
- **Description**: Create `infrastructure/` directory with Pulumi Python project
- **Tasks**:
  - ✅ Create infrastructure directory structure
  - ✅ Initialize Pulumi project with Python
  - ✅ Configure Pulumi stack for us-west-1 region
  - ✅ Set up project dependencies (pulumi-aws 7.9.0, pulumi-kubernetes 4.23.0)
- **Agent Testing**: ✅ Project initialized, dependencies installed, region configured
- **User Testing**: Pending review
- **Notes**: Used latest pulumi-aws 7.9.0, created venv for dependencies, used local Pulumi backend

### 1.3 Deploy Core Network Infrastructure - USER_TESTED
- **Status**: USER_TESTED
- **Description**: VPC with public/private subnets across 2 AZs (us-west-1a, us-west-1c)
- **Tasks**:
  - ✅ Create VPC with CIDR 10.0.0.0/16
  - ✅ Create public subnets in 2 AZs (10.0.100-101.0/24, for load balancers)
  - ✅ Create private subnets in 2 AZs (10.0.0.0/19, 10.0.32.0/19, for EKS nodes - ~16K IPs)
  - ✅ Internet Gateway and 2 NAT Gateways (HA setup - one per AZ)
  - ✅ Route tables configuration (public + private per AZ)
  - ✅ Security groups for EKS cluster and nodes
  - ✅ Deployed successfully via `pulumi up`
- **Agent Testing**: ✅ Preview successful, configuration validated
- **User Testing**: ✅ Deployment completed successfully by user
- **Notes**: Infrastructure code complete, includes proper EKS tagging and HA NAT gateways. ✅ Switched to S3 backend for state management (s3://devserver-pulumi-state-308535385114). ✅ Updated private subnets to /19 to support 1000 servers + 10000 pods (~16K IPs available)

### 1.4 Deploy EKS Auto Mode Cluster - IN_PROGRESS
- **Status**: IN_PROGRESS
- **Description**: Create EKS cluster with Auto Mode enabled
- **Tasks**:
  - 🔄 Cleaning up orphaned basic EKS cluster (deleting - ~10 mins)
  - ✅ Auto Mode Pulumi configuration ready
  - ✅ IAM roles, security groups, networking ready
  - ⏳ Deploy pure Pulumi Auto Mode cluster (pending cleanup completion)
- **Agent Testing**: Pending cluster deployment
- **User Testing**: Pending cluster deployment
- **Notes**: ✅ Found correct Pulumi syntax for Auto Mode. Previous basic cluster (non-Auto Mode) was orphaned from Pulumi state - deleted manually. Ready to deploy proper Auto Mode cluster via pure Pulumi IaC.

---

## Phase 2: Container Registry & Operator Deployment

### 2.1 Set Up ECR Repository - TODO
- **Status**: TODO
- **Description**: Create ECR repository for devserver operator images
- **Tasks**:
  - Create ECR repository for operator
  - Configure build and push pipeline
  - Build and push initial operator image
- **Agent Testing**: Build and push operator Docker image
- **User Testing**: Verify image availability in ECR
- **Notes**:

### 2.2 Deploy Custom Resource Definitions (CRDs) - TODO
- **Status**: TODO
- **Description**: Apply DevServer, DevServerFlavor, and DevServerUser CRDs
- **Tasks**:
  - Apply all CRDs from crds/ directory
  - Create necessary RBAC configurations
  - Validate CRD installation
- **Agent Testing**: `kubectl get crds` and verify CRD installation
- **User Testing**: Review CRD definitions and RBAC
- **Notes**:

### 2.3 Deploy DevServer Operator - TODO
- **Status**: TODO
- **Description**: Deploy the operator to the cluster
- **Tasks**:
  - Create Kubernetes deployment for the operator
  - Configure service account and RBAC permissions
  - Set up operator monitoring and health checks
  - Deploy operator to cluster
- **Agent Testing**: Verify operator is running and processing events
- **User Testing**: Check operator logs and functionality
- **Notes**:

---

## Phase 3: Basic DevServer Functionality

### 3.1 Create Minimal DevServerFlavors - TODO
- **Status**: TODO
- **Description**: Deploy basic CPU-only flavor for testing
- **Tasks**:
  - Create basic CPU-only DevServerFlavor
  - Configure appropriate resource requests/limits
  - Apply flavor to cluster
- **Agent Testing**: Create and verify DevServerFlavor resources
- **User Testing**: Review flavor configurations
- **Notes**:

### 3.2 Deploy Supporting Infrastructure - TODO
- **Status**: TODO
- **Description**: Set up persistent storage and networking
- **Tasks**:
  - Configure EBS CSI driver for Auto Mode
  - Set up networking for DevServer access
  - Configure any required storage classes
- **Agent Testing**: Create a simple DevServer instance
- **User Testing**: Test storage and networking functionality
- **Notes**:

---

## Phase 4: CLI Integration & Validation

### 4.1 Configure kubectl Context - TODO
- **Status**: TODO
- **Description**: Set up kubeconfig for the new cluster
- **Tasks**:
  - Configure kubectl context for new cluster
  - Test CLI access to cluster resources
  - Validate devctl CLI functionality
- **Agent Testing**: `devctl` commands against the new cluster
- **User Testing**: Manual testing of devctl commands
- **Notes**:

### 4.2 End-to-End Testing - TODO
- **Status**: TODO
- **Description**: Complete DevServer workflow testing
- **Tasks**:
  - Create DevServer using `devctl create`
  - Test DevServer lifecycle (create, access, delete)
  - Validate operator logs and resource management
  - Test complete workflow
- **Agent Testing**: Complete DevServer workflow
- **User Testing**: Manual validation of all functionality
- **Notes**:

---

## Future Phases (When Needed)

### Phase 5: Production Readiness
- Add GPU Support with B200/H200 capacity reservations
- Implement comprehensive monitoring
- Set up backup/recovery procedures
- Add additional DevServerFlavors

---

## Important Notes

### EKS Auto Mode + GPU Capacity Reservations
- **Research Required**: Verify EKS Auto Mode compatibility with On-Demand Capacity Reservations for B200/H200 instances
- **Alternative**: May need to use standard EKS with managed node groups for GPU workloads if Auto Mode doesn't support capacity reservations
- **Documentation**: Need to validate this during cluster creation phase

### Testing Strategy
- Each phase includes specific validation steps
- Agent testing validates technical functionality
- User testing validates usability and correctness
- Must complete testing before proceeding to next phase

---

**Last Updated**: 2025-10-22
**Next Step**: Deploy Auto Mode EKS cluster

---

## 🎯 **PROJECT END GOAL**
**One-line Pulumi deployment** for test/prod environments:
```bash
pulumi up  # Deploy complete DevServer infrastructure with EKS Auto Mode
```
- ✅ Pure infrastructure-as-code (no shell scripts or manual steps)
- ✅ EKS Auto Mode enabled from cluster creation
- ✅ Scalable to test/prod environments
- ✅ GPU support with capacity reservations built-in
