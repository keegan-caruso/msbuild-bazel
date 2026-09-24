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

def global_json_version(text):
    """Read an exact SDK pin, rejecting selection behavior we cannot honor.

    Args:
        text: Contents of the explicitly declared global.json file.

    Returns:
        The exact SDK version requested by the file.
    """
    data = json.decode(_json_comments(text))
    if type(data) != "dict" or type(data.get("sdk")) != "dict":
        fail("global.json requires an sdk object with an exact version")
    for key in data:
        if key not in ["sdk", "$schema"]:
            fail("Unsupported global.json field: " + key + "; declare non-SDK behavior explicitly in Bazel")
    sdk = data["sdk"]
    for key in sdk:
        if key not in ["version", "rollForward", "allowPrerelease", "errorMessage"]:
            fail("Unsupported global.json sdk field: " + key)
    version = sdk.get("version")
    if type(version) != "string" or not version:
        fail("global.json requires sdk.version")
    if sdk.get("rollForward", "patch") not in ["disable", "patch"]:
        fail("global.json rollForward must be disable or patch; Bazel acquires the exact pinned SDK")
    if type(sdk.get("allowPrerelease", True)) != "bool":
        fail("global.json sdk.allowPrerelease must be Boolean")
    if type(sdk.get("errorMessage", "")) != "string":
        fail("global.json sdk.errorMessage must be a string")
    if "-" in version and not sdk.get("allowPrerelease", True):
        fail("global.json disallows the requested prerelease SDK")
    return version
