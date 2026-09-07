"""Deterministic Starlark declarations for generated BUILD/MODULE files."""
import json


def value(item, indent=4):
    if isinstance(item, list):
        if len(item) <= 1:
            return '[' + ', '.join(value(v, indent) for v in item) + ']'
        return '[\n' + ''.join(' ' * (indent + 4) + value(v, indent + 4) + ',\n' for v in item) + ' ' * indent + ']'
    if isinstance(item, dict):
        if len(item) <= 1:
            return '{' + ', '.join(json.dumps(k) + ': ' + value(v, indent) for k, v in sorted(item.items())) + '}'
        return '{\n' + ''.join(' ' * (indent + 4) + json.dumps(k) + ': ' + value(v, indent + 4) + ',\n' for k, v in sorted(item.items())) + ' ' * indent + '}'
    if item is True: return 'True'
    if item is False: return 'False'
    if item is None: return 'None'
    return json.dumps(item, ensure_ascii=False)


def call(rule, **attrs):
    # Buildifier puts common rule attributes first, followed by alphabetic attrs.
    first = ['name', 'size', 'timeout', 'testonly', 'srcs']
    keys = [k for k in first if k in attrs] + sorted(k for k in attrs if k not in first)
    return '\n' + rule + '(\n' + ''.join('    ' + k + ' = ' + value(attrs[k]) + ',\n' for k in keys) + ')\n'
