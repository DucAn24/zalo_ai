#!/usr/bin/env bash
# Start a vLLM OpenAI-compatible server (Colab T4 / Docker). Configure with environment variables:
#   MODEL     default Qwen/Qwen3-8B-AWQ   (also try Qwen/Qwen3-4B-AWQ, Qwen/Qwen3-14B-AWQ)
#   PORT      default 8000
#   MAX_LEN   default 16384               (system prompt incl. rulebook is ~10-13k tokens)
#   GPU_UTIL  default 0.90
#   DTYPE     default half                (T4 has no bf16; use auto/bfloat16 on Ampere+)
#   MAX_SEQS  default 16
#   TP        default 1                   (tensor parallel size; 2 on 2xRTX 5090)
#   EXTRA     any additional vLLM flags
set -euo pipefail
MODEL="${MODEL:-Qwen/Qwen3-8B-AWQ}"
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-16384}"
GPU_UTIL="${GPU_UTIL:-0.90}"
DTYPE="${DTYPE:-half}"
MAX_SEQS="${MAX_SEQS:-16}"
TP="${TP:-1}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"     # V0 engine: works on Turing (T4); V1 needs newer GPUs
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
exec python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" --served-model-name "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  --max-model-len "$MAX_LEN" --gpu-memory-utilization "$GPU_UTIL" --dtype "$DTYPE" \
  --tensor-parallel-size "$TP" --max-num-seqs "$MAX_SEQS" \
  --enable-prefix-caching --seed 42 ${EXTRA:-}
