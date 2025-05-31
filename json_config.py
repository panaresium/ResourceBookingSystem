import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [],
    "resources": [],
    "users": [],
    "roles": [],
    "permissions": []
}


def ensure_defaults(data):
    """Ensure all expected keys exist in the provided config."""
    if data is None:
        data = {}
    for key, default in DEFAULT_CONFIG.items():
        data.setdefault(key, [] if isinstance(default, list) else default)
    return data

def get_config_path():
    return CONFIG_FILE


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return ensure_defaults(data)
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    cleaned = ensure_defaults(data)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2)
