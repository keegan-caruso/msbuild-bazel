# Generated from toolchains.json; verified by the .NET tooling check.
case "$(uname -m)" in
    x86_64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-x64.tar.gz
        dotnet_sha256=7ad9d2db01512e41fd580a0630321bb70cd062d7fe4c5badfb4ce81ec1eddbb8
        bazel_version=9.2.0
        bazel_url=https://releases.bazel.build/9.2.0/release/bazel-9.2.0-linux-x86_64
        bazel_sha256=7668a95db1250f12c40407251e4e203b4ec8bf39bc495d2f485b2d8c99048694
        ;;
    aarch64|arm64)
        dotnet_version=10.0.400
        dotnet_url=https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-arm64.tar.gz
        dotnet_sha256=13c219bfd1ff00a886c1523a9c7027c4f24c1e730e653376d2b81f1435da5a59
        bazel_version=9.2.0
        bazel_url=https://releases.bazel.build/9.2.0/release/bazel-9.2.0-linux-arm64
        bazel_sha256=049dd21f40ad979db11c3ee68c96a42ce75f1185e69ac61ab20de1501427a410
        ;;
    *) echo "Unsupported bootstrap architecture" >&2; return 1 ;;
esac
