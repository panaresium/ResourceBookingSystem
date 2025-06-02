from flask import Flask, jsonify, request # jsonify for error handler, request for error handlers
import os
import json # Added for json.load and json.dumps
import logging

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
# Conditional import for azure_backup
try:
    from azure_backup import restore_latest_backup_set_on_startup, backup_if_changed as azure_backup_if_changed
    azure_backup_available = True
except ImportError:
    restore_latest_backup_set_on_startup = None
    azure_backup_if_changed = None # Keep for scheduler
    azure_backup_available = False

# Imports for processing downloaded configs during startup restore
from utils import (
    _import_map_configuration_data,
    _import_resource_configurations_data,
    _import_user_configurations_data,
    add_audit_log
)

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

    # New logic for startup restore
    if azure_backup_available and callable(restore_latest_backup_set_on_startup):
        try:
            app.logger.info("Attempting to restore latest backup set from Azure on startup...")
            # Pass app.logger to the function for consistent logging
            downloaded_configs = restore_latest_backup_set_on_startup(app_logger=app.logger)
            
            if downloaded_configs: # Check if restore returned any paths
                app.logger.info(f"Startup restore downloaded config files: {downloaded_configs}")
                with app.app_context(): # Ensure operations run within application context
                    
                    # Import resource configurations first
                    resource_configs_path = downloaded_configs.get('resource_configs_path')
                    if resource_configs_path and os.path.exists(resource_configs_path):
                        app.logger.info(f"Importing resource configurations from {resource_configs_path} on startup.")
                        try:
                            with open(resource_configs_path, 'r', encoding='utf-8') as f:
                                resource_data_to_import = json.load(f)
                            # db object is globally available from extensions.py and functions are called within app_context
                            res_created, res_updated, res_errors = _import_resource_configurations_data(resource_data_to_import)
                            app.logger.info(f"Startup import of resource configs: {res_created} created, {res_updated} updated. Errors: {len(res_errors)}")
                            if res_errors: app.logger.error(f"Startup resource import errors: {res_errors}")
                            # add_audit_log needs user context or to handle being called by system
                            add_audit_log(action="STARTUP_RESTORE_IMPORT", details=f"Resource configs imported: {res_created}c, {res_updated}u. Errors: {len(res_errors)}")
                        except Exception as import_err:
                            app.logger.exception(f"Error importing resource configurations on startup from {resource_configs_path}: {import_err}")
                        finally:
                            try: os.remove(resource_configs_path)
                            except OSError as e_remove: app.logger.error(f"Error removing temp resource_configs file {resource_configs_path} on startup: {e_remove}")
                    
                    # Import map configurations
                    map_config_path = downloaded_configs.get('map_config_path')
                    if map_config_path and os.path.exists(map_config_path):
                        app.logger.info(f"Importing map configuration from {map_config_path} on startup.")
                        try:
                            with open(map_config_path, 'r', encoding='utf-8') as f:
                                map_data_to_import = json.load(f)
                            import_summary, import_status_code = _import_map_configuration_data(map_data_to_import)
                            app.logger.info(f"Startup import of map config status {import_status_code}. Summary: {json.dumps(import_summary)}")
                            add_audit_log(action="STARTUP_RESTORE_IMPORT", details=f"Map config imported. Status: {import_status_code}. Summary: {json.dumps(import_summary)}")
                        except Exception as import_err:
                            app.logger.exception(f"Error importing map configuration on startup from {map_config_path}: {import_err}")
                        finally:
                            try: os.remove(map_config_path)
                            except OSError as e_remove: app.logger.error(f"Error removing temp map_config file {map_config_path} on startup: {e_remove}")

                    # Import user configurations
                    user_configs_path = downloaded_configs.get('user_configs_path')
                    if user_configs_path and os.path.exists(user_configs_path):
                        app.logger.info(f"Importing user/role configurations from {user_configs_path} on startup.")
                        try:
                            with open(user_configs_path, 'r', encoding='utf-8') as f:
                                user_data_to_import = json.load(f)
                            # db object is globally available from extensions.py and functions are called within app_context
                            r_created, r_updated, u_created, u_updated, u_errors = _import_user_configurations_data(user_data_to_import)
                            app.logger.info(f"Startup import of user/role configs: Roles({r_created}c, {r_updated}u), Users({u_created}c, {u_updated}u). Errors: {len(u_errors)}")
                            if u_errors: app.logger.error(f"Startup user/role import errors: {u_errors}")
                            add_audit_log(action="STARTUP_RESTORE_IMPORT", details=f"User/role configs imported. Roles({r_created}c, {r_updated}u), Users({u_created}c, {u_updated}u). Errors: {len(u_errors)}")
                        except Exception as import_err:
                            app.logger.exception(f"Error importing user/role configurations on startup from {user_configs_path}: {import_err}")
                        finally:
                            try: os.remove(user_configs_path)
                            except OSError as e_remove: app.logger.error(f"Error removing temp user_configs file {user_configs_path} on startup: {e_remove}")
            else:
                app.logger.info("No configurations downloaded by startup restore, or restore did not run/succeed at downloading configs.")
        except Exception as e:
            app.logger.exception(f"Error during startup restore process (restore_latest_backup_set_on_startup call or subsequent logic): {e}")
    else:
        app.logger.info("Azure backup utilities not available (azure_backup or restore_latest_backup_set_on_startup not imported). Skipping startup restore from Azure.")

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
            scheduler.add_job(cancel_unchecked_bookings, 'interval', minutes=app.config.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5), args=[app])
        if apply_scheduled_resource_status_changes:
            scheduler.add_job(apply_scheduled_resource_status_changes, 'interval', minutes=1, args=[app])
        if run_scheduled_backup_job:
            scheduler.add_job(run_scheduled_backup_job, 'interval', minutes=app.config.get('SCHEDULER_BACKUP_JOB_INTERVAL_MINUTES', 60), args=[app]) # New config option

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
