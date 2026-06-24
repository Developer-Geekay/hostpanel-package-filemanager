import logging
import subprocess

logger = logging.getLogger(__name__)


def on_install():
    """Ensure unzip and zip system packages are present — required for archive operations."""
    r = subprocess.run(
        ["sudo", "-n", "apt-get", "install", "-y", "unzip", "zip"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        logger.warning(
            f"File Manager: could not auto-install unzip/zip "
            f"(exit {r.returncode}): {(r.stderr + r.stdout).strip()}"
        )
    else:
        logger.info("File Manager: unzip and zip packages installed/verified")


def pre_uninstall(force: bool = False):
    """Teardown hook for hostpanel-files plugin."""
    logger.info("File Manager plugin: pre_uninstall completed")
