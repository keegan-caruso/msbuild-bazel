# Generated from toolchains.json; verified by the .NET tooling check.
case "$(uname -s):$(uname -m)" in
    Linux:x86_64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-x64.tar.gz
        dotnet_sha256=7ad9d2db01512e41fd580a0630321bb70cd062d7fe4c5badfb4ce81ec1eddbb8
        bazelisk_version=1.29.0
        bazelisk_url=https://github.com/bazelbuild/bazelisk/releases/download/v1.29.0/bazelisk-linux-amd64
        bazelisk_sha256=5a408715e932c0250d28bd84555f12edbf70117de42f9181691c736eacc4a992
        ;;
    Linux:aarch64|Linux:arm64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-arm64.tar.gz
        dotnet_sha256=13c219bfd1ff00a886c1523a9c7027c4f24c1e730e653376d2b81f1435da5a59
        bazelisk_version=1.29.0
        bazelisk_url=https://github.com/bazelbuild/bazelisk/releases/download/v1.29.0/bazelisk-linux-arm64
        bazelisk_sha256=e20e8b0f4f240091b7a55bf17b9398bd4f40ee70ae0208dff95dd4c445fb4010
        ;;
    Darwin:arm64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-osx-arm64.tar.gz
        dotnet_sha256=8f11629611787a2856535aba4102b1f7ab73740aca46e88b6703502299635453
        bazelisk_version=1.29.0
        bazelisk_url=https://github.com/bazelbuild/bazelisk/releases/download/v1.29.0/bazelisk-darwin-arm64
        bazelisk_sha256=cee851f726789227d5561004e9904a52be45c3efb56f8b38b6993d6adbaa0409
        ;;
    *) echo "Unsupported bootstrap platform" >&2; return 1 ;;
esac
