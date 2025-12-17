# Build worker Dockerfile
# This image runs the build worker that consumes from RabbitMQ and executes builds

FROM python:3.11-slim

# Install git (needed for cloning build contexts) and buildctl
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install buildctl from BuildKit release
ARG BUILDKIT_VERSION=0.12.4
RUN curl -sSL https://github.com/moby/buildkit/releases/download/v${BUILDKIT_VERSION}/buildkit-v${BUILDKIT_VERSION}.linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin --strip-components=1 bin/buildctl

# Create non-root user
RUN useradd -m -s /bin/bash worker

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir pika kubernetes

# Copy application code
COPY src/devservers ./devservers

# Switch to non-root user
USER worker

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the build worker
CMD ["python", "-m", "devservers.buildworker.main"]
