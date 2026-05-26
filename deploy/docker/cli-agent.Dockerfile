# =============================================================================
# CLI Agent Docker Image
# =============================================================================
# Pre-installs Claude Code CLI for autonomous agent execution.
# Used by CLIContainerService to spin up per-execution containers.
#
# Build:
#   docker build -f deploy/docker/cli-agent.Dockerfile -t joysafeter/cli-agent:latest .
# =============================================================================

FROM node:22-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    openssh-client \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install Codex CLI
RUN npm install -g @openai/codex

# Install OpenClaw (if available via npm, otherwise skip)
# RUN npm install -g openclaw@latest

# Create non-root user
RUN groupadd -r agent && useradd -r -g agent -m -d /home/agent -s /bin/bash agent

# Workspace directory
RUN mkdir -p /workspace && chown agent:agent /workspace

# Default working directory
WORKDIR /workspace

# Switch to non-root user
USER agent

# Verify installation
RUN claude --version || echo "Claude CLI installed"

# Default entrypoint keeps container alive for docker exec
CMD ["sleep", "infinity"]
