FROM ubuntu@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96
ENV DEBIAN_FRONTEND=noninteractive
# Ubuntu 26.04 with the explicitly selected LLVM 18 compiler family.
# Setup records the resulting immutable image digest and installed packages.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    ca-certificates curl git python3 bubblewrap clang-18 lld-18 llvm-18 \
    gcc g++ make dpkg-dev libc6-dev libcrypt-dev coreutils-from-uutils- coreutils-from-gnu \
    cmake ninja-build pkg-config libicu-dev libssl-dev \
    liblttng-ust-dev libnuma-dev libunwind-dev zlib1g-dev libkrb5-dev uuid-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /
