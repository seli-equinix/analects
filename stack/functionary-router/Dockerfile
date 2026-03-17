# llama.cpp server for ARM64 + CUDA (DGX Spark GB10)
# Builds llama.cpp from source with CUDA support for Blackwell SM121
FROM nvcr.io/nvidia/cuda:13.0.0-devel-ubuntu24.04 AS build

RUN apt-get update && apt-get install -y \
    git cmake build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Build llama.cpp with CUDA
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /build/llama.cpp
WORKDIR /build/llama.cpp

# Create libcuda.so.1 symlink (stubs only have libcuda.so, linker needs .so.1 soname)
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1

RUN cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="120;121" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=OFF \
    -DCMAKE_EXE_LINKER_FLAGS="-L/usr/local/cuda/lib64/stubs -Wl,-rpath-link,/usr/local/cuda/lib64/stubs" \
    -DCMAKE_SHARED_LINKER_FLAGS="-L/usr/local/cuda/lib64/stubs" \
    && cmake --build build --config Release -j$(nproc) --target llama-server

# Runtime stage
FROM nvcr.io/nvidia/cuda:13.0.0-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y curl libgomp1 && rm -rf /var/lib/apt/lists/*

# Copy llama-server binary and required shared libraries
COPY --from=build /build/llama.cpp/build/bin/llama-server /app/llama-server
COPY --from=build /build/llama.cpp/build/bin/*.so* /app/lib/
ENV LD_LIBRARY_PATH=/app/lib

WORKDIR /app
ENTRYPOINT ["/app/llama-server"]
