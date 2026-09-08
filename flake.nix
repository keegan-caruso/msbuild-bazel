{
  description = "Pinned tools for rules_msbuild";

  # Preserve the qualified Bazel baseline; update the SDK independently.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/74c7dbb8e8adc9fdd3e734d7fd85f36f5421a2f9";

  inputs.nixpkgs-dotnet.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { nixpkgs, nixpkgs-dotnet, ... }:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pins = builtins.fromJSON (builtins.readFile ./scripts/toolchains.json);
    in {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          # Use the upstream binary SDK on both platforms, as setup.sh does.
          dotnetPkgs = import nixpkgs-dotnet { inherit system; };
          dotnet = dotnetPkgs.dotnetCorePackages.sdk_10_0-bin;
          bazelPins = builtins.fromJSON (builtins.readFile ./nix/bazel-versions.json);
          releaseBazel = version:
            pkgs.stdenvNoCC.mkDerivation {
              pname = "bazel-release";
              inherit version;
              src = pkgs.fetchurl bazelPins.${version};
              dontUnpack = true;
              dontStrip = true;
              installPhase = ''
                mkdir -p "$out/bin"
                cp "$src" "$out/bin/bazel"
                chmod +x "$out/bin/bazel"
              '';
            };
          mkShell = bazel: expectedVersion:
            assert dotnet.version == pins.dotnet.version;
            assert bazel.version == expectedVersion;
            pkgs.mkShell {
              packages = [ dotnet bazel pkgs.python3 pkgs.bash pkgs.git pkgs.curl ];
              RULES_MSBUILD_DOTNET_ROOT = "${dotnet}/share/dotnet";
              RULES_MSBUILD_BAZEL = "${bazel}/bin/bazel";
              RULES_MSBUILD_BAZEL_VERSION = expectedVersion;
              DOTNET_ROOT = "${dotnet}/share/dotnet";
              DOTNET_CLI_TELEMETRY_OPTOUT = "1";
              DOTNET_NOLOGO = "1";
            };
        in {
          default = mkShell pkgs.bazel_8 pins.bazel.version;
        } // nixpkgs.lib.optionalAttrs (system == "aarch64-darwin")
          (builtins.listToAttrs (map (version: {
            name = "bazel-" + builtins.replaceStrings [ "." ] [ "_" ] version;
            value = mkShell (releaseBazel version) version;
          }) (builtins.attrNames bazelPins))));
    };
}
