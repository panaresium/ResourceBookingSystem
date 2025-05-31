import os
import json
from datetime import datetime
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "admin_config.json")

DEFAULT_CONFIG = {
    "floor_maps": [],
    "roles": [
        {
            "name": "Administrator",
            "description": "Full system access",
            "permissions": "all_permissions,view_analytics",
        },
        {
            "name": "StandardUser",
            "description": "Can make bookings and view resources",
            "permissions": "make_bookings,view_resources",
        },
    ],
    "users": [
        {
            "username": "admin",
            "email": "admin@example.com",
            "password": "admin",
            "is_admin": True,
            "roles": ["Administrator"],
        },
        {
            "username": "user",
            "email": "user@example.com",
            "password": "userpass",
            "is_admin": False,
            "roles": ["StandardUser"],
        },
    ],
    "resources": [
        {
            "name": "Conference Room Alpha",
            "capacity": 10,
            "equipment": "Projector,Whiteboard,Teleconference",
            "tags": "large,video",
            "booking_restriction": None,
            "status": "published",
        },
        {
            "name": "Meeting Room Beta",
            "capacity": 6,
            "equipment": "Teleconference,Whiteboard",
            "tags": "medium",
            "booking_restriction": "all_users",
            "status": "published",
        },
        {
            "name": "Focus Room Gamma",
            "capacity": 2,
            "equipment": "Whiteboard",
            "tags": "quiet",
            "booking_restriction": "admin_only",
            "status": "draft",
        },
        {
            "name": "Quiet Pod Delta",
            "capacity": 1,
            "equipment": None,
            "tags": "quiet,small",
            "booking_restriction": None,
            "status": "draft",
        },
        {
            "name": "Archived Room Omega",
            "capacity": 5,
            "equipment": "Old Projector",
            "tags": "archived",
            "booking_restriction": None,
            "status": "archived",
        },
    ],
}


def get_config_path():
    return CONFIG_FILE


def _ensure_keys(data):
    for key in DEFAULT_CONFIG:
        data.setdefault(
            key, [] if isinstance(DEFAULT_CONFIG[key], list) else DEFAULT_CONFIG[key]
        )
    return data


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        return _ensure_keys(DEFAULT_CONFIG.copy())
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return _ensure_keys(data)
    except Exception:
        return _ensure_keys(DEFAULT_CONFIG.copy())


def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(_ensure_keys(data), f, indent=2)


def import_admin_config(session, config):
    """Create admin objects in the database from the given config."""
    from app import Role, User, Resource, FloorMap

    config = _ensure_keys(config)

    roles = {}
    for r in config.get("roles", []):
        role = Role(
            name=r.get("name"),
            description=r.get("description"),
            permissions=r.get("permissions"),
        )
        session.add(role)
        session.flush()
        roles[r["name"]] = role

    users = {}
    for u in config.get("users", []):
        user = User(
            username=u.get("username"),
            email=u.get("email"),
            is_admin=u.get("is_admin", False),
        )
        pwd = u.get("password")
        pwd_hash = generate_password_hash(pwd) if pwd else u.get("password_hash")
        user.password_hash = pwd_hash
        session.add(user)
        session.flush()
        for rname in u.get("roles", []):
            if rname in roles:
                user.roles.append(roles[rname])
        users[u["username"]] = user

    maps = {}
    for m in config.get("floor_maps", []):
        fm = FloorMap(
            name=m.get("name"),
            image_filename=m.get("image_filename"),
            location=m.get("location"),
            floor=m.get("floor"),
        )
        session.add(fm)
        session.flush()
        maps[m.get("name")] = fm

    for r in config.get("resources", []):
        fm = maps.get(r.get("floor_map"))
        coords = r.get("coordinates")
        coords_json = json.dumps(coords) if isinstance(coords, dict) else None
        res = Resource(
            name=r.get("name"),
            capacity=r.get("capacity"),
            equipment=r.get("equipment"),
            tags=r.get("tags"),
            booking_restriction=r.get("booking_restriction"),
            status=r.get("status", "draft"),
            published_at=datetime.utcnow() if r.get("status") == "published" else None,
            allowed_user_ids=r.get("allowed_user_ids"),
            image_filename=r.get("image_filename"),
            floor_map_id=fm.id if fm else None,
            map_coordinates=coords_json,
        )
        session.add(res)

    session.commit()


def export_admin_config(session):
    """Dump admin objects from the database into JSON config."""
    from app import Role, User, Resource, FloorMap

    data = {
        "floor_maps": [],
        "roles": [],
        "users": [],
        "resources": [],
    }

    for fm in session.query(FloorMap).all():
        data["floor_maps"].append(
            {
                "name": fm.name,
                "image_filename": fm.image_filename,
                "location": fm.location,
                "floor": fm.floor,
            }
        )

    for role in session.query(Role).all():
        data["roles"].append(
            {
                "name": role.name,
                "description": role.description,
                "permissions": role.permissions,
            }
        )

    for user in session.query(User).all():
        data["users"].append(
            {
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
                "password_hash": user.password_hash,
                "roles": [r.name for r in user.roles],
            }
        )

    for res in session.query(Resource).all():
        coords = None
        if res.map_coordinates:
            try:
                coords = json.loads(res.map_coordinates)
            except Exception:
                coords = None
        data["resources"].append(
            {
                "name": res.name,
                "capacity": res.capacity,
                "equipment": res.equipment,
                "tags": res.tags,
                "booking_restriction": res.booking_restriction,
                "status": res.status,
                "image_filename": res.image_filename,
                "allowed_user_ids": res.allowed_user_ids,
                "floor_map": res.floor_map.name if res.floor_map else None,
                "coordinates": coords,
            }
        )

    save_config(data)
