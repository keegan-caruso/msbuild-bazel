"""Native test layout built from Bazel-acquired, pinned Linux ARM64 packages."""
import json
from pathlib import Path
import shutil
from native_repository import acquire

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


def prepare(prepared, fixture):
    root, declarations = acquire(prepared, fixture)
    (root / 'fonts.conf').write_text(FONTCONFIG)
    # VSTest sets the raw test host's cwd beside its assembly too.
    for row in json.loads((prepared / 'inventory.json').read_text()):
        if row['entry'] and row['properties']['AssemblyName'].startswith(('Avalonia.Skia.', 'Avalonia.Headless.', 'Qualification.Headless.')):
            raw_link = prepared / 'source' / Path(row['project']).parent / 'bin/Release' / row['framework'] / 'native-tests'
            if not raw_link.exists():
                raw_link.symlink_to(root, target_is_directory=True)
            assert raw_link.is_symlink() and raw_link.resolve() == root
    target = prepared / 'bazel/upstream/native-tests/fonts.conf'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'fonts.conf', target)
    declarations['native-tests/fonts.conf'] = 'tests/native-tests/fonts.conf'
    return declarations, dict(LD_LIBRARY_PATH=str(root), FONTCONFIG_PATH='native-tests', FONTCONFIG_FILE='fonts.conf')
