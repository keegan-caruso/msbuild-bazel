"""Stream Bazel's concatenated, pretty-printed JSON spawn records."""
import json

def actions(path):
    lines=[]
    with path.open() as source:
        for line in source:
            # Bazel does not put a newline between records: a root closing
            # brace is commonly immediately followed by the next opening brace.
            if line.startswith('}'):
                lines.append('}')
                yield json.loads(''.join(lines))
                lines=[line[1:]] if line[1:].strip() else []
            else:
                lines.append(line)
    if ''.join(lines).strip():
        raise ValueError('Incomplete or unrecognized Bazel JSON spawn log')
