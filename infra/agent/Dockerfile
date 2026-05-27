FROM kalilinux/kali-last-release

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --fix-missing --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        iproute2 \
        jq \
        nmap \
        nodejs \
        npm \
        python3 \
        python3-pip \
        sqlmap \
        vim-tiny \
        wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex@0.133.0 \
    && codex --version

WORKDIR /workspace

CMD ["sleep", "infinity"]
