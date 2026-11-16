# NATIVE_BASE must be a locally built immutable Ubuntu 26 ARM64 / LLVM 18 image.
ARG NATIVE_BASE
FROM ${NATIVE_BASE}
ARG NATIVE_BASE
COPY packages.json install.py /tmp/source-sdk-native-overlay/
RUN python3 /tmp/source-sdk-native-overlay/install.py "$NATIVE_BASE" && rm -rf /tmp/source-sdk-native-overlay
