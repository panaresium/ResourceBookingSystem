import os
from pathlib import Path

# Application directory
# Resolve to get absolute path, ensuring consistency.
basedir = Path(__file__).resolve().parent

# --- Core Flask App Configurations ---
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key_123!@#_fallback_for_config.py')

# SERVER_NAME Configuration with logging/print for diagnostics
SERVER_NAME_FROM_ENV = os.environ.get('SERVER_NAME')
if SERVER_NAME_FROM_ENV:
    SERVER_NAME = SERVER_NAME_FROM_ENV
    print(f"INFO: [config.py] SERVER_NAME configured from environment variable: {SERVER_NAME}")
else:
    SERVER_NAME = 'localhost:5000' # Default fallback
    print(f"WARNING: [config.py] SERVER_NAME environment variable not set. Using default: {SERVER_NAME}. This may not be suitable for production or external URL generation by the scheduler.")

# Ensure APPLICATION_ROOT and PREFERRED_URL_SCHEME also have their existing defaults
APPLICATION_ROOT = os.environ.get('APPLICATION_ROOT', '/')
PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME', 'http') # Use 'https' in production

print(f"INFO: [config.py] Final effective SERVER_NAME: {SERVER_NAME}")
print(f"INFO: [config.py] Final effective APPLICATION_ROOT: {APPLICATION_ROOT}")
print(f"INFO: [config.py] Final effective PREFERRED_URL_SCHEME: {PREFERRED_URL_SCHEME}")

# For Flask-Session type extension
SESSION_TYPE = os.environ.get('SESSION_TYPE', 'filesystem')
SESSION_FILE_DIR = basedir / 'flask_session' # Directory for session files
# For CSRF protection (Flask-WTF)
WTF_CSRF_ENABLED = True # Default is True, but explicit
WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY', 'another_secret_for_csrf_in_config.py')

# --- Database Configuration ---
# Use AZURE_SQL_CONNECTION_STRING if available, otherwise DATABASE_URL, finally local SQLite.
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    print(f"INFO: [config.py] Using Postgres database from DATABASE_URL.")
    SQLALCHEMY_DATABASE_URI = database_url
else:
    print(f"WARNING: [config.py] DATABASE_URL not found. Falling back to local SQLite.")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{basedir / 'data' / 'site.db'}"

# Fallback/Legacy Override
if os.environ.get('AZURE_SQL_CONNECTION_STRING'):
     SQLALCHEMY_DATABASE_URI = os.environ.get('AZURE_SQL_CONNECTION_STRING')

SQLALCHEMY_TRACK_MODIFICATIONS = False

# --- Internationalization and Localization (i18n/l10n) ---
LANGUAGES = ['en', 'es', 'th', 'fr'] # Supported languages
BABEL_DEFAULT_LOCALE = 'en'
# Absolute path for translations directory
BABEL_TRANSLATION_DIRECTORIES = str(basedir / 'translations')


# --- Cloudflare R2 Configuration ---
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
STORAGE_PROVIDER = os.environ.get('STORAGE_PROVIDER', 'r2' if R2_ACCESS_KEY else 'local')

# --- File Upload Configurations ---
# Define base upload folder, then specific subfolders.
UPLOAD_FOLDER_BASE = basedir / 'static' # General base for static uploads
# Specific to floor maps
FLOOR_MAP_UPLOAD_FOLDER = UPLOAD_FOLDER_BASE / 'floor_map_uploads'
# Specific to resource images
RESOURCE_IMAGE_UPLOAD_FOLDER = UPLOAD_FOLDER_BASE / 'resource_uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'} # Allowed image file extensions

# --- Data and Scheduling Configurations ---
DATA_DIR = basedir / 'data' # General directory for app data (e.g., DB, JSON configs)
# Path to the JSON file storing backup schedule settings
SCHEDULE_CONFIG_FILE = DATA_DIR / 'backup_schedule.json'
# Default structure for schedule data if the JSON file is missing or corrupt
DEFAULT_SCHEDULE_DATA = {
    "is_enabled": False,
    "schedule_type": "daily",  # 'daily' or 'weekly'
    "day_of_week": None,       # 0=Monday, 6=Sunday (used if schedule_type is 'weekly')
    "time_of_day": "02:00"     # HH:MM format (24-hour)
}

# Path to the JSON file storing unified backup schedule settings
UNIFIED_SCHEDULE_CONFIG_FILE = DATA_DIR / 'unified_booking_backup_schedule.json'
DEFAULT_UNIFIED_SCHEDULE_DATA = {
    "unified_full_backup": {
        "is_enabled": False,
        "schedule_type": "daily",  # 'daily', 'weekly', 'monthly'
        "time_of_day": "02:00",   # HH:MM
        "day_of_week": None,      # 0-6 (Monday-Sunday) for weekly
        "day_of_month": None      # 1-31 for monthly
    },
    "unified_incremental_backup": {
        "is_enabled": False,
        "interval_minutes": 30
    }
}

# --- UI Controlled Settings ---
# Path to the JSON file storing UI-configurable map settings
MAP_OPACITY_CONFIG_FILE = DATA_DIR / 'map_settings.json'

# --- Google OAuth Configuration ---
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER_config.py')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER_config.py')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration" # Standard discovery URL
# OAuth scopes requesting access to user's email and profile
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
# Optional: Path to client_secret.json if that method is preferred over direct env vars for ID/Secret
# CLIENT_SECRET_FILE = basedir / 'client_secret.json'

# --- Email Configuration ---
# Old Flask-Mail variables (removed as Flask-Mail is no longer used)
# MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
# MAIL_PORT = int(os.environ.get('MAIL_PORT', 25))
# MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', '1', 'yes']
# MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', '1', 'yes']
# MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
# MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'fallback_sender@example.com') # Keep a default sender for other purposes or direct use in utils

# --- Gmail API OAuth 2.0 Client ID Configuration (for sending application emails) ---
# GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are already defined above for user OAuth.
# They will be reused here for authorizing the application to send mail via a specific Gmail account.

# The GMAIL_SENDER_ADDRESS is the email account (e.g., rmsunicef@gmail.com)
# that will be authorized to send emails.
GMAIL_SENDER_ADDRESS = os.environ.get('GMAIL_SENDER_ADDRESS') # e.g., 'rmsunicef@gmail.com'

# The Redirect URI for the Gmail authorization flow.
# This MUST be added to your Google Cloud Console "Authorized redirect URIs" for the OAuth 2.0 Client ID.
# Example: 'http://localhost:5000/authorize_gmail_callback' or 'https://yourdomain.com/authorize_gmail_callback'
GMAIL_OAUTH_REDIRECT_URI = os.environ.get('GMAIL_OAUTH_REDIRECT_URI')

# The Refresh Token obtained after the one-time authorization for GMAIL_SENDER_ADDRESS.
# This should be stored securely, e.g., as an environment variable.
GMAIL_REFRESH_TOKEN = os.environ.get('GMAIL_REFRESH_TOKEN')

# Old Gmail API Service Account Configuration variables removed.

# --- Booking and Check-in Behavior ---
CHECK_IN_GRACE_MINUTES = int(os.environ.get('CHECK_IN_GRACE_MINUTES', 15)) # Grace period for check-in in minutes
# How often the background job checks for bookings to auto-cancel if not checked in
AUTO_CANCEL_CHECK_INTERVAL_MINUTES = int(os.environ.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5))

# --- Azure Backup Configuration ---
# Interval for the legacy Azure backup job (if `backup_if_changed` is used)
AZURE_BACKUP_INTERVAL_MINUTES = int(os.environ.get('AZURE_BACKUP_INTERVAL_MINUTES', 60)) # Default to 1 hour
# Connection string for Azure Blob Storage (used by the newer azure_backup.py module)
AZURE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
# Default container name for backups in Azure Blob Storage
AZURE_CONTAINER_NAME = os.environ.get('AZURE_CONTAINER_NAME', 'roombookingbackup')
# Names for shares within Azure File Storage (if used by azure_backup.py)
AZURE_DB_SHARE = os.environ.get('AZURE_DB_SHARE', 'db-backups') # Legacy or specific component share
AZURE_CONFIG_SHARE = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups') # Legacy or specific component share
AZURE_MEDIA_SHARE = os.environ.get('AZURE_MEDIA_SHARE', 'media') # Legacy or specific component share

# Unified Azure File Share for full system backups (used by azure_backup.py's new system)
AZURE_SYSTEM_BACKUP_SHARE = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
# Base directory name within the AZURE_SYSTEM_BACKUP_SHARE where 'backup_YYYYMMDD_HHMMSS' folders are stored
# This corresponds to FULL_SYSTEM_BACKUPS_BASE_DIR in azure_backup.py
AZURE_FULL_SYSTEM_BACKUPS_BASE_DIR_NAME = os.environ.get('AZURE_FULL_SYSTEM_BACKUPS_BASE_DIR_NAME', 'full_system_backups')


# Share for booking data protection backups (JSON exports, etc.)
AZURE_BOOKING_DATA_SHARE = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups')
# Base directory name within AZURE_BOOKING_DATA_SHARE for these backups
# Corresponds to AZURE_BOOKING_DATA_PROTECTION_DIR in azure_backup.py
AZURE_BOOKING_DATA_PROTECTION_BASE_DIR_NAME = os.environ.get('AZURE_BOOKING_DATA_PROTECTION_BASE_DIR_NAME', 'booking_data_protection_backups')


# BOOKINGS_CSV_BACKUP_INTERVAL_MINUTES has been removed as it's related to legacy CSV backups.


# Unified booking data backup jobs
UNIFIED_FULL_BACKUP_ENABLED = os.environ.get('UNIFIED_FULL_BACKUP_ENABLED', 'false').lower() in ['true', '1', 'yes']
UNIFIED_FULL_BACKUP_TIME_OF_DAY = os.environ.get('UNIFIED_FULL_BACKUP_TIME_OF_DAY', '02:00')  # HH:MM 24-hour format
UNIFIED_INCREMENTAL_BACKUP_ENABLED = os.environ.get('UNIFIED_INCREMENTAL_BACKUP_ENABLED', 'false').lower() in ['true', '1', 'yes']
UNIFIED_INCREMENTAL_BACKUP_INTERVAL_MINUTES = int(os.environ.get('UNIFIED_INCREMENTAL_BACKUP_INTERVAL_MINUTES', 30))


# --- Notification Webhooks ---
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
TEAMS_WEBHOOK_URL = os.environ.get('TEAMS_WEBHOOK_URL')

# --- Default Admin User (for initial setup) ---
# Consider security implications for production. Best to set via env vars.
DEFAULT_ADMIN_EMAIL = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'ChangeMe123!')

# --- Application Specific Settings (Examples) ---
APP_NAME = "Meeting Room Booking System"
MAX_BOOKING_DURATION_HOURS = int(os.environ.get('MAX_BOOKING_DURATION_HOURS', 8))
MIN_BOOKING_DURATION_MINUTES = int(os.environ.get('MIN_BOOKING_DURATION_MINUTES', 15))
BOOKING_LEAD_TIME_DAYS = int(os.environ.get('BOOKING_LEAD_TIME_DAYS', 14)) # How far in advance users can book
DEFAULT_ITEMS_PER_PAGE = int(os.environ.get('DEFAULT_ITEMS_PER_PAGE', 10)) # For pagination

# --- Map View Settings ---
try:
    raw_opacity = os.environ.get('MAP_RESOURCE_OPACITY')
    if raw_opacity is not None:
        MAP_RESOURCE_OPACITY_VALUE = float(raw_opacity)
        if not (0.0 <= MAP_RESOURCE_OPACITY_VALUE <= 1.0):
            print(f"Warning: MAP_RESOURCE_OPACITY environment variable value '{raw_opacity}' is out of range (0.0-1.0). Using default 0.7.")
            MAP_RESOURCE_OPACITY_VALUE = 0.7
    else:
        MAP_RESOURCE_OPACITY_VALUE = 0.7 # Default if env var is not set
except ValueError:
    MAP_RESOURCE_OPACITY_VALUE = 0.7 # Default if conversion to float fails
    # It's tricky to access raw_opacity here if os.environ.get already failed or returned None then float() failed.
    # So, the warning message might need to be more generic or we assume raw_opacity was the problematic value.
    print(f"Warning: MAP_RESOURCE_OPACITY environment variable is not a valid float. Using default 0.7.")

# Ensure the final variable name matches what the app will use, e.g., MAP_RESOURCE_OPACITY
MAP_RESOURCE_OPACITY = MAP_RESOURCE_OPACITY_VALUE

# --- SocketIO Configuration ---
# Example: For using a message queue like Redis in production for SocketIO
SOCKETIO_MESSAGE_QUEUE = os.environ.get('SOCKETIO_MESSAGE_QUEUE') # e.g., 'redis://localhost:6379/0'

# --- Logging Configuration ---
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
# Path for a rotating file log handler, if configured in app.py
LOG_FILE = basedir / 'logs' / 'app.log'


# --- Directory Creation ---
# Ensure necessary directories exist when this config is loaded.
# This is useful if the application doesn't create them elsewhere.
def ensure_dir_exists(dir_path: Path):
    dir_path.mkdir(parents=True, exist_ok=True)

ensure_dir_exists(DATA_DIR)
ensure_dir_exists(SESSION_FILE_DIR) # For filesystem-based sessions
ensure_dir_exists(FLOOR_MAP_UPLOAD_FOLDER)
ensure_dir_exists(RESOURCE_IMAGE_UPLOAD_FOLDER)
ensure_dir_exists(basedir / 'instance') # Often used for SQLite DBs or other instance-specific files
ensure_dir_exists(basedir / 'logs') # For log files if LOG_FILE is used

# --- Final Check & Output ---
# You can add a print statement here for debugging if needed, e.g.,
# print(f"Config loaded. SQLALCHEMY_DATABASE_URI: {SQLALCHEMY_DATABASE_URI}")
# print(f"FLOOR_MAP_UPLOAD_FOLDER: {FLOOR_MAP_UPLOAD_FOLDER}")

# Note: Values that are directly `app.config['KEY'] = value` in the original app.py
# and are not derived from os.environ or other logic here, should be added as simple
# Python variables. Example: if app.py had `app.config['MY_CONSTANT'] = 123`,
# then here you'd have `MY_CONSTANT = 123`.
# The Flask app setup will then do `app.config.from_object('config')`.

# Example of a direct config not from environment (if it existed in app.py's app.config)
# SOME_APP_SPECIFIC_FLAG = True
# MAX_LOGIN_ATTEMPTS = 5
