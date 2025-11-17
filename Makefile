# Conditional pytest flags based on VERBOSE environment variable
VERBOSE ?= 0
MAX_JOBS ?= 4
NAMESPACE ?= default
PYTEST_VERBOSE = $(if $(filter 1,$(VERBOSE)),-v -s,)
PYTEST_PARALLEL_JOBS = $(if $(MAX_JOBS),-n $(MAX_JOBS),)
KOPF = uv run kopf
PYTHON = uv run python
PRECOMMIT = uv run pre-commit
PYTEST = uv run pytest

.PHONY: sync
sync:
	@echo "🔄 Syncing files..."
	# Using --dev since I'm assuming that's what you want from running the Makefile
	uv sync --dev

.PHONY: test
test: lint sync
	@echo "🧪 Running tests$(if $(MAX_JOBS), with $(MAX_JOBS) parallel jobs,)$(if $(filter 1,$(VERBOSE)), with verbose output,)... (use VERBOSE=1 for detailed output, MAX_JOBS=<n> for parallel tests)"
	$(PYTEST) $(PYTEST_PARALLEL_JOBS) $(PYTEST_VERBOSE) tests

.PHONY: install-crds
install-crds: crds/*.yaml
	@echo "🔄 Installing CRDs..."
	kubectl apply -f crds/

.PHONY: run
run: install-crds sync
	@echo "🏃 Running operator in namespace $(NAMESPACE)..."
	$(KOPF) run --dev -m devservers.operator --namespace $(NAMESPACE)

.PHONY: lint
lint: pre-commit

.PHONY: pre-commit
pre-commit: sync
	@$(PRECOMMIT) install
	@echo "🔄 Running pre-commit checks..."
	$(PRECOMMIT) run --all-files

DOCKER_REGISTRY :=
DOCKER_IMAGE := $(DOCKER_REGISTRY)seemethere/devserver

.PHONY: docker-build
docker-build:
	@echo "🏗️ Building Docker image..."
	docker build -t $(DOCKER_IMAGE) .

.PHONY: docker-push
docker-push:
	@echo "🔄 Pushing Docker image..."
	docker push $(DOCKER_IMAGE)


CLUSTER_NAME = devserver-cluster

.PHONY: up
up:
	@echo "🚀 Creating k3d cluster..."
	k3d cluster create $(CLUSTER_NAME)

.PHONY: down
down:
	@echo "🔥 Deleting k3d cluster..."
	k3d cluster delete $(CLUSTER_NAME)
