FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv clang-18 llvm-18 cmake ninja-build ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE /app/
COPY faultdebug /app/faultdebug
COPY scripts /app/scripts
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir .
ENV PATH="/opt/venv/bin:/usr/lib/llvm-18/bin:$PATH" PYTHONPATH=/app
COPY CMakeLists.txt /app/
COPY include /app/include
COPY runtime /app/runtime
COPY cmake /app/cmake
COPY test/shop /app/test/shop
RUN cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=clang-18 \
    -DCMAKE_CXX_COMPILER=clang++-18 -DFAULTDEBUG_BUILD_TESTS=OFF \
    -DFAULTDEBUG_BUILD_SHOP=ON -DFAULTDEBUG_PYTHON_EXECUTABLE=/opt/venv/bin/python \
    && cmake --build build --parallel 2 \
    && fault-debug index build/compile_commands.json -o /opt/shop-index.json \
    && fault-debug bundle --source-root build/faultdebug-source-snapshot/files \
       --output /opt/shop-bundle --index /opt/shop-index.json \
       --binary build/test/shop/libshop_boundary.so --binary build/libfaultdebug_runtime.so
ENV SHOP_BOUNDARY=/app/build/test/shop/libshop_boundary.so \
    FAULTDEBUG_RUNTIME_DIR=/app/build LD_LIBRARY_PATH=/app/build
EXPOSE 8080
# A per-service numeric identity and collector command are supplied by Compose.
