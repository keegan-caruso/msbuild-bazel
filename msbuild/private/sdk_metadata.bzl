"""SDK archive validation and exact-version release metadata resolution."""

load(":sdk_repositories.bzl", "SDK_PLATFORMS")

def sdk_version(value):
    """Validate an exact version without a catalog allowlist.

    Args:
        value: SDK or runtime version.

    Returns:
        The validated version.
    """
    if type(value) != "string" or not value or any([c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-+" for c in value.elems()]):
        fail("SDK/runtime versions must be explicit safe version strings")
    return value

def sdk_platforms(platforms):
    """Validate supported, unique archive platforms.

    Args:
        platforms: Requested runtime identifiers.
    """
    if not platforms or len(platforms) != len({p: True for p in platforms}):
        fail("SDK platforms must be nonempty and unique")
    for platform in platforms:
        if platform not in SDK_PLATFORMS:
            fail("Unsupported SDK platform: " + platform)

def sdk_download(archive):
    """Validate a locked archive declaration.

    Args:
        archive: URLs and SRI integrity.

    Returns:
        The validated declaration.
    """
    if type(archive) != "dict" or sorted(archive.keys()) != ["integrity", "urls"]:
        fail("SDK archives require exactly urls and integrity")
    urls = archive["urls"]
    integrity = archive["integrity"]
    if type(urls) != "list" or not urls or any([type(url) != "string" or not url or any([c in url for c in ["\n", "\r", "\000"]]) for url in urls]):
        fail("SDK archive URLs must be nonempty strings")
    if type(integrity) != "string" or not integrity or not (integrity.startswith("sha256-") or integrity.startswith("sha512-")):
        fail("SDK archives require SHA-256 or SHA-512 integrity")
    return archive

def sdk_selection(sdk):
    """Validate a recorded SDK selection.

    Args:
        sdk: Runtime version and archive declarations.

    Returns:
        The validated selection.
    """
    if type(sdk) != "dict" or sorted(sdk.keys()) != ["platforms", "runtime"] or type(sdk["platforms"]) != "dict":
        fail("SDK facts require runtime and platforms")
    sdk_version(sdk["runtime"])
    sdk_platforms(sdk["platforms"].keys())
    for archive in sdk["platforms"].values():
        sdk_download(archive)
    return sdk

def _integrity(hex_digest):
    if type(hex_digest) != "string" or len(hex_digest) != 128 or any([c not in "0123456789abcdefABCDEF" for c in hex_digest.elems()]):
        fail("Release metadata SDK hash must be SHA-512 hex")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    result = []
    for offset in range(0, 128, 6):
        chunk = hex_digest[offset:offset + 6]
        number = int(chunk + "0" * (6 - len(chunk)), 16)
        result.extend([alphabet[number // 262144], alphabet[number // 4096 % 64], alphabet[number // 64 % 64] if len(chunk) >= 4 else "=", alphabet[number % 64] if len(chunk) == 6 else "="])
    return "sha512-" + "".join(result)

def resolve_sdk(text, version, platforms):
    """Select archive hashes without executing the SDK or selecting latest.

    Args:
        text: Release metadata JSON.
        version: Exact SDK version.
        platforms: Requested archive platforms.

    Returns:
        Runtime version and selected archive declarations.
    """
    metadata = json.decode(text)
    if type(metadata) != "dict" or type(metadata.get("releases")) != "list":
        fail("Expected .NET releases.json metadata")
    matches = []
    for release in metadata["releases"]:
        for sdk in [release.get("sdk", {})] + release.get("sdks", []):
            if sdk.get("version") == version and sdk not in matches:
                matches.append(sdk)
    if len(matches) != 1:
        fail("Release metadata must identify exactly one SDK %s" % version)
    sdk = matches[0]
    runtime = sdk_version(sdk.get("runtime-version"))
    archives = {}
    for platform in sorted(platforms):
        candidates = [file for file in sdk.get("files", []) if file.get("rid") == platform and file.get("name", "").endswith(".tar.gz")]
        if len(candidates) != 1:
            fail("Release metadata must identify one SDK archive for %s / %s" % (version, platform))
        file = candidates[0]
        archives[platform] = sdk_download({"urls": [file.get("url")], "integrity": _integrity(file.get("hash"))})
    return {"runtime": runtime, "platforms": archives}
