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

# ============================================================================
# BuildKit Service
# ============================================================================

BUILDKIT_NS := buildkit-system
BUILDWORKER_IMAGE := $(DOCKER_REGISTRY)devserver/buildworker

.PHONY: buildkit-deploy
buildkit-deploy: install-crds
	@echo "🏗️ Deploying BuildKit service..."
	kubectl apply -f examples/buildkit/

.PHONY: buildkit-status
buildkit-status:
	@echo "📊 BuildKit service status..."
	@echo "\n=== BuilderPools ==="
	@kubectl get builderpools.devserver.io 2>/dev/null || echo "No BuilderPools found"
	@echo "\n=== Builds ==="
	@kubectl get builds.devserver.io --all-namespaces 2>/dev/null || echo "No Builds found"
	@echo "\n=== BuildKit System Pods ==="
	@kubectl get pods -n $(BUILDKIT_NS) 2>/dev/null || echo "Namespace not found"

.PHONY: buildkit-logs
buildkit-logs:
	@echo "📜 BuildKit logs..."
	kubectl logs -n $(BUILDKIT_NS) -l app=buildworker --tail=100 -f

.PHONY: buildkit-worker-build
buildkit-worker-build:
	@echo "🏗️ Building buildworker image..."
	docker build -f docker/buildworker/Dockerfile -t $(BUILDWORKER_IMAGE):latest .

.PHONY: buildkit-worker-push
buildkit-worker-push: buildkit-worker-build
	@echo "📤 Pushing buildworker image..."
	docker push $(BUILDWORKER_IMAGE):latest

.PHONY: buildkit-worker-run
buildkit-worker-run: sync
	@echo "🏃 Running buildworker locally..."
	RABBITMQ_HOST=localhost \
	RABBITMQ_PORT=5672 \
	RABBITMQ_USERNAME=buildqueue \
	RABBITMQ_PASSWORD=changeme-in-production \
	BUILDKIT_HOST=tcp://localhost:1234 \
	$(PYTHON) -m devservers.buildworker.main

.PHONY: buildkit-port-forward
buildkit-port-forward:
	@echo "🔌 Port-forwarding RabbitMQ and BuildKit..."
	@echo "RabbitMQ: localhost:5672 (AMQP), localhost:15672 (Management UI)"
	@echo "BuildKit: localhost:1234"
	@kubectl port-forward -n $(BUILDKIT_NS) svc/rabbitmq 5672:5672 15672:15672 &
	@kubectl port-forward -n $(BUILDKIT_NS) svc/default 1234:1234 &
	@echo "Port forwarding started. Press Ctrl+C to stop."
	@wait

.PHONY: buildkit-clean
buildkit-clean:
	@echo "🧹 Cleaning up BuildKit resources..."
	-kubectl delete -f examples/buildkit/ --ignore-not-found
	-kubectl delete namespace $(BUILDKIT_NS) --ignore-not-found

.PHONY: buildkit-dev
buildkit-dev: buildkit-deploy
	@echo "🚀 Starting BuildKit development environment..."
	@echo "Starting port-forward for RabbitMQ..."
	@kubectl wait --for=condition=ready pod -l app=rabbitmq -n $(BUILDKIT_NS) --timeout=120s
	@kubectl scale deployment buildworker -n $(BUILDKIT_NS) --replicas=0
	@pkill -f "port-forward.*rabbitmq" || true
	@kubectl port-forward -n $(BUILDKIT_NS) svc/rabbitmq 5672:5672 15672:15672 &
	@sleep 2
	@echo "RabbitMQ available at localhost:5672 (AMQP) and localhost:15672 (UI)"
	@echo ""
	@echo "Run these in separate terminals:"
	@echo "  Terminal 1: make run                    # Start operator"
	@echo "  Terminal 2: make buildkit-worker-run    # Start build worker"
	@echo ""
	@echo "Then create builds with: kubectl apply -f examples/buildkit/build.yaml"

.PHONY: buildkit-full
buildkit-full: up buildkit-dev
	@echo "✅ Full BuildKit environment ready!"
