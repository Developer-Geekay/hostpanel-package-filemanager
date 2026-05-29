from hostpanel_filemanager.files import router as filemanager_router

PLUGIN_MANIFEST = {
    "requires_core": [1, 0, 0],
    "nav_items": [
        {
            "nav_route":         "files",
            "nav_label":         "File Manager",
            "nav_icon":          "folder_open",
            "nav_section":       "hosting",
            "nav_section_label": "Hosting",
            "nav_section_order": 10,
            "admin_only":        False,
        },
    ],
}

routers = [filemanager_router]
