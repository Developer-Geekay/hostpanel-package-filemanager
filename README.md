# hostpanel-files

Premium File Manager plugin for [HostPanel](https://github.com/Developer-Geekay/hostpanel).

Provides dynamic sidebar folder tree navigation, breadcrumbs navigation, visual grid lists of directories, empty states, and dynamic CDNs loading of **Ace Editor** for premium syntax-highlighted code editing. Includes built-in Zip compress and decompress (Unzip) operations with strict safe-path validation.

## Features

- **Folder Tree:** Recursive dynamic folder listing using `/cpanelapi/files/tree`.
- **Breadcrumbs:** Fast directory jumps (`Home / home / testuser / public_html`).
- **Code Editor:** Dynamic loading of Ace Editor tomorrow_night theme, supporting multiple language syntaxes (JavaScript, HTML, CSS, Python, Bash, PHP, Markdown, JSON, etc.) automatically matching the active file extension.
- **Archive Operations:** Zip packing of directories and Zip Slip protected extraction.
- **Standard HostPanel Aesthetics:** Inherits and integrates 100% with the native dashboard theme variables (`tokens.css` and `components.css`) with zero duplicate styling.

## Install

From the HostPanel Package Manager UI, upload `hostpanel-files-1.0.0.zip`, or manually:

```bash
pip install -e plugin/
```

## Structure

```
├── bin/            # Empty bundled binaries
├── conf/           # Config templates
├── service/        # Daemon systemd services
├── sudoers/        # Visudoers config files
├── plugin/         # Backend setuptools Python package
└── frontend/       # Preact HTM single-file plugin
```

## Build

To build the package `.zip` file for HostPanel package manager:

```bash
bash build.sh
```

This will output `hostpanel-files-1.0.0.zip`.

## License

MIT
