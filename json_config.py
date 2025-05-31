import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [
        {
            "id": 1,
            "name": "Main Building",
            "image_filename": "sample_map.png",
            "location": "HQ",
            "floor": "1"
        }
    ],
    "resources": [
        {
            "id": 1,
            "name": "Conference Room",
            "capacity": 10,
            "equipment": "Projector",
            "tags": "large",
            "booking_restriction": None,
            "status": "published",
            "floor_map_id": 1,
            "map_coordinates": {
                "type": "rect",
                "x": 10,
                "y": 20,
                "width": 30,
                "height": 30
            }
        }
    ],
    "users": [
        {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "password": "admin",
            "is_admin": True,
            "roles": [1]
        },
        {
            "id": 2,
            "username": "user",
            "email": "user@example.com",
            "password": "userpass",
            "is_admin": False,
            "roles": [2]
        }
    ],
    "roles": [
        {
            "id": 1,
            "name": "Administrator",
            "description": "Full access",
            "permissions": "all_permissions"
        },
        {
            "id": 2,
            "name": "User",
            "description": "Standard user",
            "permissions": "book_resource"
        }
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
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()



def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def ensure_keys(data):
    """Ensure the configuration dictionary has all expected top-level keys."""
    for key, default_val in DEFAULT_CONFIG.items():
        data.setdefault(key, [] if isinstance(default_val, list) else default_val)
    return data


def import_admin_config():
    """Populate the database with data from the JSON config if empty."""
    from app import db, User, Role, Resource, FloorMap

    config = ensure_keys(load_config())

    if Role.query.count() == 0:
        for item in config.get("roles", []):
            role = Role(id=item.get("id"), name=item.get("name"),
                        description=item.get("description"),
                        permissions=item.get("permissions"))
            db.session.add(role)
        db.session.commit()

    if User.query.count() == 0:
        for item in config.get("users", []):
            user = User(id=item.get("id"), username=item.get("username"),
                        email=item.get("email"),
                        is_admin=item.get("is_admin", False))
            user.set_password(item.get("password", "changeme"))
            for rid in item.get("roles", []):
                role = Role.query.get(rid)
                if role:
                    user.roles.append(role)
            db.session.add(user)
        db.session.commit()

    if FloorMap.query.count() == 0:
        for item in config.get("floor_maps", []):
            fm = FloorMap(id=item.get("id"), name=item.get("name"),
                          image_filename=item.get("image_filename"),
                          location=item.get("location"),
                          floor=item.get("floor"))
            db.session.add(fm)
        db.session.commit()

    if Resource.query.count() == 0:
        for item in config.get("resources", []):
            r = Resource(id=item.get("id"), name=item.get("name"),
                         capacity=item.get("capacity"),
                         equipment=item.get("equipment"),
                         tags=item.get("tags"),
                         booking_restriction=item.get("booking_restriction"),
                         status=item.get("status", "draft"),
                         floor_map_id=item.get("floor_map_id"))
            coords = item.get("map_coordinates")
            if coords is not None:
                r.map_coordinates = json.dumps(coords)
            db.session.add(r)
        db.session.commit()


def export_admin_config():
    """Write admin data from the database to the JSON config file."""
    from app import db, User, Role, Resource, FloorMap

    config = ensure_keys(load_config())

    config["roles"] = [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "permissions": r.permissions,
        }
        for r in Role.query.all()
    ]

    config["users"] = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "password": None,
            "is_admin": u.is_admin,
            "roles": [role.id for role in u.roles],
        }
        for u in User.query.all()
    ]

    config["floor_maps"] = [
        {
            "id": fm.id,
            "name": fm.name,
            "image_filename": fm.image_filename,
            "location": fm.location,
            "floor": fm.floor,
        }
        for fm in FloorMap.query.all()
    ]

    config["resources"] = [
        {
            "id": res.id,
            "name": res.name,
            "capacity": res.capacity,
            "equipment": res.equipment,
            "tags": res.tags,
            "booking_restriction": res.booking_restriction,
            "status": res.status,
            "floor_map_id": res.floor_map_id,
            "map_coordinates": json.loads(res.map_coordinates)
            if res.map_coordinates
            else None,
        }
        for res in Resource.query.all()
    ]

    save_config(config)
