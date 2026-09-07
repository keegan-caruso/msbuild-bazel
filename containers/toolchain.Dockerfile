FROM ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq \
    python3 curl ca-certificates libicu70 libssl3 zlib1g git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/rules_msbuild-toolchain
COPY scripts/setup.sh scripts/setup.py scripts/toolchain_pins.py scripts/toolchains.json scripts/env.sh scripts/check.sh scripts/dotnet.sh scripts/bazel.sh scripts/setup-starlark.py scripts/check-starlark.py scripts/starlark-tools.json ./scripts/
COPY global.json .bazelversion ./
RUN bash scripts/setup.sh --toolchain-only && rm -rf .cache
ENV RULES_MSBUILD_DOTNET_ROOT=/opt/rules_msbuild-toolchain/.tools/dotnet \
    RULES_MSBUILD_BAZEL=/opt/rules_msbuild-toolchain/.tools/bin/bazel \
    RULES_MSBUILD_CONTAINER_PREBUILT=1
WORKDIR /
