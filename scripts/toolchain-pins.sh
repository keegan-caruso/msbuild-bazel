# Generated from toolchains.json; verified by the .NET tooling check.
case "$(uname -m)" in
    x86_64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-x64.tar.gz
        dotnet_sha256=7ad9d2db01512e41fd580a0630321bb70cd062d7fe4c5badfb4ce81ec1eddbb8
        bazel_version=8.4.2
        bazel_url=https://releases.bazel.build/8.4.2/release/bazel-8.4.2-linux-x86_64
        bazel_sha256=4dc8e99dfa802e252dac176d08201fd15c542ae78c448c8a89974b6f387c282c
        ;;
    aarch64|arm64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-arm64.tar.gz
        dotnet_sha256=13c219bfd1ff00a886c1523a9c7027c4f24c1e730e653376d2b81f1435da5a59
        bazel_version=8.4.2
        bazel_url=https://releases.bazel.build/8.4.2/release/bazel-8.4.2-linux-arm64
        bazel_sha256=58e6042fc54f3bf5704452b579f575ae935817d4b842a76123f05fae6b1f9a83
        ;;
    *) echo "Unsupported bootstrap architecture" >&2; return 1 ;;
esac
