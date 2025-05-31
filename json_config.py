import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [],
    "resources": [],
    "users": [],
    "permissions": []
}

def get_config_path():
    return CONFIG_FILE


def load_config():
    """Load the admin configuration JSON ensuring all keys exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    data = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update({k: loaded.get(k, data[k]) for k in DEFAULT_CONFIG})
        except Exception:
            pass
    return data


def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
