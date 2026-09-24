{
  description = "Optional development tools for rules_msbuild";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/74c7dbb8e8adc9fdd3e734d7fd85f36f5421a2f9";
  inputs.nixpkgs-dotnet.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { nixpkgs, nixpkgs-dotnet, ... }:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" ];
      pins = builtins.fromJSON (builtins.readFile ./scripts/toolchains.json);
    in {
      devShells = nixpkgs.lib.genAttrs systems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          dotnetPkgs = import nixpkgs-dotnet { inherit system; };
          dotnet = dotnetPkgs.dotnetCorePackages.sdk_10_0-bin;
          launcher = if system == "aarch64-darwin" then pins.bazelisk.platforms.osx-arm64 else pins.bazelisk;
          bazelisk = pkgs.stdenvNoCC.mkDerivation {
            pname = "bazelisk";
            inherit (pins.bazelisk) version;
            src = pkgs.fetchurl { inherit (launcher) url sha256; };
            dontUnpack = true;
            dontStrip = true;
            installPhase = ''
              mkdir -p "$out/bin"
              cp "$src" "$out/bin/bazelisk"
              chmod +x "$out/bin/bazelisk"
              ln -s bazelisk "$out/bin/bazel"
            '';
          };
        in {
          default = assert dotnet.version == pins.dotnet.version; pkgs.mkShell {
            packages = [ dotnet bazelisk pkgs.python3 pkgs.bash pkgs.git pkgs.curl ];
            # The development wrapper pulls unrelated tools into the runtime closure.
            # Explicit actions consume the pinned SDK itself.
            RULES_MSBUILD_DOTNET_ROOT = "${dotnet.unwrapped}/share/dotnet";
            RULES_MSBUILD_BAZELISK = "${bazelisk}/bin/bazelisk";
            DOTNET_ROOT = "${dotnet.unwrapped}/share/dotnet";
            DOTNET_CLI_TELEMETRY_OPTOUT = "1";
            DOTNET_NOLOGO = "1";
          };
        });
    };
}
