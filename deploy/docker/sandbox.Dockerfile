FROM golang:1.24-bookworm AS go-builder
ENV GOPATH=/go
ENV PATH=$PATH:/go/bin
ENV CGO_ENABLED=0

# Install Go tools - Web Security & OSINT (each with error handling)
# Core scanning tools
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest || echo "nuclei install failed"
RUN go install github.com/projectdiscovery/httpx/cmd/httpx@latest || echo "httpx install failed"
RUN go install github.com/projectdiscovery/katana/cmd/katana@latest || echo "katana install failed"
RUN go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest || echo "naabu install failed"
RUN go install github.com/projectdiscovery/interactsh/cmd/interactsh-client@latest || echo "interactsh install failed"
RUN go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest || echo "subfinder install failed"

# Fuzzing tools
RUN go install github.com/ffuf/ffuf/v2@latest || echo "ffuf install failed"
RUN go install github.com/OJ/gobuster/v3@latest || echo "gobuster install failed"

# URL discovery tools
RUN go install github.com/tomnomnom/waybackurls@latest || echo "waybackurls install failed"
RUN go install github.com/tomnomnom/anew@latest || echo "anew install failed"
RUN go install github.com/lc/gau/v2/cmd/gau@latest || echo "gau install failed"

# Vulnerability scanning
RUN go install github.com/hahwul/dalfox/v2@latest || echo "dalfox install failed"
RUN go install github.com/aquasecurity/trivy/cmd/trivy@latest || echo "trivy install failed"

# OSINT tools (amass is large, may fail)
RUN go install github.com/owasp-amass/amass/v4/...@latest || \
    go install github.com/OWASP/Amass/v3/...@latest || echo "amass install failed"

# Clean up Go caches to reduce image size
RUN go clean -cache -modcache || true && rm -rf /go/pkg /tmp/*

FROM debian:stable-slim AS downloader
RUN apt-get update && apt-get install -y --no-install-recommends wget && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /downloads

# Download Kiterunner (amd64 only, skip if download fails)
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
    (wget -q --timeout=30 https://github.com/assetnote/kiterunner/releases/download/v1.0.2/kiterunner_1.0.2_linux_amd64.tar.gz && \
    tar xzf kiterunner_1.0.2_linux_amd64.tar.gz && \
    mv kr /usr/local/bin/kr && \
    rm -f kiterunner_1.0.2_linux_amd64.tar.gz) || \
    (echo "Kiterunner download failed, skipping..." && touch /usr/local/bin/kr); \
    else \
    echo "Kiterunner not available for $ARCH, skipping..." && \
    touch /usr/local/bin/kr; \
    fi

FROM kalilinux/kali-rolling

ARG DEBIAN_FRONTEND=noninteractive

# Combined apt install - core tools for skills
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Base System
    curl wget git unzip jq \
    python3-full python3-pip python3-venv pipx \
    libpcap-dev \
    # Core Kali Tools (Web & Network)
    nmap masscan sqlmap nikto hydra wafw00f whatweb \
    seclists amass feroxbuster theharvester zaproxy \
    # Report Generation & Node.js (for npm-audit)
    pandoc nodejs npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/*

# Copy Go Binaries
COPY --from=go-builder /go/bin/* /usr/local/bin/

# Copy Downloaded Tools
COPY --from=downloader /usr/local/bin/kr /usr/local/bin/

# Python Tools (via pipx) & npm tools - clean cache after
ENV PATH=$PATH:/root/.local/bin
RUN pipx install arjun && \
    pipx install dirsearch && \
    pipx install uro && \
    pipx install pip-audit && \
    npm install -g npm-audit-html && \
    npm cache clean --force && \
    rm -rf /root/.cache/pip /tmp/*

# Create directories
RUN mkdir -p /app /data

# Nuclei Templates - shallow clone & remove .git to save space
RUN git clone --depth 1 https://github.com/projectdiscovery/nuclei-templates.git /root/nuclei-templates && \
    rm -rf /root/nuclei-templates/.git

# Tool Configurations
RUN mkdir -p /root/.config/{nuclei,httpx,naabu,katana,subfinder,amass}

COPY configs/nuclei.yaml /root/.config/nuclei/config.yaml
COPY configs/httpx.yaml /root/.config/httpx/config.yaml
COPY configs/naabu.yaml /root/.config/naabu/config.yaml
COPY configs/katana.yaml /root/.config/katana/config.yaml
COPY configs/subfinder.yaml /root/.config/subfinder/config.yaml
COPY configs/amass.yaml /root/.config/amass/config.yaml

WORKDIR /app
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
