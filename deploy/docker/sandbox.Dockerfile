FROM golang:1.23-bookworm AS go-builder
ENV GOPATH=/go
ENV PATH=$PATH:/go/bin
ENV CGO_ENABLED=0

# Install Go tools - Web Security & OSINT (clean build cache after)
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest && \
    go install github.com/projectdiscovery/httpx/cmd/httpx@latest && \
    go install github.com/projectdiscovery/katana/cmd/katana@latest && \
    go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest && \
    go install github.com/projectdiscovery/interactsh/cmd/interactsh-client@latest && \
    go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest && \
    go install github.com/ffuf/ffuf/v2@latest && \
    go install github.com/OJ/gobuster/v3@latest && \
    go install github.com/tomnomnom/waybackurls@latest && \
    go install github.com/tomnomnom/anew@latest && \
    go install github.com/zricethezav/gitleaks/v8@latest && \
    go install github.com/aquasecurity/trivy/cmd/trivy@latest && \
    go install github.com/lc/gau/v2/cmd/gau@latest && \
    go install github.com/hahwul/dalfox/v2@latest && \
    (go install github.com/owasp-amass/amass/v4/...@latest || \
    go install github.com/OWASP/Amass/v3/...@latest || true) && \
    go clean -cache -modcache && \
    rm -rf /go/pkg /tmp/*

FROM debian:stable-slim AS downloader
RUN apt-get update && apt-get install -y --no-install-recommends wget && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /downloads

# Download Kiterunner (amd64 only, skip on other architectures)
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
    wget -q https://github.com/assetnote/kiterunner/releases/download/v1.0.2/kiterunner_1.0.2_linux_amd64.tar.gz && \
    tar xzf kiterunner_1.0.2_linux_amd64.tar.gz && \
    mv kr /usr/local/bin/kr && \
    rm -f kiterunner_1.0.2_linux_amd64.tar.gz; \
    else \
    echo "Kiterunner not available for $ARCH, skipping..." && \
    touch /usr/local/bin/kr; \
    fi

# Download Burp Suite Community JAR
RUN wget -q "https://portswigger.net/burp/releases/download?product=community&version=2024.12&type=Jar" -O /downloads/burpsuite_community.jar || \
    echo "Burp download failed, creating placeholder" && touch /downloads/burpsuite_community.jar

FROM kalilinux/kali-rolling

ARG DEBIAN_FRONTEND=noninteractive

# Combined apt install to reduce layers & cleanup in same layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Base System & Runtimes
    build-essential curl wget git vim-tiny zsh unzip jq iputils-ping \
    python3-full python3-pip python3-venv pipx \
    default-jre-headless libpcap-dev \
    # Core Kali Tools (Web & Network)
    nmap masscan sqlmap nikto hydra wafw00f whatweb \
    seclists zaproxy amass feroxbuster theharvester \
    # Report Generation & Node.js
    pandoc nodejs npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/*

# Copy Go Binaries (strip debug info is already done via CGO_ENABLED=0)
COPY --from=go-builder /go/bin/* /usr/local/bin/

# Copy Downloaded Tools
COPY --from=downloader /usr/local/bin/kr /usr/local/bin/
COPY --from=downloader /downloads/burpsuite_community.jar /opt/burpsuite_community.jar

# Python Tools (via pipx) & npm tools - clean cache after
ENV PATH=$PATH:/root/.local/bin
RUN pipx install arjun && \
    pipx install dirsearch && \
    pipx install uro && \
    pipx install pip-audit && \
    (pipx install xsser || true) && \
    npm install -g npm-audit-html && \
    npm cache clean --force && \
    rm -rf /root/.cache/pip /tmp/*

# Create non-root user & directories
RUN useradd -m -s /bin/zsh pentest && \
    mkdir -p /app /data && \
    chown -R pentest:pentest /app /data

# Nuclei Templates - shallow clone & remove .git to save space
RUN mkdir -p /home/pentest/nuclei-templates && \
    git clone --depth 1 https://github.com/projectdiscovery/nuclei-templates.git /home/pentest/nuclei-templates && \
    rm -rf /home/pentest/nuclei-templates/.git && \
    chown -R pentest:pentest /home/pentest/nuclei-templates

# Tool Configurations
RUN mkdir -p /home/pentest/.config/{nuclei,httpx,naabu,katana,subfinder,amass}

COPY configs/nuclei.yaml /home/pentest/.config/nuclei/config.yaml
COPY configs/httpx.yaml /home/pentest/.config/httpx/config.yaml
COPY configs/naabu.yaml /home/pentest/.config/naabu/config.yaml
COPY configs/katana.yaml /home/pentest/.config/katana/config.yaml
COPY configs/subfinder.yaml /home/pentest/.config/subfinder/config.yaml
COPY configs/amass.yaml /home/pentest/.config/amass/config.yaml

# Entrypoint & final setup
WORKDIR /app
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && \
    chown -R pentest:pentest /home/pentest

# Setup Zsh for pentest user (minimal oh-my-zsh)
USER pentest
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended || true && \
    rm -rf ~/.oh-my-zsh/.git

USER root

VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
