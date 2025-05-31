import os
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [],
    "resources": [],
    "roles": [
        {
            "name": "Administrator",
            "description": "Full system access",
            "permissions": "all_permissions,view_analytics"
        },
        {
            "name": "StandardUser",
            "description": "Can make bookings and view resources",
            "permissions": "make_bookings,view_resources"
        }
    ],
    "users": [
        {
            "username": "admin",
            "email": "admin@example.com",
            "password_hash": "pbkdf2:sha256:1000000$REXEh8S9ozI9C8Ry$2112ba94eeedbd023af5774e6b4a1aa1b895b93c99df14eb9d0bf8b8a5a90df3",
            "is_admin": True,
            "roles": ["Administrator"]
        },
        {
            "username": "user",
            "email": "user@example.com",
            "password_hash": "pbkdf2:sha256:1000000$GL7ffbfkTYPtoSc6$3c2e6b66aea688d6b2444ec7735f78ca2513bc40d17d15ac9c3254d23ee2ce45",
            "is_admin": False,
            "roles": ["StandardUser"]
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


def ensure_required_keys(cfg):
    """Ensure top-level keys exist in the configuration."""
    for key in ("floor_maps", "resources", "roles", "users"):
        cfg.setdefault(key, [])


def import_admin_data(db, User, Role, FloorMap, Resource):
    """Import admin-related records from JSON if none exist."""
    cfg = load_config()
    ensure_required_keys(cfg)
    if not db.session.query(User.id).first():
        # Import roles
        for r in cfg.get("roles", []):
            role = Role(name=r.get("name"), description=r.get("description"), permissions=r.get("permissions"))
            db.session.add(role)
        db.session.commit()

        # Import users
        from werkzeug.security import generate_password_hash
        for u in cfg.get("users", []):
            user = User(
                username=u.get("username"),
                email=u.get("email"),
                password_hash=u.get("password_hash") or generate_password_hash("admin", method="pbkdf2:sha256"),
                is_admin=u.get("is_admin", False),
            )
            db.session.add(user)
            for role_name in u.get("roles", []):
                role = Role.query.filter_by(name=role_name).first()
                if role:
                    user.roles.append(role)
        db.session.commit()

        # Import floor maps
        for fm in cfg.get("floor_maps", []):
            fmap = FloorMap(
                name=fm.get("name"),
                image_filename=fm.get("image_filename"),
                location=fm.get("location"),
                floor=fm.get("floor"),
            )
            db.session.add(fmap)
            db.session.flush()
            for res in fm.get("resources", []):
                resource = Resource(
                    name=res.get("name"),
                    capacity=res.get("capacity"),
                    equipment=res.get("equipment"),
                    map_coordinates=json.dumps(res.get("map_coordinates")),
                    status=res.get("status", "published"),
                    floor_map_id=fmap.id,
                )
                db.session.add(resource)
        db.session.commit()


def export_admin_config(db, User, Role, FloorMap, Resource):
    """Export admin data from the database to the JSON configuration file."""
    cfg = load_config()
    ensure_required_keys(cfg)
    cfg["roles"] = [
        {"name": r.name, "description": r.description, "permissions": r.permissions}
        for r in Role.query.all()
    ]
    cfg["users"] = [
        {
            "username": u.username,
            "email": u.email,
            "password_hash": u.password_hash,
            "is_admin": u.is_admin,
            "roles": [role.name for role in u.roles],
        }
        for u in User.query.all()
    ]
    cfg["floor_maps"] = []
    for fm in FloorMap.query.all():
        fm_entry = {
            "name": fm.name,
            "image_filename": fm.image_filename,
            "location": fm.location,
            "floor": fm.floor,
            "resources": [],
        }
        for res in Resource.query.filter_by(floor_map_id=fm.id).all():
            fm_entry["resources"].append(
                {
                    "name": res.name,
                    "capacity": res.capacity,
                    "equipment": res.equipment,
                    "map_coordinates": json.loads(res.map_coordinates or "{}"),
                    "status": res.status,
                }
            )
        cfg["floor_maps"].append(fm_entry)

    save_config(cfg)

