import os
import json

# Default hashed passwords for sample users
ADMIN_HASH = (
    "pbkdf2:sha256:1000000$xc0Zq25M8zJA4unr$ac2921dc12b8592876eee09f6fdf44524949f63ccfa02edc328604fae5d45387"
)
USER_HASH = (
    "pbkdf2:sha256:1000000$X2esCUQh5qZCkHw5$c19af4300a124363c10726e483fecbc7c3fc7a027be2a746b17a9e11c4b78fbc"
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')

DEFAULT_CONFIG = {
    "floor_maps": [],
    "resources": [],
    "roles": [
        {
            "id": 1,
            "name": "Administrator",
            "description": "Full system access",
            "permissions": "all_permissions,view_analytics",
        },
        {
            "id": 2,
            "name": "StandardUser",
            "description": "Can make bookings and view resources",
            "permissions": "make_bookings,view_resources",
        },
    ],
    "users": [
        {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "password_hash": ADMIN_HASH,
            "is_admin": True,
            "roles": [1],
        },
        {
            "id": 2,
            "username": "user",
            "email": "user@example.com",
            "password_hash": USER_HASH,
            "is_admin": False,
            "roles": [2],
        },
    ],
}


def ensure_default_keys(data):
    """Ensure all expected keys exist in the configuration."""
    if data is None:
        data = {}
    for key, value in DEFAULT_CONFIG.items():
        data.setdefault(key, json.loads(json.dumps(value)))
    return data

def get_config_path():
    return CONFIG_FILE


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        return ensure_default_keys({})
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ensure_default_keys(data)
    except Exception:
        return ensure_default_keys({})


def save_config(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(ensure_default_keys(data), f, indent=2)


def import_admin_data(db, User, Role):
    """Import users and roles from the JSON configuration into the database."""
    cfg = load_config()

    role_map = {}
    for r in cfg.get('roles', []):
        role = Role(name=r['name'], description=r.get('description'), permissions=r.get('permissions', ''))
        db.session.add(role)
        db.session.flush()
        role_map[r.get('id', role.id)] = role

    for u in cfg.get('users', []):
        user = User(username=u['username'], email=u['email'], password_hash=u.get('password_hash', ''), is_admin=u.get('is_admin', False))
        db.session.add(user)
        db.session.flush()
        for rid in u.get('roles', []):
            role = role_map.get(rid)
            if role:
                user.roles.append(role)

    db.session.commit()


def export_admin_data(db, User, Role):
    """Write users and roles from the database to the JSON configuration."""
    cfg = load_config()
    cfg['roles'] = [
        {
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'permissions': r.permissions,
        }
        for r in Role.query.all()
    ]
    cfg['users'] = [
        {
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'password_hash': u.password_hash,
            'is_admin': u.is_admin,
            'roles': [role.id for role in u.roles],
        }
        for u in User.query.all()
    ]
    save_config(cfg)
