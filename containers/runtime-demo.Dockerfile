FROM ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc
ENV DEBIAN_FRONTEND=noninteractive
# Ubuntu 22.04 / Clang 14 matches the qualified native runtime tool boundary.
# Setup records the resulting immutable image digest and installed packages.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    ca-certificates curl git python3 bubblewrap clang clang-14 lld lld-14 llvm llvm-14 \
    build-essential cmake ninja-build pkg-config libicu-dev libssl-dev \
    liblttng-ust-dev libnuma-dev libunwind-dev zlib1g-dev libkrb5-dev uuid-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /
