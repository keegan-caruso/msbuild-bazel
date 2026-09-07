FROM ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq \
    python3 curl ca-certificates libicu70 libssl3 zlib1g git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/msbuild-bazel-toolchain
COPY scripts/setup.sh scripts/setup.py scripts/toolchain_pins.py scripts/toolchains.json scripts/env.sh scripts/check.sh scripts/dotnet.sh scripts/bazel.sh ./scripts/
COPY global.json .bazelversion ./
RUN bash scripts/setup.sh && rm -rf .cache
ENV SPIKE_DOTNET_ROOT=/opt/msbuild-bazel-toolchain/.tools/dotnet \
    SPIKE_BAZEL=/opt/msbuild-bazel-toolchain/.tools/bin/bazel \
    SPIKE_CONTAINER_PREBUILT=1
WORKDIR /
