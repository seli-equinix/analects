# CCA Embedding Server — Qwen3-Embedding-8B via vLLM pooling runner
# Produces 4096-dimensional embeddings for code intelligence + semantic search
#
# Based on vllm-dgx-spark-gb10, configured for embedding (pooling) mode.
# Model weights must be mounted at /models/Qwen3-Embedding-8B.
#
# Usage:
#   docker run --gpus all -v /data/models:/models:ro -p 8200:8000 hellohal2064/cca-embedding-server
#
# API:
#   POST /v1/embeddings  — OpenAI-compatible embeddings endpoint
#   GET  /health         — Health check

FROM hellohal2064/vllm-qwen3.5-gb10:latest

# Override entrypoint — embedding uses vLLM pooling runner directly (no tool calling)
ENTRYPOINT ["vllm"]
CMD ["serve", "/models/Qwen3-Embedding-8B", \
     "--runner", "pooling", \
     "--port", "8000", \
     "--host", "0.0.0.0", \
     "--dtype", "auto", \
     "--max-model-len", "8192", \
     "--gpu-memory-utilization", "0.15", \
     "--attention-config.backend=TRITON_ATTN", \
     "--served-model-name", "Qwen/Qwen3-Embedding-8B", \
     "--load-format", "fastsafetensors"]

# Embedding-specific environment
ENV VLLM_FASTSAFETENSORS_NOGDS=1
ENV OMP_NUM_THREADS=20
ENV TOKENIZERS_PARALLELISM=true

EXPOSE 8000
