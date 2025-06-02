from flask import Flask, jsonify, request # jsonify for error handler, request for error handlers
import os # For basic path joining if needed by config directly
import logging # For basic logging config

# Import configurations, extensions, and initialization functions
import config
from extensions import db, login_manager, oauth, mail, csrf, socketio
from models import User # Needed for load_user, others loaded via db object

from translations import init_translations # SimpleTranslator is used internally by init_translations now
from flask_wtf.csrf import CSRFError # For the error handler

from auth import init_auth
from routes.ui import init_ui_routes
from routes.admin_ui import init_admin_ui_routes
from routes.api_resources import init_api_resources_routes
from routes.api_bookings import init_api_bookings_routes
from routes.api_users import init_api_users_routes
from routes.api_maps import init_api_maps_routes
from routes.api_roles import init_api_roles_routes
from routes.api_waitlist import init_api_waitlist_routes
from routes.api_system import init_api_system_routes

# For scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from scheduler_tasks import cancel_unchecked_bookings, apply_scheduled_resource_status_changes, run_scheduled_backup_job
# Conditional import for azure_backup's backup_if_changed
try:
    from azure_backup import backup_if_changed as azure_backup_if_changed
    from azure_backup import restore_from_share as azure_restore_from_share # For initial restore
except ImportError:
    azure_backup_if_changed = None
    azure_restore_from_share = None

# For SQLite pragmas - these functions will be moved here
_sqlite_configured_factory = False # Module-level flag for pragma configuration

def configure_sqlite_pragmas_factory(current_app, current_db):
    """Apply WAL-related pragmas for SQLite databases once."""
    global _sqlite_configured_factory
    if _sqlite_configured_factory:
        return

    if current_app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        try:
            from sqlalchemy import text # Import text here to keep it local if possible
            engine = current_db.engine
            # Use 'with engine.connect() as connection:' for SQLAlchemy 2.0 compatibility
            with engine.connect() as connection:
                connection.execute(text("PRAGMA journal_mode=WAL"))
                connection.execute(text("PRAGMA synchronous=NORMAL"))
                connection.execute(text("PRAGMA busy_timeout=30000"))
                connection.commit() # Ensure pragmas are committed if connection doesn't auto-commit
            current_app.logger.info("SQLite database configured for WAL mode and related settings via factory.")
            _sqlite_configured_factory = True # Set flag after successful configuration
        except Exception as e:
            current_app.logger.exception(f"Failed to configure SQLite pragmas via factory: {e}")


def _ensure_sqlite_configured_factory_hook(current_app, current_db):
    # This function will be registered with @app.before_request
    configure_sqlite_pragmas_factory(current_app, current_db)

def create_app(config_object=config):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    # Corrected template_folder and static_folder paths assuming app_factory.py is in root.
    # If app_factory is in a sub-directory, these might need adjustment (e.g. app.Flask('instance', ...))

    # 1. Load Configuration
    app.config.from_object(config_object)

    # Ensure UPLOAD_FOLDER and other paths from config are created if not existing
    # This logic was in app.py; it's better here or in config.py itself.
    # config.py now handles directory creation, so this might be redundant.
    # However, double-checking critical folders controlled by app.config is fine.
    if not os.path.exists(app.config['DATA_DIR']): # From config.py
        os.makedirs(app.config['DATA_DIR'])


    # 2. Initialize Logging (Basic, can be expanded)
    # Using Flask's built-in logger. Configuration can be enhanced.
    # BasicConfig is often called by app.py's old top-level code.
    # If that's removed, ensure logging is configured here or by WSGI server.
    # For now, relying on Flask's default logger setup + any config in config_object
    app.logger.setLevel(app.config.get('LOG_LEVEL', 'INFO').upper())


    # Initial restore from Azure if configured (was in app.py)
    if azure_restore_from_share:
        try:
            app.logger.info("Attempting to restore data from Azure File Share on startup...")
            azure_restore_from_share() # Call the imported function
        except Exception as e:
            app.logger.exception(f'Failed to restore data from Azure File Share on startup: {e}')


    # 3. Initialize Extensions
    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app, message_queue=app.config.get('SOCKETIO_MESSAGE_QUEUE')) # Add message_queue from config

    # login_manager and oauth are initialized within init_auth

    # 4. Setup SQLite Pragmas (if using SQLite)
    with app.app_context(): # Important for operations needing app context, like DB access
        configure_sqlite_pragmas_factory(app, db)

    @app.before_request
    def ensure_sqlite_configured_wrapper():
       _ensure_sqlite_configured_factory_hook(app, db)

    # 5. Register i18n
    init_translations(app)

    # 6. Register Auth (includes LoginManager and OAuth init)
    init_auth(app, login_manager, oauth, csrf)

    # 7. Register Blueprints
    init_ui_routes(app)
    init_admin_ui_routes(app)
    init_api_resources_routes(app)
    init_api_bookings_routes(app)
    init_api_users_routes(app)
    init_api_maps_routes(app)
    init_api_roles_routes(app)
    init_api_waitlist_routes(app)
    init_api_system_routes(app)

    # 8. Register Error Handlers
    @app.errorhandler(CSRFError)
    def handle_csrf_error_factory(e):
        app.logger.warning(f"CSRF error encountered: {e.description}. Request URL: {request.url}")
        # Consider what info is safe to expose in error. e.description is usually safe.
        return jsonify(error=str(e.description), type='CSRF_ERROR'), 400

    @app.errorhandler(404)
    def not_found_error(error):
        # Distinguish between API and HTML requests for 404
        if request.blueprint and request.blueprint.startswith('api_'): # A bit simplistic, adjust if needed
             return jsonify(error="Not Found", message=str(error)), 404
        # return render_template('404.html'), 404 # Assuming you have a 404.html
        return "Page Not Found (HTML - create a template for this)", 404 # Placeholder

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback() # Rollback the session in case of DB error
        if request.blueprint and request.blueprint.startswith('api_'):
             return jsonify(error="Internal Server Error", message=str(error)), 500
        # return render_template('500.html'), 500 # Assuming you have a 500.html
        return "Internal Server Error (HTML - create a template for this)", 500 # Placeholder


    # 9. Initialize Scheduler
    apscheduler_available_check = True # Assuming it's available unless explicitly configured otherwise
    try:
        from apscheduler.schedulers.background import BackgroundScheduler # Already imported
    except ImportError:
        apscheduler_available_check = False
        app.logger.warning("APScheduler not installed. Scheduled tasks will not run.")

    if apscheduler_available_check and app.config.get("SCHEDULER_ENABLED", True): # Add a config flag
        scheduler = BackgroundScheduler(daemon=True) # daemon=True allows app to exit even if scheduler thread is running

        # Add jobs from scheduler_tasks.py
        if cancel_unchecked_bookings:
            scheduler.add_job(cancel_unchecked_bookings, 'interval', minutes=app.config.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5))
        if apply_scheduled_resource_status_changes:
            scheduler.add_job(apply_scheduled_resource_status_changes, 'interval', minutes=1)
        if run_scheduled_backup_job:
            scheduler.add_job(run_scheduled_backup_job, 'interval', minutes=app.config.get('SCHEDULER_BACKUP_JOB_INTERVAL_MINUTES', 60)) # New config option

        if azure_backup_if_changed: # Legacy Azure backup
             scheduler.add_job(azure_backup_if_changed, 'interval', minutes=app.config.get('AZURE_BACKUP_INTERVAL_MINUTES', 60))

        if not app.testing:
             try:
                 scheduler.start()
                 app.logger.info("Background scheduler started.")
             except Exception as e:
                 app.logger.exception(f"Failed to start background scheduler: {e}")
        else:
            app.logger.info("Background scheduler not started in test mode or if SCHEDULER_ENABLED is False.")
        app.scheduler = scheduler
    else:
        app.logger.info("APScheduler not available or SCHEDULER_ENABLED is False. Scheduled tasks disabled.")
        app.scheduler = None # Ensure app.scheduler exists even if not started

    app.logger.info("Flask app created and configured via factory.")

    return app
