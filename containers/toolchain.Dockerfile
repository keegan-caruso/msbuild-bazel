FROM ubuntu@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq \
    curl ca-certificates libbrotli1 libc6 libgcc-s1 libgssapi-krb5-2 libicu78 libssl3t64 libstdc++6 tzdata zlib1g git libarchive-tools=3.8.5-1ubuntu2.3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/rules_msbuild-toolchain
COPY payload.tar ./
RUN bsdtar -xf payload.tar && rm payload.tar
ENV RULES_MSBUILD_TAR=/usr/bin/bsdtar
ENV BAZELISK_HOME=/opt/rules_msbuild-toolchain/.cache/bazelisk
RUN bash scripts/setup.sh --toolchain-only \
    && bash scripts/bazel.sh --version \
    && rm -rf .cache/downloads .cache/nuget .cache/dotnet-home
RUN apt-get update -qq && apt-get install -y -qq bubblewrap python3 && rm -rf /var/lib/apt/lists/*
ENV RULES_MSBUILD_DOTNET_ROOT=/opt/rules_msbuild-toolchain/.tools/dotnet \
    RULES_MSBUILD_BAZEL=/opt/rules_msbuild-toolchain/scripts/bazel-launcher.sh \
    RULES_MSBUILD_BAZELISK=/opt/rules_msbuild-toolchain/.tools/bin/bazelisk \
    RULES_MSBUILD_CONTAINER_PREBUILT=1
WORKDIR /
