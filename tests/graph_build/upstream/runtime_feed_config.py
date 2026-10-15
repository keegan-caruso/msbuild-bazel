"""Pin the signed-package source ambiguity in the runtime qualification only."""
import xml.etree.ElementTree as ET


def pin_runtime_feeds(config):
    text = config.read_text()
    document = ET.fromstring(text)
    keys = [item.get('key') for item in document.findall('./packageSources/add')]
    assert 'dotnet-public' in keys
    mapping = ET.Element('packageSourceMapping')
    for key in keys:
        feed = ET.SubElement(mapping, 'packageSource', key=key)
        ET.SubElement(feed, 'package', pattern='*')
        if key == 'dotnet-public':
            ET.SubElement(feed, 'package', pattern='Microsoft.Diagnostics.NETCore.Client')
    existing = document.find('packageSourceMapping')
    if existing is not None:
        def rows(element):
            return [(item.get('key'), [package.get('pattern') for package in item]) for item in element]
        assert rows(existing) == rows(mapping), 'Unexpected runtime package-source mapping'
        return
    config.write_text(text.replace('</configuration>', ET.tostring(mapping, encoding='unicode') + '\n</configuration>'))
