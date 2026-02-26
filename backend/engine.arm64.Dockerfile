FROM docker.m.daocloud.io/kalilinux/kali-rolling:latest

ENV UV_INSTALLER=https://astral.sh/uv/install.sh
ENV DEBIAN_FRONTEND=noninteractive

# Use faster mirror
RUN tee /etc/apt/sources.list <<EOF
deb http://mirrors.tuna.tsinghua.edu.cn/kali kali-rolling main contrib non-free non-free-firmware
EOF

# Preseed keyboard configuration & prevent services from starting
RUN echo "keyboard-configuration keyboard-configuration/layoutcode string us" | debconf-set-selections && \
    echo "keyboard-configuration keyboard-configuration/modelcode string pc105" | debconf-set-selections && \
    printf '#!/bin/sh\nexit 0\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d

# Install base system in one layer
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends sudo kali-linux-core && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Allow services to start manually later
RUN rm -f /usr/sbin/policy-rc.d

# Setup user
RUN useradd -m -s /bin/bash seclens && \
    usermod -aG sudo seclens && \
    echo "seclens ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    mkdir -p /home/seclens/configs \
             /home/seclens/wordlists \
             /home/seclens/output \
             /home/seclens/scripts \
             /home/seclens/tools \
             /home/seclens/.cache/uv \
             /home/seclens/.npm-global \
             /app/runtime \
             /app/tools \
             /app/certs \
             /workspace && \
    chown -R seclens:seclens /app/certs /home/seclens /workspace

# Install all system packages in one layer (smaller image)
RUN apt-get update && \
apt-get install -y --no-install-recommends \
    # Basic utilities
    wget curl git vim nano unzip tar less man-db procps htop tmux \
    # Networking
    net-tools dnsutils whois iproute2 iputils-ping netcat-traditional \
    nmap ncat ndiff \
    # Development
    build-essential software-properties-common \
    gcc libc6-dev pkg-config libpcap-dev libssl-dev libffi-dev gdb \
    # Python
    python3 python3-pip python3-dev python3-venv python3-setuptools pipx \
    # Go & Node
#    golang-go nodejs npm \
    # Security tools
    sqlmap nuclei subfinder naabu ffuf zaproxy wapiti \
    # Utils
    jq parallel ripgrep && \
    # Give nmap capabilities
    setcap cap_net_raw,cap_net_admin,cap_net_bind_service+eip $(which nmap) && \
    # Clean up in same layer
    apt-get autoremove -y && \
    apt-get autoclean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Node tools in one layer
ENV NPM_CONFIG_PREFIX=/home/seclens/.npm-global
RUN #npm install -g retire eslint js-beautify jshint

# Setup Python environment
ENV PATH="/usr/local/bin:/home/seclens/go/bin:/home/seclens/.local/bin:/home/seclens/.npm-global/bin:/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

# way 1 to install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
RUN ls -lah /root
RUN mv /root/.local/bin/uv /usr/local/bin/uv
RUN ls -lah /usr/local/bin/uv

# way 2 to install uv
#RUN pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
#    pip3 config set global.trusted-host pypi.tuna.tsinghua.edu.cn && \
#    pip3 install uv && \
#    mv $(which uv) /usr/local/bin/uv

# Create uv cache directory for the test user and adjust permissions
RUN mkdir -p /home/seclens/.cache/uv && \
    chown -R seclens:seclens /home/seclens/.cache
RUN mkdir -p /workspace /app && chown -R seclens:seclens /workspace /app

USER seclens
# Add /usr/local/bin to PATH to ensure uv is available
ENV PATH="/usr/local/bin:${PATH}"
RUN echo $PATH

WORKDIR /app
COPY pyproject_engine.toml ./pyproject.toml
#COPY uv.lock README.md ./
COPY README.md ./
COPY app/ /app/app
RUN uv sync

# Add PATH to shell profiles
RUN echo 'export PATH="/home/seclens/go/bin:/home/seclens/.local/bin:/home/seclens/.npm-global/bin:$PATH"' \
    >> /home/seclens/.bashrc && \
    echo 'export PATH="/home/seclens/go/bin:/home/seclens/.local/bin:/home/seclens/.npm-global/bin:$PATH"' \
    >> /home/seclens/.profile

USER seclens
WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]
