import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

# Default structure for the admin configuration JSON file.  The
# configuration keeps track of several admin managed objects in
# lists so that the data can be easily updated outside of the
# database and stored in Azure File Share.
#
# * ``floor_maps`` - floor map metadata with resource areas and
#   other configuration details.
# * ``resources``  - resource configuration details such as
#   capacity or equipment.
# * ``users``      - user configuration details for bulk import
#   or update.
# * ``permissions`` - role/permission mappings.
DEFAULT_CONFIG = {
    "floor_maps": [],
    "resources": [],
    "users": [],
    "permissions": []
    }

def get_config_path():
    return CONFIG_FILE


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:

            data = json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()
    for key, value in DEFAULT_CONFIG.items():
        data.setdefault(key, value.copy() if isinstance(value, list) else value)
    return data



def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
