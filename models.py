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
    is_active = db.Column(db.Boolean, default=True, nullable=False) # Added for Flask-Login

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
    display_order = db.Column(db.Integer, nullable=True, default=0)
    is_published = db.Column(db.Boolean, nullable=True, default=True)
    description = db.Column(db.Text, nullable=True)
    map_data_json = db.Column(db.Text, nullable=True)

    def __repr__(self):
        # Consider adding offsets to repr if useful for debugging
        loc_floor = f"{self.location or 'N/A'} - Floor {self.floor}" if self.location or self.floor else ""
        return f"<FloorMap {self.name} ({loc_floor}) Offsets(x:{self.offset_x}, y:{self.offset_y})>"

class BookingSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    allow_past_bookings = db.Column(db.Boolean, default=False)
    max_booking_days_in_future = db.Column(db.Integer, nullable=True, default=14)
    allow_multiple_resources_same_time = db.Column(db.Boolean, default=False)
    max_bookings_per_user = db.Column(db.Integer, nullable=True, default=None)
    enable_check_in_out = db.Column(db.Boolean, default=False)
    past_booking_time_adjustment_hours = db.Column(db.Integer, default=0)
    check_in_minutes_before = db.Column(db.Integer, nullable=False, default=15)
    check_in_minutes_after = db.Column(db.Integer, nullable=False, default=15)
    checkin_reminder_minutes_before = db.Column(db.Integer, nullable=False, default=30)
    pin_auto_generation_enabled = db.Column(db.Boolean, default=True, nullable=False)
    pin_length = db.Column(db.Integer, default=6, nullable=False)
    pin_allow_manual_override = db.Column(db.Boolean, default=True, nullable=False)
    allow_check_in_without_pin = db.Column(db.Boolean, default=True, nullable=False, server_default='true')
    resource_checkin_url_requires_login = db.Column(db.Boolean, default=True, nullable=False)
    map_resource_opacity = db.Column(db.Float, nullable=False, default=0.7)
    enable_auto_checkout = db.Column(db.Boolean, default=False, nullable=False)
    auto_checkout_delay_minutes = db.Column(db.Integer, default=60, nullable=False)

    # Global offset in hours to adjust "current time" perception for booking logic.
    # Positive values make "now" seem earlier (allowing bookings further in the past if past bookings are enabled, or requiring future bookings to be even further out).
    # Negative values make "now" seem later (restricting past bookings more, or allowing future bookings sooner).
    global_time_offset_hours = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    auto_release_if_not_checked_in_minutes = db.Column(db.Integer, nullable=True, default=None)

    def to_dict(self):
        """Serializes the BookingSettings object to a dictionary."""
        return {
            'allow_past_bookings': self.allow_past_bookings,
            'max_booking_days_in_future': self.max_booking_days_in_future,
            'allow_multiple_resources_same_time': self.allow_multiple_resources_same_time,
            'max_bookings_per_user': self.max_bookings_per_user,
            'enable_check_in_out': self.enable_check_in_out,
            'past_booking_time_adjustment_hours': self.past_booking_time_adjustment_hours,
            'check_in_minutes_before': self.check_in_minutes_before,
            'check_in_minutes_after': self.check_in_minutes_after,
            'checkin_reminder_minutes_before': self.checkin_reminder_minutes_before,
            'pin_auto_generation_enabled': self.pin_auto_generation_enabled,
            'pin_length': self.pin_length,
            'pin_allow_manual_override': self.pin_allow_manual_override,
            'allow_check_in_without_pin': self.allow_check_in_without_pin,
            'resource_checkin_url_requires_login': self.resource_checkin_url_requires_login,
            'map_resource_opacity': self.map_resource_opacity,
            'enable_auto_checkout': self.enable_auto_checkout,
            'auto_checkout_delay_minutes': self.auto_checkout_delay_minutes,
            'global_time_offset_hours': self.global_time_offset_hours,
            'auto_release_if_not_checked_in_minutes': self.auto_release_if_not_checked_in_minutes
        }

    @classmethod
    def from_dict(cls, data, db_session):
        """
        Updates or creates a BookingSettings record from a dictionary.
        Assumes there's only one BookingSettings record.
        """
        if not data or not isinstance(data, dict):
            return None

        settings = db_session.query(cls).first()
        if not settings:
            settings = cls()
            db_session.add(settings)

        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
            # else:
                # Optionally log or handle keys in data that don't exist on the model
                # current_app.logger.warning(f"Key '{key}' in data not found on BookingSettings model.")
        return settings

    def __repr__(self):
        return f"<BookingSettings {self.id} auto_release_minutes={self.auto_release_if_not_checked_in_minutes}>"

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
    map_allowed_role_ids = db.Column(db.Text, nullable=True) # Stores JSON list of role IDs
    current_pin = db.Column(db.String(10), nullable=True, default=None)

    bookings = db.relationship('Booking', backref='resource_booked', lazy=True, cascade="all, delete-orphan")
    floor_map = db.relationship('FloorMap', backref=db.backref('resources', lazy='dynamic'))
    roles = db.relationship('Role', secondary=resource_roles_table,
                            backref=db.backref('allowed_resources', lazy='dynamic'))
    pins = db.relationship('ResourcePIN', backref='resource', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Resource {self.name}>"

class ResourcePIN(db.Model):
    __tablename__ = 'resource_pin' # Explicit table name
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    pin_value = db.Column(db.String(255), nullable=False) # Adjust length as needed
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.String(500), nullable=True)

    # Add a unique constraint for pin_value per resource_id
    __table_args__ = (db.UniqueConstraint('resource_id', 'pin_value', name='uq_resource_pin_value'),)

    def __repr__(self):
        return f'<ResourcePIN {self.pin_value} for Resource {self.resource_id}>'

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
    check_in_token = db.Column(db.String(255), nullable=True) # New field
    check_in_token_expires_at = db.Column(db.DateTime, nullable=True) # New field
    checkin_reminder_sent_at = db.Column(db.DateTime, nullable=True)
    last_modified = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # New fields for storing the intended local display time (HH:MM:SS) of the booking slot
    booking_display_start_time = db.Column(db.Time, nullable=True)
    booking_display_end_time = db.Column(db.Time, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('resource_id', 'start_time', 'end_time', name='uq_booking_resource_time'),
    )

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

class MaintenanceSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    schedule_type = db.Column(db.String(50), nullable=False)  # 'recurring_day', 'specific_day', 'date_range'
    day_of_week = db.Column(db.String(50), nullable=True)  # Comma-separated list of days (0-6)
    day_of_month = db.Column(db.Integer, nullable=True)  # 1-31
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_availability = db.Column(db.Boolean, default=False, nullable=False)
    resource_selection_type = db.Column(db.String(50), nullable=False)  # 'all', 'building', 'floor', 'specific'
    resource_ids = db.Column(db.Text, nullable=True)  # Comma-separated list of resource IDs
    building_id = db.Column(db.Integer, nullable=True)
    floor_id = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f'<MaintenanceSchedule {self.name}>'
