from flask import Flask, jsonify, request # jsonify for error handler, request for error handlers
import os
import json # Added for json.load and json.dumps
import logging

# Import configurations, extensions, and initialization functions
import config
from extensions import db, login_manager, oauth, mail, csrf, socketio, migrate
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
from routes.admin_api_bookings import init_admin_api_bookings_routes # New import
from routes.admin_api_system_settings import init_admin_api_system_settings_routes # New import

# For scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from scheduler_tasks import cancel_unchecked_bookings, apply_scheduled_resource_status_changes, run_scheduled_backup_job, run_scheduled_booking_csv_backup # Added new task
# Conditional import for azure_backup
try:
    from azure_backup import restore_latest_backup_set_on_startup, backup_if_changed as azure_backup_if_changed, restore_incremental_bookings
    azure_backup_available = True
except ImportError:
    restore_latest_backup_set_on_startup = None
    azure_backup_if_changed = None # Keep for scheduler
    restore_incremental_bookings = None # Add placeholder
    azure_backup_available = False

# Imports for processing downloaded configs during startup restore
from utils import (
    load_scheduler_settings, # Added for new setting
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

# Helper function to load Booking CSV schedule settings
def load_booking_csv_schedule_settings(app):
    default_settings = {
        'enabled': False,
        'interval_value': 24,
        'interval_unit': 'hours', # 'minutes', 'hours', 'days'
        'range_type': 'all'    # 'all', '1day', '3days', '7days'
    }
    # Ensure DATA_DIR is available in app.config before this function is called.
    if not app.config.get('DATA_DIR'):
        app.logger.error("DATA_DIR not configured in app. Cannot load booking_csv_schedule.json. Using defaults.")
        return default_settings

    config_file_path = os.path.join(app.config['DATA_DIR'], 'booking_csv_schedule.json')

    if os.path.exists(config_file_path):
        try:
            with open(config_file_path, 'r') as f:
                settings = json.load(f)

            # Basic validation/merge with defaults
            validated_settings = default_settings.copy()
            # Only update keys that are expected and have correct types if possible
            for key, default_value in default_settings.items():
                if key in settings and isinstance(settings[key], type(default_value)):
                    validated_settings[key] = settings[key]
                elif key in settings: # Log type mismatch or unexpected key
                    app.logger.warning(f"Booking CSV schedule config: Key '{key}' has unexpected type or value '{settings[key]}'. Using default for this key.")

            # Specific validation for interval_unit and range_type against allowed values
            if validated_settings['interval_unit'] not in ['minutes', 'hours', 'days']:
                app.logger.warning(f"Booking CSV schedule config: Invalid interval_unit '{validated_settings['interval_unit']}'. Reverting to default.")
                validated_settings['interval_unit'] = default_settings['interval_unit']
            if not isinstance(validated_settings.get('interval_value'), int) or validated_settings.get('interval_value') <= 0:
                app.logger.warning(f"Booking CSV schedule config: Invalid interval_value '{validated_settings.get('interval_value', 'Not Set')}'. Reverting to default.")
                validated_settings['interval_value'] = default_settings['interval_value']

            if validated_settings['range_type'] not in ['all', '1day', '3days', '7days']:
                app.logger.warning(f"Booking CSV schedule config: Invalid range_type '{validated_settings['range_type']}'. Reverting to default.")
                validated_settings['range_type'] = default_settings['range_type']

            # Ensure 'enabled' is a boolean
            if not isinstance(validated_settings.get('enabled'), bool):
                app.logger.warning(f"Booking CSV schedule config: Invalid type for 'enabled' ('{validated_settings.get('enabled')}'). Reverting to default (False).")
                validated_settings['enabled'] = default_settings['enabled']

            return validated_settings
        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"Error loading or parsing booking_csv_schedule.json: {e}. Using default settings.", exc_info=True)
            return default_settings
    return default_settings

def create_app(config_object=config, testing=False): # Added testing parameter
    app = Flask(__name__, template_folder='templates', static_folder='static')
    # Corrected template_folder and static_folder paths assuming app_factory.py is in root.
    # If app_factory is in a sub-directory, these might need adjustment (e.g. app.Flask('instance', ...))

    # 1. Load Configuration
    app.config.from_object(config_object)

    if testing:
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['LOGIN_DISABLED'] = True # Custom flag for decorators
        app.config['SCHEDULER_ENABLED'] = False # Disable scheduler during tests
        app.config['MAIL_SUPPRESS_SEND'] = True # Suppress emails
        app.config['SERVER_NAME'] = 'localhost.test' # For url_for in tests without active request context

    # Initialize DB early
    db.init_app(app)

    if testing:
        # EXTREMELY MINIMAL SETUP FOR TESTING when create_app(testing=True)
        app.logger.setLevel(logging.DEBUG)
        if not app.logger.hasHandlers():
            app.logger.addHandler(logging.StreamHandler())
        app.logger.info("Flask app CREATED in EXTREMELY MINIMAL testing mode.")
        # Skip almost all other initializations for this specific test run
        return app # Return early for minimal test

    # Conditional setup for non-testing vs testing (this block is now only for non-testing)
    # Production or non-testing development setup for DATA_DIR and specific configs
    if not os.path.exists(app.config['DATA_DIR']):
        os.makedirs(app.config['DATA_DIR'])
    app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] = load_booking_csv_schedule_settings(app)
    # Note: app.logger is not fully configured yet here, so logging these settings is deferred

    # 2. Initialize Logging (this block is now only for non-testing)
    # Full logging setup for production/development
    default_log_level_str = 'INFO'
    log_level_str = os.environ.get('APP_GLOBAL_LOG_LEVEL', default_log_level_str).upper()
    log_level_map = {
        'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING,
        'ERROR': logging.ERROR, 'CRITICAL': logging.CRITICAL
    }
    effective_log_level = log_level_map.get(log_level_str, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(effective_log_level)
    if not root_logger.hasHandlers():
        stream_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
        logging.info(f"Root logger configured with level {log_level_str} and a default StreamHandler.")
    else:
        logging.info(f"Root logger level set to {log_level_str}. Existing handlers detected.")

    app_log_level_config = app.config.get('LOG_LEVEL', default_log_level_str).upper()
    app_effective_log_level = log_level_map.get(app_log_level_config, logging.INFO)
    app.logger.setLevel(app_effective_log_level)
    logging.info(f"Flask app.logger level set to {app_log_level_config}.")
    # Log settings after logger is configured
    app.logger.info(f"Loaded Booking CSV Schedule Settings: {app.config.get('BOOKING_CSV_SCHEDULE_SETTINGS')}")
    # This else block was associated with the `if not testing:` block for logging.
    # However, the `if testing: return app` statement higher up makes this else unreachable.
    # I'm removing it to avoid confusion. If minimal logging for testing is desired
    # and the early return is removed, this structure would need revisiting.
    # else:
        # Minimal logging for testing
        # app.logger.setLevel(logging.DEBUG) # Or WARNING to reduce noise if DEBUG is too verbose
        if not app.logger.hasHandlers(): # Ensure app.logger has a handler for tests
            app.logger.addHandler(logging.StreamHandler())
        # app.logger.info("Logging configured for TESTING mode.")
        # app.logger.info(f"Testing Booking CSV Schedule Settings: {app.config.get('BOOKING_CSV_SCHEDULE_SETTINGS')}")

    # New logic for startup restore - SKIP IF TESTING
    if not testing and azure_backup_available and callable(restore_latest_backup_set_on_startup):
        try:
            app.logger.info("Attempting to restore latest backup set from Azure on startup...")
            # Pass app.logger to the function for consistent logging
            downloaded_configs = restore_latest_backup_set_on_startup(app_logger=app.logger)
            
            if downloaded_configs: # Check if restore returned any paths
                app.logger.info(f"Startup restore downloaded config files: {downloaded_configs}")
                with app.app_context(): # Ensure operations run within application context
                    # db.init_app(app) should be called before this point so db operations can proceed.
                    
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

    # New: Conditional restore of incremental booking backups - SKIP IF TESTING
    if not testing and azure_backup_available and callable(restore_incremental_bookings):
        app.logger.info("Checking configuration for automatic restore of incremental booking records on startup...")
        scheduler_settings = load_scheduler_settings() # Load from utils.py
        should_restore_bookings = scheduler_settings.get('auto_restore_booking_records_on_startup', False)

        if should_restore_bookings:
            app.logger.info("Attempting to restore incremental booking records on startup as configured...")
            try:
                # Pass app instance directly. SocketIO and task_id are None for startup.
                restore_summary = restore_incremental_bookings(app=app, socketio_instance=None, task_id=None)
                app.logger.info(f"Incremental booking records restore attempt completed. Summary: {restore_summary}")
                if restore_summary.get('status') not in ['success', 'success_no_files']:
                     app.logger.warning(f"Incremental booking restore on startup finished with status: {restore_summary.get('status')}. Errors: {restore_summary.get('errors')}")
                # Add an audit log for the attempt
                with app.app_context():  # <<< WRAPPER ADDED
                    add_audit_log(action="STARTUP_INCREMENTAL_BOOKING_RESTORE_ATTEMPT",
                                  details=f"Status: {restore_summary.get('status')}, Files: {restore_summary.get('files_processed')}, Created: {restore_summary.get('bookings_created')}, Updated: {restore_summary.get('bookings_updated')}, Errors: {len(restore_summary.get('errors', []))}")
            except Exception as e_incr_restore:
                app.logger.exception(f"Error during startup incremental booking records restore: {e_incr_restore}")
                with app.app_context():  # <<< WRAPPER ADDED
                    add_audit_log(action="STARTUP_INCREMENTAL_BOOKING_RESTORE_ERROR", details=f"Exception: {str(e_incr_restore)}")
        else:
            app.logger.info("Automatic restore of incremental booking records on startup is disabled in settings.")
    elif not testing and callable(load_scheduler_settings) and load_scheduler_settings().get('auto_restore_booking_records_on_startup', False):
        # This case handles if setting is true, but azure_backup_available or restore_incremental_bookings is not.
        app.logger.warning("Automatic restore of incremental booking records is configured, but Azure backup utilities (restore_incremental_bookings) are not available. Skipping.")


    # 3. Initialize Extensions
    # db.init_app(app) has been moved to earlier in the factory function
    mail.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app, message_queue=app.config.get('SOCKETIO_MESSAGE_QUEUE')) # Add message_queue from config
    migrate.init_app(app, db)

    # login_manager and oauth are initialized within init_auth

    # 4. Setup SQLite Pragmas (if using SQLite) - Skip if testing
    if not testing and app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        with app.app_context():
            configure_sqlite_pragmas_factory(app, db)

        @app.before_request
        def ensure_sqlite_configured_wrapper():
           # Also check if not testing here, and URI starts with sqlite
           if not current_app.config.get('TESTING', False) and \
              current_app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
               _ensure_sqlite_configured_factory_hook(app, db)

    # 5. Register i18n
    init_translations(app) # i18n might be needed for tests if templates are rendered

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
    init_admin_api_bookings_routes(app) # Register new blueprint
    init_admin_api_system_settings_routes(app) # Register new blueprint

    # 8. Register Error Handlers - Skip if testing
    if not testing:
        @app.errorhandler(CSRFError)
        def handle_csrf_error_factory(e):
            app.logger.warning(f"CSRF error encountered: {e.description}. Request URL: {request.url}")
            return jsonify(error=str(e.description), type='CSRF_ERROR'), 400

        @app.errorhandler(404)
        def not_found_error(error):
            if request.blueprint and request.blueprint.startswith('api_'):
                 return jsonify(error="Not Found", message=str(error)), 404
            return "Page Not Found (HTML - create a template for this)", 404 # Placeholder

        @app.errorhandler(500)
        def internal_error(error):
            db.session.rollback()
            if request.blueprint and request.blueprint.startswith('api_'):
                 return jsonify(error="Internal Server Error", message=str(error)), 500
            return "Internal Server Error (HTML - create a template for this)", 500 # Placeholder

    # 9. Initialize Scheduler
    # Skip if testing or if SCHEDULER_ENABLED is False in config
    if not testing and app.config.get("SCHEDULER_ENABLED", True):
        apscheduler_available_check = True
        try:
            from apscheduler.schedulers.background import BackgroundScheduler # Already imported
        except ImportError:
            apscheduler_available_check = False
            app.logger.warning("APScheduler not installed. Scheduled tasks will not run.")

        if apscheduler_available_check:
            scheduler = BackgroundScheduler(daemon=True)

            # Add jobs from scheduler_tasks.py
        if cancel_unchecked_bookings:
            scheduler.add_job(cancel_unchecked_bookings, 'interval', minutes=app.config.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5), args=[app])
        if apply_scheduled_resource_status_changes:
            scheduler.add_job(apply_scheduled_resource_status_changes, 'interval', minutes=1, args=[app])
        if run_scheduled_backup_job:
            scheduler.add_job(run_scheduled_backup_job, 'interval', minutes=app.config.get('SCHEDULER_BACKUP_JOB_INTERVAL_MINUTES', 60), args=[app]) # New config option

        if run_scheduled_booking_csv_backup: # Check if the function exists
            booking_schedule_settings = app.config['BOOKING_CSV_SCHEDULE_SETTINGS']
            if booking_schedule_settings.get('enabled'):
                interval_value = booking_schedule_settings.get('interval_value', 24) # Default from helper if somehow missing
                interval_unit = booking_schedule_settings.get('interval_unit', 'hours') # Default from helper

                # APScheduler uses plural for interval units (minutes, hours, days)
                # However, the add_job function takes kwargs like hours=X, minutes=Y, days=Z
                job_kwargs = {}
                if interval_unit == 'minutes':
                    job_kwargs['minutes'] = interval_value
                elif interval_unit == 'hours':
                    job_kwargs['hours'] = interval_value
                elif interval_unit == 'days':
                    job_kwargs['days'] = interval_value
                else:
                    # Should not happen due to validation in load_booking_csv_schedule_settings
                    app.logger.warning(f"Invalid interval unit '{interval_unit}' from settings. Defaulting to 24 hours.")
                    job_kwargs['hours'] = 24

                scheduler.add_job(
                    run_scheduled_booking_csv_backup,
                    'interval',
                    id='scheduled_booking_csv_backup_job', # Add an ID for later modification/removal
                    **job_kwargs,
                    args=[app] # Pass the app instance itself
                )
                app.logger.info(f"Scheduled booking CSV backup job added: Interval {interval_value} {interval_unit}, Range: {booking_schedule_settings.get('range_type')}.")
            else:
                app.logger.info("Scheduled booking CSV backup is disabled in settings. Job not added.")

        if azure_backup_if_changed: # Legacy Azure backup
             scheduler.add_job(azure_backup_if_changed, 'interval', minutes=app.config.get('AZURE_BACKUP_INTERVAL_MINUTES', 60))

        # if not app.testing: # Original condition
        if not app.config.get('TESTING', False) and app.config.get("SCHEDULER_ENABLED", True): # More robust check
             try:
                 scheduler.start()
                 app.logger.info("Background scheduler started.")
             except Exception as e:
                 app.logger.exception(f"Failed to start background scheduler: {e}")
        else:
            app.logger.info("Background scheduler not started (either in test mode or SCHEDULER_ENABLED is False).")
            app.scheduler = scheduler
        else: # apscheduler_available_check is False
            app.scheduler = None # Ensure app.scheduler exists
            app.logger.info("APScheduler not installed, so it was not started.")
    else: # Testing or SCHEDULER_ENABLED is False
        app.scheduler = None # Ensure app.scheduler exists but is None
        if testing:
            app.logger.info("Scheduler not started in TESTING mode.")
        else: # SCHEDULER_ENABLED was False
            app.logger.info("Scheduler not started because SCHEDULER_ENABLED is False.")

    if not testing: # Final log message only if not testing
        app.logger.info("Flask app created and configured via factory.")

    return app
