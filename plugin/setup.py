from setuptools import setup, find_packages

setup(
    name="hostpanel-files",
    version="1.0.6",
    packages=find_packages(),
    install_requires=["fastapi", "pydantic"],
    entry_points={
        "hostpanel.modules": [
            "files = hostpanel_filemanager.plugin"
        ],
        "hostpanel.setup": [
            "hostpanel-files = hostpanel_filemanager.lifecycle:on_install"
        ],
        "hostpanel.lifecycle": [
            "hostpanel-files = hostpanel_filemanager.lifecycle:pre_uninstall"
        ],
    }
)
