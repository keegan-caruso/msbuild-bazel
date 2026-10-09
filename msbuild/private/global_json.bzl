"""Deterministic SDK selection from an explicitly declared global.json."""

def _json_comments(text):
    # Keep strings intact, including URLs and escaped quotes. Preserve separators
    # when removing comments so adjacent tokens cannot accidentally be joined.
    result = []
    state = "normal"
    escaped = False
    skip = False
    for i in range(len(text)):
        c = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""
        if skip:
            skip = False
            continue
        if state == "string":
            result.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                state = "normal"
        elif state == "line":
            if c == "\n":
                result.append(c)
                state = "normal"
        elif state == "block":
            if c == "*" and next_char == "/":
                state = "normal"
                skip = True
        elif c == '"':
            result.append(c)
            state = "string"
        elif c == "/" and next_char in ["/", "*"]:
            result.append(" ")
            state = "line" if next_char == "/" else "block"
            skip = True
        else:
            result.append(c)
    if state in ["string", "block"]:
        fail("Unterminated string or comment in global.json")
    return "".join(result)

def global_json_sdk(text):
    """Read a declared SDK version and supported selection policy.

    Args:
        text: Contents of the explicitly declared global.json file.

    Returns:
        Requested version, roll-forward policy and prerelease eligibility.
    """
    data = json.decode(_json_comments(text))
    if type(data) != "dict" or type(data.get("sdk")) != "dict":
        fail("global.json requires an sdk object with an exact version")
    for key in data:
        if key not in ["sdk", "$schema", "msbuild-sdks"]:
            fail("Unsupported global.json field: " + key + "; declare non-SDK behavior explicitly in Bazel")
    msbuild_sdks = data.get("msbuild-sdks", {})
    if type(msbuild_sdks) != "dict" or any([type(name) != "string" or not name or type(value) != "string" or not value for name, value in msbuild_sdks.items()]):
        fail("global.json msbuild-sdks must map SDK names to explicit versions")

    # These select MSBuild imports, not the dotnet SDK. Compilation/sync must
    # separately provide their packages through a declared package_lock.
    sdk = data["sdk"]
    for key in sdk:
        if key not in ["version", "rollForward", "allowPrerelease", "errorMessage"]:
            fail("Unsupported global.json sdk field: " + key)
    version = sdk.get("version")
    if type(version) != "string" or not version:
        fail("global.json requires sdk.version")
    policy = sdk.get("rollForward", "patch")
    policies = {value.lower(): value for value in ["disable", "patch", "latestPatch", "latestFeature"]}
    if type(policy) != "string" or policy.lower() not in policies:
        fail("global.json rollForward must be disable, patch, latestPatch or latestFeature")
    policy = policies[policy.lower()]
    if type(sdk.get("allowPrerelease", True)) != "bool":
        fail("global.json sdk.allowPrerelease must be Boolean")
    if type(sdk.get("errorMessage", "")) != "string":
        fail("global.json sdk.errorMessage must be a string")

    # dotnet permits prereleases whenever the requested version is itself a preview.
    preview = "-" in version.split("+")[0]
    return {"version": version, "rollForward": policy, "allowPrerelease": preview or sdk.get("allowPrerelease", True)}
