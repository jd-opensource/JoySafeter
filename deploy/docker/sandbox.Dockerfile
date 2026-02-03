FROM golang:1.23-bookworm AS go-builder
ENV GOPATH=/go
ENV PATH=$PATH:/go/bin

# Install Go tools
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest && \
    go install github.com/projectdiscovery/httpx/cmd/httpx@latest && \
    go install github.com/projectdiscovery/katana/cmd/katana@latest && \
    go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest && \
    go install github.com/projectdiscovery/interactsh/cmd/interactsh-client@latest && \
    go install github.com/ffuf/ffuf/v2@latest && \
    go install github.com/OJ/gobuster/v3@latest && \
    go install github.com/tomnomnom/waybackurls@latest && \
    go install github.com/tomnomnom/anew@latest && \
    go install github.com/zricethezav/gitleaks/v8@latest && \
    go install github.com/aquasecurity/trivy/cmd/trivy@latest

FROM debian:stable-slim AS downloader
RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*
WORKDIR /downloads

# Download Kiterunner
RUN wget -q https://github.com/assetnote/kiterunner/releases/download/v1.0.2/kr_linux_amd64.tar.gz && \
    tar xzf kr_linux_amd64.tar.gz && \
    mv kr /usr/local/bin/kr

# Download Burp Suite Community JAR (updated to 2024.x)
RUN wget -q "https://portswigger.net/burp/releases/download?product=community&version=2024.12&type=Jar" -O /downloads/burpsuite_community.jar

FROM kalilinux/kali-rolling

ARG DEBIAN_FRONTEND=noninteractive

# 1. Base System & Runtimes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    git \
    vim \
    zsh \
    unzip \
    jq \
    iputils-ping \
    python3-full \
    python3-pip \
    python3-venv \
    pipx \
    default-jre \
    libpcap-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Core Kali Tools (Web & Network)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    masscan \
    sqlmap \
    nikto \
    hydra \
    wafw00f \
    whatweb \
    seclists \
    zaproxy \
    && rm -rf /var/lib/apt/lists/*

# 3. Report Generation Tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy Go Binaries
COPY --from=go-builder /go/bin/* /usr/local/bin/

# 5. Copy Downloaded Tools
COPY --from=downloader /usr/local/bin/kr /usr/local/bin/
COPY --from=downloader /downloads/burpsuite_community.jar /opt/burpsuite_community.jar

# 6. Python Tools (via pipx) including dependency scanning
ENV PATH=$PATH:/root/.local/bin
RUN pipx install arjun && \
    pipx install dirsearch && \
    pipx install uro && \
    pipx install pip-audit

# 7. Node.js and npm-audit (for JavaScript dependency scanning)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/* && \
    npm install -g npm-audit-html

# 8. Create non-root user for security
RUN useradd -m -s /bin/zsh pentest && \
    mkdir -p /app /data && \
    chown -R pentest:pentest /app /data

# 9. Configuration (as root for initial setup)
WORKDIR /app
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Setup Zsh for pentest user
USER pentest
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended || true

# Switch back to root for entrypoint (entrypoint can drop privileges if needed)
USER root

# Ensure pentest user can access necessary directories
RUN chown -R pentest:pentest /home/pentest

VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
