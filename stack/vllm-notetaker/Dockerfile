# CCA Note-Taker — Qwen3.5-9B-FP8 for summarization + tool orchestration
# Small dense model serving CCA's note-taker and tool_orchestrator roles
#
# Based on vllm-dgx-spark-gb10, configured with thinking + tool calling.
# Model weights must be mounted at /models/Qwen3.5-9B-FP8.
#
# Usage:
#   docker run --gpus all -v /data/models:/models:ro -p 8400:8400 hellohal2064/cca-notetaker
#
# API:
#   POST /v1/chat/completions  — OpenAI-compatible chat (with tool calling)
#   GET  /health               — Health check

FROM hellohal2064/vllm-qwen3.5-gb10:latest

# Note-taker model and server config (read by base entrypoint.sh)
ENV MODEL_PATH=/models/Qwen3.5-9B-FP8
ENV MAX_MODEL_LEN=32768
ENV GPU_MEMORY_UTIL=0.5
ENV HOST=0.0.0.0
ENV PORT=8400

# Attention backend — FlashInfer (native SM121)
ENV ATTENTION_BACKEND=FLASHINFER

# 9B is dense — disable MoE backends
ENV VLLM_USE_FLASHINFER_MOE_FP8=0
ENV VLLM_USE_DEEP_GEMM=0
ENV VLLM_MOE_USE_DEEP_GEMM=0

# Tool calling + reasoning parsers (matches main vLLM on Spark2)
ENV TOOL_CALL_PARSER=qwen3_coder
ENV REASONING_PARSER=qwen3

# CPU parallelization
ENV OMP_NUM_THREADS=10
ENV TOKENIZERS_PARALLELISM=true

# GPU clock boost (DGX GB10 has no thermal issues)
ENV GPU_CLOCK_MAX=3003

# Suppress FLA format mismatch warnings
ENV PYTHONWARNINGS=ignore::UserWarning:vllm.model_executor.layers.fla.ops

# Additional vLLM args passed to entrypoint.sh
CMD ["--load-format", "fastsafetensors", \
     "--enable-prefix-caching", \
     "--max-num-batched-tokens", "8192", \
     "--kv-cache-dtype", "fp8_e4m3"]

EXPOSE 8400
