import sys
import os
import zipfile
import re

# Read version from setup.py
setup_path = os.path.join('plugin', 'setup.py')
with open(setup_path, 'r') as f:
    setup_content = f.read()

version_match = re.search(r"version\s*=\s*[\"']([^\"']+)[\"']", setup_content)
if not version_match:
    print("Error: Could not find version in plugin/setup.py")
    sys.exit(1)

version = version_match.group(1)
out = f"hostpanel-files-{version}.zip"

print(f"Building {out}...")
if os.path.exists(out):
    os.remove(out)

folders = ['plugin', 'bin', 'conf', 'service', 'sudoers', 'frontend']
skip_dirs = {'__pycache__'}

with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if file.endswith('.pyc') or file.startswith('.'):
                    continue
                filepath = os.path.join(root, file)
                # Ensure zip paths always use Unix-style forward slashes regardless of local OS
                arcname = filepath.replace(os.sep, '/')
                zf.write(filepath, arcname)

print(f"Done -> {out}")
