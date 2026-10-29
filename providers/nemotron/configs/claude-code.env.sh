# Point Claude Code at NVIDIA's free models via a local LiteLLM proxy.
#
# WHY a proxy: the NVIDIA cloud endpoint speaks OpenAI /v1/chat/completions, NOT
# Anthropic /v1/messages (verified: /v1/messages returns 404). LiteLLM translates
# Anthropic <-> OpenAI, so Claude Code talks to it unchanged.
#
# 1) Start the proxy in another terminal:
#      export NVIDIA_API_KEY=...            # your nvapi- key
#      litellm --config configs/litellm.config.yaml --port 4000
# 2) source this file, then run `claude`.
#
# Caveat: Claude Code's built-in aliases (haiku/sonnet/opus) are also used for
# background tasks; map ALL of them so nothing tries to reach a real Anthropic
# model name (which the proxy would 404).

export ANTHROPIC_BASE_URL="http://localhost:4000"
export ANTHROPIC_AUTH_TOKEN="sk-local-dummy"   # any non-empty string unless you set master_key

# Map Claude Code's model aliases onto proxy model_names (see litellm.config.yaml):
export ANTHROPIC_DEFAULT_OPUS_MODEL="opus"
export ANTHROPIC_DEFAULT_SONNET_MODEL="sonnet"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="haiku"

# Route subagents to a fast/cheap free model:
export CLAUDE_CODE_SUBAGENT_MODEL="haiku"

echo "Claude Code -> NVIDIA NIM via localhost:4000 (start LiteLLM first)."
