from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import json # Required for Resource.map_coordinates if methods involving it are moved

# Assuming 'db' is initialized in 'extensions.py' and will be imported
# For example: from .extensions import db (if extensions.py is in the same package)
# Or: from extensions import db (if extensions.py is in PYTHONPATH and can be imported directly)
# For this task, we'll use `from extensions import db`
from extensions import db

# Association table for User and Role (Many-to-Many)
user_roles_table = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True)
)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    permissions = db.Column(db.Text, nullable=True)  # e.g., comma-separated: "edit_resource,delete_user"

    def __repr__(self):
        return f'<Role {self.name}>'

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    google_id = db.Column(db.String(200), nullable=True, unique=True)
    google_email = db.Column(db.String(200), nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    section = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    position = db.Column(db.String(100), nullable=True)
    facebook_id = db.Column(db.String(200), nullable=True, unique=True)
    instagram_id = db.Column(db.String(200), nullable=True, unique=True)

    roles = db.relationship('Role', secondary=user_roles_table,
                            backref=db.backref('users', lazy='dynamic'))

    def __repr__(self):
        return f'<User {self.username} (Admin: {self.is_admin})>'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_permission(self, permission):
        if self.is_admin: # Super admin (legacy) has all permissions
            return True
        # Check for 'all_permissions' in any role
        if any('all_permissions' in role.permissions.split(',') for role in self.roles if role.permissions):
            return True
        # Check for the specific permission string
        for role in self.roles:
            if role.permissions and permission in role.permissions.split(','):
                return True
        return False

class FloorMap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False, unique=True)
    location = db.Column(db.String(100), nullable=True)
    floor = db.Column(db.String(50), nullable=True)
    # New offset columns
    offset_x = db.Column(db.Integer, nullable=False, default=0)
    offset_y = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        # Consider adding offsets to repr if useful for debugging
        loc_floor = f"{self.location or 'N/A'} - Floor {self.floor}" if self.location or self.floor else ""
        return f"<FloorMap {self.name} ({loc_floor}) Offsets(x:{self.offset_x}, y:{self.offset_y})>"

class BookingSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    allow_past_bookings = db.Column(db.Boolean, default=False)
    max_booking_days_in_future = db.Column(db.Integer, nullable=True, default=None)
    allow_multiple_resources_same_time = db.Column(db.Boolean, default=False)
    max_bookings_per_user = db.Column(db.Integer, nullable=True, default=None)
    enable_check_in_out = db.Column(db.Boolean, default=False)
    past_booking_time_adjustment_hours = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<BookingSettings {self.id}>"

# Association table for Resource and Role (Many-to-Many for resource-specific role permissions)
resource_roles_table = db.Table('resource_roles',
    db.Column('resource_id', db.Integer, db.ForeignKey('resource.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True)
)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=True)
    equipment = db.Column(db.String(200), nullable=True)
    tags = db.Column(db.String(200), nullable=True)
    booking_restriction = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='draft')
    published_at = db.Column(db.DateTime, nullable=True)
    allowed_user_ids = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    is_under_maintenance = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_until = db.Column(db.DateTime, nullable=True)
    max_recurrence_count = db.Column(db.Integer, nullable=True)
    scheduled_status = db.Column(db.String(50), nullable=True)
    scheduled_status_at = db.Column(db.DateTime, nullable=True)
    floor_map_id = db.Column(db.Integer, db.ForeignKey('floor_map.id'), nullable=True)
    map_coordinates = db.Column(db.Text, nullable=True)

    bookings = db.relationship('Booking', backref='resource_booked', lazy=True, cascade="all, delete-orphan")
    floor_map = db.relationship('FloorMap', backref=db.backref('resources', lazy='dynamic'))
    roles = db.relationship('Role', secondary=resource_roles_table,
                            backref=db.backref('allowed_resources', lazy='dynamic'))

    def __repr__(self):
        return f"<Resource {self.name}>"

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    title = db.Column(db.String(100), nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checked_out_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='approved')
    recurrence_rule = db.Column(db.String(200), nullable=True)
    admin_deleted_message = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<Booking {self.title or self.id} for Resource {self.resource_id} from {self.start_time.strftime('%Y-%m-%d %H:%M')} to {self.end_time.strftime('%Y-%m-%d %H:%M')}>"

class WaitlistEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    resource = db.relationship('Resource')
    user = db.relationship('User')

    def __repr__(self):
        return f"<WaitlistEntry resource={self.resource_id} user={self.user_id}>"

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    username = db.Column(db.String(80), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)

    user = db.relationship('User')

    def __repr__(self):
        return f'<AuditLog {self.timestamp} - {self.username or "System"} - {self.action}>'
