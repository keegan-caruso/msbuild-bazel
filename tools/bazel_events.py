"""Read concatenated JSON execution records emitted by Bazel."""
import json


def json_stream(path):
    text = path.read_text()
    decoder = json.JSONDecoder()
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        yield value
        text = text.lstrip()[end:]

