# Codex CLI worker image for consult.py --transport codex. Codex runs ONLY in here, never on the host.
FROM node:22-bookworm-slim
ARG CODEX_VERSION=0.161.0
ARG UID=503
ARG GID=20
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates bubblewrap \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @openai/codex@${CODEX_VERSION} \
 && npm cache clean --force \
 && (getent group ${GID} >/dev/null || groupadd -g ${GID} codex) \
 && useradd -u ${UID} -g ${GID} -M -d /tmp/home -s /usr/sbin/nologin codex
ENV CODEX_HOME=/codex HOME=/tmp/home
USER ${UID}:${GID}
WORKDIR /packet
ENTRYPOINT ["codex"]
