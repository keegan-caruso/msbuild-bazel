"""Pinned Linux ARM64 native test data; no worker-installed fonts or Fontconfig."""
import hashlib
import json
from pathlib import Path
import shutil

FONTCONFIG = '''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir prefix="relative">native-tests/fonts</dir>
  <cachedir prefix="relative">native-tests/cache</cachedir>
  <match target="pattern"><edit name="family" mode="append_last"><string>DejaVu Sans</string></edit></match>
  <alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>serif</family><prefer><family>DejaVu Serif</family></prefer></alias>
  <alias><family>monospace</family><prefer><family>DejaVu Sans Mono</family></prefer></alias>
  <alias><family>Arial</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>Times New Roman</family><prefer><family>DejaVu Serif</family></prefer></alias>
  <alias><family>Courier New</family><prefer><family>DejaVu Sans Mono</family></prefer></alias>
</fontconfig>
'''


def prepare(prepared):
    root = prepared / 'native-tests'
    declarations = {}
    inventory = json.loads((prepared / 'inventory.json').read_text())
    headless = any(r['entry'] and 'Headless' in r['properties']['AssemblyName'] for r in inventory)
    rows = [row for row in json.loads(Path(__file__).with_name('native-inputs.json').read_text()) if headless or not row.get('headlessOnly')]

    for row in rows:
        source = Path(row['source'])
        assert source.exists(), ('Missing pinned Ubuntu ARM64 test input', source)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row['sha256'], ('Native test input version mismatch', source)
        target = root / row['destination']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    root.mkdir(exist_ok=True)
    (root / 'fonts.conf').write_text(FONTCONFIG)
    # VSTest sets the raw test host's cwd beside its assembly too.
    for row in json.loads((prepared / 'inventory.json').read_text()):
        if row['entry'] and row['properties']['AssemblyName'].startswith(('Avalonia.Skia.', 'Avalonia.Headless.', 'Qualification.Headless.')):
            raw_link = prepared / 'source' / Path(row['project']).parent / 'bin/Release' / row['framework'] / 'native-tests'
            if not raw_link.exists():
                raw_link.symlink_to(root, target_is_directory=True)
            assert raw_link.is_symlink() and raw_link.resolve() == root
    for relative in [row['destination'] for row in rows] + ['fonts.conf']:
        target = prepared / 'bazel/upstream/native-tests' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
        declarations['native-tests/' + relative] = 'tests/native-tests/' + relative
    return declarations, dict(LD_LIBRARY_PATH=str(root), FONTCONFIG_PATH='native-tests', FONTCONFIG_FILE='fonts.conf')
