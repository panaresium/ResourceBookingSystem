import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [
        {
            "id": 1,
            "name": "Main Office",
            "image_filename": "sample_map.png",
            "location": "HQ",
            "floor": "1"
        }
    ],
    "resources": [
        {
            "id": 1,
            "name": "Conference Room Alpha",
            "capacity": 10,
            "equipment": "Projector,Whiteboard,Teleconference",
            "tags": "large,video",
            "booking_restriction": None,
            "status": "published",
            "published_at": "2025-05-31T10:12:44Z",
            "allowed_user_ids": None,
            "floor_map_id": 1,
            "map_coordinates": None
        },
        {
            "id": 2,
            "name": "Meeting Room Beta",
            "capacity": 6,
            "equipment": "Teleconference,Whiteboard",
            "tags": "medium",
            "booking_restriction": "all_users",
            "status": "published",
            "published_at": "2025-05-31T10:12:44Z",
            "allowed_user_ids": "2,1",
            "floor_map_id": 1,
            "map_coordinates": None
        },
        {
            "id": 3,
            "name": "Focus Room Gamma",
            "capacity": 2,
            "equipment": "Whiteboard",
            "tags": "quiet",
            "booking_restriction": "admin_only",
            "status": "draft",
            "published_at": None,
            "allowed_user_ids": None,
            "floor_map_id": 1,
            "map_coordinates": None
        },
        {
            "id": 4,
            "name": "Quiet Pod Delta",
            "capacity": 1,
            "equipment": None,
            "tags": "quiet,small",
            "booking_restriction": None,
            "status": "draft",
            "published_at": None,
            "allowed_user_ids": None,
            "floor_map_id": 1,
            "map_coordinates": None
        },
        {
            "id": 5,
            "name": "Archived Room Omega",
            "capacity": 5,
            "equipment": "Old Projector",
            "tags": "archived",
            "booking_restriction": None,
            "status": "archived",
            "published_at": "2025-05-01T10:12:44Z",
            "allowed_user_ids": None,
            "floor_map_id": 1,
            "map_coordinates": None
        }
    ],
    "roles": [
        {
            "id": 1,
            "name": "Administrator",
            "description": "Full system access",
            "permissions": "all_permissions,view_analytics"
        },
        {
            "id": 2,
            "name": "StandardUser",
            "description": "Can make bookings and view resources",
            "permissions": "make_bookings,view_resources"
        }
    ],
    "users": [
        {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "password_hash": "pbkdf2:sha256:1000000$x9GksIQSoMAxLWOM$232c239484111feec94908903c9c272e56b328f407f00518daf33573e81a0aeb",
            "is_admin": True
        },
        {
            "id": 2,
            "username": "user",
            "email": "user@example.com",
            "password_hash": "pbkdf2:sha256:1000000$9tfGR8avTY83hRCj$56ca805582abfeee4c1835ae5e49cf26d30f05e799eaeb6214aa1ea4f185469f",
            "is_admin": False
        }
    ],
    "user_roles": [
        {"user_id": 1, "role_id": 1},
        {"user_id": 2, "role_id": 2}
    ],
    "resource_roles": [
        {"resource_id": 3, "role_id": 1},
        {"resource_id": 1, "role_id": 2},
        {"resource_id": 1, "role_id": 1},
        {"resource_id": 4, "role_id": 2}
    ]
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

    # Ensure all expected keys exist
    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in data:
            data[key] = value
            changed = True
    if changed:
        save_config(data)
    return data

def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
