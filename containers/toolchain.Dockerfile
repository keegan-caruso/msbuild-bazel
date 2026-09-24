FROM ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq \
    curl ca-certificates libicu70 libssl3 zlib1g git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/rules_msbuild-toolchain
COPY payload.tar ./
RUN tar -xf payload.tar && rm payload.tar
ENV BAZELISK_HOME=/opt/rules_msbuild-toolchain/.cache/bazelisk
RUN bash scripts/setup.sh --toolchain-only \
    && USE_BAZEL_VERSION=8.8.0 bash scripts/bazel.sh --version \
    && rm -rf .cache/downloads .cache/nuget .cache/dotnet-home
RUN apt-get update -qq && apt-get install -y -qq bubblewrap python3 && rm -rf /var/lib/apt/lists/*
ENV RULES_MSBUILD_DOTNET_ROOT=/opt/rules_msbuild-toolchain/.tools/dotnet \
    RULES_MSBUILD_BAZEL=/opt/rules_msbuild-toolchain/scripts/bazel-launcher.sh \
    RULES_MSBUILD_CONTAINER_PREBUILT=1
WORKDIR /
