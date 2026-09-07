{
  description = "Pinned tools for rules_msbuild";

  # This revision contains both experimental baseline versions.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/74c7dbb8e8adc9fdd3e734d7fd85f36f5421a2f9";

  outputs = { nixpkgs, ... }:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pins = builtins.fromJSON (builtins.readFile ./scripts/toolchains.json);
    in {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          # Use the upstream binary SDK on both platforms, as setup.sh does.
          dotnet = pkgs.dotnetCorePackages.sdk_10_0-bin;
          bazel = pkgs.bazel_8;
        in {
          default = assert dotnet.version == pins.dotnet.version;
            assert bazel.version == pins.bazel.version;
            pkgs.mkShell {
              packages = [ dotnet bazel pkgs.python3 pkgs.bash pkgs.git pkgs.curl ];
              RULES_MSBUILD_DOTNET_ROOT = "${dotnet}/share/dotnet";
              RULES_MSBUILD_BAZEL = "${bazel}/bin/bazel";
              DOTNET_ROOT = "${dotnet}/share/dotnet";
              DOTNET_CLI_TELEMETRY_OPTOUT = "1";
              DOTNET_NOLOGO = "1";
            };
        });
    };
}
