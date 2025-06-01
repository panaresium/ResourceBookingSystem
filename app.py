from flask import Flask, jsonify, render_template, request, url_for, redirect, session, Blueprint, has_request_context # Added Blueprint and has_request_context
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text  # Add this and for WAL pragma setup
from datetime import datetime, date, timedelta, time, timezone # Ensure all are here
import os
import uuid # For generating unique task IDs
import json # For serializing coordinates
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # For User model and init_db
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth # Added for Google Sign-In

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
import pathlib # For finding the client_secret.json file path
import logging # Added for logging
from functools import wraps # For permission_required decorator
from flask import abort # For permission_required decorator
from flask import g  # For storing current locale
from flask_wtf.csrf import CSRFProtect, CSRFError # For CSRF protection
from flask_socketio import SocketIO
# import urllib # Not strictly needed for the simplified list_routes

try:
    from azure_backup import (
        save_floor_map_to_share,
        backup_if_changed,
        restore_from_share,
        create_full_backup,       # Added
        list_available_backups,   # Added
        restore_full_backup,      # Added
        verify_backup_set         # Added for health checks
    )
    import azure_backup # Import the module itself to access constants like FLOOR_MAP_UPLOADS
except Exception:
    save_floor_map_to_share = None
    backup_if_changed = None
    restore_from_share = None
    create_full_backup = None     # Added fallback
    list_available_backups = None # Added fallback
    restore_full_backup = None    # Added fallback
    verify_backup_set = None      # Added fallback
    azure_backup = None           # Added fallback for the module itself

# Attempt to import APScheduler; provide a basic fallback if unavailable
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    apscheduler_available = True
except ImportError:  # pragma: no cover - fallback if APScheduler isn't installed
    apscheduler_available = False

    class BackgroundScheduler:  # Minimal fallback implementation
        def __init__(self, *args, **kwargs):
            self.jobs = []

        def add_job(self, func, trigger=None, minutes=0, **kwargs):
            self.jobs.append((func, minutes))

        def start(self):
            import threading, time

            def run_job(job_func, interval):
                while True:
                    time.sleep(interval * 60)
                    try:
                        job_func()
                    except Exception:
                        logging.exception("Error in fallback scheduler job")

            for func, minutes in self.jobs:
                t = threading.Thread(target=run_job, args=(func, minutes), daemon=True)
                t.start()


# Attempt to import Flask-Mail; provide a fallback if unavailable
try:
    from flask_mail import Mail, Message
    mail_available = True
except ImportError:  # pragma: no cover - fallback for environments without Flask-Mail
    mail_available = False

    class Mail:
        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, app):
            pass

        def send(self, message):
            # No-op if Flask-Mail isn't installed
            pass

    class Message:
        def __init__(self, subject='', recipients=None, body=''):
            self.subject = subject
            self.recipients = recipients or []
            self.body = body

mail = Mail() # Define global mail object

# Base directory of the app - project root
basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'floor_map_uploads')
RESOURCE_UPLOAD_FOLDER = os.path.join(basedir, 'static', 'resource_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure the data directory exists (it should be created by init_setup.py)
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__, template_folder='templates', static_folder='static')
socketio = SocketIO(app)

# --- Simple JSON-based translation system ---
class SimpleTranslator:
    def __init__(self, translations_dir='locales', default_locale='en'):
        self.translations_dir = os.path.join(basedir, translations_dir)
        self.default_locale = default_locale
        self.translations = {}
        self._load_translations()

    def _load_translations(self):
        if not os.path.isdir(self.translations_dir):
            return
        for fname in os.listdir(self.translations_dir):
            if fname.endswith('.json'):
                code = fname.rsplit('.', 1)[0]
                path = os.path.join(self.translations_dir, fname)
                with open(path, 'r', encoding='utf-8') as f:
                    try:
                        self.translations[code] = json.load(f)
                    except Exception:
                        self.translations[code] = {}

    def gettext(self, text, lang=None):
        lang = lang or self.default_locale
        return self.translations.get(lang, {}).get(text, text)

translator = SimpleTranslator()

def _(text):
    lang = get_locale() if has_request_context() else translator.default_locale
    return translator.gettext(text, lang)

app.jinja_env.globals['_'] = _

# Define locale selector function first
def get_locale():
    # Try to get language from query parameter first
    lang_query = request.args.get('lang')
    if lang_query and lang_query in app.config.get('LANGUAGES', ['en']): # app needs to be in scope or passed
        return lang_query
    
    # Attempt to get language from user's session (if stored there)
    # user_lang = session.get('language') 
    # if user_lang and user_lang in app.config.get('LANGUAGES', ['en']):
    #    return user_lang

    # Fallback to Accept-Languages header
    # Ensure 'app' is accessible here if app.config is used, or pass 'app' if necessary.
    # For now, assume 'app' is in scope as it was in the original.
    return request.accept_languages.best_match(app.config.get('LANGUAGES', ['en']))

# Set locale on `g` and provide languages to templates
@app.before_request
def set_locale():
    g.locale = get_locale()

@app.context_processor
def inject_languages():
    return {'available_languages': app.config.get('LANGUAGES', ['en'])}

# Configurations
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESOURCE_UPLOAD_FOLDER'] = RESOURCE_UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key_123!@#') # Ensure SECRET_KEY is set from env or default

# Initialize CSRF Protection - AFTER app.config['SECRET_KEY'] is set
csrf = CSRFProtect(app)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    app.logger.warning(f"CSRF error encountered: {e.description}")
    return jsonify({'error': e.description, 'type': 'CSRF_ERROR'}), 400

# Localization configuration
app.config['LANGUAGES'] = ['en', 'es', 'th']

# Google OAuth Configuration - Recommended to use environment variables
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER')
app.config['GOOGLE_DISCOVERY_URL'] = "https://accounts.google.com/.well-known/openid-configuration"

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['RESOURCE_UPLOAD_FOLDER']):
    os.makedirs(app.config['RESOURCE_UPLOAD_FOLDER'])
if restore_from_share:
    try:
        restore_from_share()
    except Exception:
        app.logger.exception('Failed to restore data from Azure File Share')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'AZURE_SQL_CONNECTION_STRING',
    os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(DATA_DIR, 'site.db'))
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # silence the warning

# Flask-Mail configuration (defaults can be overridden with environment variables)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'localhost')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 25))
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', '1', 'yes']
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', '1', 'yes']
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'] or 'noreply@example.com')

# Initialize Flask-Mail if available
if mail_available:
    mail.init_app(app)

# Booking check-in configuration
app.config['CHECK_IN_GRACE_MINUTES'] = int(os.environ.get('CHECK_IN_GRACE_MINUTES', '15'))
app.config['AUTO_CANCEL_CHECK_INTERVAL_MINUTES'] = int(os.environ.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', '5'))
app.config['AZURE_BACKUP_INTERVAL_MINUTES'] = int(os.environ.get('AZURE_BACKUP_INTERVAL_MINUTES', '60'))

# Basic Logging Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
# For Flask's built-in logger, you might configure it further if needed,
# but basicConfig provides a good default if running app.py directly.
# app.logger.setLevel(logging.INFO) # Example if using Flask's logger predominantly

# OAuth 2.0 setup
# Note: client_secret.json is not used directly by google-auth-oauthlib Flow if client_id and client_secret are set in config.
# However, if you were to use it, this is how you might define its path:
# CLIENT_SECRET_FILE = os.path.join(pathlib.Path(__file__).parent, 'client_secret.json') 

# OAuth Scopes, request email and profile
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']

def get_google_flow():
    redirect_uri_dynamic = url_for('login_google_callback', _external=True)
    return Flow.from_client_config(
        client_config={'web': {
            'client_id': app.config['GOOGLE_CLIENT_ID'],
            'client_secret': app.config['GOOGLE_CLIENT_SECRET'],
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri_dynamic], # Use dynamic URI
            'javascript_origins': ['http://127.0.0.1:5000'] # Or your app's origin - this might also need to be dynamic in a real-world scenario
        }},
        scopes=SCOPES,
        redirect_uri=redirect_uri_dynamic # Use dynamic URI
    )

db = SQLAlchemy(app)

# Configure SQLite pragmas (e.g., WAL mode) on the first request
_sqlite_configured = False


def configure_sqlite_pragmas():
    """Apply WAL-related pragmas for SQLite databases once."""
    global _sqlite_configured
    if _sqlite_configured:
        return
    _sqlite_configured = True
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        try:
            engine = db.engine
            if hasattr(engine, "execute"):
                engine.execute(text("PRAGMA journal_mode=WAL"))
                engine.execute(text("PRAGMA synchronous=NORMAL"))
                engine.execute(text("PRAGMA busy_timeout=30000"))
            else:
                with engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL"))
                    conn.execute(text("PRAGMA synchronous=NORMAL"))
                    conn.execute(text("PRAGMA busy_timeout=30000"))
            app.logger.info(
                "SQLite database configured for WAL mode and related settings"
            )
        except Exception:
            app.logger.exception("Failed to configure SQLite pragmas")


@app.before_request
def _ensure_sqlite_configured():
    configure_sqlite_pragmas()


# Blueprint for analytics routes
analytics_bp = Blueprint('analytics', __name__, url_prefix='/admin/analytics')


# Authlib OAuth 2.0 Client Setup
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url=app.config['GOOGLE_DISCOVERY_URL'],
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'serve_login'
login_manager.login_message_category = 'info'
# Example of wrapping a message that Flask-Login might use.
# Note: This specific message is often configured directly in Flask-Login,
# but if it were a custom message, this is how you'd wrap it.
login_manager.login_message = 'Please log in to access this page.'

@login_manager.unauthorized_handler
def unauthorized_callback():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized'}), 401
    return redirect(url_for('serve_login', next=request.url))

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

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
    email = db.Column(db.String(120), unique=True, nullable=False) # Optional for now, but good practice
    password_hash = db.Column(db.String(256), nullable=False) # Increased length for potentially longer hashes
    is_admin = db.Column(db.Boolean, default=False, nullable=False) # Kept for now
    google_id = db.Column(db.String(200), nullable=True, unique=True)
    google_email = db.Column(db.String(200), nullable=True)
    
    roles = db.relationship('Role', secondary=user_roles_table,
                            backref=db.backref('users', lazy='dynamic'))

    def __repr__(self):
        return f'<User {self.username} (Admin: {self.is_admin})>'

    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
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
    image_filename = db.Column(db.String(255), nullable=False, unique=True) # Store unique filename
    location = db.Column(db.String(100), nullable=True)
    floor = db.Column(db.String(50), nullable=True)

    def __repr__(self):
        loc_floor = f"{self.location or 'N/A'} - Floor {self.floor}" if self.location or self.floor else ""
        return f"<FloorMap {self.name} ({loc_floor})>"

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

    image_filename = db.Column(db.String(255), nullable=True)  # <-- Add this line

    is_under_maintenance = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_until = db.Column(db.DateTime, nullable=True)

    # Maximum number of occurrences allowed when creating recurring bookings.
    max_recurrence_count = db.Column(db.Integer, nullable=True)

    # Scheduled status change fields
    scheduled_status = db.Column(db.String(50), nullable=True)
    scheduled_status_at = db.Column(db.DateTime, nullable=True)

    floor_map_id = db.Column(db.Integer, db.ForeignKey('floor_map.id'), nullable=True)
    map_coordinates = db.Column(db.Text, nullable=True) # To store JSON like {'type':'rect', 'x':10, 'y':20, 'width':50, 'height':30}
    
    # Relationships
    bookings = db.relationship('Booking', backref='resource_booked', lazy=True, cascade="all, delete-orphan")
    floor_map = db.relationship('FloorMap', backref=db.backref('resources', lazy='dynamic')) # Optional but useful
    
    # RBAC: Many-to-many relationship for roles that can book/access this resource
    roles = db.relationship('Role', secondary=resource_roles_table,
                            backref=db.backref('allowed_resources', lazy='dynamic'))

    def __repr__(self):
        return f"<Resource {self.name}>"

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=True)  # Placeholder for user
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    title = db.Column(db.String(100), nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checked_out_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='approved')
    recurrence_rule = db.Column(db.String(200), nullable=True)

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # User performing action
    username = db.Column(db.String(80), nullable=True) # Denormalized for easy display
    action = db.Column(db.String(100), nullable=False) # e.g., "LOGIN", "CREATE_USER"
    details = db.Column(db.Text, nullable=True) # e.g., "User admin logged in"

    user = db.relationship('User') # Optional, for easier access to user object if needed

    def __repr__(self):
        return f'<AuditLog {self.timestamp} - {self.username or "System"} - {self.action}>'

class BackupScheduleConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    schedule_type = db.Column(db.String(50), nullable=False, default='daily') # 'daily', 'weekly'
    day_of_week = db.Column(db.Integer, nullable=True) # 0=Monday, 6=Sunday, for weekly schedule
    time_of_day = db.Column(db.Time, nullable=False)    # HH:MM
    last_run_date = db.Column(db.Date, nullable=True) # Stores the date of the last successful run

    def __repr__(self):
        return f"<BackupScheduleConfig id={self.id} enabled={self.is_enabled} type={self.schedule_type} time={self.time_of_day.strftime('%H:%M')} last_run={self.last_run_date}>"

# --- Audit Log Helper ---
def add_audit_log(action: str, details: str, user_id: int = None, username: str = None):
    """Adds an entry to the audit log."""
    try:
        log_user_id = user_id
        log_username = username

        if current_user and current_user.is_authenticated:
            if log_user_id is None:
                log_user_id = current_user.id
            if log_username is None:
                log_username = current_user.username
        
        # If user_id is provided but username is not, try to fetch username
        if log_user_id is not None and log_username is None:
            user = User.query.get(log_user_id)
            if user:
                log_username = user.username
            else: # Fallback if user not found for some reason
                log_username = f"User ID {log_user_id}"
        
        # If no user context at all (e.g. system action, or pre-login)
        if log_user_id is None and log_username is None:
            log_username = "System" # Or None, depending on preference

        log_entry = AuditLog(
            user_id=log_user_id,
            username=log_username,
            action=action,
            details=details
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Error adding audit log: {e}", exc_info=True)
        db.session.rollback() # Rollback in case of error during audit logging itself

# --- Resource Helper ---
def resource_to_dict(resource: Resource) -> dict:
    return {
        'id': resource.id,
        'name': resource.name,
        'capacity': resource.capacity,
        'equipment': resource.equipment,
        'status': resource.status,
        'tags': resource.tags,
        'booking_restriction': resource.booking_restriction,
        'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None,
        'published_at': resource.published_at.replace(tzinfo=timezone.utc).isoformat() if resource.published_at else None,
        'allowed_user_ids': resource.allowed_user_ids,
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles],
        'floor_map_id': resource.floor_map_id,
        'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
        'is_under_maintenance': resource.is_under_maintenance,
        'maintenance_until': resource.maintenance_until.replace(tzinfo=timezone.utc).isoformat() if resource.maintenance_until else None,
        'max_recurrence_count': resource.max_recurrence_count,
        'scheduled_status': resource.scheduled_status,
        'scheduled_status_at': resource.scheduled_status_at.replace(tzinfo=timezone.utc).isoformat() if resource.scheduled_status_at else None
    }
# --- Simple Email Notification System ---
email_log = []
slack_log = []

teams_log = []


def send_email(to_address: str, subject: str, body: str):
    """Log an outgoing email (placeholder for real email delivery)."""
    email_entry = {
        'to': to_address,
        'subject': subject,
        'body': body,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    email_log.append(email_entry)
    app.logger.info(f"Email queued to {to_address}: {subject}") # This log remains for all cases

    if mail_available:
        try:
            msg = Message(
                subject=subject,
                recipients=[to_address],
                body=body,
                sender=app.config.get('MAIL_DEFAULT_SENDER')
            )
            mail.send(msg)
            app.logger.info(f"Email successfully sent to {to_address} via Flask-Mail.")
        except Exception as e:
            app.logger.error(f"Failed to send email to {to_address} via Flask-Mail: {e}", exc_info=True)
    elif not mail_available:
        app.logger.info("Flask-Mail not available, email not sent via external server.")


def send_slack_notification(text: str):
    """Record a slack notification in the log (placeholder)."""
    slack_log.append({'message': text, 'timestamp': datetime.now(timezone.utc).isoformat()})

def send_teams_notification(to_email: str, title: str, text: str):
    """Send a simple Teams notification via webhook if configured."""
    log_entry = {
        'to': to_email,
        'title': title,
        'text': text,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    teams_log.append(log_entry)
    webhook = os.environ.get('TEAMS_WEBHOOK_URL')
    if webhook and to_email:
        try:
            payload = {'title': title, 'text': f"{to_email}: {text}"}
            requests.post(webhook, json=payload, timeout=5)
        except Exception:
            app.logger.exception(f"Failed to send Teams notification to {to_email}")

def parse_simple_rrule(rule_str: str):
    """Parse a minimal RRULE string supporting FREQ and COUNT."""
    if not rule_str:
        return None, 1
    parts = {}
    for part in rule_str.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k.upper()] = v
    freq = parts.get('FREQ', '').upper()
    try:
        count = int(parts.get('COUNT', '1')) if parts.get('COUNT') else 1
    except (ValueError, TypeError):
        app.logger.warning(f"Invalid COUNT value in RRULE '{rule_str}'")
        return None, 1
    if freq not in {'DAILY', 'WEEKLY'}:
        return None, 1
    return freq, max(1, count)

# Helper function to get map configuration data
def _get_map_configuration_data() -> dict:
    """Helper function to generate map configuration data."""
    floor_maps = FloorMap.query.all()
    floor_maps_data = []
    for fm in floor_maps:
        floor_maps_data.append({
            'id': fm.id,
            'name': fm.name,
            'image_filename': fm.image_filename,
            'location': fm.location,
            'floor': fm.floor
        })

    mapped_resources = Resource.query.filter(Resource.floor_map_id.isnot(None)).all()
    mapped_resources_data = []
    for r in mapped_resources:
        mapped_resources_data.append({
            'id': r.id,
            'name': r.name,
            'floor_map_id': r.floor_map_id,
            'map_coordinates': json.loads(r.map_coordinates) if r.map_coordinates else None,
            'booking_restriction': r.booking_restriction,
            'allowed_user_ids': r.allowed_user_ids,
            'role_ids': [role.id for role in r.roles] # Exporting as a list of role IDs
        })

    return {
        'floor_maps': floor_maps_data,
        'mapped_resources': mapped_resources_data
    }

# Helper function to import map configuration data
def _import_map_configuration_data(config_data: dict) -> tuple[dict, int]:
    """Helper function to process imported map configuration data."""
    if not isinstance(config_data, dict) or 'floor_maps' not in config_data or 'mapped_resources' not in config_data:
        return {'error': 'Invalid configuration format. Expected "floor_maps" and "mapped_resources" keys.'}, 400

    maps_created = 0
    maps_updated = 0
    maps_errors = []
    resource_updates = 0
    resource_errors = []
    image_reminders = []

    # Import Floor Maps
    if isinstance(config_data.get('floor_maps'), list):
        for fm_data in config_data['floor_maps']:
            try:
                fm = None
                if fm_data.get('id') is not None:
                    fm = FloorMap.query.get(fm_data['id'])

                if not fm and fm_data.get('name'):
                    fm = FloorMap.query.filter_by(name=fm_data['name']).first()

                action = "UPDATE_FLOOR_MAP_VIA_IMPORT"
                if not fm:
                    fm = FloorMap()
                    action = "CREATE_FLOOR_MAP_VIA_IMPORT"
                    if not fm_data.get('name') or not fm_data.get('image_filename'):
                        maps_errors.append({'error': 'Missing name or image_filename for new map.', 'data': fm_data})
                        continue

                fm.name = fm_data.get('name', fm.name)
                fm.image_filename = fm_data.get('image_filename', fm.image_filename)
                fm.location = fm_data.get('location', fm.location)
                fm.floor = fm_data.get('floor', fm.floor)

                if fm.image_filename and not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], fm.image_filename)):
                    image_reminders.append(f"Ensure image '{fm.image_filename}' for map '{fm.name}' exists in 'static/floor_map_uploads/'.")

                if action == "CREATE_FLOOR_MAP_VIA_IMPORT":
                    db.session.add(fm)
                    maps_created += 1
                else:
                    maps_updated += 1

                db.session.commit() # Commit each map to get ID for resources if it's new
                fm_data['processed_id'] = fm.id # Store processed ID for resource mapping
                add_audit_log(action=action, details=f"FloorMap '{fm.name}' (ID: {fm.id}) processed by import by {current_user.username}.")

            except Exception as e:
                db.session.rollback()
                maps_errors.append({'error': f"Error processing floor map '{fm_data.get('name', 'N/A')}': {str(e)}", 'data': fm_data})

    # Import Mapped Resource configurations
    if isinstance(config_data.get('mapped_resources'), list):
        for res_map_data in config_data['mapped_resources']:
            try:
                resource = None
                if res_map_data.get('id') is not None:
                    resource = Resource.query.get(res_map_data['id'])

                if not resource and res_map_data.get('name'): # Fallback to name if ID not found or not provided
                    resource = Resource.query.filter_by(name=res_map_data['name']).first()

                if not resource:
                    resource_errors.append({'error': f"Resource not found by ID or name: '{res_map_data.get('name') or res_map_data.get('id', 'N/A')}'", 'data': res_map_data})
                    continue

                imported_floor_map_id = res_map_data.get('floor_map_id')
                target_floor_map = None
                if imported_floor_map_id is not None:
                    processed_map_entry = next((m for m in config_data['floor_maps'] if m.get('id') == imported_floor_map_id and 'processed_id' in m), None)
                    if processed_map_entry:
                        target_floor_map = FloorMap.query.get(processed_map_entry['processed_id'])
                    else:
                        target_floor_map = FloorMap.query.get(imported_floor_map_id)

                if target_floor_map:
                    resource.floor_map_id = target_floor_map.id
                elif imported_floor_map_id is not None:
                    resource_errors.append({'error': f"FloorMap ID '{imported_floor_map_id}' not found for resource '{resource.name}'.", 'data': res_map_data})

                if 'map_coordinates' in res_map_data:
                    resource.map_coordinates = json.dumps(res_map_data['map_coordinates']) if res_map_data['map_coordinates'] else None
                if 'booking_restriction' in res_map_data:
                    resource.booking_restriction = res_map_data['booking_restriction']
                if 'allowed_user_ids' in res_map_data:
                    resource.allowed_user_ids = res_map_data['allowed_user_ids']
                if 'role_ids' in res_map_data and isinstance(res_map_data['role_ids'], list):
                    new_roles = []
                    for r_id in res_map_data['role_ids']:
                        role = Role.query.get(r_id)
                        if role: new_roles.append(role)
                        else: resource_errors.append({'error': f"Role ID '{r_id}' not found for resource '{resource.name}'.", 'data': res_map_data})
                    resource.roles = new_roles

                resource_updates +=1
                add_audit_log(action="UPDATE_RESOURCE_MAP_INFO_VIA_IMPORT", details=f"Resource '{resource.name}' (ID: {resource.id}) map info updated by import by {current_user.username}.")
            except Exception as e:
                db.session.rollback()
                resource_errors.append({'error': f"Error processing resource mapping for '{res_map_data.get('name', 'N/A')}': {str(e)}", 'data': res_map_data})
        try:
            db.session.commit()
        except Exception as e_commit_res:
            db.session.rollback()
            resource_errors.append({'error': f"General DB error committing resource mappings: {str(e_commit_res)}"})

    summary = {
        'message': "Map configuration import processed.",
        'maps_created': maps_created, 'maps_updated': maps_updated, 'maps_errors': maps_errors,
        'resource_mappings_updated': resource_updates, 'resource_mapping_errors': resource_errors,
        'image_reminders': image_reminders
    }
    status_code = 200
    if maps_errors or resource_errors:
        status_code = 207 # Multi-Status
        summary['message'] += " Some entries had errors."
        app.logger.warning(f"Map configuration import by {current_user.username} completed with errors/reminders. Summary: {summary}")
    else:
        app.logger.info(f"Map configuration import by {current_user.username} successful. Summary: {summary}")

    add_audit_log(action="IMPORT_MAP_CONFIGURATION_COMPLETED", details=f"User {current_user.username} completed map configuration import. Summary: {str(summary)}")
    return summary, status_code

# --- Scheduled Backup Job ---
# This function needs to be defined before it's referenced by the scheduler.
def run_scheduled_backup_job():
    """
    Checks the backup schedule and runs a full backup if due.
    This function is intended to be called by APScheduler.
    """
    with app.app_context(): # Essential for DB access and app.logger
        app.logger.info("run_scheduled_backup_job: Checking backup schedule...")
        try:
            schedule_config = db.session.query(BackupScheduleConfig).first()

            if not schedule_config:
                app.logger.warning("run_scheduled_backup_job: No backup schedule configuration found. Skipping.")
                return

            if not schedule_config.is_enabled:
                app.logger.info("run_scheduled_backup_job: Scheduled backups are disabled. Skipping.")
                return

            now_utc = datetime.now(timezone.utc)
            current_time_utc = now_utc.time()
            current_date_utc = now_utc.date()

            # Check if already run today
            if schedule_config.last_run_date == current_date_utc:
                app.logger.info(f"run_scheduled_backup_job: Backup for {current_date_utc.isoformat()} has already run. Skipping.")
                return

            backup_due = False
            if schedule_config.schedule_type == 'daily':
                # Check if current time is at or after scheduled time (within the hour)
                # A more precise check would compare current_time_utc with schedule_config.time_of_day directly
                # and ensure it's within a small window (e.g. job interval) past the scheduled time.
                # For an hourly job, checking the hour is a common approach.
                if current_time_utc.hour == schedule_config.time_of_day.hour and \
                   current_time_utc.minute >= schedule_config.time_of_day.minute: # Ensure we don't miss it if job runs slightly late
                    backup_due = True
            elif schedule_config.schedule_type == 'weekly':
                if now_utc.weekday() == schedule_config.day_of_week: # 0=Monday, 6=Sunday
                    if current_time_utc.hour == schedule_config.time_of_day.hour and \
                       current_time_utc.minute >= schedule_config.time_of_day.minute:
                        backup_due = True

            if backup_due:
                app.logger.info(f"run_scheduled_backup_job: Backup is due for {current_date_utc.isoformat()} at {schedule_config.time_of_day.strftime('%H:%M')}. Starting backup...")

                timestamp_str = now_utc.strftime('%Y%m%d_%H%M%S')
                map_config = _get_map_configuration_data() # Ensure this helper is accessible

                if not create_full_backup: # Check if the azure_backup function is available
                    app.logger.error("run_scheduled_backup_job: create_full_backup function not available/imported.")
                    return

                # Pass None for socketio and task_id as this is an automated job
                success = create_full_backup(timestamp_str, map_config_data=map_config, socketio_instance=None, task_id=None)

                if success:
                    app.logger.info(f"run_scheduled_backup_job: Scheduled backup completed successfully. Timestamp: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_SUCCESS", details=f"Scheduled backup successful. Timestamp: {timestamp_str}", username="System")
                    schedule_config.last_run_date = current_date_utc
                    db.session.commit()
                else:
                    app.logger.error(f"run_scheduled_backup_job: Scheduled backup failed. Timestamp attempted: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_FAILED", details=f"Scheduled backup failed. Timestamp attempted: {timestamp_str}", username="System")
            else:
                # This log can be verbose if the scheduler runs frequently. Consider logging level or less frequent logging.
                app.logger.debug(f"run_scheduled_backup_job: Backup not currently due. Current time: {current_time_utc.strftime('%H:%M:%S')}, Scheduled: {schedule_config.time_of_day.strftime('%H:%M')}, Type: {schedule_config.schedule_type}, Last Run: {schedule_config.last_run_date}")

        except Exception as e:
            app.logger.exception("run_scheduled_backup_job: Error during scheduled backup job execution.")
            add_audit_log(action="SCHEDULED_BACKUP_ERROR", details=f"Exception: {str(e)}", username="System")

@app.route("/")
def serve_index():
    if current_user.is_authenticated:
        upcoming_bookings = Booking.query.filter(
            Booking.user_name == current_user.username, # Assuming bookings are linked by username
            Booking.start_time > datetime.now(timezone.utc)
        ).order_by(Booking.start_time.asc()).all()
        return render_template("index.html", upcoming_bookings=upcoming_bookings)
    else:
        return render_template("login.html")

@app.route("/resources")
def serve_resources():
    return render_template("resources.html")

@app.route("/login")
def serve_login():
    return render_template("login.html")

# Simple route to log out via a browser request and redirect to the public
# resources page. This complements the JSON API logout endpoint and provides
# a straightforward way to clear the session when JavaScript-based navigation
# fails to redirect properly.
@app.route('/logout')
def logout_and_redirect():
    user_identifier = current_user.username if current_user.is_authenticated else "Anonymous"
    user_id_for_log = current_user.id if current_user.is_authenticated else None
    try:
        logout_user()
        app.logger.info(f"User '{user_identifier}' logged out via /logout.")
        add_audit_log(action="LOGOUT_SUCCESS",
                     details=f"User '{user_identifier}' logged out.",
                     user_id=user_id_for_log,
                     username=user_identifier)
    except Exception as e:
        app.logger.exception(f"Error during logout for user {user_identifier}:")
        add_audit_log(action="LOGOUT_FAILED",
                     details=f"Logout attempt failed for user '{user_identifier}'. Error: {str(e)}",
                     user_id=user_id_for_log,
                     username=user_identifier)
    return redirect(url_for('serve_resources'))

@app.route("/profile")
@login_required
def serve_profile_page():
    """Serves the user's profile page."""
    # current_user is available thanks to Flask-Login
    app.logger.info(f"User {current_user.username} accessed their profile page.")
    return render_template("profile.html", 
                           username=current_user.username, 
                           email=current_user.email)

@app.route("/profile/edit")
@login_required
def serve_edit_profile_page():
    """Render form for editing profile."""
    app.logger.info(f"User {current_user.username} accessed edit profile page.")
    return render_template("edit_profile.html", email=current_user.email)

@app.route("/my_bookings")
@login_required
def serve_my_bookings_page():
    """Serves the 'My Bookings' page."""
    app.logger.info(f"User {current_user.username} accessed My Bookings page.")
    return render_template("my_bookings.html")

@app.route("/calendar")
@login_required
def serve_calendar():
    """Serves the calendar view."""
    app.logger.info(f"User {current_user.username} accessed Calendar page.")
    return render_template("calendar.html")

# --- Permission Decorator ---
def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                # Or redirect to login: return redirect(url_for('serve_login', next=request.url))
                return abort(401) 
            if not current_user.has_permission(permission):
                app.logger.warning(f"User {current_user.username} lacks permission '{permission}' for {f.__name__}")
                return abort(403) # Forbidden
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/admin/users_manage')
@login_required
@permission_required('manage_users')
def serve_user_management_page():
    # if not current_user.is_admin: # Replaced by decorator
    #     app.logger.warning(f"Non-admin user {current_user.username} attempted to access User Management page.")
    #     return redirect(url_for('serve_index'))
    app.logger.info(f"Admin user {current_user.username} accessed User Management page.")
    return render_template("user_management.html")

@app.route('/admin/logs')
@login_required
@permission_required('view_audit_logs')
def serve_audit_log_page():
    # if not current_user.is_admin: # Replaced by decorator
    #     app.logger.warning(f"Non-admin user {current_user.username} attempted to access Audit Log page.")
    #     return redirect(url_for('serve_index'))
    app.logger.info(f"Admin user {current_user.username} accessed Audit Log page.")
    return render_template("log_view.html")

@app.route('/admin/maps')
@login_required
@permission_required('manage_floor_maps') # Or 'manage_resources' depending on primary function
def serve_admin_maps():
    # if not current_user.is_admin: # Replaced by decorator
    #     return redirect(url_for('serve_index'))
    return render_template("admin_maps.html")

@app.route('/admin/resources_manage')
@login_required
@permission_required('manage_resources')
def serve_resource_management_page():
    app.logger.info(f"Admin user {current_user.username} accessed Resource Management page.")
    return render_template("resource_management.html")

@app.route('/admin/bookings')
@login_required
@permission_required('manage_bookings')
def serve_admin_bookings_page():
    app.logger.info(f"User {current_user.username} accessed Admin Bookings page.")
    try:
        bookings_query = db.session.query(
            Booking.id,
            Booking.title,
            Booking.start_time,
            Booking.end_time,
            Booking.status,
            User.username.label('user_username'),
            Resource.name.label('resource_name')
        ).join(Resource, Booking.resource_id == Resource.id)\
         .join(User, Booking.user_name == User.username)

        all_bookings = bookings_query.order_by(Booking.start_time.desc()).all()

        bookings_list = []
        for booking_row in all_bookings:
            bookings_list.append({
                'id': booking_row.id,
                'title': booking_row.title,
                'start_time': booking_row.start_time,
                'end_time': booking_row.end_time,
                'status': booking_row.status,
                'user_username': booking_row.user_username,
                'resource_name': booking_row.resource_name
            })

        return render_template("admin_bookings.html", bookings=bookings_list)
    except Exception as e:
        app.logger.error(f"Error fetching bookings for admin page: {e}", exc_info=True)
        return render_template("admin_bookings.html", bookings=[], error="Could not load bookings.")

@app.route('/admin/backup_restore')
@login_required
@permission_required('manage_system') # Assuming this permission exists or will be added
def serve_backup_restore_page():
    """Serves the admin page for backup and restore operations."""
    app.logger.info(f"User {current_user.username} accessed Backup/Restore admin page.")
    # The actual template 'admin_backup_restore.html' will be created in a later step.
    return render_template('admin_backup_restore.html')

# --- Analytics Routes ---
@analytics_bp.route('/')
@login_required
@permission_required('view_analytics')
def analytics_dashboard():
    app.logger.info(f"User {current_user.username} accessed analytics dashboard.")
    return render_template('analytics.html')


@analytics_bp.route('/data/bookings')
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    last_30_days = datetime.now(timezone.utc) - timedelta(days=30)
    results = (
        db.session.query(Resource.name, func.date(Booking.start_time), func.count(Booking.id))
        .join(Resource)
        .filter(Booking.start_time >= last_30_days)
        .group_by(Resource.name, func.date(Booking.start_time))
        .all()
    )

    data = {}
    for resource_name, day, count in results:
        day_str = day.isoformat() if hasattr(day, 'isoformat') else str(day)
        data.setdefault(resource_name, []).append({'date': day_str, 'count': count})
    return jsonify(data)

@app.route('/map_view/<int:map_id>')
def serve_map_view(map_id):
    # You could fetch map name here to pass to template title, but JS will fetch full details
    return render_template("map_view.html", map_id_from_flask=map_id)

@app.route('/login/google')
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for('serve_index'))
    
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    # Store the state in the session to verify in the callback
    session['oauth_state'] = state 
    return redirect(authorization_url)

@app.route('/login/google/callback')
def login_google_callback():
    state = session.pop('oauth_state', None)
    # It's important to verify the state to prevent CSRF attacks.
    # For explicit state check:
    if state is None or state != request.args.get('state'):
        app.logger.error("Invalid OAuth state parameter during Google callback. Potential CSRF.")
        # Flash messages are not part of this app's error handling strategy
        # If flash messages were used, they would be like: flash(_('Invalid OAuth state.'), 'error')
        return redirect(url_for('serve_login'))

    flow = get_google_flow()
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e: # Catches errors like MismatchingStateError (already covered by above state check) or others
        app.logger.error(f"Error fetching OAuth token from Google: {e}", exc_info=True)
        # flash(_("Authentication failed: Could not fetch token. Please try again."), "danger")
        return redirect(url_for('serve_login')) 

    if not flow.credentials:
        app.logger.error("Failed to retrieve credentials from Google after token fetch.")
        # flash(_("Failed to retrieve credentials from Google. Please try again."), "danger")
        return redirect(url_for('serve_login'))

    # Extract the ID token from credentials
    id_token_jwt = flow.credentials.id_token

    try:
        # Verify the ID token and extract user info
        # The audience ('aud') parameter must match your Google Client ID
        id_info = id_token.verify_oauth2_token(
            id_token_jwt, google_requests.Request(), app.config['GOOGLE_CLIENT_ID']
        )

        google_user_id = id_info.get('sub')
        google_user_email = id_info.get('email')

        if not google_user_id or not google_user_email:
            app.logger.error(f"Google ID token verification successful, but 'sub' or 'email' missing. Email: {google_user_email}, Sub: {google_user_id}")
            # flash(_("Could not retrieve Google ID or email. Please ensure your Google account has an email and permissions are granted."), "danger")
            return redirect(url_for('serve_login'))

        # Check if user exists by google_id
        user = User.query.filter_by(google_id=google_user_id).first()

        if user: # User found by google_id
            if user.is_admin: # Only allow admin users for this application
                login_user(user)
                app.logger.info(f"Admin user {user.username} (Google ID: {google_user_id}) logged in via Google.")
                # flash(_('Welcome back, %(username)s!', username=user.username), 'success')
                return redirect(url_for('serve_index')) 
            else:
                app.logger.warning(f"Non-admin user {user.username} (Google ID: {google_user_id}) attempted Google login. Denied.")
                # flash(_('Your Google account is linked, but it is not associated with an admin user for this application.'), 'danger')
                return redirect(url_for('serve_login')) 

        # If no user by google_id, check if an existing admin user has this email
        # This is to link an existing admin account (username/password) to Google Sign-In
        admin_with_email = User.query.filter_by(email=google_user_email, is_admin=True).first()

        if admin_with_email:
            # Check if this Google ID is already linked to another account (should be rare if google_id is unique)
            existing_google_id_user = User.query.filter_by(google_id=google_user_id).first() # This should be the same as `user` if found
            if existing_google_id_user and existing_google_id_user.id != admin_with_email.id:
                app.logger.error(f"Google ID {google_user_id} (email: {google_user_email}) is already linked to user {existing_google_id_user.username}, but trying to link to {admin_with_email.username}.")
                # flash(_('This Google account is already linked to a different user. Please contact support.'), 'danger')
                return redirect(url_for('serve_login'))

            admin_with_email.google_id = google_user_id
            admin_with_email.google_email = google_user_email 
            try:
                db.session.commit()
                login_user(admin_with_email)
                app.logger.info(f"Admin user {admin_with_email.username} successfully linked their Google account (ID: {google_user_id}).")
                return redirect(url_for('serve_index')) 
            except Exception as e:
                db.session.rollback()
                app.logger.exception(f"Database error linking Google ID {google_user_id} to user {admin_with_email.username}:")
                return redirect(url_for('serve_login'))
        else:
            app.logger.warning(f"Google account (Email: {google_user_email}, ID: {google_user_id}) not associated with any existing admin user. Login denied for this application.")
            return redirect(url_for('serve_login'))

    except ValueError as e: # Specifically for id_token.verify_oauth2_token
        app.logger.error(f"Invalid Google ID token during Google login: {e}", exc_info=True)
        return redirect(url_for('serve_login'))
    except Exception as e: # Catch any other unexpected errors
        app.logger.exception("An unexpected error occurred during Google login callback:")
        return redirect(url_for('serve_login')) 


@app.route('/api/resources', methods=['GET'])
def get_resources():
    try:
        query = Resource.query.filter_by(status='published')

        capacity = request.args.get('capacity', type=int)
        if capacity is not None:
            query = query.filter(Resource.capacity >= capacity)

        equipment = request.args.get('equipment')
        if equipment:
            for item in [e.strip().lower() for e in equipment.split(',') if e.strip()]:
                query = query.filter(Resource.equipment.ilike(f'%{item}%'))

        tags = request.args.get('tags')
        if tags:
            for tag in [t.strip().lower() for t in tags.split(',') if t.strip()]:
                query = query.filter(Resource.tags.ilike(f'%{tag}%'))

        resources_query = query.all()
            
        resources_list = []
        for resource in resources_query:
            resources_list.append({
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity,
                'equipment': resource.equipment,
                'tags': resource.tags,
                'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None,
                'floor_map_id': resource.floor_map_id,
                'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
                'booking_restriction': resource.booking_restriction,
                'status': resource.status,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids,
                'roles': [{'id': role.id, 'name': role.name} for role in resource.roles],
                'is_under_maintenance': resource.is_under_maintenance,
                'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None
            })
        app.logger.info("Successfully fetched published resources.")
        return jsonify(resources_list), 200
    except Exception as e:
        app.logger.exception("Error fetching resources:")
        return jsonify({'error': 'Failed to fetch resources due to a server error.'}), 500

@app.route('/api/resources/<int:resource_id>/availability', methods=['GET'])
def get_resource_availability(resource_id):
    # Get the date from query parameters, default to today if not provided
    date_str = request.args.get('date')
    
    target_date_obj = None
    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.warning(f"Invalid date format provided: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        resource = Resource.query.get(resource_id)
        if not resource:
            app.logger.warning(f"Resource availability check for non-existent resource ID: {resource_id}")
            return jsonify({'error': 'Resource not found.'}), 404

        if resource.is_under_maintenance and (resource.maintenance_until is None or target_date_obj <= resource.maintenance_until.date()):
            until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else 'until further notice'
            return jsonify({'error': f'Resource under maintenance until {until_str}.'}), 403

        bookings_on_date = Booking.query.filter(
            Booking.resource_id == resource_id,
            func.date(Booking.start_time) == target_date_obj
        ).all()

        booked_slots = []
        for booking in bookings_on_date:
            grace = app.config.get('CHECK_IN_GRACE_MINUTES', 15)
            now = datetime.now(timezone.utc)

            # Ensure booking.start_time is offset-aware (UTC) before comparison
            booking_start_time_aware = booking.start_time
            if booking_start_time_aware.tzinfo is None:
                booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

            can_check_in = (
                booking.checked_in_at is None and
                booking_start_time_aware - timedelta(minutes=grace) <= now <= booking_start_time_aware + timedelta(minutes=grace)
            )
            booked_slots.append({
                'title': booking.title,
                'user_name': booking.user_name,
                'start_time': booking.start_time.strftime('%H:%M:%S'),
                'end_time': booking.end_time.strftime('%H:%M:%S'),
                'booking_id': booking.id,
                'checked_in_at': booking.checked_in_at.isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in
            })
        
        return jsonify(booked_slots), 200

    except Exception as e:
        app.logger.exception(f"Error fetching availability for resource {resource_id} on {target_date_obj}:")
        return jsonify({'error': 'Failed to fetch resource availability due to a server error.'}), 500


@app.route('/api/maps', methods=['GET'])
def get_public_floor_maps():
    try:
        maps = FloorMap.query.all()
        maps_list = []
        for m in maps:
            maps_list.append({
                'id': m.id,
                'name': m.name,
                'image_filename': m.image_filename, # Keep for consistency, though frontend might not use it directly for this feature
                'location': m.location,
                'floor': m.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}')
            })
        # app.logger.info("Successfully fetched all floor maps for public API.") # Optional logging
        return jsonify(maps_list), 200
    except Exception as e:
        app.logger.exception("Error fetching public floor maps:")
        return jsonify({'error': 'Failed to fetch maps due to a server error.'}), 500

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/admin/maps', methods=['POST'])
@login_required
def upload_floor_map():
    if not current_user.has_permission('manage_floor_maps'):
        add_audit_log(action="UPLOAD_MAP_DENIED", details=f"User {current_user.username} lacks permission 'manage_floor_maps'.")
        return jsonify({'error': 'Permission denied to manage floor maps.'}), 403

    if 'map_image' not in request.files:
        app.logger.warning("Map image missing in upload request.")
        return jsonify({'error': 'No map_image file part in the request.'}), 400
    
    file = request.files['map_image']
    map_name = request.form.get('map_name')
    location = request.form.get('location')
    floor = request.form.get('floor')

    if not map_name:
        app.logger.warning("Map name missing in upload request.")
        return jsonify({'error': 'map_name is required.'}), 400
    
    if file.filename == '':
        app.logger.warning("No file selected for map upload.")
        return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        # Check for existing map with same name or filename to prevent duplicates
        existing_map_by_filename = FloorMap.query.filter_by(image_filename=filename).first()
        existing_map_by_name = FloorMap.query.filter_by(name=map_name).first()
        
        if existing_map_by_filename:
            app.logger.warning(f"Attempt to upload map with duplicate filename: {filename}")
            return jsonify({'error': 'A map with this image filename already exists.'}), 409 # Conflict
        if existing_map_by_name:
            app.logger.warning(f"Attempt to upload map with duplicate name: {map_name}")
            return jsonify({'error': 'A map with this name already exists.'}), 409 # Conflict

        file_path = None # Initialize file_path to ensure it's defined for potential cleanup
        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            if save_floor_map_to_share:
                try:
                    save_floor_map_to_share(file_path, filename)
                except Exception:
                    app.logger.exception('Failed to upload floor map to Azure File Share')

            new_map = FloorMap(name=map_name, image_filename=filename,
                               location=location, floor=floor)
            db.session.add(new_map)
            db.session.commit()
            app.logger.info(f"Floor map '{map_name}' uploaded successfully by {current_user.username}.")
            add_audit_log(action="CREATE_MAP_SUCCESS", details=f"Floor map '{map_name}' (ID: {new_map.id}) uploaded successfully.")
            return jsonify({
                'id': new_map.id,
                'name': new_map.name,
                'image_filename': new_map.image_filename,
                'location': new_map.location,
                'floor': new_map.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{new_map.image_filename}')
            }), 201
        except Exception as e:
            db.session.rollback()
            if file_path and os.path.exists(file_path): # Attempt to clean up saved file on error
                 os.remove(file_path)
                 app.logger.info(f"Cleaned up partially uploaded file: {file_path}")
            app.logger.exception(f"Error uploading floor map '{map_name}':")
            # Audit log for failed map upload attempt
            add_audit_log(action="CREATE_MAP_FAILED", details=f"Failed to upload floor map '{map_name}'. Error: {str(e)}", username=current_user.username if current_user.is_authenticated else "Unknown")
            return jsonify({'error': f'Failed to upload map due to a server error.'}), 500
    else:
        app.logger.warning(f"File type not allowed for map upload: {file.filename}")
        return jsonify({'error': 'File type not allowed. Allowed types are: png, jpg, jpeg.'}), 400

@app.route('/api/admin/maps', methods=['GET'])
@login_required
def get_floor_maps():
    if not current_user.has_permission('manage_floor_maps'):
        return jsonify({'error': 'Permission denied to manage floor maps.'}), 403
    try:
        maps = FloorMap.query.all()
        maps_list = []
        for m in maps:
            maps_list.append({
                'id': m.id,
                'name': m.name,
                'image_filename': m.image_filename,
                'location': m.location,
                'floor': m.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}')
            })
        app.logger.info("Successfully fetched all floor maps for admin.")
        return jsonify(maps_list), 200
    except Exception as e:
        app.logger.exception("Error fetching floor maps:")
        return jsonify({'error': 'Failed to fetch maps due to a server error.'}), 500

@app.route('/api/admin/maps/<int:map_id>', methods=['DELETE'])
@login_required
@permission_required('manage_floor_maps')
def delete_floor_map(map_id):
    floor_map = FloorMap.query.get(map_id)
    if not floor_map:
        app.logger.warning(f"Attempt to delete non-existent floor map ID: {map_id} by user {current_user.username}")
        return jsonify({'error': 'Floor map not found.'}), 404

    map_name_for_log = floor_map.name # Capture for logging before deletion
    image_filename_for_log = floor_map.image_filename

    try:
        # Unmap resources associated with this floor map
        associated_resources = Resource.query.filter_by(floor_map_id=map_id).all()
        for resource in associated_resources:
            resource.floor_map_id = None
            resource.map_coordinates = None

        db.session.flush() # Flush changes to resources before committing map deletion

        # Delete the FloorMap object
        db.session.delete(floor_map)

        # Delete the associated image file
        if floor_map.image_filename:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], floor_map.image_filename)
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
                    app.logger.info(f"Successfully deleted map image file: {image_path}")
                else:
                    app.logger.warning(f"Map image file not found for deletion: {image_path}")
            except OSError as e:
                # Log the error but continue with map deletion from DB
                app.logger.error(f"Error deleting map image file {image_path}: {e}", exc_info=True)

        db.session.commit()

        app.logger.info(f"Floor map ID {map_id} ('{map_name_for_log}') and its image '{image_filename_for_log}' deleted successfully by {current_user.username}.")
        add_audit_log(
            action="DELETE_MAP_SUCCESS",
            details=f"Floor map ID {map_id} ('{map_name_for_log}', image: '{image_filename_for_log}') and associated resource mappings deleted by user {current_user.username}."
        )
        return jsonify({'message': f"Floor map '{map_name_for_log}' and associated resource mappings deleted successfully."}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting floor map ID {map_id} ('{map_name_for_log}'):")
        add_audit_log(
            action="DELETE_MAP_FAILED",
            details=f"Failed to delete floor map ID {map_id} ('{map_name_for_log}'). Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to delete floor map due to a server error.'}), 500

# Helper function to get map configuration data
# Duplicated _get_map_configuration_data and _import_map_configuration_data removed for brevity, assume they exist as before

@app.route('/api/admin/maps/export_configuration', methods=['GET'])
@login_required
@permission_required('manage_floor_maps') # Or a new, more specific permission if desired
def export_map_configuration():
    try:
        export_data = _get_map_configuration_data()
        response = jsonify(export_data)
        response.headers['Content-Disposition'] = 'attachment; filename=map_configuration_export.json'
        response.mimetype = 'application/json'

        app.logger.info(f"User {current_user.username} exported map configuration.")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION", details=f"User {current_user.username} exported map configuration.")
        return response

    except Exception as e:
        app.logger.exception("Error exporting map configuration:")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to export map configuration. Error: {str(e)}")
        return jsonify({'error': 'Failed to export map configuration due to a server error.'}), 500

@app.route('/api/admin/maps/import_configuration', methods=['POST'])
@login_required
@permission_required('manage_floor_maps') # Or a new, more specific permission
def import_map_configuration():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request.'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'File must be a JSON file.'}), 400

    try:
        config_data = json.load(file)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file.'}), 400

    summary, status_code = _import_map_configuration_data(config_data)
    return jsonify(summary), status_code


@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['PUT'])
@login_required 
def update_resource_map_info(resource_id):
    if not current_user.has_permission('manage_resources'):
        add_audit_log(action="UPDATE_RESOURCE_MAP_INFO_DENIED", details=f"User {current_user.username} lacks permission 'manage_resources'.")
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    data = request.get_json()
    if not data:
        app.logger.warning(f"Invalid input for update_resource_map_info for resource {resource_id}: No JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to update map info for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    # Process booking_restriction
    if 'booking_restriction' in data:
        booking_restriction_data = data.get('booking_restriction')
        allowed_restrictions = ['admin_only', 'all_users', None, ""] 
        if booking_restriction_data not in allowed_restrictions:
            app.logger.warning(f"Invalid booking_restriction value '{booking_restriction_data}' for resource {resource_id}.")
            return jsonify({'error': f'Invalid booking_restriction value. Allowed: {allowed_restrictions}. Received: {booking_restriction_data}'}), 400
        resource.booking_restriction = booking_restriction_data if booking_restriction_data != "" else None

    # Process allowed_user_ids
    if 'allowed_user_ids' in data: # This key must be present to modify allowed_user_ids
        user_ids_str_list = data.get('allowed_user_ids') # Expecting a string of comma-separated IDs or null
        if user_ids_str_list is None or user_ids_str_list.strip() == "":
            resource.allowed_user_ids = None
        elif isinstance(user_ids_str_list, str):
            try: # Validate that all are integers
                processed_ids = sorted(list(set(int(uid.strip()) for uid in user_ids_str_list.split(',') if uid.strip())))
                resource.allowed_user_ids = ",".join(map(str, processed_ids)) if processed_ids else None
            except ValueError:
                app.logger.warning(f"Invalid user ID in allowed_user_ids for resource {resource_id}: {user_ids_str_list}")
                return jsonify({'error': 'Invalid allowed_user_ids format. Expected a comma-separated string of integers or null.'}), 400
        else: # Should be string or null
            app.logger.warning(f"Incorrect type for allowed_user_ids for resource {resource_id}: {type(user_ids_str_list)}")
            return jsonify({'error': 'allowed_user_ids must be a string or null.'}), 400


    # Process role_ids for RBAC
    if 'role_ids' in data:
        role_ids = data.get('role_ids')
        if role_ids is None: # Explicitly setting to no roles
            resource.roles = []
        elif isinstance(role_ids, list):
            new_roles = []
            for r_id in role_ids:
                if not isinstance(r_id, int):
                    return jsonify({'error': f'Invalid role ID type: {r_id}. Must be integer.'}), 400
                role = Role.query.get(r_id)
                if not role:
                    return jsonify({'error': f'Role with ID {r_id} not found.'}), 400
                new_roles.append(role)
            resource.roles = new_roles
        else:
            return jsonify({'error': 'role_ids must be a list of integers or null.'}), 400

    # Logic for map and coordinates
    # Only update map info if 'floor_map_id' is explicitly in the payload
    if 'floor_map_id' in data: 
        floor_map_id_data = data.get('floor_map_id')
        coordinates_data = data.get('coordinates') # This should be present if floor_map_id is not null

        if floor_map_id_data is not None: 
            floor_map = FloorMap.query.get(floor_map_id_data)
            if not floor_map:
                app.logger.warning(f"Floor map ID {floor_map_id_data} not found for resource {resource_id}.")
                return jsonify({'error': 'Floor map not found.'}), 404
            resource.floor_map_id = floor_map_id_data

            if not coordinates_data or not isinstance(coordinates_data, dict):
                app.logger.warning(f"Missing or invalid coordinates for resource {resource_id} when floor_map_id is {floor_map_id_data}.")
                return jsonify({'error': 'Missing or invalid coordinates data when floor_map_id is provided.'}), 400
            
            if coordinates_data.get('type') == 'rect':
                required_coords = ['x', 'y', 'width', 'height']
                if not all(k in coordinates_data and isinstance(coordinates_data[k], (int, float)) for k in required_coords):
                    app.logger.warning(f"Invalid rect coordinates for resource {resource_id}: {coordinates_data}")
                    return jsonify({'error': 'Rect coordinates require numeric x, y, width, height.'}), 400
                resource.map_coordinates = json.dumps(coordinates_data)
            else:
                app.logger.warning(f"Invalid coordinates type for resource {resource_id}: {coordinates_data.get('type')}")
                return jsonify({'error': "Invalid coordinates type. Only 'rect' is supported."}), 400
        else: # floor_map_id is explicitly set to null (or empty string handled by frontend)
            resource.floor_map_id = None
            resource.map_coordinates = None
    
    try:
        db.session.commit()
        app.logger.info(f"Successfully updated map/permission info for resource ID {resource.id} by user {current_user.username}.")
        updated_resource_data = {
            'id': resource.id, 'name': resource.name,
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
            'booking_restriction': resource.booking_restriction, 'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'allowed_user_ids': resource.allowed_user_ids, 
            'roles': [{'id': role.id, 'name': role.name} for role in resource.roles],
            'capacity': resource.capacity, 'equipment': resource.equipment
        }
        add_audit_log(action="UPDATE_RESOURCE_MAP_INFO_SUCCESS", details=f"Map/permission info for resource ID {resource.id} ('{resource.name}') updated.")
        return jsonify(updated_resource_data), 200
        
    except Exception as e:
        db.session.rollback()
        add_audit_log(action="UPDATE_RESOURCE_MAP_INFO_FAILED", details=f"Failed to update map/permission info for resource ID {resource_id}. Error: {str(e)}")
        app.logger.exception(f"Error committing update_resource_map_info for resource {resource_id}:")
        return jsonify({'error': 'Failed to update resource due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/publish', methods=['POST'])
@login_required
def publish_resource(resource_id):
    if not current_user.has_permission('manage_resources'):
        add_audit_log(action="PUBLISH_RESOURCE_DENIED", details=f"User {current_user.username} lacks permission 'manage_resources'.")
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to publish non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.status == 'published':
        app.logger.info(f"Resource {resource_id} is already published. No action taken.")
        return jsonify({'message': 'Resource is already published.', 
                        'resource': {
                            'id': resource.id, 'name': resource.name, 'status': resource.status, 
                            'published_at': resource.published_at.isoformat() if resource.published_at else None
                        }}), 200
    
    if resource.status != 'draft':
        app.logger.warning(f"Attempt to publish resource {resource_id} from invalid status: {resource.status}")
        return jsonify({'error': f'Resource cannot be published from status: {resource.status}. Must be a draft.'}), 400

    try:
        resource.status = 'published'
        resource.published_at = datetime.now(timezone.utc)
        db.session.commit()
        app.logger.info(f"Resource {resource_id} ('{resource.name}') published successfully by {current_user.username}.")
        updated_resource_data = {
            'id': resource.id, 'name': resource.name, 'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'booking_restriction': resource.booking_restriction, 'capacity': resource.capacity,
            'equipment': resource.equipment, 'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None
        }
        add_audit_log(action="PUBLISH_RESOURCE_SUCCESS", details=f"Resource {resource_id} ('{resource.name}') published successfully.")
        return jsonify({'message': 'Resource published successfully.', 'resource': updated_resource_data}), 200
        
    except Exception as e:
        db.session.rollback()
        add_audit_log(action="PUBLISH_RESOURCE_FAILED", details=f"Failed to publish resource {resource_id}. Error: {str(e)}")
        app.logger.exception(f"Error publishing resource {resource_id}:")
        return jsonify({'error': 'Failed to publish resource due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>', methods=['PUT'])
@login_required
def update_resource_details(resource_id):
    if not current_user.has_permission('manage_resources'):
        add_audit_log(action="UPDATE_RESOURCE_DETAILS_DENIED", details=f"User {current_user.username} lacks permission 'manage_resources'.")
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to update non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    data = request.get_json()
    if not data:
        app.logger.warning(f"Update attempt for resource {resource_id} with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    # Fields that can be updated via this endpoint
    allowed_fields = [
        'name', 'capacity', 'equipment', 'status',
        'booking_restriction', 'allowed_user_ids',
        'is_under_maintenance', 'maintenance_until',
        'max_recurrence_count', 'scheduled_status', 'scheduled_status_at',
        'tags'
    ]
    
    # Validate status if provided
    if 'status' in data:
        new_status = data.get('status')
        valid_statuses = ['draft', 'published', 'archived']
        if new_status not in valid_statuses:
            app.logger.warning(f"Invalid status value '{new_status}' for resource {resource_id}.")
            return jsonify({'error': f"Invalid status value. Allowed values are: {', '.join(valid_statuses)}."}), 400
        
        # Handle published_at logic
        if new_status == 'published' and resource.status != 'published': # Changed to published
            if resource.published_at is None:
                resource.published_at = datetime.now(timezone.utc)
        # If status changes away from 'published', current requirements are to leave published_at as is.
        resource.status = new_status

    for field in allowed_fields:
        if field in data and field != 'status': # Status is handled separately
            if field == 'capacity':
                try:
                    value = data[field]
                    if value is not None: # Allow setting capacity to null
                        value = int(value)
                    setattr(resource, field, value)
                except (ValueError, TypeError):
                    app.logger.warning(f"Invalid capacity value '{data[field]}' for resource {resource_id}.")
                    return jsonify({'error': f"Invalid value for capacity. Must be an integer or null."}), 400
            elif field == 'booking_restriction':
                booking_restriction_data = data.get('booking_restriction')
                allowed_restrictions = ['admin_only', 'all_users', None, ""] 
                if booking_restriction_data not in allowed_restrictions:
                    app.logger.warning(f"Invalid booking_restriction value '{booking_restriction_data}' for resource {resource_id}.")
                    return jsonify({'error': f'Invalid booking_restriction value. Allowed: {allowed_restrictions}. Received: {booking_restriction_data}'}), 400
                resource.booking_restriction = booking_restriction_data if booking_restriction_data != "" else None
            elif field == 'allowed_user_ids':
                user_ids_str_list = data.get('allowed_user_ids')
                if user_ids_str_list is None or user_ids_str_list.strip() == "":
                    resource.allowed_user_ids = None
                elif isinstance(user_ids_str_list, str):
                    try:
                        processed_ids = sorted(list(set(int(uid.strip()) for uid in user_ids_str_list.split(',') if uid.strip())))
                        resource.allowed_user_ids = ",".join(map(str, processed_ids)) if processed_ids else None
                    except ValueError:
                        app.logger.warning(f"Invalid user ID in allowed_user_ids for resource {resource_id}: {user_ids_str_list}")
                        return jsonify({'error': 'Invalid allowed_user_ids format. Expected a comma-separated string of integers or null.'}), 400
                else:
                    app.logger.warning(f"Incorrect type for allowed_user_ids for resource {resource_id}: {type(user_ids_str_list)}")
                    return jsonify({'error': 'allowed_user_ids must be a string or null.'}), 400
            elif field == 'is_under_maintenance':
                resource.is_under_maintenance = bool(data.get('is_under_maintenance'))
            elif field == 'maintenance_until':
                maint_val = data.get('maintenance_until')
                if maint_val:
                    try:
                        resource.maintenance_until = datetime.fromisoformat(maint_val)
                    except ValueError:
                        return jsonify({'error': 'Invalid maintenance_until format. Use ISO datetime.'}), 400
                else:
                    resource.maintenance_until = None
            elif field == 'max_recurrence_count':
                value = data.get('max_recurrence_count')
                if value is not None and value != '':
                    try:
                        resource.max_recurrence_count = int(value)
                    except ValueError:
                        return jsonify({'error': 'max_recurrence_count must be an integer or null.'}), 400
                else:
                    resource.max_recurrence_count = None
            elif field == 'scheduled_status':
                value = data.get('scheduled_status')
                # Allowed: 'draft', 'published', 'archived', or None (empty string from form becomes None)
                valid_scheduled_statuses = ['draft', 'published', 'archived']
                if value is None or value == "":
                    resource.scheduled_status = None
                elif value not in valid_scheduled_statuses:
                    return jsonify({'error': f"Invalid scheduled_status value '{value}'. Allowed: {valid_scheduled_statuses} or empty/null."}), 400
                else:
                    resource.scheduled_status = value
            elif field == 'scheduled_status_at':
                value = data.get('scheduled_status_at')
                if value is None or value == "":
                    resource.scheduled_status_at = None
                else:
                    try:
                        if not isinstance(value, str): # Basic type check
                             raise ValueError("Input must be a string for datetime conversion")
                        resource.scheduled_status_at = datetime.fromisoformat(value)
                    except ValueError:
                        return jsonify({'error': 'Invalid scheduled_status_at format. Use ISO datetime string (YYYY-MM-DDTHH:MM:SS) or empty/null.'}), 400
            elif field == 'tags':
                resource.tags = data.get('tags')
            else: # For 'name', 'equipment'
                setattr(resource, field, data[field])

    # Handle role_ids separately
    if 'role_ids' in data:
        role_ids = data.get('role_ids')
        if role_ids is None: # Explicitly setting to no roles
            resource.roles = []
        elif isinstance(role_ids, list):
            new_roles = []
            for r_id in role_ids:
                if not isinstance(r_id, int):
                    return jsonify({'error': f'Invalid role ID type: {r_id}. Must be integer.'}), 400
                role = Role.query.get(r_id)
                if not role:
                    return jsonify({'error': f'Role with ID {r_id} not found.'}), 400
                new_roles.append(role)
            resource.roles = new_roles
        else:
            return jsonify({'error': 'role_ids must be a list of integers or null.'}), 400
            
    try:
        db.session.commit()
        app.logger.info(f"Resource {resource_id} ('{resource.name}') updated successfully by {current_user.username}.")
        # Return the updated resource
        updated_resource_data = {
            'id': resource.id,
            'name': resource.name,
            'capacity': resource.capacity,
            'equipment': resource.equipment,
            'tags': resource.tags,
            'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'booking_restriction': resource.booking_restriction,
            'allowed_user_ids': resource.allowed_user_ids,
            'roles': [{'id': role.id, 'name': role.name} for role in resource.roles], # Return new roles list
            # Map-related fields are not updated here, but returned for consistency
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
            'is_under_maintenance': resource.is_under_maintenance,
            'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None,
            'max_recurrence_count': resource.max_recurrence_count,
            'scheduled_status': resource.scheduled_status,
            'scheduled_status_at': resource.scheduled_status_at.isoformat() if resource.scheduled_status_at else None
        }
        add_audit_log(action="UPDATE_RESOURCE_DETAILS_SUCCESS", details=f"Resource ID {resource.id} ('{resource.name}') details updated. Data: {str(data)}")
        return jsonify(updated_resource_data), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error updating resource {resource_id}:")
        add_audit_log(action="UPDATE_RESOURCE_DETAILS_FAILED", details=f"Failed to update resource ID {resource_id}. Error: {str(e)}. Data: {str(data)}")
        return jsonify({'error': 'Failed to update resource due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/image', methods=['POST'])
@login_required
def upload_resource_image(resource_id):
    if not current_user.has_permission('manage_resources'):
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404

    if 'resource_image' not in request.files:
        return jsonify({'error': 'No resource_image file part in the request.'}), 400

    file = request.files['resource_image']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        existing_by_filename = Resource.query.filter_by(image_filename=filename).first()
        if existing_by_filename and existing_by_filename.id != resource_id:
            return jsonify({'error': 'A resource with this image filename already exists.'}), 409
        file_path = os.path.join(app.config['RESOURCE_UPLOAD_FOLDER'], filename)
        old_path = None
        try:
            file.save(file_path)
            if resource.image_filename and resource.image_filename != filename:
                old_path = os.path.join(app.config['RESOURCE_UPLOAD_FOLDER'], resource.image_filename)
            resource.image_filename = filename
            db.session.commit()
            if old_path and os.path.exists(old_path):
                os.remove(old_path)
            return jsonify({'message': 'Image uploaded successfully.',
                            'image_url': url_for('static', filename=f'resource_uploads/{filename}')}), 200
        except Exception as e:
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'error': 'Failed to upload image due to a server error.'}), 500
    else:
        return jsonify({'error': 'File type not allowed. Allowed types are: png, jpg, jpeg.'}), 400

@app.route('/api/admin/resources/<int:resource_id>', methods=['DELETE'])
@login_required
def delete_resource(resource_id):
    if not current_user.has_permission('manage_resources'):
        add_audit_log(action="DELETE_RESOURCE_DENIED", details=f"User {current_user.username} lacks permission 'manage_resources'.")
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to delete non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    try:
        # Bookings associated with this resource will be deleted due to cascade="all, delete-orphan"
        resource_name_for_log = resource.name  # Capture before deletion
        old_image = resource.image_filename
        db.session.delete(resource)
        db.session.commit()
        if old_image:
            old_path = os.path.join(app.config['RESOURCE_UPLOAD_FOLDER'], old_image)
            if os.path.exists(old_path):
                os.remove(old_path)
        app.logger.info(f"Resource {resource_id} ('{resource_name_for_log}') and its associated bookings deleted successfully by {current_user.username}.")
        add_audit_log(action="DELETE_RESOURCE_SUCCESS", details=f"Resource ID {resource_id} ('{resource_name_for_log}') deleted.")
        return jsonify({'message': f"Resource '{resource_name_for_log}' (ID: {resource_id}) and its bookings deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting resource {resource_id}:")
        add_audit_log(action="DELETE_RESOURCE_FAILED", details=f"Failed to delete resource ID {resource_id} ('{resource_name_for_log}'). Error: {str(e)}")
        return jsonify({'error': 'Failed to delete resource due to a server error.'}), 500

@app.route('/api/admin/resources', methods=['GET'])
@login_required
@permission_required('manage_resources')
def get_all_resources():
    try:
        resources = Resource.query.all()
        resources_list = [resource_to_dict(r) for r in resources]
        return jsonify(resources_list), 200
    except Exception as e:
        app.logger.exception("Error fetching all resources:")
        return jsonify({'error': 'Failed to fetch resources due to a server error.'}), 500

@app.route('/api/admin/resources/export', methods=['GET'])
@login_required
@permission_required('manage_resources')
def export_all_resources():
    try:
        resources = Resource.query.all()
        resources_list = [resource_to_dict(r) for r in resources]

        # Create a JSON response that prompts a file download
        response = jsonify(resources_list)
        response.headers['Content-Disposition'] = 'attachment; filename=resources_export.json'
        response.mimetype = 'application/json'

        app.logger.info(f"User {current_user.username} exported all resources.")
        add_audit_log(action="EXPORT_ALL_RESOURCES", details=f"User {current_user.username} exported all resources.")
        return response
    except Exception as e:
        app.logger.exception("Error exporting all resources:")
        add_audit_log(action="EXPORT_ALL_RESOURCES_FAILED", details=f"User {current_user.username} failed to export all resources. Error: {str(e)}")
        return jsonify({'error': 'Failed to export resources due to a server error.'}), 500

@app.route('/api/admin/resources/import', methods=['POST'])
@login_required
@permission_required('manage_resources')
def import_resources():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request.'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'File must be a JSON file.'}), 400

    try:
        resources_data = json.load(file)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file.'}), 400

    if not isinstance(resources_data, list):
        return jsonify({'error': 'JSON data must be a list of resource objects.'}), 400

    created_count = 0
    updated_count = 0
    errors = []

    for res_data in resources_data:
        try:
            resource = None
            if 'id' in res_data and res_data['id'] is not None:
                resource = Resource.query.get(res_data['id'])

            if not resource and 'name' in res_data: # If not found by ID, try by name
                resource = Resource.query.filter_by(name=res_data['name']).first()

            if resource: # Update existing resource
                action = "UPDATE_RESOURCE_VIA_IMPORT"
            else: # Create new resource
                resource = Resource()
                action = "CREATE_RESOURCE_VIA_IMPORT"
                if 'name' not in res_data or not res_data['name']:
                    errors.append({'error': 'Missing name for new resource.', 'data': res_data})
                    continue
                # Check for duplicate name before creating a new one explicitly
                if Resource.query.filter_by(name=res_data['name']).first():
                    errors.append({'error': f"Resource with name '{res_data['name']}' already exists.", 'data': res_data})
                    continue


            for key, value in res_data.items():
                if key == 'id': # ID is used for lookup, not set directly unless creating
                    if action == "CREATE_RESOURCE_VIA_IMPORT" and value is not None:
                        # We could allow setting ID if it's unique, but it's safer to let DB assign.
                        # For now, we ignore ID from payload if creating, unless specific logic allows it.
                        # If `id` is part of res_data and it's a new resource, this field is skipped by setattr
                        pass
                    continue
                elif key == 'image_url': # image_url is derived, image_filename is stored
                    continue # Skip direct assignment of image_url
                elif key == 'published_at' and value:
                    resource.published_at = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else None
                elif key == 'maintenance_until' and value:
                    resource.maintenance_until = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else None
                elif key == 'scheduled_status_at' and value:
                    resource.scheduled_status_at = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else None
                elif key == 'map_coordinates' and value:
                    resource.map_coordinates = json.dumps(value) if value else None
                elif key == 'roles':
                    if isinstance(value, list):
                        new_roles = []
                        for role_info in value:
                            role_id = role_info.get('id')
                            role_name = role_info.get('name')
                            role = None
                            if role_id is not None:
                                role = Role.query.get(role_id)
                            elif role_name:
                                role = Role.query.filter_by(name=role_name).first()

                            if role:
                                new_roles.append(role)
                            else:
                                errors.append({'error': f"Role not found: id={role_id}, name={role_name}", 'resource_name': res_data.get('name')})
                        resource.roles = new_roles
                    else:
                        errors.append({'error': "Invalid format for roles, expected a list.", 'resource_name': res_data.get('name')})

                elif hasattr(resource, key):
                    setattr(resource, key, value)
                # else:
                #     app.logger.warning(f"Resource import: Unknown key '{key}' for resource '{res_data.get('name', 'N/A')}'")


            if action == "CREATE_RESOURCE_VIA_IMPORT":
                db.session.add(resource)
                created_count += 1
            else: # Update
                updated_count += 1

            # Commit each resource individually to isolate errors, or commit all at once at the end.
            # Committing individually might be slower but gives more granular error feedback if needed.
            # For now, let's try committing after each resource.
            try:
                db.session.commit()
                add_audit_log(action=action, details=f"Resource '{resource.name}' (ID: {resource.id}) processed via import by {current_user.username}.")
            except Exception as e_commit:
                db.session.rollback()
                errors.append({'error': f"DB error for resource '{res_data.get('name')}': {str(e_commit)}", 'data': res_data})
                if action == "CREATE_RESOURCE_VIA_IMPORT": created_count -=1
                else: updated_count -=1


        except Exception as e_outer:
            db.session.rollback() # Ensure rollback if an error occurs during processing a single resource
            errors.append({'error': f"Error processing resource '{res_data.get('name', 'Unknown')}': {str(e_outer)}", 'data': res_data})

    final_message = f"Import completed. Created: {created_count}, Updated: {updated_count}."
    if errors:
        final_message += f" Errors: {len(errors)}."
        app.logger.warning(f"Resource import by {current_user.username} completed with errors. Created: {created_count}, Updated: {updated_count}, Errors: {len(errors)}. Details: {errors}")
        add_audit_log(action="IMPORT_RESOURCES_WITH_ERRORS", details=final_message + f" Error details: {str(errors[:5])}") # Log first 5 errors
        return jsonify({'message': final_message, 'created': created_count, 'updated': updated_count, 'errors': errors}), 207 # Multi-Status
    else:
        app.logger.info(f"Resource import by {current_user.username} successful. Created: {created_count}, Updated: {updated_count}.")
        add_audit_log(action="IMPORT_RESOURCES_SUCCESS", details=final_message)
        return jsonify({'message': final_message, 'created': created_count, 'updated': updated_count, 'errors': errors}), 200


@app.route('/api/admin/resources', methods=['POST'])
@login_required
@permission_required('manage_resources')
def create_resource():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    name = data.get('name')
    if not name or not name.strip():
        return jsonify({'error': 'Name is required.'}), 400
    existing = Resource.query.filter(func.lower(Resource.name) == func.lower(name.strip())).first()
    if existing:
        return jsonify({'error': f"Resource with name '{name}' already exists."}), 409

    capacity = data.get('capacity')
    try:
        if capacity is not None:
            capacity = int(capacity)
    except (ValueError, TypeError):
        return jsonify({'error': 'Capacity must be an integer or null.'}), 400

    equipment = data.get('equipment')
    tags = data.get('tags')

    new_resource = Resource(name=name.strip(), capacity=capacity, equipment=equipment, tags=tags)
    try:
        db.session.add(new_resource)
        db.session.commit()
        return jsonify(resource_to_dict(new_resource)), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error creating resource:")
        return jsonify({'error': 'Failed to create resource due to a server error.'}), 500

@app.route('/api/admin/resources/bulk', methods=['POST'])
@login_required
@permission_required('manage_resources')
def create_resources_bulk():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    prefix = data.get('prefix', '')
    suffix = data.get('suffix', '')
    start = data.get('start', 1)
    count = data.get('count')
    padding = data.get('padding', 0)

    try:
        start = int(start)
    except (ValueError, TypeError):
        return jsonify({'error': 'start must be an integer.'}), 400

    if count is None:
        return jsonify({'error': 'count is required.'}), 400
    try:
        count = int(count)
        if count <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'count must be a positive integer.'}), 400

    try:
        padding = int(padding)
    except (ValueError, TypeError):
        return jsonify({'error': 'padding must be an integer.'}), 400

    capacity = data.get('capacity')
    try:
        if capacity not in (None, ''):
            capacity = int(capacity)
        else:
            capacity = None
    except (ValueError, TypeError):
        return jsonify({'error': 'Capacity must be an integer or null.'}), 400

    equipment = data.get('equipment')
    tags = data.get('tags')
    status = data.get('status', 'draft')
    valid_statuses = ['draft', 'published', 'archived']
    if status not in valid_statuses:
        return jsonify({'error': f"Invalid status value. Allowed values are: {', '.join(valid_statuses)}."}), 400

    created_resources = []
    skipped = []
    for i in range(count):
        number = str(start + i).zfill(padding) if padding > 0 else str(start + i)
        name = f"{prefix}{number}{suffix}"
        if not name.strip():
            skipped.append(name)
            continue
        existing = Resource.query.filter(func.lower(Resource.name) == func.lower(name.strip())).first()
        if existing:
            skipped.append(name)
            continue
        r = Resource(name=name.strip(), capacity=capacity, equipment=equipment, status=status, tags=tags)
        db.session.add(r)
        created_resources.append(r)
    try:
        db.session.commit()
        return jsonify({'created': [resource_to_dict(r) for r in created_resources], 'skipped': skipped}), 201
    except Exception:
        db.session.rollback()
        app.logger.exception("Error creating resources in bulk:")
        return jsonify({'error': 'Failed to create resources due to a server error.'}), 500


@app.route('/api/admin/resources/bulk', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resources_bulk():
    data = request.get_json()
    if not data or 'ids' not in data or not isinstance(data['ids'], list):
        return jsonify({'error': 'Invalid input. "ids" list required.'}), 400

    ids = data['ids']
    updates = data.get('fields', {})
    if not updates:
        return jsonify({'error': 'No update fields provided.'}), 400

    allowed_fields = ['name', 'capacity', 'equipment', 'status', 'tags']
    valid_statuses = ['draft', 'published', 'archived']

    updated = []
    skipped = []

    for rid in ids:
        resource = Resource.query.get(rid)
        if not resource:
            skipped.append(rid)
            continue
        if 'status' in updates:
            new_status = updates['status']
            if new_status not in valid_statuses:
                return jsonify({'error': f"Invalid status value. Allowed values are: {', '.join(valid_statuses)}."}), 400
            if new_status == 'published' and resource.status != 'published' and resource.published_at is None:
                resource.published_at = datetime.utcnow()
            resource.status = new_status
        for field in allowed_fields:
            if field in updates and field != 'status':
                if field == 'capacity':
                    try:
                        value = updates[field]
                        if value is not None:
                            value = int(value)
                        setattr(resource, field, value)
                    except (ValueError, TypeError):
                        return jsonify({'error': f'Invalid value for capacity. Must be an integer or null.'}), 400
                elif field == 'tags':
                    setattr(resource, field, updates[field])
                else:
                    setattr(resource, field, updates[field])
        updated.append(rid)

    try:
        db.session.commit()
        return jsonify({'updated': updated, 'skipped': skipped}), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Error updating resources in bulk:")
        return jsonify({'error': 'Failed to update resources due to a server error.'}), 500


@app.route('/api/admin/resources/bulk', methods=['DELETE'])
@login_required
@permission_required('manage_resources')
def delete_resources_bulk():
    data = request.get_json()
    if not data or 'ids' not in data or not isinstance(data['ids'], list):
        return jsonify({'error': 'Invalid input. "ids" list required.'}), 400

    ids = data['ids']
    deleted = []
    skipped = []

    for rid in ids:
        resource = Resource.query.get(rid)
        if not resource:
            skipped.append(rid)
            continue
        db.session.delete(resource)
        deleted.append(rid)

    try:
        db.session.commit()
        return jsonify({'deleted': deleted, 'skipped': skipped}), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Error deleting resources in bulk:")
        return jsonify({'error': 'Failed to delete resources due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>', methods=['GET'])
@login_required
@permission_required('manage_resources')
def get_resource_details(resource_id):
    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404
    return jsonify(resource_to_dict(resource)), 200

@app.route('/api/admin/users', methods=['GET'])
@login_required
def get_all_users():
    if not current_user.has_permission('manage_users'):
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    try:
        username_filter = request.args.get('username_filter')
        is_admin_filter = request.args.get('is_admin')
        role_id_filter = request.args.get('role_id', type=int)

        query = User.query

        if username_filter:
            query = query.filter(User.username.ilike(f"%{username_filter}%"))

        if is_admin_filter is not None and is_admin_filter != '':
            val = is_admin_filter.lower()
            if val in ['true', '1', 'yes']:
                query = query.filter_by(is_admin=True)
            elif val in ['false', '0', 'no']:
                query = query.filter_by(is_admin=False)
            else:
                return jsonify({'error': 'Invalid is_admin value. Use true or false.'}), 400

        if role_id_filter:
            query = query.join(User.roles).filter(Role.id == role_id_filter)

        users = query.all()

        users_list = [{
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'is_admin': u.is_admin,
            'google_id': u.google_id,
            'roles': [{'id': role.id, 'name': role.name} for role in u.roles]  # Added roles
        } for u in users]
        app.logger.info(f"Admin user {current_user.username} fetched users list with filters.")
        return jsonify(users_list), 200
    except Exception:
        app.logger.exception("Error fetching all users:")
        return jsonify({'error': 'Failed to fetch users due to a server error.'}), 500

@app.route('/api/admin/users', methods=['POST'])
@login_required
def create_user():
    if not current_user.has_permission('manage_users'):
        add_audit_log(action="CREATE_USER_DENIED", details=f"User {current_user.username} lacks permission 'manage_users'.")
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    is_admin = data.get('is_admin', False) # Default to False if not provided

    if not username or not username.strip():
        return jsonify({'error': 'Username is required.'}), 400
    if not email or not email.strip():
        return jsonify({'error': 'Email is required.'}), 400
    if not password: # Password is required for new user
        return jsonify({'error': 'Password is required.'}), 400
    
    # Basic email validation
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'error': 'Invalid email format.'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': f"Username '{username}' already exists."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': f"Email '{email}' already registered."}), 409

    new_user = User(username=username.strip(), email=email.strip(), is_admin=is_admin)
    new_user.set_password(password)
    
    try:
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"User '{new_user.username}' created successfully by {current_user.username}.")
        add_audit_log(action="CREATE_USER_SUCCESS", details=f"User '{new_user.username}' (ID: {new_user.id}) created. Admin: {new_user.is_admin}.")
        return jsonify({
            'id': new_user.id,
            'username': new_user.username,
            'email': new_user.email,
            'is_admin': new_user.is_admin,
            'google_id': new_user.google_id # Will be None initially
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error creating user '{username}':")
        add_audit_log(action="CREATE_USER_FAILED", details=f"Failed to create user '{username}'. Error: {str(e)}")
        return jsonify({'error': 'Failed to create user due to a server error.'}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    if not current_user.has_permission('manage_users'):
        add_audit_log(action="UPDATE_USER_DENIED", details=f"User {current_user.username} lacks permission 'manage_users' for user ID {user_id}.")
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    user_to_update = User.query.get(user_id)
    if not user_to_update:
        return jsonify({'error': 'User not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    # Update username if provided and changed
    new_username = data.get('username')
    if new_username and new_username.strip() and user_to_update.username != new_username.strip():
        if User.query.filter(User.id != user_id).filter_by(username=new_username.strip()).first():
            return jsonify({'error': f"Username '{new_username.strip()}' already exists."}), 409
        user_to_update.username = new_username.strip()

    # Update email if provided and changed
    new_email = data.get('email')
    if new_email and new_email.strip() and user_to_update.email != new_email.strip():
        if '@' not in new_email or '.' not in new_email.split('@')[-1]:
            return jsonify({'error': 'Invalid email format.'}), 400
        if User.query.filter(User.id != user_id).filter_by(email=new_email.strip()).first():
            return jsonify({'error': f"Email '{new_email.strip()}' already registered."}), 409
        user_to_update.email = new_email.strip()
        # If email changes, should we reset google_id/google_email if they were linked to the old email?
        # For now, this is not handled, but could be a consideration.

    # Update password if provided
    new_password = data.get('password')
    if new_password: # Only update if password is not empty
        user_to_update.set_password(new_password)
        app.logger.info(f"Password updated for user ID {user_id} by {current_user.username}.")

    # Update admin status if provided
    if 'is_admin' in data and isinstance(data['is_admin'], bool):
        # Prevent admin from accidentally de-admining themselves if they are the only admin
        # This check is based on the is_admin flag. A similar check for roles will be added.
        if user_to_update.id == current_user.id and not data['is_admin']:
            num_admins_flag = User.query.filter_by(is_admin=True).count()
            if num_admins_flag == 1:
                app.logger.warning(f"Admin user {current_user.username} attempted to remove their own admin status (is_admin flag) as the sole admin flag holder.")
                # This might be too restrictive if roles are the primary mechanism. Consider if this check is still needed.
                # For now, keeping it as a defense layer.
                # return jsonify({'error': 'Cannot remove is_admin flag from the only user with this flag.'}), 400
        user_to_update.is_admin = data['is_admin']

    # Update roles if 'role_ids' is provided in the payload
    if 'role_ids' in data:
        role_ids = data.get('role_ids', [])
        if not isinstance(role_ids, list):
            return jsonify({'error': 'role_ids must be a list of integers.'}), 400
        
        new_roles = []
        for r_id in role_ids:
            if not isinstance(r_id, int):
                return jsonify({'error': f'Invalid role ID type: {r_id}. Must be integer.'}), 400
            role = Role.query.get(r_id)
            if not role:
                return jsonify({'error': f'Role with ID {r_id} not found.'}), 400
            new_roles.append(role)

        # Safeguard: Prevent removal of "Administrator" role from the last admin user who has it.
        # This counts users who currently have the "Administrator" role.
        admin_role = Role.query.filter_by(name="Administrator").first()
        if admin_role: # Ensure admin role exists
            is_removing_admin_role_from_this_user = admin_role not in new_roles and admin_role in user_to_update.roles
            
            if is_removing_admin_role_from_this_user and user_to_update.id == current_user.id :
                # Check if this user is one of the last users with the Administrator role
                users_with_admin_role = User.query.filter(User.roles.any(id=admin_role.id)).all()
                if len(users_with_admin_role) == 1 and users_with_admin_role[0].id == user_to_update.id:
                    app.logger.warning(f"Admin user {current_user.username} attempted to remove their own 'Administrator' role as the sole holder of this role.")
                    return jsonify({'error': 'Cannot remove the "Administrator" role from the only user holding it.'}), 403
        
        user_to_update.roles = new_roles
        app.logger.info(f"Roles updated for user ID {user_id} by {current_user.username}. New roles: {[r.name for r in new_roles]}")


    try:
        db.session.commit()
        app.logger.info(f"User ID {user_id} ('{user_to_update.username}') updated successfully by {current_user.username}.")
        add_audit_log(action="UPDATE_USER_SUCCESS", details=f"User '{user_to_update.username}' (ID: {user_id}) updated. Data: {str(data)}")
        return jsonify({
            'id': user_to_update.id,
            'username': user_to_update.username,
            'email': user_to_update.email,
            'is_admin': user_to_update.is_admin,
            'google_id': user_to_update.google_id,
            'roles': [{'id': role.id, 'name': role.name} for role in user_to_update.roles] # Return updated roles
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error updating user {user_id}:")
        return jsonify({'error': 'Failed to update user due to a server error.'}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.has_permission('manage_users'):
        add_audit_log(action="DELETE_USER_DENIED", details=f"User {current_user.username} lacks permission 'manage_users' for user ID {user_id}.")
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    user_to_delete = User.query.get(user_id)
    if not user_to_delete:
        return jsonify({'error': 'User not found.'}), 404

    # Safeguard: Prevent admin from deleting themselves via this endpoint
    if current_user.id == user_to_delete.id:
        app.logger.warning(f"Admin user {current_user.username} attempted to delete their own account (ID: {user_id}) via admin endpoint.")
        return jsonify({'error': 'Admins cannot delete their own account through this endpoint. Use a different method if self-deletion is intended and supported.'}), 403

    # Safeguard: Prevent deletion of the only admin user
    if user_to_delete.is_admin:
        num_admins = User.query.filter_by(is_admin=True).count()
        if num_admins == 1:
            app.logger.warning(f"Admin user {current_user.username} attempted to delete the only admin user (ID: {user_id}, Username: {user_to_delete.username}).")
            return jsonify({'error': 'Cannot delete the only admin user in the system.'}), 403
    
    try:
        # Note: Bookings are not directly linked via foreign key from User, but by user_name string.
        # If there's a need to anonymize or reassign bookings, that would be a separate, more complex operation.
        # For now, deleting the user does not affect booking records directly other than orphaning the user_name.
        username_for_log = user_to_delete.username # Capture before deletion
        db.session.delete(user_to_delete)
        db.session.commit()
        app.logger.info(f"User ID {user_id} ('{username_for_log}') deleted successfully by {current_user.username}.")
        add_audit_log(action="DELETE_USER_SUCCESS", details=f"User '{username_for_log}' (ID: {user_id}) deleted by '{current_user.username}'.")
        return jsonify({'message': f"User '{username_for_log}' (ID: {user_id}) deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting user {user_id}:")
        add_audit_log(action="DELETE_USER_FAILED", details=f"Failed to delete user ID {user_id} ('{username_for_log}'). Error: {str(e)}")
        return jsonify({'error': 'Failed to delete user due to a server error.'}), 500

@app.route('/api/admin/users/<int:user_id>/assign_google_auth', methods=['POST'])
@login_required
def assign_google_auth(user_id):
    if not current_user.has_permission('manage_users'):
        add_audit_log(action="ASSIGN_GOOGLE_AUTH_DENIED", details=f"User {current_user.username} lacks permission 'manage_users' for user ID {user_id}.")
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    user_to_update = User.query.get(user_id)
    if not user_to_update:
        return jsonify({'error': 'User not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    google_id_to_assign = data.get('google_id')
    if not google_id_to_assign or not isinstance(google_id_to_assign, str) or not google_id_to_assign.strip():
        return jsonify({'error': 'google_id is required and must be a non-empty string.'}), 400
    
    google_id_to_assign = google_id_to_assign.strip()

    # Check if this Google ID is already used by another user
    existing_user_with_google_id = User.query.filter(User.google_id == google_id_to_assign, User.id != user_id).first()
    if existing_user_with_google_id:
        app.logger.warning(f"Attempt to assign already used Google ID '{google_id_to_assign}' to user {user_id}. It's already linked to user {existing_user_with_google_id.id}.")
        return jsonify({'error': f"Google ID '{google_id_to_assign}' is already associated with another user (ID: {existing_user_with_google_id.id}, Username: {existing_user_with_google_id.username})."}), 409

    user_to_update.google_id = google_id_to_assign
    user_to_update.google_email = None # Clear associated email as it's a manual ID assignment

    try:
        db.session.commit()
        app.logger.info(f"Google ID '{google_id_to_assign}' assigned to user ID {user_id} ('{user_to_update.username}') by {current_user.username}.")
        add_audit_log(action="ASSIGN_GOOGLE_AUTH_SUCCESS", details=f"Google ID '{google_id_to_assign}' assigned to user '{user_to_update.username}' (ID: {user_id}).")
        return jsonify({
            'id': user_to_update.id,
            'username': user_to_update.username,
            'email': user_to_update.email,
            'is_admin': user_to_update.is_admin,
            'google_id': user_to_update.google_id,
            'google_email': user_to_update.google_email
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error assigning Google ID to user {user_id}:")
        return jsonify({'error': 'Failed to assign Google ID due to a server error.'}), 500

@app.route('/api/admin/users/bulk', methods=['DELETE'])
@login_required
def delete_users_bulk():
    if not current_user.has_permission('manage_users'):
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    data = request.get_json()
    if not data or 'ids' not in data or not isinstance(data['ids'], list):
        return jsonify({'error': 'Invalid input. "ids" list required.'}), 400

    ids = data['ids']
    deleted = []
    skipped = []
    for uid in ids:
        user = User.query.get(uid)
        if not user or user.id == current_user.id:
            skipped.append(uid)
            continue
        db.session.delete(user)
        deleted.append(uid)

    try:
        db.session.commit()
        return jsonify({'deleted': deleted, 'skipped': skipped}), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Error deleting users in bulk:")
        return jsonify({'error': 'Failed to delete users due to a server error.'}), 500


@app.route('/api/admin/users/export', methods=['GET'])
@login_required
def export_users():
    if not current_user.has_permission('manage_users'):
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    users = User.query.all()
    roles = Role.query.all()

    users_data = []
    for u in users:
        users_data.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'is_admin': u.is_admin,
            'roles': [r.id for r in u.roles]
        })

    roles_data = []
    for r in roles:
        roles_data.append({
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'permissions': r.permissions
        })

    return jsonify({'users': users_data, 'roles': roles_data}), 200


@app.route('/api/admin/users/import', methods=['POST'])
@login_required
def import_users():
    if not current_user.has_permission('manage_users'):
        return jsonify({'error': 'Permission denied to manage users.'}), 403

    data = request.get_json()
    if not data or 'users' not in data or not isinstance(data['users'], list):
        return jsonify({'error': 'Invalid input. "users" list required.'}), 400

    created = []
    updated = []
    errors = []

    for item in data['users']:
        if 'id' in item:
            user = User.query.get(item['id'])
            if not user:
                errors.append({'id': item['id'], 'error': 'User not found'})
                continue
            if 'username' in item and item['username']:
                if User.query.filter(User.id != user.id, User.username == item['username']).first():
                    errors.append({'id': item['id'], 'error': 'Username already exists'})
                    continue
                user.username = item['username']
            if 'email' in item and item['email']:
                if User.query.filter(User.id != user.id, User.email == item['email']).first():
                    errors.append({'id': item['id'], 'error': 'Email already exists'})
                    continue
                user.email = item['email']
            if 'password' in item and item['password']:
                user.set_password(item['password'])
            if 'is_admin' in item:
                user.is_admin = bool(item['is_admin'])
            if 'role_ids' in item and isinstance(item['role_ids'], list):
                roles = [Role.query.get(rid) for rid in item['role_ids'] if Role.query.get(rid)]
                user.roles = roles
            updated.append(user.id)
        else:
            username = item.get('username')
            email = item.get('email')
            password = item.get('password')
            if not username or not email or not password:
                errors.append({'username': username, 'error': 'Missing required fields'})
                continue
            if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
                errors.append({'username': username, 'error': 'User exists'})
                continue
            new_user = User(username=username, email=email, is_admin=item.get('is_admin', False))
            new_user.set_password(password)
            if 'role_ids' in item and isinstance(item['role_ids'], list):
                roles = [Role.query.get(rid) for rid in item['role_ids'] if Role.query.get(rid)]
                new_user.roles = roles
            db.session.add(new_user)
            db.session.flush()
            created.append(new_user.id)

    try:
        db.session.commit()
        return jsonify({'created': created, 'updated': updated, 'errors': errors}), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Error importing users:")
        return jsonify({'error': 'Failed to import users due to a server error.'}), 500

# --- Waitlist Management APIs ---
@app.route('/api/admin/waitlist', methods=['GET'])
@login_required
def get_waitlist_entries():
    if not current_user.has_permission('manage_resources'):
        return jsonify({'error': 'Permission denied to manage waitlist.'}), 403

    entries = WaitlistEntry.query.order_by(WaitlistEntry.timestamp.asc()).all()
    response_list = []
    for entry in entries:
        user = User.query.get(entry.user_id)
        resource = Resource.query.get(entry.resource_id)
        response_list.append({
            'id': entry.id,
            'resource_id': entry.resource_id,
            'resource_name': resource.name if resource else None,
            'user_id': entry.user_id,
            'username': user.username if user else None,
            'timestamp': entry.timestamp.replace(tzinfo=timezone.utc).isoformat(),
        })
    return jsonify(response_list), 200


@app.route('/api/admin/waitlist/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_waitlist_entry_admin(entry_id):
    if not current_user.has_permission('manage_resources'):
        return jsonify({'error': 'Permission denied to manage waitlist.'}), 403

    entry = WaitlistEntry.query.get(entry_id)
    if not entry:
        return jsonify({'error': 'Waitlist entry not found.'}), 404

    db.session.delete(entry)
    db.session.commit()
    return jsonify({'message': 'Waitlist entry deleted.'}), 200

# --- Role Management APIs ---

# --- Audit Log API ---
@app.route('/api/admin/logs', methods=['GET'])
@login_required
def get_audit_logs():
    if not current_user.has_permission('view_audit_logs'):
        return jsonify({'error': 'Permission denied to view audit logs.'}), 403

    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 30, type=int)
        
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        username_filter = request.args.get('username_filter')
        action_filter = request.args.get('action_filter')

        query = AuditLog.query

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                query = query.filter(AuditLog.timestamp >= datetime.combine(start_date, time.min))
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD.'}), 400
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                # Add one day to make the end_date inclusive for the whole day
                query = query.filter(AuditLog.timestamp < datetime.combine(end_date + timedelta(days=1), time.min))
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD.'}), 400

        if username_filter:
            query = query.filter(AuditLog.username.ilike(f"%{username_filter}%"))
        
        if action_filter:
            query = query.filter(AuditLog.action.ilike(f"%{action_filter}%"))

        pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
        
        logs_list = [{
            'id': log.id,
            'timestamp': log.timestamp.replace(tzinfo=timezone.utc).isoformat(), 
            'user_id': log.user_id,
            'username': log.username,
            'action': log.action,
            'details': log.details
        } for log in pagination.items]

        return jsonify({
            'logs': logs_list,
            'total_logs': pagination.total,
            'current_page': pagination.page,
            'total_pages': pagination.pages,
            'per_page': pagination.per_page
        }), 200

    except Exception as e:
        app.logger.exception("Error fetching audit logs:")
        return jsonify({'error': 'Failed to fetch audit logs due to a server error.'}), 500


@app.route('/api/admin/roles', methods=['GET'])
@login_required
def get_roles():
    if not current_user.has_permission('manage_roles'):
        return jsonify({'error': 'Permission denied to manage roles.'}), 403
    
    roles = Role.query.all()
    roles_list = [{
        'id': role.id,
        'name': role.name,
        'description': role.description,
        'permissions': role.permissions
    } for role in roles]
    return jsonify(roles_list), 200

@app.route('/api/admin/roles', methods=['POST'])
@login_required
def create_role():
    if not current_user.has_permission('manage_roles'):
        add_audit_log(action="CREATE_ROLE_DENIED", details=f"User {current_user.username} lacks permission 'manage_roles'.")
        return jsonify({'error': 'Permission denied to manage roles.'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    name = data.get('name')
    description = data.get('description')
    permissions = data.get('permissions')

    if not name or not name.strip():
        return jsonify({'error': 'Role name is required.'}), 400
    
    # Case-insensitive check for uniqueness
    if Role.query.filter(func.lower(Role.name) == func.lower(name.strip())).first():
        return jsonify({'error': f"Role name '{name.strip()}' already exists."}), 409

    new_role = Role(
        name=name.strip(), 
        description=description.strip() if description else None,
        permissions=permissions.strip() if permissions else None
    )
    
    try:
        db.session.add(new_role)
        db.session.commit()
        app.logger.info(f"Role '{new_role.name}' created successfully by {current_user.username}.")
        add_audit_log(action="CREATE_ROLE_SUCCESS", details=f"Role '{new_role.name}' (ID: {new_role.id}) created with permissions: {new_role.permissions}.")
        return jsonify({
            'id': new_role.id,
            'name': new_role.name,
            'description': new_role.description,
            'permissions': new_role.permissions
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error creating role '{name}':")
        return jsonify({'error': 'Failed to create role due to a server error.'}), 500

@app.route('/api/admin/roles/<int:role_id>', methods=['PUT'])
@login_required
def update_role(role_id):
    if not current_user.has_permission('manage_roles'):
        add_audit_log(action="UPDATE_ROLE_DENIED", details=f"User {current_user.username} lacks permission 'manage_roles' for role ID {role_id}.")
        return jsonify({'error': 'Permission denied to manage roles.'}), 403

    role_to_update = Role.query.get(role_id)
    if not role_to_update:
        return jsonify({'error': 'Role not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    # Protected role check for "Administrator"
    if role_to_update.name == "Administrator":
        if 'name' in data and data.get('name').strip() != "Administrator":
            return jsonify({'error': 'Cannot rename the "Administrator" role.'}), 403
        if 'permissions' in data and data.get('permissions') != "all":
             return jsonify({'error': 'Cannot change permissions of the "Administrator" role.'}), 403
        # Allow description update for Administrator role
        if 'description' in data:
            role_to_update.description = data.get('description', role_to_update.description).strip()

    else: # For roles other than "Administrator"
        new_name = data.get('name')
        if new_name and new_name.strip() and role_to_update.name != new_name.strip():
            # Case-insensitive check
            if Role.query.filter(func.lower(Role.name) == func.lower(new_name.strip()), Role.id != role_id).first():
                return jsonify({'error': f"Role name '{new_name.strip()}' already exists."}), 409
            role_to_update.name = new_name.strip()

        if 'description' in data:
            role_to_update.description = data.get('description', role_to_update.description).strip()
        
        if 'permissions' in data:
            role_to_update.permissions = data.get('permissions', role_to_update.permissions).strip()

    try:
        db.session.commit()
        app.logger.info(f"Role ID {role_id} ('{role_to_update.name}') updated successfully by {current_user.username}.")
        add_audit_log(action="UPDATE_ROLE_SUCCESS", details=f"Role '{role_to_update.name}' (ID: {role_id}) updated. New data: {str(data)}")
        return jsonify({
            'id': role_to_update.id,
            'name': role_to_update.name,
            'description': role_to_update.description,
            'permissions': role_to_update.permissions
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error updating role {role_id}:")
        return jsonify({'error': 'Failed to update role due to a server error.'}), 500

@app.route('/api/admin/roles/<int:role_id>', methods=['DELETE'])
@login_required
def delete_role(role_id):
    if not current_user.has_permission('manage_roles'):
        add_audit_log(action="DELETE_ROLE_DENIED", details=f"User {current_user.username} lacks permission 'manage_roles' for role ID {role_id}.")
        return jsonify({'error': 'Permission denied to manage roles.'}), 403

    role_to_delete = Role.query.get(role_id)
    if not role_to_delete:
        return jsonify({'error': 'Role not found.'}), 404

    # Protected role check
    if role_to_delete.name == "Administrator":
        return jsonify({'error': 'Cannot delete the "Administrator" role.'}), 403
    
    # Check if role is assigned to any users
    if role_to_delete.users.first(): # Checks if the 'users' backref yields any user
        app.logger.warning(f"Attempt to delete role '{role_to_delete.name}' (ID: {role_id}) which is still assigned to users.")
        return jsonify({'error': f"Cannot delete role '{role_to_delete.name}' because it is currently assigned to one or more users."}), 409

    try:
        role_name_for_log = role_to_delete.name # Capture before deletion
        db.session.delete(role_to_delete)
        db.session.commit()
        app.logger.info(f"Role '{role_name_for_log}' (ID: {role_id}) deleted successfully by {current_user.username}.")
        add_audit_log(action="DELETE_ROLE_SUCCESS", details=f"Role '{role_name_for_log}' (ID: {role_id}) deleted.")
        return jsonify({'message': f"Role '{role_name_for_log}' deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting role {role_id}:")
        add_audit_log(action="DELETE_ROLE_FAILED", details=f"Failed to delete role ID {role_id} ('{role_to_delete.name}'). Error: {str(e)}")
        return jsonify({'error': 'Failed to delete role due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['DELETE'])
@login_required
def delete_resource_map_info(resource_id):
    if not current_user.has_permission('manage_resources'):
        add_audit_log(action="DELETE_RESOURCE_MAP_INFO_DENIED", details=f"User {current_user.username} lacks permission 'manage_resources'.")
        return jsonify({'error': 'Permission denied to manage resources.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to delete map info for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.floor_map_id is None and resource.map_coordinates is None:
        app.logger.info(f"Resource {resource_id} is not mapped. No action taken for map info deletion.")
        return jsonify({'message': 'Resource is not currently mapped. No changes made.'}), 200 

    try:
        resource.floor_map_id = None
        resource.map_coordinates = None
        resource_name_for_log = resource.name # Capture before modification
        db.session.commit()
        app.logger.info(f"Map information for resource ID {resource_id} deleted by {current_user.username}.")
        add_audit_log(action="DELETE_RESOURCE_MAP_INFO_SUCCESS", details=f"Map information for resource ID {resource_id} ('{resource_name_for_log}') deleted.")
        return jsonify({'message': f'Map information for resource ID {resource_id} has been deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting map info for resource {resource_id}:")
        add_audit_log(action="DELETE_RESOURCE_MAP_INFO_FAILED", details=f"Failed to delete map info for resource ID {resource_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to delete map information due to a server error.'}), 500

@app.route('/api/map_details/<int:map_id>', methods=['GET'])
def get_map_details(map_id):
    date_str = request.args.get('date')
    target_date_obj = None

    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.warning(f"Invalid date format for map details: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        floor_map = FloorMap.query.get(map_id)
        if not floor_map:
            app.logger.warning(f"Map details requested for non-existent map ID: {map_id}")
            return jsonify({'error': 'Floor map not found.'}), 404

        map_details_response = {
            'id': floor_map.id,
            'name': floor_map.name,
            'image_url': url_for('static', filename=f'floor_map_uploads/{floor_map.image_filename}'),
            'location': floor_map.location,
            'floor': floor_map.floor
        }
        
        # Ensure only published resources are shown on the public map view
        mapped_resources_query = Resource.query.filter(
            Resource.floor_map_id == map_id,
            Resource.map_coordinates.isnot(None),
            Resource.status == 'published' 
        ).all()

        mapped_resources_list = []
        for resource in mapped_resources_query:
            bookings_on_date = Booking.query.filter(
                Booking.resource_id == resource.id,
                func.date(Booking.start_time) == target_date_obj
            ).all()
            bookings_info = [{'title': b.title, 'user_name': b.user_name, 
                              'start_time': b.start_time.strftime('%H:%M:%S'), 
                              'end_time': b.end_time.strftime('%H:%M:%S')} for b in bookings_on_date]
            
            resource_info = {
                'id': resource.id, 'name': resource.name, 'capacity': resource.capacity,
                'equipment': resource.equipment,
                'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None,
                'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
                'booking_restriction': resource.booking_restriction, 'status': resource.status,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids, 
                'roles': [{'id': role.id, 'name': role.name} for role in resource.roles], # Include roles
                'bookings_on_date': bookings_info
            }
            mapped_resources_list.append(resource_info)
        
        app.logger.info(f"Successfully fetched map details for map ID {map_id} for date {target_date_obj}.")
        return jsonify({
            'map_details': map_details_response,
            'mapped_resources': mapped_resources_list
        }), 200

    except Exception as e:
        app.logger.exception(f"Error fetching map details for map_id {map_id}:")
        return jsonify({'error': 'Failed to fetch map details due to a server error.'}), 500

@csrf.exempt # Login endpoint should be exempt from CSRF
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        app.logger.warning("Login attempt with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        app.logger.warning("Login attempt with missing username or password.")
        return jsonify({'error': 'Username and password are required.'}), 400

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        login_user(user)
        user_data = {'id': user.id, 'username': user.username, 'email': user.email, 'is_admin': user.is_admin}
        app.logger.info(f"User '{username}' logged in successfully.")
        add_audit_log(action="LOGIN_SUCCESS", details=f"User '{username}' logged in successfully.", user_id=user.id, username=user.username)
        return jsonify({'success': True, 'message': 'Login successful.', 'user': user_data}), 200
    else:
        app.logger.warning(f"Invalid login attempt for username: {username}")
        add_audit_log(action="LOGIN_FAILED", details=f"Failed login attempt for username: '{username}'.")
        return jsonify({'error': 'Invalid username or password.'}), 401

@csrf.exempt
@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """Log out the current user if authenticated.

    This endpoint previously required authentication which meant a stale session
    cookie resulted in a failed logout attempt on page load.  By removing the
    ``@login_required`` decorator and checking ``current_user`` ourselves we can
    safely treat a request from an anonymous user as a successful logout.
    """
    user_identifier = current_user.username if current_user.is_authenticated else "Anonymous"
    user_id_for_log = current_user.id if current_user.is_authenticated else None

    try:
        # ``logout_user`` is safe to call for anonymous users; it simply clears
        # any user-related session data if present.
        logout_user()
        app.logger.info(f"User '{user_identifier}' logged out successfully.")
        add_audit_log(
            action="LOGOUT_SUCCESS",
            details=f"User '{user_identifier}' logged out.",
            user_id=user_id_for_log,
            username=user_identifier,
        )
        return jsonify({'success': True, 'message': 'Logout successful.'}), 200
    except Exception as e:
        app.logger.exception(f"Error during logout for user {user_identifier}:")
        add_audit_log(
            action="LOGOUT_FAILED",
            details=f"Logout attempt failed for user '{user_identifier}'. Error: {str(e)}",
            user_id=user_id_for_log,
            username=user_identifier,
        )
        return jsonify({'error': 'Logout failed due to a server error.'}), 500

@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    if current_user.is_authenticated:
        user_data = {
            'id': current_user.id, 'username': current_user.username, 
            'email': current_user.email, 'is_admin': current_user.is_admin
        }
        # app.logger.debug(f"Auth status check: User '{current_user.username}' is logged in.") # Too verbose for INFO
        return jsonify({'logged_in': True, 'user': user_data}), 200
    else:
        # app.logger.debug("Auth status check: No user logged in.") # Too verbose for INFO
        return jsonify({'logged_in': False}), 200

@app.route('/api/profile', methods=['PUT'])
@login_required
def update_profile():
    """Update current user's email or password."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    email = data.get('email')
    password = data.get('password')

    if not email and not password:
        return jsonify({'error': 'No changes submitted.'}), 400

    if email:
        if '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'error': 'Invalid email format.'}), 400
        existing = User.query.filter(User.id != current_user.id).filter_by(email=email.strip()).first()
        if existing:
            return jsonify({'error': f"Email '{email.strip()}' already registered."}), 409
        current_user.email = email.strip()

    if password:
        current_user.set_password(password)

    try:
        db.session.commit()
        user_data = {'id': current_user.id, 'username': current_user.username, 'email': current_user.email}
        app.logger.info(f"User {current_user.username} updated their profile.")
        return jsonify({'success': True, 'user': user_data, 'message': 'Profile updated.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error updating profile for user {current_user.username}:")
        return jsonify({'error': 'Failed to update profile due to a server error.'}), 500

@app.route('/api/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.get_json()

    if not data:
        app.logger.warning(f"Booking attempt by {current_user.username} with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource_id = data.get('resource_id')
    date_str = data.get('date_str')
    start_time_str = data.get('start_time_str')
    end_time_str = data.get('end_time_str')
    title = data.get('title')
    user_name_for_record = data.get('user_name')
    recurrence_rule_str = data.get('recurrence_rule')

    required_fields = {'resource_id': resource_id, 'date_str': date_str, 
                       'start_time_str': start_time_str, 'end_time_str': end_time_str}
    missing_fields = [field for field, value in required_fields.items() if value is None]
    if missing_fields:
        app.logger.warning(f"Booking attempt by {current_user.username} missing fields: {', '.join(missing_fields)}")
        return jsonify({'error': f'Missing required field(s): {", ".join(missing_fields)}'}), 400
    
    if not user_name_for_record: # Though logged_in, ensure user_name for record is present
        app.logger.warning(f"Booking attempt by {current_user.username} missing user_name_for_record in payload.")
        return jsonify({'error': 'user_name for the booking record is required in payload.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Booking attempt by {current_user.username} for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    # Permission Enforcement Logic
    can_book = False
    app.logger.info(f"Checking booking permissions for user '{current_user.username}' (ID: {current_user.id}, IsAdmin: {current_user.is_admin}) on resource ID {resource_id} ('{resource.name}').")
    app.logger.debug(f"Resource booking_restriction: '{resource.booking_restriction}', Allowed User IDs: '{resource.allowed_user_ids}', Resource Roles: {[role.name for role in resource.roles]}")

    if current_user.is_admin:
        app.logger.info(f"Booking permitted for admin user '{current_user.username}' on resource {resource_id}.")
        can_book = True
    elif resource.booking_restriction == 'admin_only':
        # This case is technically covered if current_user.is_admin is false, but explicit for clarity
        app.logger.warning(f"Booking denied: Non-admin user '{current_user.username}' attempted to book admin-only resource {resource_id}.")
        # No need to return here, can_book remains False and will be handled at the end.
    else:
        # 1. Check allowed user IDs
        if resource.allowed_user_ids:
            allowed_ids_list = {int(uid.strip()) for uid in resource.allowed_user_ids.split(',') if uid.strip()}
            if current_user.id in allowed_ids_list:
                app.logger.info(f"Booking permitted: User '{current_user.username}' (ID: {current_user.id}) is in allowed_user_ids for resource {resource_id}.")
                can_book = True
        
        # 2. If not allowed by ID, check roles (resource.roles is now a list of Role objects)
        if not can_book and resource.roles: 
            user_role_ids = {role.id for role in current_user.roles}
            resource_allowed_role_ids = {role.id for role in resource.roles}
            app.logger.debug(f"User role IDs: {user_role_ids}, Resource allowed role IDs: {resource_allowed_role_ids}")
            if not user_role_ids.isdisjoint(resource_allowed_role_ids): # Check for any common role ID
                app.logger.info(f"Booking permitted: User '{current_user.username}' has a matching role for resource {resource_id}.")
                can_book = True
        
        # 3. If no specific user IDs or roles are defined for the resource, and it's not admin_only
        # This implies it's open to all authenticated users.
        # The old `booking_restriction == 'all_users'` can be mapped to this condition.
        if not can_book and \
           not (resource.allowed_user_ids and resource.allowed_user_ids.strip()) and \
           not resource.roles and \
           resource.booking_restriction != 'admin_only':
            app.logger.info(f"Booking permitted: Resource {resource_id} is open to all authenticated users (no specific user/role restrictions).")
            can_book = True

    if not can_book:
        app.logger.warning(f"Booking denied for user '{current_user.username}' on resource {resource_id} based on evaluated permissions.")
        # Construct a more informative error message if needed, but for now, a generic one.
        return jsonify({'error': 'You are not authorized to book this resource based on its permission settings.'}), 403

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_h, start_m = map(int, start_time_str.split(':'))
        end_h, end_m = map(int, end_time_str.split(':'))
        new_booking_start_time = datetime.combine(booking_date, time(start_h, start_m))
        new_booking_end_time = datetime.combine(booking_date, time(end_h, end_m))
        if new_booking_end_time <= new_booking_start_time:
            app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid time range: {start_time_str} - {end_time_str}")
            return jsonify({'error': 'End time must be after start time.'}), 400
    except ValueError:
        app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid date/time format: {date_str} {start_time_str}-{end_time_str}")
        return jsonify({'error': 'Invalid date or time format.'}), 400

    if resource.is_under_maintenance and (resource.maintenance_until is None or new_booking_start_time < resource.maintenance_until):
        until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else 'until further notice'
        return jsonify({'error': f'Resource under maintenance until {until_str}.'}), 403

    freq, count = parse_simple_rrule(recurrence_rule_str)
    if recurrence_rule_str and freq is None:
        return jsonify({'error': 'Invalid recurrence rule.'}), 400
    if resource.max_recurrence_count is not None and count > resource.max_recurrence_count:
        return jsonify({'error': 'Recurrence exceeds allowed limit for this resource.'}), 400

    occurrences = []
    for i in range(count):
        delta = timedelta(days=i) if freq == 'DAILY' else timedelta(weeks=i) if freq == 'WEEKLY' else timedelta(0)
        occurrences.append((new_booking_start_time + delta, new_booking_end_time + delta))

    # Check for user's overlapping bookings on ANY resource for the first slot
    # This check is primarily for non-recurring bookings or the very first instance of a recurrence.
    # More specific checks for each recurrence instance are done inside the loop.
    if occurrences: # Only check if there's at least one occurrence
        first_occ_start, first_occ_end = occurrences[0]
        first_slot_user_conflict = Booking.query.filter(
            Booking.user_name == user_name_for_record,
            Booking.start_time < first_occ_end,
            Booking.end_time > first_occ_start
        ).first()

        if first_slot_user_conflict:
            # Ensure resource_booked relationship is loaded to access its name
            # This might require a join or selectinload if not automatically handled by backref,
            # but direct access usually works if the session is active.
            conflicting_resource_name = first_slot_user_conflict.resource_booked.name if first_slot_user_conflict.resource_booked else "an unknown resource"
            return jsonify({'error': f"You already have a booking for resource '{conflicting_resource_name}' from {first_slot_user_conflict.start_time.strftime('%H:%M')} to {first_slot_user_conflict.end_time.strftime('%H:%M')} that overlaps with the requested time slot on {first_occ_start.strftime('%Y-%m-%d')}."}), 409
    
    for occ_start, occ_end in occurrences:
        conflicting = Booking.query.filter(
            Booking.resource_id == resource_id,
            Booking.start_time < occ_end,
            Booking.end_time > occ_start
        ).first()
        if conflicting:
            existing_waitlist_count = WaitlistEntry.query.filter_by(resource_id=resource_id).count()
            if existing_waitlist_count < 2: # Simplified waitlist logic for brevity
                waitlist_entry = WaitlistEntry(resource_id=resource_id, user_id=current_user.id) # Assuming current_user context
                db.session.add(waitlist_entry)
                # db.session.commit() # Commit waitlist entry separately or with main booking transaction
                app.logger.info(f"Added user {current_user.id} to waitlist for resource {resource_id} due to conflict with booking {conflicting.id}")

            return jsonify({'error': f"This time slot ({occ_start.strftime('%Y-%m-%d %H:%M')} to {occ_end.strftime('%Y-%m-%d %H:%M')}) on resource '{resource.name}' is already booked or conflicts. You may have been added to the waitlist if available."}), 409

        # New check: User's overlapping bookings on ANY OTHER resource for this specific recurrence
        user_conflicting_recurring = Booking.query.filter(
            Booking.user_name == user_name_for_record,
            Booking.resource_id != resource_id, # Important: only check OTHER resources
            Booking.start_time < occ_end,
            Booking.end_time > occ_start
        ).first()

        if user_conflicting_recurring:
            conflicting_resource_name = user_conflicting_recurring.resource_booked.name if user_conflicting_recurring.resource_booked else "an unknown resource"
            return jsonify({'error': f"You already have a booking for resource '{conflicting_resource_name}' from {user_conflicting_recurring.start_time.strftime('%H:%M')} to {user_conflicting_recurring.end_time.strftime('%H:%M')} that overlaps with the requested occurrence on {occ_start.strftime('%Y-%m-%d')}."}), 409

    try:
        created = []
        for occ_start, occ_end in occurrences:
            new_booking = Booking(
                resource_id=resource_id,
                start_time=occ_start,
                end_time=occ_end,
                title=title,
                user_name=user_name_for_record,
                recurrence_rule=recurrence_rule_str
            )
            # If your application supports approval workflow, set status here
            db.session.add(new_booking)
            db.session.commit()
            created.append(new_booking)
            add_audit_log(action="CREATE_BOOKING", details=f"Booking ID {new_booking.id} for resource ID {resource_id} ('{resource.name}') created by user '{user_name_for_record}'. Title: '{title}'.")
            socketio.emit('booking_updated', {'action': 'created', 'booking_id': new_booking.id, 'resource_id': resource_id})
        created_data = [{
            'id': b.id,
            'resource_id': b.resource_id,
            'title': b.title,
            'user_name': b.user_name,
            'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'status': b.status,
            'recurrence_rule': b.recurrence_rule
        } for b in created]
        return jsonify({'bookings': created_data}), 201
        
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error creating booking for resource {resource_id} by {current_user.username}:")
        add_audit_log(action="CREATE_BOOKING_FAILED", details=f"Failed to create booking for resource ID {resource_id} by user '{current_user.username}'. Error: {str(e)}")
        return jsonify({'error': 'Failed to create booking due to a server error.'}), 500

@app.route('/api/bookings/my_bookings', methods=['GET'])
@login_required
def get_my_bookings():
    """
    Fetches all bookings for the currently authenticated user.
    Orders bookings by start_time descending (most recent/upcoming first).
    """
    try:
        user_bookings = Booking.query.filter_by(user_name=current_user.username)\
                                     .order_by(Booking.start_time.desc())\
                                     .all()
        
        bookings_list = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            resource_name = resource.name if resource else "Unknown Resource"
            grace = app.config.get('CHECK_IN_GRACE_MINUTES', 15)
            now = datetime.now(timezone.utc)

            # Ensure booking.start_time is offset-aware (UTC) before comparison
            booking_start_time_aware = booking.start_time
            if booking_start_time_aware.tzinfo is None:
                booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

            can_check_in = (
                booking.checked_in_at is None and
                booking_start_time_aware - timedelta(minutes=grace) <= now <= booking_start_time_aware + timedelta(minutes=grace)
            )
            bookings_list.append({
                'id': booking.id,
                'resource_id': booking.resource_id,
                'resource_name': resource_name,
                'user_name': booking.user_name,
                'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end_time': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'title': booking.title,
                'recurrence_rule': booking.recurrence_rule,
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in
            })
        
        app.logger.info(f"User '{current_user.username}' fetched their bookings. Count: {len(bookings_list)}")
        return jsonify(bookings_list), 200

    except Exception as e:
        app.logger.exception(f"Error fetching bookings for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch your bookings due to a server error.'}), 500


@app.route('/api/bookings/my_bookings_for_date', methods=['GET'])
@login_required
def get_my_bookings_for_date():
    """
    Fetches bookings for the currently authenticated user for a specific date.
    Expects a 'date' query parameter in 'YYYY-MM-DD' format.
    """
    date_str = request.args.get('date')
    if not date_str:
        app.logger.warning(f"User '{current_user.username}' called my_bookings_for_date without a date parameter.")
        return jsonify({'error': 'Missing date query parameter. Please provide a date in YYYY-MM-DD format.'}), 400

    try:
        target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        app.logger.warning(f"User '{current_user.username}' provided invalid date format '{date_str}' for my_bookings_for_date.")
        return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    try:
        user_bookings_on_date = db.session.query(
                Booking.id, # Added booking ID
                Booking.title, # Added booking title
                Booking.resource_id,
                Resource.name.label('resource_name'),
                Booking.start_time,
                Booking.end_time
            ).join(Resource, Booking.resource_id == Resource.id)\
            .filter(Booking.user_name == current_user.username)\
            .filter(func.date(Booking.start_time) == target_date_obj)\
            .order_by(Booking.start_time.asc())\
            .all()

        bookings_list = []
        for booking_row in user_bookings_on_date:
            bookings_list.append({
                'booking_id': booking_row.id,
                'title': booking_row.title,
                'resource_id': booking_row.resource_id,
                'resource_name': booking_row.resource_name,
                'start_time': booking_row.start_time.strftime('%H:%M:%S'),
                'end_time': booking_row.end_time.strftime('%H:%M:%S')
            })

        app.logger.info(f"User '{current_user.username}' fetched their bookings for date {date_str}. Count: {len(bookings_list)}")
        return jsonify(bookings_list), 200

    except Exception as e:
        app.logger.exception(f"Error fetching bookings for user '{current_user.username}' on date {date_str}:")
        return jsonify({'error': 'Failed to fetch your bookings for the specified date due to a server error.'}), 500

@app.route('/api/bookings/calendar', methods=['GET'])
@login_required
def bookings_calendar():
    """Return bookings for the current user in FullCalendar format."""
    try:
        user_bookings = Booking.query.filter_by(user_name=current_user.username).all()
        events = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            title = booking.title or (resource.name if resource else 'Booking')
            events.append({
                'id': booking.id,
                'title': title,
                'start': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'recurrence_rule': booking.recurrence_rule,
                'resource_id': booking.resource_id
            })
        return jsonify(events), 200
    except Exception as e:
        app.logger.exception("Error fetching calendar bookings:")
        return jsonify({'error': 'Failed to fetch bookings.'}), 500

@app.route('/api/admin/bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_cancel_booking(booking_id):
    app.logger.info(f"Admin user {current_user.username} attempting to cancel booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            app.logger.warning(f"Admin cancel attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        # Define terminal states where a booking cannot be cancelled
        terminal_statuses = ['cancelled', 'rejected', 'completed', 'checked_out']
        if booking.status and booking.status.lower() in terminal_statuses:
            app.logger.warning(f"Admin cancel attempt: Booking ID {booking_id} is already in a terminal state: '{booking.status}'.")
            return jsonify({'error': f'Booking is already in a terminal state ({booking.status}) and cannot be cancelled.'}), 400

        original_status = booking.status
        booking.status = 'cancelled'

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        booking_title = booking.title or "N/A"

        audit_details = (
            f"Admin '{current_user.username}' cancelled booking ID {booking.id}. "
            f"Original status: '{original_status}'. "
            f"Booked by: '{booking.user_name}'. "
            f"Resource: '{resource_name}' (ID: {booking.resource_id}). "
            f"Title: '{booking_title}'."
        )

        db.session.commit()
        add_audit_log(action="ADMIN_CANCEL_BOOKING", details=audit_details)
        socketio.emit('booking_updated', {'action': 'cancelled_admin', 'booking_id': booking_id, 'resource_id': booking.resource_id, 'new_status': 'cancelled'})


        app.logger.info(f"Admin user {current_user.username} successfully cancelled booking ID: {booking_id}.")
        return jsonify({'message': 'Booking cancelled successfully.', 'booking_id': booking_id, 'new_status': 'cancelled'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error during admin cancellation of booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_CANCEL_BOOKING_FAILED",
            details=f"Admin '{current_user.username}' failed to cancel booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to cancel booking due to a server error.'}), 500

@app.route('/api/bookings/my_booked_resources', methods=['GET'])
@login_required
def get_my_booked_resources():
    """
    Returns a list of unique resources the current user has booked.
    """
    try:
        # Step 1: Get distinct resource_ids booked by the current user
        # Assuming Booking.user_name stores the username of the user who made the booking.
        booked_resource_ids_query = db.session.query(Booking.resource_id)\
            .filter(Booking.user_name == current_user.username)\
            .distinct()\
            .all()
        
        booked_resource_ids = [item[0] for item in booked_resource_ids_query]

        if not booked_resource_ids:
            app.logger.info(f"User '{current_user.username}' has not booked any resources yet.")
            return jsonify([]), 200

        # Step 2: Fetch the details of these resources
        # We are interested in all statuses of resources they have booked, not just 'published'
        resources = Resource.query.filter(Resource.id.in_(booked_resource_ids)).all()
        
        # Step 3: Serialize the resources to dictionary/JSON
        # Using the existing resource_to_dict helper if suitable, or define custom serialization
        resources_list = [resource_to_dict(resource) for resource in resources]
        
        app.logger.info(f"Successfully fetched {len(resources_list)} unique booked resources for user '{current_user.username}'.")
        return jsonify(resources_list), 200

    except Exception as e:
        app.logger.exception(f"Error fetching booked resources for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch booked resources due to a server error.'}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
@login_required
def delete_booking_by_user(booking_id):
    """
    Allows an authenticated user to delete their own booking.
    """
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            app.logger.warning(f"User '{current_user.username}' attempted to delete non-existent booking ID: {booking_id}")
            return jsonify({'error': 'Booking not found.'}), 404

        # Authorization: User can only delete their own bookings.
        if booking.user_name != current_user.username:
            app.logger.warning(f"User '{current_user.username}' unauthorized attempt to delete booking ID: {booking_id} owned by '{booking.user_name}'.")
            return jsonify({'error': 'You are not authorized to delete this booking.'}), 403

        # For audit log: get resource name before deleting booking
        resource_name = "Unknown Resource"
        if booking.resource_booked: # Check if backref is populated
            resource_name = booking.resource_booked.name
        
        booking_start = booking.start_time
        booking_end = booking.end_time
        booking_details_for_log = (
            f"Booking ID: {booking.id}, "
            f"Resource: {resource_name} (ID: {booking.resource_id}), "
            f"Title: '{booking.title}', "
            f"Original User: '{booking.user_name}', "
            f"Time: {booking_start.isoformat()} to {booking_end.isoformat()}"
        )

        db.session.delete(booking)
        db.session.commit()

        if current_user.email:
            send_teams_notification(
                current_user.email,
                "Booking Cancelled",
                f"Your booking for {resource_name} starting at {booking_start.strftime('%Y-%m-%d %H:%M')} has been cancelled."
            )


        # Notify next user on waitlist, if any
        next_entry = (
            WaitlistEntry.query.filter_by(resource_id=booking.resource_id)
            .order_by(WaitlistEntry.timestamp.asc())
            .first()
        )
        if next_entry:
            user_to_notify = User.query.get(next_entry.user_id)
            db.session.delete(next_entry)
            db.session.commit()
            if user_to_notify:
                send_email(
                    user_to_notify.email,
                    f"Slot available for {resource_name}",
                    f"The slot you requested for {resource_name} is now available.",
                )
                if user_to_notify.email:
                    send_teams_notification(
                        user_to_notify.email,
                        "Waitlist Slot Released",
                        f"A slot for {resource_name} is now available to book."
                    )


        add_audit_log(
            action="CANCEL_BOOKING_USER",
            details=f"User '{current_user.username}' cancelled their booking. {booking_details_for_log}"
        )
        socketio.emit('booking_updated', {'action': 'deleted', 'booking_id': booking_id, 'resource_id': booking.resource_id})
        app.logger.info(f"User '{current_user.username}' successfully deleted booking ID: {booking_id}. Details: {booking_details_for_log}")
        return jsonify({'message': 'Booking cancelled successfully.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting booking ID {booking_id} for user '{current_user.username}':")
        # Avoid logging potentially sensitive booking_id in generic error if booking object couldn't be fetched.
        add_audit_log(action="CANCEL_BOOKING_USER_FAILED", details=f"User '{current_user.username}' failed to cancel booking ID: {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to cancel booking due to a server error.'}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['PUT'])
@login_required
def update_booking_by_user(booking_id):
    """
    Allows an authenticated user to update the title, start_time, or end_time of their own booking.
    Expects start_time and end_time as ISO 8601 formatted datetime strings.
    """
    app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request received. User: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    data = request.get_json()
    app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request JSON data: {data}")

    if not data:
        app.logger.warning(f"[API PUT /api/bookings/{booking_id}] No JSON data received.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' attempted to update non-existent booking ID.")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.user_name != current_user.username:
            app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' unauthorized attempt to update booking ID owned by '{booking.user_name}'.")
            return jsonify({'error': 'You are not authorized to update this booking.'}), 403

        # data variable is already defined and logged above.
        # Redundant check `if not data:` is removed as it's covered by the initial check.

        old_title = booking.title
        old_start_time = booking.start_time
        old_end_time = booking.end_time
        
        changes_made = False
        change_details_list = []

        # Handle title update
        if 'title' in data:
            new_title = str(data.get('title', '')).strip()
            if not new_title:
                app.logger.warning(f"User '{current_user.username}' provided empty title for booking {booking_id}.")
                return jsonify({'error': 'Title cannot be empty.'}), 400
            if new_title != old_title:
                booking.title = new_title
                changes_made = True
                change_details_list.append(f"title from '{old_title}' to '{new_title}'")

        # Handle start_time and end_time updates
        new_start_iso = data.get('start_time')
        new_end_iso = data.get('end_time')

        # Determine if time update is intended
        time_update_intended = new_start_iso is not None or new_end_iso is not None
        
        parsed_new_start_time = None
        parsed_new_end_time = None

        if time_update_intended:
            if not new_start_iso or not new_end_iso:
                app.logger.warning(f"User '{current_user.username}' provided incomplete time for booking {booking_id}. Start: {new_start_iso}, End: {new_end_iso}")
                return jsonify({'error': 'Both start_time and end_time are required if one is provided.'}), 400
            try:
                parsed_new_start_time = datetime.fromisoformat(new_start_iso)
                parsed_new_end_time = datetime.fromisoformat(new_end_iso)
            except ValueError:
                app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided invalid ISO format. Start: {new_start_iso}, End: {new_end_iso}")
                return jsonify({'error': 'Invalid datetime format. Use ISO 8601.'}), 400

            if parsed_new_start_time >= parsed_new_end_time:
                app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided start_time not before end_time.")
                return jsonify({'error': 'Start time must be before end time.'}), 400

            resource = Resource.query.get(booking.resource_id)
            if not resource: 
                app.logger.error(f"[API PUT /api/bookings/{booking_id}] Resource ID {booking.resource_id} for booking {booking_id} not found during update.")
                return jsonify({'error': 'Associated resource not found.'}), 500
            
            # Check for maintenance conflict ONLY IF the new time range is different from old,
            # to allow title changes for bookings already in maintenance.
            time_changed = parsed_new_start_time != old_start_time or parsed_new_end_time != old_end_time
            if time_changed and resource.is_under_maintenance:
                # Check if the new booking period overlaps with the maintenance period
                maintenance_active = False
                if resource.maintenance_until is None: # Indefinite maintenance
                    maintenance_active = True
                else: # Maintenance with an end date
                    if parsed_new_start_time < resource.maintenance_until or parsed_new_end_time <= resource.maintenance_until:
                        maintenance_active = True
                
                if maintenance_active:
                    # Further check: if the *original* booking was already entirely within this maintenance, allow time changes within it.
                    # This is complex. For now, a simpler check: if new times fall into active maintenance, reject.
                    # A more nuanced check might be needed if bookings *during* maintenance are allowed to be shifted.
                    # Current logic: if resource is under maintenance and new times are proposed, check them.
                    maint_until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else "indefinitely"
                    app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Booking update conflicts with resource maintenance (until {maint_until_str}).")
                    return jsonify({'error': f'Resource is under maintenance until {maint_until_str} and the new time slot falls within this period.'}), 403

            # Conflict checking with other bookings
            if time_changed:
                conflicting_booking = Booking.query.filter(
                    Booking.resource_id == booking.resource_id,
                    Booking.id != booking_id,  # Exclude the current booking
                    Booking.start_time < parsed_new_end_time,
                    Booking.end_time > parsed_new_start_time
                ).first()

                if conflicting_booking:
                    app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Update conflicts with existing booking {conflicting_booking.id} for resource {booking.resource_id}.")
                    return jsonify({'error': 'The updated time slot conflicts with an existing booking.'}), 409
            
            if time_changed:
                booking.start_time = parsed_new_start_time
                booking.end_time = parsed_new_end_time
                changes_made = True
                change_details_list.append(f"time from {old_start_time.isoformat()} to {parsed_new_start_time.isoformat()}-{parsed_new_end_time.isoformat()}")

        if not changes_made:
            app.logger.info(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' submitted update with no actual changes.")
            return jsonify({'error': 'No changes supplied.'}), 400

        app.logger.info(f"[API PUT /api/bookings/{booking_id}] Attempting to commit changes to DB: Title='{booking.title}', Start='{booking.start_time.isoformat()}', End='{booking.end_time.isoformat()}'")
        db.session.commit()
        app.logger.info(f"[API PUT /api/bookings/{booking_id}] DB commit successful.")
        
        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"

        # Send update email if times changed
        if mail_available and current_user.email and any("time from" in change for change in change_details_list):
            try:
                msg = Message( # This will now use the global mail object's Message class if mail_available is True
                    subject="Booking Updated",
                    recipients=[current_user.email],
                    body=(
                        f"Your booking for {resource_name} has been updated.\n"
                        f"New Title: {booking.title}\n"
                        f"New Start Time: {booking.start_time.strftime('%Y-%m-%d %H:%M')}\n"
                        f"New End Time: {booking.end_time.strftime('%Y-%m-%d %H:%M')}\n"
                    ),
                    sender=app.config.get('MAIL_DEFAULT_SENDER') # Added sender
                )
                mail.send(msg) # This will use the global mail object
                app.logger.info(f"Booking update email sent to {current_user.email} via Flask-Mail.")
            except Exception as mail_e: # Use different variable name for mail exception
                app.logger.exception(f"[API PUT /api/bookings/{booking_id}] Failed to send booking update email to {current_user.email} via Flask-Mail: {mail_e}")
        
        change_summary_text = '; '.join(change_details_list)
        add_audit_log(
            action="UPDATE_BOOKING_USER",
            details=(
                f"User '{current_user.username}' updated booking ID: {booking.id} "
                f"for resource '{resource_name}'. Changes: {change_summary_text}."
            )
        )
        app.logger.info(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' successfully updated booking. Changes: {change_summary_text}.")
        
        # Log the successful response being sent
        response_data = {
            'id': booking.id,
            'resource_id': booking.resource_id,
            'resource_name': resource_name, 
            'user_name': booking.user_name,
            'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'title': booking.title
        }
        app.logger.info(f"[API PUT /api/bookings/{booking_id}] Sending successful response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        db.session.rollback()
        # Enhanced logging for exceptions
        app.logger.exception(f"[API PUT /api/bookings/{booking_id}] Critical error during booking update for user '{current_user.username if current_user.is_authenticated else 'Anonymous'}'. Error: {str(e)}")
        add_audit_log(action="UPDATE_BOOKING_USER_FAILED", details=f"User '{current_user.username if current_user.is_authenticated else 'Anonymous'}' failed to update booking ID: {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to update booking due to a server error.'}), 500


@app.route('/api/bookings/<int:booking_id>/check_in', methods=['POST'])
@login_required
def check_in_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found.'}), 404
    if booking.user_name != current_user.username:
        return jsonify({'error': 'You are not authorized to check in for this booking.'}), 403
    if booking.checked_in_at:
        return jsonify({'error': 'Booking already checked in.'}), 400
    now = datetime.now(timezone.utc)
    grace = app.config.get('CHECK_IN_GRACE_MINUTES', 15)
    if now < booking.start_time - timedelta(minutes=grace) or now > booking.start_time + timedelta(minutes=grace):
        return jsonify({'error': 'Check-in not allowed at this time.'}), 400
    booking.checked_in_at = now
    db.session.commit()
    return jsonify({'message': 'Checked in successfully.', 'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat()}), 200


@app.route('/api/bookings/<int:booking_id>/check_out', methods=['POST'])
@login_required
def check_out_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found.'}), 404
    if booking.user_name != current_user.username:
        return jsonify({'error': 'You are not authorized to check out of this booking.'}), 403
    if not booking.checked_in_at:
        return jsonify({'error': 'Cannot check out without checking in.'}), 400
    if booking.checked_out_at:
        return jsonify({'error': 'Booking already checked out.'}), 400
    booking.checked_out_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'message': 'Checked out successfully.', 'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat()}), 200


@app.route('/admin/bookings/pending', methods=['GET'])
@login_required
def list_pending_bookings():
    if not current_user.is_admin:
        return abort(403)
    pending = Booking.query.filter_by(status='pending').all()
    result = []
    for b in pending:
        result.append({
            'id': b.id,
            'resource_id': b.resource_id,
            'resource_name': b.resource_booked.name if b.resource_booked else None,
            'user_name': b.user_name,
            'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'title': b.title,
        })
    return jsonify(result), 200


@app.route('/admin/bookings/<int:booking_id>/approve', methods=['POST'])
@login_required
def approve_booking_admin(booking_id):
    if not current_user.is_admin:
        return abort(403)
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'approved'
    db.session.commit()
    user = User.query.filter_by(username=booking.user_name).first()
    if user:
        send_email(user.email, 'Booking Approved',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been approved.")
    send_slack_notification(f"Booking {booking.id} approved by {current_user.username}")
    return jsonify({'success': True}), 200


@app.route('/admin/bookings/<int:booking_id>/reject', methods=['POST'])
@login_required
def reject_booking_admin(booking_id):
    if not current_user.is_admin:
        return abort(403)
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'rejected'
    db.session.commit()
    user = User.query.filter_by(username=booking.user_name).first()
    if user:
        send_email(user.email, 'Booking Rejected',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been rejected.")
    send_slack_notification(f"Booking {booking.id} rejected by {current_user.username}")
    return jsonify({'success': True}), 200

# Register blueprint after routes are defined
app.register_blueprint(analytics_bp)

# --- Booking Check-in Background Job ---
def cancel_unchecked_bookings():
    with app.app_context():
        grace_minutes = app.config.get('CHECK_IN_GRACE_MINUTES', 15)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
        stale = Booking.query.filter(
            Booking.checked_in_at.is_(None),
            Booking.start_time < cutoff
        ).all()
        if stale:
            for b in stale:
                db.session.delete(b)
            db.session.commit()
            app.logger.info(f"Auto-cancelled {len(stale)} unchecked bookings")

scheduler = BackgroundScheduler()
scheduler.add_job(
    cancel_unchecked_bookings,
    'interval',
    minutes=app.config.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5)
)

# --- Scheduled Resource Status Change Job ---
def apply_scheduled_resource_status_changes():
    with app.app_context(): # Required for database operations outside of Flask request context
        now = datetime.now(timezone.utc)
        # Query for resources that have a scheduled_status_at in the past or present,
        # and have a non-null, non-empty scheduled_status.
        resources_to_update = Resource.query.filter(
            Resource.scheduled_status_at.isnot(None),
            Resource.scheduled_status_at <= now,
            Resource.scheduled_status.isnot(None),
            Resource.scheduled_status != ""  # Explicitly exclude empty string as a target status
        ).all()

        if not resources_to_update:
            # app.logger.info("No resource status changes to apply at this time.") # Optional: for debugging
            return

        for resource in resources_to_update:
            old_status = resource.status
            new_status = resource.scheduled_status # This is now guaranteed not to be None or ""
            
            app.logger.info(
                f"Applying scheduled status change for resource {resource.id} ('{resource.name}') "
                f"from '{old_status}' to '{new_status}' scheduled for {resource.scheduled_status_at.isoformat()}"
            )
            
            resource.status = new_status
            
            # Handle published_at logic if status changes to 'published'
            if new_status == 'published' and old_status != 'published':
                # Set/update published_at when transitioning to 'published'
                # This aligns with how publish_resource endpoint behaves (sets it unconditionally)
                # and how update_resource_details behaves (sets if it was None and changing to published).
                # Using `resource.scheduled_status_at` for precision, or `now` if that's preferred.
                resource.published_at = resource.scheduled_status_at 
            
            add_audit_log(
                action="SYSTEM_APPLY_SCHEDULED_STATUS",
                details=(
                    f"Resource {resource.id} ('{resource.name}') status automatically changed "
                    f"from '{old_status}' to '{new_status}' as scheduled for {resource.scheduled_status_at.isoformat()}."
                ),
                username="System" # Explicitly mark as a system action
            )
            
            # Clear the scheduled fields after applying the change
            resource.scheduled_status = None
            resource.scheduled_status_at = None
        
        try:
            db.session.commit()
            app.logger.info(f"Successfully applied scheduled status changes for {len(resources_to_update)} resources.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error committing scheduled status changes: {e}", exc_info=True)

# Add the new job to the scheduler
scheduler.add_job(
    apply_scheduled_resource_status_changes,
    'interval',
    minutes=1 # Check every minute, or a longer interval like 5 minutes
)

if backup_if_changed:
    scheduler.add_job(
        backup_if_changed,
        'interval',
        minutes=app.config.get('AZURE_BACKUP_INTERVAL_MINUTES', 60)
    )

# Add the scheduled backup job
scheduler.add_job(
    func=run_scheduled_backup_job,
    trigger='interval',
    minutes=60 # Check every hour
)


# Exported names for easier importing in tests and other modules
__all__ = [
    "app",
    "db",
    "User",
    "Resource",
    "Booking",
    "WaitlistEntry",
    "FloorMap",
    "email_log",
    "teams_log",
    "scheduler",
]

@app.route('/ping')
def ping():
    # Ensure necessary imports are at the top of app.py:
    # from flask import jsonify
    # from datetime import datetime, timezone
    return jsonify(message='pong', timestamp=datetime.now(timezone.utc).isoformat()), 200

@app.route('/debug/list_routes')
def debug_list_routes():
    # Ensure necessary imports are at the top of app.py:
    # from flask import jsonify
    # import urllib
    output = []
    for rule in app.url_map.iter_rules():
        options = {}
        for arg in rule.arguments:
            options[arg] = f"[{arg}]"

        methods = ','.join(sorted(rule.methods))
        # url = urllib.parse.unquote(url_for(rule.endpoint, **options)) # This can fail if rule has no args or complex ones
        url = str(rule) # Rule.rule gives the path pattern
        line = f"{url:50s} {methods:20s} {rule.endpoint:20s}"
        output.append(line)

    # Sort output for easier reading
    output.sort()

    # Create a simple HTML response for better readability in the browser
    html_output = "<html><head><title>Registered Routes</title></head><body><pre>"
    html_output += "\n".join(output)
    html_output += "</pre></body></html>"

    # Return as HTML
    return html_output, 200

# --- Backup and Restore API Routes ---

@app.route('/api/admin/one_click_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_one_click_backup():
    app.logger.info(f"User {current_user.username} initiated one-click backup.")
    task_id = uuid.uuid4().hex
    app.logger.info(f"Generated task_id {task_id} for one-click backup.")

    if not create_full_backup:
        app.logger.error("Azure backup module not available for one-click backup.")
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'task_id': task_id}), 500
    try:
        timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        map_config_data = _get_map_configuration_data()
        success = create_full_backup(
            timestamp_str,
            map_config_data=map_config_data,
            socketio_instance=socketio,
            task_id=task_id
        )
        if success:
            message = f"Backup process initiated with timestamp {timestamp_str}. See live logs for completion status."
            app.logger.info(f"One-click backup process for task {task_id} (timestamp {timestamp_str}) completed with overall success: {success}.")
            add_audit_log(action="ONE_CLICK_BACKUP_COMPLETED", details=f"Task {task_id}, Timestamp {timestamp_str}, Success: {success}")
            return jsonify({'success': True, 'message': message, 'task_id': task_id, 'timestamp': timestamp_str}), 200
        else:
            message = "Backup process initiated but reported failure. Check server logs for details."
            app.logger.error(f"One-click backup process for task {task_id} (timestamp {timestamp_str}) failed.")
            add_audit_log(action="ONE_CLICK_BACKUP_COMPLETED_WITH_FAILURES", details=f"Task {task_id}, Timestamp {timestamp_str}, Success: {success}")
            return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500
    except Exception as e:
        app.logger.exception(f"Exception during one-click backup (task {task_id}) initiated by {current_user.username}:")
        add_audit_log(action="ONE_CLICK_BACKUP_ERROR", details=f"Task {task_id}, Exception: {str(e)}")
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}', 'task_id': task_id}), 500

@app.route('/api/admin/list_backups', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_backups():
    app.logger.info(f"User {current_user.username} requested list of available backups.")
    if not list_available_backups:
        app.logger.error("Azure backup module not available for listing backups.")
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'backups': []}), 500
    try:
        backups = list_available_backups()
        app.logger.info(f"Found {len(backups)} available backups.")
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        app.logger.exception(f"Exception listing available backups for user {current_user.username}:")
        return jsonify({'success': False, 'message': f'An error occurred while listing backups: {str(e)}', 'backups': []}), 500

@app.route('/api/admin/one_click_restore', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_one_click_restore():
    data = request.get_json()
    task_id = uuid.uuid4().hex

    if not data or 'backup_timestamp' not in data:
        app.logger.warning(f"Restore attempt (task {task_id}) with missing backup_timestamp.")
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400

    backup_timestamp = data['backup_timestamp']
    app.logger.info(f"User {current_user.username} initiated restore (task {task_id}) for timestamp: {backup_timestamp}.")

    if not restore_full_backup or not _import_map_configuration_data:
        app.logger.error(f"Azure backup or map import module not available for restore (task {task_id}).")
        if socketio:
             socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore module not configured on server.', 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': 'Restore module is not configured or available.', 'task_id': task_id}), 500

    try:
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore process starting...', 'detail': f'Timestamp: {backup_timestamp}'})

        restored_db_path, map_config_json_path = restore_full_backup(
            backup_timestamp,
            socketio_instance=socketio,
            task_id=task_id
        )

        if not restored_db_path:
            message = f"Restore (task {task_id}) failed during file download phase for timestamp {backup_timestamp}."
            app.logger.error(message)
            add_audit_log(action="ONE_CLICK_RESTORE_FILE_OPS_FAILED", details=message)
            return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500

        app.logger.info(f"Database restored (task {task_id}) for backup {backup_timestamp} to {restored_db_path}.")

        map_import_summary_msg = "Map configuration file was not part of this backup or was not downloaded."
        if map_config_json_path and os.path.exists(map_config_json_path):
            app.logger.info(f"Map config JSON {map_config_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio:
                socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing map configuration...', 'detail': map_config_json_path})
            try:
                with open(map_config_json_path, 'r', encoding='utf-8') as f:
                    map_config_data_to_import = json.load(f)
                import_summary, import_status_code = _import_map_configuration_data(map_config_data_to_import)
                map_import_summary_msg = f"Map configuration import from {backup_timestamp} completed with status {import_status_code}."
                if socketio:
                    socketio.emit('restore_progress', {'task_id': task_id, 'status': f'Map configuration import status: {import_status_code}', 'detail': map_import_summary_msg})
                if import_status_code >= 400:
                    app.logger.error(f"Failed to import map config (task {task_id}): {json.dumps(import_summary)}")
                else:
                    app.logger.info(f"Successfully imported map config (task {task_id}).")
            except Exception as map_import_exc:
                map_import_summary_msg = f"Error processing map config file {map_config_json_path} (task {task_id}): {str(map_import_exc)}"
                app.logger.exception(map_import_summary_msg)
                if socketio:
                    socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Error during map configuration import.', 'detail': str(map_import_exc)})
            finally:
                try:
                    os.remove(map_config_json_path)
                except OSError as e_remove:
                    app.logger.error(f"Error removing temp map config file {map_config_json_path} (task {task_id}): {e_remove}")
        else:
            app.logger.info(f"No map config file for {backup_timestamp} (task {task_id}). Skipping map import.")
            if socketio:
                 socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Map configuration import skipped (no file).'})

        final_message = f"Restore (task {task_id}) from {backup_timestamp} file ops completed. DB restored. {map_import_summary_msg} Restart app."
        app.logger.info(final_message)
        add_audit_log(action="ONE_CLICK_RESTORE_COMPLETED", details=final_message)
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore process fully completed. Please restart application.', 'detail': 'SUCCESS'})
        return jsonify({'success': True, 'message': 'Restore process initiated. See live logs.', 'task_id': task_id}), 200
    except Exception as e:
        app.logger.exception(f"Critical exception during restore (task {task_id}) for {backup_timestamp}:")
        add_audit_log(action="ONE_CLICK_RESTORE_CRITICAL_ERROR", details=f"Task {task_id}, Exception: {str(e)} for {backup_timestamp}")
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': f'Critical error during restore: {str(e)}', 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': f'An unexpected critical error: {str(e)}', 'task_id': task_id}), 500

@app.route('/api/admin/restore_dry_run/<string:backup_timestamp>', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_dry_run(backup_timestamp):
    task_id = uuid.uuid4().hex
    # backup_timestamp is from URL parameter
    app.logger.info(f"User {current_user.username} initiated RESTORE DRY RUN (task {task_id}) for timestamp: {backup_timestamp}.")

    if not restore_full_backup:
        app.logger.error(f"Azure backup module not available for restore dry run (task {task_id}).")
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run: Backup module not configured on server.', 'detail': 'ERROR', 'actions': []})
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'task_id': task_id, 'actions': []}), 500

    try:
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run starting...', 'detail': f'Timestamp: {backup_timestamp}', 'actions': []})

        # restore_full_backup(dry_run=True) returns (None, None, actions_list)
        # It emits its own SocketIO messages for detailed steps, including "backup not found".
        db_path_placeholder, map_config_path_placeholder, actions_list = restore_full_backup(
            backup_timestamp,
            dry_run=True,
            socketio_instance=socketio,
            task_id=task_id
        )

        final_actions_list = list(actions_list) # Ensure it's a list

        # The logic for "backup not found" (where db_path_placeholder would be None) is tricky
        # because for a dry run, db_path_placeholder is *always* None from azure_backup.py.
        # azure_backup.py's restore_full_backup is responsible for emitting a SocketIO message
        # if the backup is not found (e.g., "DRY RUN: Backup timestamp X not found...").
        # If that specific error occurs, actions_list would likely be empty.
        # This API endpoint will thus report completion, and the UI will show the detailed error from azure_backup.

        # Check if azure_backup.py indicated map config would be processed (it adds specific actions for this)
        # The current task asks to append "DRY RUN: Would import map configuration..." if map_config_path_placeholder is not None.
        # However, map_config_path_placeholder is always None for dry_run.
        # The actions_list from azure_backup.py should already detail this.
        # For simplicity and to avoid duplicate messages, we trust actions_list from azure_backup.py.
        # No specific check for map_config_path_placeholder here to add more actions.

        message = f"Restore Dry Run (task {task_id}) for {backup_timestamp} completed."
        app.logger.info(message)
        # Log the number of actions that would be performed.
        add_audit_log(action="RESTORE_DRY_RUN_COMPLETED", details=f"{message} Actions: {len(final_actions_list)} items.")

        if socketio:
            # The 'actions' field here will deliver the list of actions to the UI.
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run completed.', 'detail': 'SUCCESS', 'actions': final_actions_list})

        return jsonify({'success': True, 'message': message, 'task_id': task_id, 'actions': final_actions_list}), 200

    except Exception as e:
        app.logger.exception(f"Critical exception during restore dry run (task {task_id}) for {backup_timestamp}:")
        add_audit_log(action="RESTORE_DRY_RUN_CRITICAL_ERROR", details=f"Task {task_id}, Exception: {str(e)} for {backup_timestamp}")
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': f'DRY RUN: Critical error: {str(e)}', 'detail': 'ERROR', 'actions': []})
        return jsonify({'success': False, 'message': f'An unexpected critical error during dry run: {str(e)}', 'task_id': task_id, 'actions': []}), 500


@app.route('/api/admin/selective_restore', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_selective_restore():
    data = request.get_json()
    task_id = uuid.uuid4().hex

    if not data:
        return jsonify({'success': False, 'message': 'Invalid input. JSON data expected.', 'task_id': task_id}), 400

    backup_timestamp = data.get('backup_timestamp')
    components = data.get('components') # Expected to be a list of strings

    if not backup_timestamp:
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400
    if not components or not isinstance(components, list) or not all(isinstance(c, str) for c in components):
        return jsonify({'success': False, 'message': 'Components list is required and must be a list of strings.', 'task_id': task_id}), 400
    if not components: # Empty list check
        return jsonify({'success': False, 'message': 'At least one component must be selected for selective restore.', 'task_id': task_id}), 400


    app.logger.info(f"User {current_user.username} initiated SELECTIVE RESTORE (task {task_id}) for ts: {backup_timestamp}, components: {components}.")
    if socketio:
        socketio.emit('restore_progress', {
            'task_id': task_id,
            'status': 'Selective Restore process starting...',
            'detail': f'Timestamp: {backup_timestamp}, Components: {", ".join(components)}'
        })

    overall_success = True # Assume success until a component fails
    actions_performed_summary = []

    # These will store actual paths if component runs, or placeholders if azure_backup component returns them for dry_run (not applicable here as dry_run=False)
    final_restored_db_path = None
    final_downloaded_map_config_path = None

    # Ensure azure_backup and its components are loaded
    if not restore_full_backup: # Used as a proxy to check if azure_backup module loaded its functions
        message = "Selective Restore failed: Backup module is not configured or available."
        app.logger.error(message)
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': message, 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500

    try:
        service_client = azure_backup._get_service_client() # Use the helper from azure_backup
        # Get share clients - it's okay if they don't exist yet, component functions will check _client_exists
        db_share_client = service_client.get_share_client(os.environ.get('AZURE_DB_SHARE', 'db-backups'))
        config_share_client = service_client.get_share_client(os.environ.get('AZURE_CONFIG_SHARE', 'config-backups'))
        media_share_client = service_client.get_share_client(os.environ.get('AZURE_MEDIA_SHARE', 'media'))

        if 'database' in components:
            if not azure_backup._client_exists(db_share_client):
                db_msg = f"Database component skipped: Share '{db_share_client.share_name}' does not exist."
                app.logger.warning(db_msg)
                actions_performed_summary.append(db_msg)
                overall_success = False # Or treat as partial success, depending on desired strictness
            else:
                db_success, db_msg, _, db_path = azure_backup.restore_database_component(
                    backup_timestamp, db_share_client, dry_run=False, socketio_instance=socketio, task_id=task_id
                )
                actions_performed_summary.append(f"Database: {db_msg}")
                if db_success:
                    final_restored_db_path = db_path
                else:
                    overall_success = False # DB restore failure is critical for this component's success

        if 'map_config' in components:
            if not azure_backup._client_exists(config_share_client):
                mc_msg = f"Map Config component skipped: Share '{config_share_client.share_name}' does not exist."
                app.logger.warning(mc_msg)
                actions_performed_summary.append(mc_msg)
                # overall_success = False # Typically map config is not critical to halt others
            else:
                mc_success, mc_msg, _, mc_path = azure_backup.download_map_config_component(
                    backup_timestamp, config_share_client, dry_run=False, socketio_instance=socketio, task_id=task_id
                )
                actions_performed_summary.append(f"Map Config Download: {mc_msg}")
                if mc_success and mc_path and os.path.exists(mc_path):
                    final_downloaded_map_config_path = mc_path
                    app.logger.info(f"Map config JSON {mc_path} downloaded for selective restore (task {task_id}).")
                    socketio_detail = f"Importing map configuration from {mc_path}"
                    if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': socketio_detail })
                    try:
                        with open(mc_path, 'r', encoding='utf-8') as f:
                            map_data_to_import = json.load(f)
                        import_summary, import_status_code = _import_map_configuration_data(map_data_to_import)
                        map_import_summary_msg = f"Map config import from {mc_path} status: {import_status_code}. Summary: {json.dumps(import_summary)}"
                        actions_performed_summary.append(map_import_summary_msg)
                        if import_status_code >= 400:
                            app.logger.error(f"Failed map config import (task {task_id}): {map_import_summary_msg}")
                            overall_success = False
                        else:
                            app.logger.info(f"Successful map config import (task {task_id}).")
                        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': map_import_summary_msg})
                    except Exception as map_import_exc:
                        err_msg = f"Error processing map config file {mc_path} (task {task_id}): {str(map_import_exc)}"
                        actions_performed_summary.append(err_msg)
                        app.logger.exception(err_msg)
                        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': err_msg, 'detail': 'ERROR'})
                        overall_success = False
                    finally:
                        try:
                            os.remove(mc_path)
                        except OSError as e_remove:
                            app.logger.error(f"Error removing temp map config file {mc_path} (task {task_id}): {e_remove}")
                elif not mc_success: # Download failed
                    overall_success = False

        # Media components
        if 'floor_maps' in components or 'resource_uploads' in components:
            if not azure_backup._client_exists(media_share_client):
                media_msg = f"Media components (floor_maps, resource_uploads) skipped: Share '{media_share_client.share_name}' does not exist."
                app.logger.warning(media_msg)
                actions_performed_summary.append(media_msg)
                if 'floor_maps' in components : overall_success = False
                if 'resource_uploads' in components : overall_success = False
            else:
                if 'floor_maps' in components:
                    # Constants like FLOOR_MAP_UPLOADS are directly from azure_backup module
                    fm_success, fm_msg, _ = azure_backup.restore_media_component(
                        backup_timestamp, "FloorMaps", azure_backup.FLOOR_MAP_UPLOADS,
                        f"floor_map_uploads", # Pass base name, component adds _{timestamp_str}
                        media_share_client, dry_run=False, socketio_instance=socketio, task_id=task_id
                    )
                    actions_performed_summary.append(f"Floor Maps: {fm_msg}")
                    if not fm_success: overall_success = False

                if 'resource_uploads' in components:
                    ru_success, ru_msg, _ = azure_backup.restore_media_component(
                        backup_timestamp, "ResourceUploads", azure_backup.RESOURCE_UPLOADS,
                        f"resource_uploads", # Pass base name
                        media_share_client, dry_run=False, socketio_instance=socketio, task_id=task_id
                    )
                    actions_performed_summary.append(f"Resource Uploads: {ru_msg}")
                    if not ru_success: overall_success = False

        final_status_message = f"Selective restore (task {task_id}) for {backup_timestamp} components {components} finished. Overall Success: {overall_success}. Details: {'; '.join(actions_performed_summary)}"
        app.logger.info(final_status_message)
        add_audit_log(action="SELECTIVE_RESTORE_COMPLETED", details=final_status_message)
        if socketio:
            socketio.emit('restore_progress', {
                'task_id': task_id,
                'status': 'Selective restore process completed.',
                'detail': 'SUCCESS' if overall_success else 'PARTIAL_FAILURE',
                'summary': actions_performed_summary
            })
        return jsonify({'success': overall_success, 'message': final_status_message, 'task_id': task_id, 'summary': actions_performed_summary}), 200

    except Exception as e:
        error_message = f"Critical error during selective restore (task {task_id}): {str(e)}"
        app.logger.exception(error_message)
        add_audit_log(action="SELECTIVE_RESTORE_CRITICAL_ERROR", details=error_message)
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': error_message, 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': error_message, 'task_id': task_id}), 500

# --- Backup Schedule API Routes ---

@app.route('/api/admin/verify_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_verify_backup():
    data = request.get_json()
    task_id = uuid.uuid4().hex

    if not data or 'backup_timestamp' not in data:
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400

    backup_timestamp = data['backup_timestamp']
    app.logger.info(f"User {current_user.username} initiated VERIFY BACKUP (task {task_id}) for timestamp: {backup_timestamp}.")

    if not verify_backup_set: # Check if the function is available
        message = "Backup verification module not configured or available."
        app.logger.error(message)
        if socketio:
             socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': message, 'detail': 'ERROR', 'results': None})
        return jsonify({'success': False, 'message': message, 'task_id': task_id, 'results': None}), 500

    try:
        if socketio:
            socketio.emit('verify_backup_progress', {
                'task_id': task_id,
                'status': 'Backup verification starting...',
                'detail': f'Timestamp: {backup_timestamp}'
            })

        verification_results = verify_backup_set(
            backup_timestamp,
            socketio_instance=socketio,
            task_id=task_id
        )

        final_message = f"Verification for backup {backup_timestamp} (task {task_id}) completed. Status: {verification_results.get('status')}."
        app.logger.info(final_message)
        add_audit_log(action="VERIFY_BACKUP_COMPLETED", details=f"{final_message} Results: {json.dumps(verification_results)}")

        if socketio:
            socketio.emit('verify_backup_progress', {
                'task_id': task_id,
                'status': f"Verification complete: {verification_results.get('status')}",
                'detail': 'SUCCESS' if verification_results.get('status') == 'verified_present' else 'INFO',
                'results': verification_results
            })
        return jsonify({'success': True, 'message': final_message, 'task_id': task_id, 'results': verification_results}), 200

    except Exception as e:
        error_message = f"Error during backup verification for {backup_timestamp} (task {task_id}): {str(e)}"
        app.logger.exception(error_message)
        add_audit_log(action="VERIFY_BACKUP_ERROR", details=error_message)
        if socketio:
            socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': 'Backup verification failed.', 'detail': str(e), 'results': None})
        return jsonify({'success': False, 'message': error_message, 'task_id': task_id, 'results': None}), 500


@app.route('/api/admin/backup_schedule', methods=['GET'])
@login_required
@permission_required('manage_system')
def get_backup_schedule():
    app.logger.info(f"User {current_user.username} fetching backup schedule configuration.")
    try:
        schedule_config = db.session.query(BackupScheduleConfig).first()
        if schedule_config:
            return jsonify({
                'id': schedule_config.id,
                'is_enabled': schedule_config.is_enabled,
                'schedule_type': schedule_config.schedule_type,
                'day_of_week': schedule_config.day_of_week,
                'time_of_day': schedule_config.time_of_day.strftime('%H:%M:%S') if schedule_config.time_of_day else None
            }), 200
        else:
            app.logger.warning("No backup schedule configuration found.")
            return jsonify({'is_enabled': False, 'schedule_type': 'daily', 'day_of_week': None, 'time_of_day': '02:00:00'}), 200
    except Exception as e:
        app.logger.exception("Error fetching backup schedule config:")
        return jsonify({'success': False, 'message': f'Error fetching schedule: {str(e)}'}), 500

@app.route('/api/admin/backup_schedule', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_backup_schedule():
    app.logger.info(f"User {current_user.username} attempting to update backup schedule.")
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid input. JSON data expected.'}), 400
    try:
        is_enabled = data.get('is_enabled')
        schedule_type = data.get('schedule_type')
        day_of_week_str = data.get('day_of_week')
        time_of_day_str = data.get('time_of_day')

        if not isinstance(is_enabled, bool):
            return jsonify({'success': False, 'message': 'is_enabled must be true or false.'}), 400
        if schedule_type not in ['daily', 'weekly']:
            return jsonify({'success': False, 'message': "schedule_type must be 'daily' or 'weekly'."}), 400

        parsed_time_of_day = None
        if time_of_day_str:
            try:
                parsed_time_of_day = datetime.strptime(time_of_day_str, '%H:%M').time()
            except ValueError:
                try:
                    parsed_time_of_day = datetime.strptime(time_of_day_str, '%H:%M:%S').time()
                except ValueError:
                    return jsonify({'success': False, 'message': "time_of_day must be in HH:MM or HH:MM:SS format."}), 400
        else:
            return jsonify({'success': False, 'message': 'time_of_day is required.'}), 400

        parsed_day_of_week = None
        if schedule_type == 'weekly':
            if day_of_week_str is None or day_of_week_str == '':
                 return jsonify({'success': False, 'message': 'day_of_week is required for weekly schedule.'}), 400
            try:
                parsed_day_of_week = int(day_of_week_str)
                if not (0 <= parsed_day_of_week <= 6):
                    raise ValueError("Day of week must be 0-6.")
            except ValueError as ve:
                 return jsonify({'success': False, 'message': str(ve)}), 400

        schedule_config = db.session.query(BackupScheduleConfig).first()
        if not schedule_config:
            schedule_config = BackupScheduleConfig(id=1)
            db.session.add(schedule_config)
            app.logger.info("No existing backup schedule config, creating new one.")

        schedule_config.is_enabled = is_enabled
        schedule_config.schedule_type = schedule_type
        schedule_config.time_of_day = parsed_time_of_day
        schedule_config.day_of_week = parsed_day_of_week if schedule_type == 'weekly' else None

        db.session.commit()
        app.logger.info(f"Backup schedule updated by {current_user.username}: {data}")
        add_audit_log(action="UPDATE_BACKUP_SCHEDULE", details=f"User {current_user.username} updated backup schedule. New config: {data}")
        app.logger.info("Placeholder: Scheduler would be reconfigured here.") # Actual scheduler reconfig is complex
        return jsonify({'success': True, 'message': 'Backup schedule updated successfully.'}), 200
    except ValueError as ve: # Specific validation errors
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error updating backup schedule config:")
        add_audit_log(action="UPDATE_BACKUP_SCHEDULE_FAILED", details=f"Error: {str(e)}. Data: {data}")
        return jsonify({'success': False, 'message': f'Error updating schedule: {str(e)}'}), 500

if __name__ == "__main__":
    # To initialize the DB, run `python init_setup.py` once or import
    # `init_db` from `init_setup` in a Python shell. Pass force=True if you
    # really want to wipe existing data.
    try:
        scheduler.start()
    except Exception:
        app.logger.exception("Failed to start background scheduler")
    # Avoid using _() here because no request context exists at startup
    app.logger.info(translator.gettext("Flask app starting...", translator.default_locale))
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

@app.route('/api/resources/<int:resource_id>/all_bookings', methods=['GET'])
@login_required
def get_all_bookings_for_resource(resource_id):
    """
    Fetches all bookings for a specific resource within a given date range,
    formatted for FullCalendar.
    """
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    if not start_str or not end_str:
        app.logger.warning(f"Missing start or end query parameters for resource {resource_id} all_bookings.")
        return jsonify({'error': 'Missing start or end query parameters.'}), 400

    try:
        # Try parsing directly as ISO8601 datetime (handles offsets like +07:00 and Z)
        start_dt_aware = datetime.fromisoformat(start_str)
        end_dt_aware = datetime.fromisoformat(end_str)

        # Convert to UTC then make naive for DB comparison, assuming DB stores naive UTC
        # If already naive (e.g. fromisoformat didn't find tz info), astimezone(timezone.utc) would error
        # So, check if tzinfo is present first.
        if start_dt_aware.tzinfo:
            start_dt = start_dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
        else: # Already naive
            start_dt = start_dt_aware

        if end_dt_aware.tzinfo:
            end_dt = end_dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
        else: # Already naive
            end_dt = end_dt_aware

    except ValueError:
        # If ISO8601 datetime parsing fails, try parsing as YYYY-MM-DD date
        try:
            start_dt_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_dt_date = datetime.strptime(end_str, '%Y-%m-%d').date()

            start_dt = datetime.combine(start_dt_date, time.min) # Start of the day (naive)
            end_dt = datetime.combine(end_dt_date, time.max)     # End of the day (naive)
        except ValueError:
            app.logger.warning(f"Invalid date format for resource {resource_id} all_bookings. Start: {start_str}, End: {end_str}. Neither full ISO8601 datetime nor YYYY-MM-DD.")
            return jsonify({'error': 'Invalid date format. Use ISO8601 for start and end parameters (e.g., YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DD).'}), 400

    try:
        resource = Resource.query.get(resource_id)
        if not resource:
            app.logger.warning(f"Resource not found for ID {resource_id} in all_bookings endpoint.")
            return jsonify({'error': 'Resource not found.'}), 404

        bookings_for_resource = Booking.query.filter(
            Booking.resource_id == resource_id,
            Booking.start_time < end_dt,
            Booking.end_time > start_dt
        ).all()

        events = []
        for booking in bookings_for_resource:
            events.append({
                'id': booking.id,
                'title': booking.title or resource.name,
                'start': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'color': 'blue',
                'display': 'block',
                'extendedProps': { # Optional: include more data if needed by frontend
                    'user_name': booking.user_name,
                    'status': booking.status
                }
            })

        app.logger.info(f"Fetched {len(events)} bookings for resource {resource_id} between {start_str} and {end_str}.")
        return jsonify(events), 200

    except Exception as e:
        app.logger.exception(f"Error fetching all bookings for resource {resource_id}:")
        return jsonify({'error': 'Failed to fetch bookings due to a server error.'}), 500
