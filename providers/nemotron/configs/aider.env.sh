# Point aider at NVIDIA's free models. No proxy needed (OpenAI-compatible).
# Prefix the model with `openai/` so aider uses the OpenAI-compatible driver.
#
#   source configs/aider.env.sh
#   aider --model openai/nvidia/nemotron-3-super-120b-a12b

export OPENAI_API_BASE="https://integrate.api.nvidia.com/v1"
export OPENAI_API_KEY="${NVIDIA_API_KEY}"

echo "aider -> NVIDIA NIM. Run: aider --model openai/nvidia/nemotron-3-super-120b-a12b"
