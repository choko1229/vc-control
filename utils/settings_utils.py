# utils/settings_utils.py

import settings

def reload_settings():
    from importlib import reload
    reload(settings)
    return settings
