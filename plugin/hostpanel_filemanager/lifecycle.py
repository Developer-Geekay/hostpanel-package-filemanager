import logging

logger = logging.getLogger(__name__)

def on_install():
    """Setup hook for hostpanel-files plugin."""
    logger.info("File Manager plugin: on_install completed")

def pre_uninstall(force: bool = False):
    """Teardown hook for hostpanel-files plugin."""
    logger.info("File Manager plugin: pre_uninstall completed")
