import os
import pathlib

# Base directory of the app - project root
basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'floor_map_uploads')
RESOURCE_UPLOAD_FOLDER = os.path.join(basedir, 'static', 'resource_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure the data directory exists (it should be created by init_setup.py)
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

SCHEDULE_CONFIG_FILE = os.path.join(DATA_DIR, 'backup_schedule.json')
DEFAULT_SCHEDULE_DATA = {
    "is_enabled": False,
    "schedule_type": "daily",
    "day_of_week": None, # 0=Monday, 6=Sunday
    "time_of_day": "02:00" # HH:MM format
}

# Flask App Configurations
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key_123!@#')
SQLALCHEMY_DATABASE_URI = os.environ.get(
    'AZURE_SQL_CONNECTION_STRING',
    os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(DATA_DIR, 'site.db'))
)
SQLALCHEMY_TRACK_MODIFICATIONS = False
LANGUAGES = ['en', 'es', 'th']

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
# CLIENT_SECRET_FILE = os.path.join(pathlib.Path(__file__).parent, 'client_secret.json') # Example if used

# Flask-Mail configuration
MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 25))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', '1', 'yes']
MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', '1', 'yes']
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USERNAME or 'noreply@example.com')

# Booking check-in configuration
CHECK_IN_GRACE_MINUTES = int(os.environ.get('CHECK_IN_GRACE_MINUTES', '15'))
AUTO_CANCEL_CHECK_INTERVAL_MINUTES = int(os.environ.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', '5'))
AZURE_BACKUP_INTERVAL_MINUTES = int(os.environ.get('AZURE_BACKUP_INTERVAL_MINUTES', '60'))

# Note: app.config specific assignments like app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# will be handled in app.py by importing these values.
# For example, in app.py:
# from config import UPLOAD_FOLDER, RESOURCE_UPLOAD_FOLDER, SECRET_KEY, SQLALCHEMY_DATABASE_URI, etc.
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# app.config['RESOURCE_UPLOAD_FOLDER'] = RESOURCE_UPLOAD_FOLDER
# app.config['SECRET_KEY'] = SECRET_KEY
# ... and so on for other configurations.
# This file (config.py) will define the Python variables.
# The app.py will then use these variables to set app.config dictionary entries.
# This separation keeps all configuration definitions in one place.
