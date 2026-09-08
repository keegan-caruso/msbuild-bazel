"""Report potential MSBuild time inputs without evaluating projects or authorizing reuse."""
import argparse
import json
from pathlib import Path
import re
from xml.parsers import expat


RULES = {
    'wall-clock': re.compile(r'\$\(\s*\[System\.(?:DateTime|DateTimeOffset)\]\s*::\s*(?:Now|UtcNow|Today)\b', re.I),
    'elapsed-clock': re.compile(r'\$\(\s*\[System\.(?:Environment\]\s*::\s*TickCount(?:64)?|Diagnostics\.Stopwatch\]\s*::\s*GetTimestamp)\b', re.I),
    'file-timestamp': re.compile(r'\$\(\s*\[System\.IO\.(?:File|Directory)\]\s*::\s*Get(?:LastWriteTime|LastAccessTime|CreationTime)(?:Utc)?\b', re.I),
    'item-timestamp': re.compile(r'%\(\s*(?:[\w.-]+\.)?(?:ModifiedTime|CreatedTime|AccessedTime)\s*\)', re.I),
}
EXTENSIONS = {'.proj', '.csproj', '.vbproj', '.fsproj', '.props', '.targets'}


def unescape(value):
    return re.sub(r'%([0-9a-f]{2})', lambda match: chr(int(match[1], 16)), value, flags=re.I)


def scan(paths, *, follow_imports=True, contents=None):
    report = dict(schemaVersion=1, scope='msbuild-time-diagnostics', reuseEnabled=False,
                  eligibility='not-established', files=[], findings=[], coverageGaps=[], errors=[])
    seen = set()

    def visit(path):
        path = Path(path).resolve()
        if path in seen:
            return
        seen.add(path)
        if contents is None and path.suffix.lower() not in EXTENSIONS:
            report['errors'].append(dict(file=str(path), message='expected an MSBuild project or import file'))
            return
        parser = expat.ParserCreate(namespace_separator='}')
        stack, imports = [], []

        def location(node):
            targets = [ancestor['attrs'].get('Name', '') for ancestor in stack if ancestor['tag'] == 'Target']
            return dict(file=str(path), line=node['line'], element=node['tag'],
                        phase='target' if targets else 'evaluation', target=targets[-1] if targets else None,
                        conditions=[ancestor['attrs']['Condition'] for ancestor in stack if 'Condition' in ancestor['attrs']])

        def inspect(node, value, field):
            decoded = unescape(value)
            for rule, pattern in RULES.items():
                if pattern.search(decoded):
                    report['findings'].append(dict(location(node), rule=rule, field=field,
                                                   expression=value.strip(), disposition='potential-dependency'))

        def start(name, attrs):
            tag = name.split('}')[-1]
            node = dict(tag=tag, attrs=attrs, line=parser.CurrentLineNumber, text=[])
            stack.append(node)
            for name, value in attrs.items():
                inspect(node, value, '@' + name)
            if tag == 'Project' and attrs.get('Sdk') or tag == 'Sdk':
                report['coverageGaps'].append(dict(location(node), reason='implicit SDK imports are not resolved; supply files explicitly'))
            if tag in ('Exec', 'UsingTask'):
                report['coverageGaps'].append(dict(location(node), reason='external process or task implementation is not analyzed'))
            if tag == 'Import':
                imports.append((dict(location(node)), attrs))

        def end(name):
            node = stack[-1]
            inspect(node, ''.join(node['text']), 'text')
            stack.pop()

        def characters(value):
            if stack:
                stack[-1]['text'].append(value)

        def reject_doctype(*args):
            raise ValueError('DTD declarations are not supported')

        parser.StartElementHandler, parser.EndElementHandler = start, end
        parser.CharacterDataHandler = characters
        parser.StartDoctypeDeclHandler = reject_doctype
        try:
            parser.Parse(path.read_bytes() if contents is None else contents[path], True)
        except (OSError, expat.ExpatError, ValueError) as error:
            report['errors'].append(dict(file=str(path), message=str(error)))
            return
        report['files'].append(str(path))
        if not follow_imports:
            return
        for origin, attrs in imports:
            value = unescape(attrs.get('Project', ''))
            value = re.sub(r'\$\(MSBuildThisFileDirectory\)', lambda _: str(path.parent) + '/', value, flags=re.I)
            if attrs.get('Sdk') or not value or any(token in value for token in ('$(', '@(', '%(', '*', '?', ';')):
                report['coverageGaps'].append(dict(origin, reason='dynamic, wildcard or SDK import is unresolved', expression=value))
                continue
            imported = Path(value.replace('\\', '/'))
            if not imported.is_absolute():
                imported = path.parent / imported
            if not imported.is_file():
                report['coverageGaps'].append(dict(origin, reason='literal import is missing (condition not evaluated)', expression=value))
            else:
                # Keep the import edge context; conditions are not evaluated.
                report.setdefault('imports', []).append(dict(origin, importedFile=str(imported.resolve())))
                visit(imported)

    for path in paths:
        visit(path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--graph-request', type=Path, help='Scan project/import bytes from an existing GraphExport request and output')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.graph_request:
        if args.files:
            parser.error('files and --graph-request are mutually exclusive')
        from msbuild_graph_diagnostics import scan_graph
        report = scan_graph(args.graph_request)
    else:
        if not args.files:
            parser.error('supply files or --graph-request')
        report = scan(args.files)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
    return 2 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
