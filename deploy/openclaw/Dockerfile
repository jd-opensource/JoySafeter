# OpenClaw Docker 镜像
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:22-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV BUN_INSTALL="/usr/local" \
    PATH="/usr/local/bin:$PATH" \
    DEBIAN_FRONTEND=noninteractive

# 1. 合并系统依赖安装与全局工具安装，并清理缓存
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    chromium \
    curl \
    build-essential \
    ffmpeg \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    git \
    gosu \
    jq \
    locales \
    openssh-client \
    procps \
    python3 \
    socat \
    tini \
    unzip \
    websockify && \
    sed -i 's/^# *en_US.UTF-8 UTF-8$/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen && \
    # update-locale 在部分 slim 基础镜像中会返回 invalid locale settings，这里改为直接写入默认 locale 配置
    printf 'LANG=en_US.UTF-8\nLANGUAGE=en_US:en\nLC_ALL=en_US.UTF-8\n' > /etc/default/locale && \
    # 配置 git 使用 HTTPS 替代 SSH
    git config --system url."https://github.com/".insteadOf ssh://git@github.com/ && \
    # 更新 npm 并安装全局包
    npm install -g npm@latest && \
    npm install -g openclaw@2026.3.11 opencode-ai@latest playwright playwright-extra puppeteer-extra-plugin-stealth @steipete/bird && \
    npm install -g @anthropic-ai/claude-code && \
    # 安装飞书官方插件 CLI
    #curl -fsSL https://sf3-cn.feishucdn.com/obj/open-platform-opendoc/4d184b1ba733bae2423a89e196a2ef8f_QATOjKH1WN.tgz -o /tmp/feishu-openclaw-plugin-onboard-cli.tgz && \
    #npm install -g /tmp/feishu-openclaw-plugin-onboard-cli.tgz && \
    # 安装 bun 和 qmd
    curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash && \
    /usr/local/bin/bun install -g @tobilu/qmd && \
    # 安装 Playwright 浏览器依赖
    npx playwright install chromium --with-deps && \
    # 清理 apt 缓存
    apt-get purge -y --auto-remove && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.npm /root/.cache

# 2. 插件安装（作为 node 用户以避免后期权限修复带来的镜像膨胀）
RUN mkdir -p /home/node/.openclaw/workspace /home/node/.openclaw/extensions && \
    chown -R node:node /home/node

USER node
ENV HOME=/home/node
WORKDIR /home/node

# 安装linuxbrew（Homebrew 的 Linux 版本），并配置环境变量
RUN mkdir -p /home/node/.linuxbrew/Homebrew && \
    git clone --depth 1 https://github.com/Homebrew/brew /home/node/.linuxbrew/Homebrew && \
    mkdir -p /home/node/.linuxbrew/bin && \
    ln -s /home/node/.linuxbrew/Homebrew/bin/brew /home/node/.linuxbrew/bin/brew && \
    chown -R node:node /home/node/.linuxbrew && \
    chmod -R g+rwX /home/node/.linuxbrew

#RUN cd /home/node/.openclaw/extensions && \
#  git clone --depth 1 https://github.com/soimy/openclaw-channel-dingtalk.git dingtalk && \
#  cd dingtalk && \
#  npm install --omit=dev --legacy-peer-deps && \
#  timeout 300 openclaw plugins install -l . || true && \
#  cd /home/node/.openclaw/extensions && \
#  git clone --depth 1 -b v4.17.25 https://github.com/Daiyimo/openclaw-napcat.git napcat && \
#  cd napcat && \
#  npm install --production && \
#  timeout 300 openclaw plugins install -l . || true && \
#  cd /home/node/.openclaw && \
#  git clone https://github.com/sliverp/qqbot.git && \
#  cd qqbot && \
#  timeout 300 bash ./scripts/upgrade.sh || true && \
#  timeout 300 openclaw plugins install . || true && \
#  timeout 300 openclaw plugins install @sunnoy/wecom || true && \
  # 为飞书官方插件 CLI 预置最小配置，避免 update 阶段因缺少 channels.feishu.appId/appSecret 报错
#  mkdir -p /home/node/.openclaw && \
#  printf '{\n  "channels": {\n    "feishu": {\n      "enabled": false,\n      "appId": "2222222222222222",\n      "appSecret": "1111111111111111",\n      "accounts": {\n        "default": {\n          "appId": "2222222222222222",\n          "appSecret": "1111111111111111",\n          "botName": "OpenClaw Bot"\n        }\n      }\n    }\n  }\n}\n' > /home/node/.openclaw/openclaw.json && \
  # 预执行安装命令（容器内需手动交互，此处仅作声明或环境准备）
  # feishu-plugin-onboard update && \
#  find /home/node/.openclaw/extensions -name ".git" -type d -exec rm -rf {} + && \
#  rm -rf /home/node/.openclaw/qqbot/.git && \
#  rm -rf /tmp/* /home/node/.npm /home/node/.cache
  
# 3. 最终配置
USER root

# 复制初始化脚本并确保换行符为 LF
#COPY ./init.sh /usr/local/bin/init.sh
#RUN sed -i 's/\r$//' /usr/local/bin/init.sh && chmod +x /usr/local/bin/init.sh

# 设置环境变量
ENV HOME=/home/node \
    TERM=xterm-256color \
    NODE_PATH=/usr/local/lib/node_modules \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    NODE_ENV=production \
    PATH="/home/node/.linuxbrew/bin:/home/node/.linuxbrew/sbin:/usr/local/lib/node_modules/.bin:${PATH}" \
    HOMEBREW_NO_AUTO_UPDATE=1 \
    HOMEBREW_NO_INSTALL_CLEANUP=1

# 暴露端口
EXPOSE 18789 18790

# 设置工作目录为 home
WORKDIR /home/node

# 使用初始化脚本作为入口点
#ENTRYPOINT ["/bin/bash", "/usr/local/bin/init.sh"]

COPY start-openclaw.sh /usr/local/bin/start-openclaw.sh
RUN chmod +x /usr/local/bin/start-openclaw.sh
CMD ["/usr/local/bin/start-openclaw.sh"]

ENTRYPOINT ["/bin/bash", "/usr/local/bin/start-openclaw.sh"]