from flask import Flask, jsonify, request # jsonify for error handler, request for error handlers
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import json # Added for json.load and json.dumps
import logging

# Import configurations, extensions, and initialization functions
import config
from extensions import db, login_manager, oauth, csrf, socketio, migrate # Removed mail
# from flask_mail import Message # Removed: Added for test email - no longer needed by factory
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
from routes.gmail_auth import init_gmail_auth_routes # Added for Gmail OAuth flow

# For scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from scheduler_tasks import (
    cancel_unchecked_bookings,
    apply_scheduled_resource_status_changes,
    run_scheduled_backup_job,
    # run_scheduled_booking_csv_backup, # LEGACY - Removed
    auto_checkout_overdue_bookings,
    auto_release_unclaimed_bookings,
    send_checkin_reminders,
    run_scheduled_incremental_booking_data_task, # New task for unified incrementals
    run_periodic_full_booking_data_task # New task for unified periodic fulls
)
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
    DEFAULT_FULL_BACKUP_SCHEDULE, # Added for full backup job scheduling
    _import_map_configuration_data,
    _import_resource_configurations_data,
    _import_user_configurations_data,
    add_audit_log,
    send_email,
    load_unified_backup_schedule_settings
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

# Removed load_booking_csv_schedule_settings helper function

def create_app(config_object=config, testing=False): # Added testing parameter
    app = Flask(__name__, template_folder='templates', static_folder='static')
    # Corrected template_folder and static_folder paths assuming app_factory.py is in root.
    # If app_factory is in a sub-directory, these might need adjustment (e.g. app.Flask('instance', ...))

    # NEW LOGS HERE:
    # Note: app.logger might not be fully configured with handlers/levels yet,
    # but messages sent to it should be buffered or handled once logging is set up.
    # For immediate critical output if needed, standard print() or logging.warning() could be used
    # before app.logger is reliably configured. However, standard practice is to use app.logger.
    app.logger.error("ERROR_DIAG: APP_FACTORY - create_app function entered.")
    # from extensions import mail # mail has been removed from imports
    # app.logger.error(f"ERROR_DIAG: APP_FACTORY - Initial mail object ID in create_app: {id(mail)}") # mail removed

    # 1. Load Configuration
    app.config.from_object(config_object)

    # Add ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
    # app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] = load_booking_csv_schedule_settings(app) # Removed
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
    # if not root_logger.hasHandlers():
    #     stream_handler = logging.StreamHandler()
    #     formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    #     stream_handler.setFormatter(formatter)
    #     root_logger.addHandler(stream_handler)
    #     logging.info(f"Root logger configured with level {log_level_str} and a default StreamHandler.")
    # else:
    #     logging.info(f"Root logger level set to {log_level_str}. Existing handlers detected.")

    app_log_level_config = app.config.get('LOG_LEVEL', default_log_level_str).upper()
    app_effective_log_level = log_level_map.get(app_log_level_config, logging.INFO)
    app.logger.setLevel(app_effective_log_level)
    logging.info(f"Flask app.logger level set to {app_log_level_config} (effective: {app.logger.level}).")

    # Clear existing handlers and add a new explicit one
    app.logger.handlers.clear()
    logging.info("Cleared existing handlers from app.logger.")

    stream_handler_app = logging.StreamHandler()
    formatter_app = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    stream_handler_app.setFormatter(formatter_app)
    app.logger.addHandler(stream_handler_app)
    logging.info("Added new explicit StreamHandler to app.logger.")

    app.logger.propagate = False
    logging.info("Ensured app.logger.propagate is False.")

    # Control verbosity of Azure SDK loggers based on app's log level
    azure_logger_names = [
        'azure.core.pipeline.policies.http_logging_policy',
        'azure.storage.fileshare',
        'azure_backup'  # Assuming azure_backup.py uses logging.getLogger(__name__)
    ]

    # app_effective_log_level holds the logging.LEVEL value for app.logger
    if app_effective_log_level == logging.INFO:
        logging.info("Application log level is INFO. Setting verbose Azure SDK loggers to WARNING.")
        for logger_name in azure_logger_names:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
    elif app_effective_log_level == logging.DEBUG:
        logging.info("Application log level is DEBUG. Azure SDK loggers will retain their default/debug verbosity.")
        # Optionally, explicitly set them to DEBUG or INFO if needed
        # for logger_name in azure_logger_names:
        #     logging.getLogger(logger_name).setLevel(logging.DEBUG)

    # Ensure DEBUG level is comprehensively set if configured
    if app.config.get('LOG_LEVEL') == 'DEBUG':
        app.logger.info("LOG_LEVEL is DEBUG, ensuring Flask app and root logger levels are set to DEBUG.")
        logging.getLogger().setLevel(logging.DEBUG) # Ensure root logger is also DEBUG
        app.logger.setLevel(logging.DEBUG) # Explicitly set app logger to DEBUG again
        app.logger.debug("DEBUG log level confirmed for app.logger and root logger.")

    # Log settings after logger is configured
    # app.logger.info(f"Loaded Booking CSV Schedule Settings: {app.config.get('BOOKING_CSV_SCHEDULE_SETTINGS')}") # Removed
    # This else block was associated with the `if not testing:` block for logging.
    # However, the `if testing: return app` statement higher up makes this else unreachable.
    # The following lines were causing an IndentationError because they were part of this
    # effectively commented-out (or unreachable) else block.
    # They are now removed entirely as the logic for testing logging is handled
    # within the `if testing: return app` block or not at all if minimal logging is sufficient there.
    # Previous problematic lines:
    #    if not app.logger.hasHandlers(): # Ensure app.logger has a handler for tests
    #        app.logger.addHandler(logging.StreamHandler())

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
                        app.logger.debug(f"Importing resource configurations from {resource_configs_path} on startup.")
                        try:
                            with open(resource_configs_path, 'r', encoding='utf-8') as f:
                                resource_data_to_import = json.load(f)
                            # db object is globally available from extensions.py and functions are called within app_context
                            res_created, res_updated, res_errors = _import_resource_configurations_data(resource_data_to_import)
                            app.logger.debug(f"Startup import of resource configs: {res_created} created, {res_updated} updated. Errors: {len(res_errors)}")
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
                        app.logger.debug(f"Importing map configuration from {map_config_path} on startup.")
                        try:
                            with open(map_config_path, 'r', encoding='utf-8') as f:
                                map_data_to_import = json.load(f)
                            import_summary, import_status_code = _import_map_configuration_data(map_data_to_import)
                            app.logger.debug(f"Startup import of map config status {import_status_code}. Summary: {json.dumps(import_summary)}")
                            add_audit_log(action="STARTUP_RESTORE_IMPORT", details=f"Map config imported. Status: {import_status_code}. Summary: {json.dumps(import_summary)}")
                        except Exception as import_err:
                            app.logger.exception(f"Error importing map configuration on startup from {map_config_path}: {import_err}")
                        finally:
                            try: os.remove(map_config_path)
                            except OSError as e_remove: app.logger.error(f"Error removing temp map_config file {map_config_path} on startup: {e_remove}")

                    # Import user configurations
                    user_configs_path = downloaded_configs.get('user_configs_path')
                    if user_configs_path and os.path.exists(user_configs_path):
                        app.logger.debug(f"Importing user/role configurations from {user_configs_path} on startup.")
                        try:
                            with open(user_configs_path, 'r', encoding='utf-8') as f:
                                user_data_to_import = json.load(f)
                            # db object is globally available from extensions.py and functions are called within app_context
                            r_created, r_updated, u_created, u_updated, u_errors = _import_user_configurations_data(user_data_to_import)
                            app.logger.debug(f"Startup import of user/role configs: Roles({r_created}c, {r_updated}u), Users({u_created}c, {u_updated}u). Errors: {len(u_errors)}")
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
    # Removed Flask-Mail related diagnostic logs and mail.init_app(app)
    # mail.init_app(app) # Removed

    # Test email sending block - mail object and its state are no longer relevant here
    # mail_state_for_test = getattr(mail, 'state', None) # mail removed
    # app_from_state_for_test = getattr(mail_state_for_test, 'app', None) # mail removed
    # app.logger.error(f"ERROR_DIAG: APP_FACTORY - Test email check: mail.state: {mail_state_for_test}, mail.state.app: {app_from_state_for_test}") # mail removed

    # app.logger.info("Attempting to send test email from app_factory.py...")
    # with app.app_context():
    #     try:
    #         # utils.send_email now handles its own detailed success/failure logging.
    #         # The factory's role is just to trigger the test email.
    #         send_email(
    #             to_address="debug@example.com",
    #             subject="Test Email from App Factory (Startup Check)",
    #             body="This is a test email sent from app_factory.py during application startup to check email functionality."
    #         )
    #         # Success message is now primarily handled within send_email or by observing logs from utils.py
    #         app.logger.info("Test email dispatch attempt from factory completed. Check logs for success/failure details from utils.send_email.")
    #     except Exception as e_factory_mail:
    #         # This will catch unexpected errors if the send_email call itself fails catastrophically.
    #         app.logger.error(f"Test email dispatch from factory FAILED due to an unexpected error: {e_factory_mail}", exc_info=True)

    csrf.init_app(app)
    socketio.init_app(app) # Add message_queue from config
    migrate.init_app(app, db)

    # login_manager and oauth are initialized within init_auth

    # 4. Setup SQLite Pragmas (if using SQLite) - Skip if testing
    if not testing and app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        with app.app_context():
            configure_sqlite_pragmas_factory(app, db)

        @app.before_request
        def ensure_sqlite_configured_wrapper():
           # Also check if not testing here, and URI starts with sqlite
           # Use 'app.config' from the closure instead of 'current_app.config'
           if not app.config.get('TESTING', False) and \
              app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
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
    init_gmail_auth_routes(app) # Added for Gmail OAuth flow

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
            all_scheduler_settings = load_scheduler_settings() # Load once for all jobs

            # Add jobs from scheduler_tasks.py
            if cancel_unchecked_bookings: # Check if function exists before adding
                scheduler.add_job(cancel_unchecked_bookings, 'interval', minutes=app.config.get('AUTO_CANCEL_CHECK_INTERVAL_MINUTES', 5), args=[app])
            if apply_scheduled_resource_status_changes: # Check if function exists
                scheduler.add_job(apply_scheduled_resource_status_changes, 'interval', minutes=1, args=[app])

            # Dynamic scheduling for Full System Backup
            if run_scheduled_backup_job:
                # all_scheduler_settings loaded above
                full_backup_config = all_scheduler_settings.get('full_backup', DEFAULT_FULL_BACKUP_SCHEDULE.copy())

                if full_backup_config.get('is_enabled'):
                    job_id = 'scheduled_full_system_backup_job'
                    trigger_args = {}
                    trigger_type = None
                    schedule_type = full_backup_config.get('schedule_type', 'daily') # Default to daily

                    try:
                        if schedule_type == 'interval':
                            trigger_type = 'interval'
                            unit = full_backup_config.get('interval_unit', 'hours')
                            value = int(full_backup_config.get('interval_value', 24)) # Default to 24 if missing
                            if value <= 0: # Basic validation
                                app.logger.error(f"Invalid interval value ({value}) for full system backup. Must be positive. Job not scheduled.")
                                trigger_type = None # Prevent scheduling
                            elif unit == 'minutes':
                                trigger_args['minutes'] = value
                            elif unit == 'hours':
                                trigger_args['hours'] = value
                            else: # Unknown unit
                                app.logger.error(f"Invalid interval unit ({unit}) for full system backup. Must be 'minutes' or 'hours'. Job not scheduled.")
                                trigger_type = None # Prevent scheduling

                            if trigger_type:
                                app.logger.info(f"Scheduling full system backup job ({job_id}) to run every {value} {unit}.")

                        elif schedule_type == 'daily':
                            trigger_type = 'cron'
                            time_of_day = full_backup_config.get('time_of_day', '02:00') # Default if missing
                            time_parts = time_of_day.split(':')
                            trigger_args['hour'] = int(time_parts[0])
                            trigger_args['minute'] = int(time_parts[1])
                            app.logger.info(f"Scheduling full system backup job ({job_id}) to run daily at {trigger_args['hour']:02d}:{trigger_args['minute']:02d}.")

                        elif schedule_type == 'weekly':
                            trigger_type = 'cron'
                            time_of_day = full_backup_config.get('time_of_day', '02:00') # Default if missing
                            day_of_week = full_backup_config.get('day_of_week', 0) # Default to Monday if missing
                            time_parts = time_of_day.split(':')
                            trigger_args['day_of_week'] = str(day_of_week)
                            trigger_args['hour'] = int(time_parts[0])
                            trigger_args['minute'] = int(time_parts[1])
                            app.logger.info(f"Scheduling full system backup job ({job_id}) to run weekly on day {trigger_args['day_of_week']} at {trigger_args['hour']:02d}:{trigger_args['minute']:02d}.")

                        else:
                            app.logger.warning(f"Unknown schedule_type '{schedule_type}' for full system backup job ({job_id}). Job not scheduled.")

                        if trigger_type:
                            scheduler.add_job(
                                func=run_scheduled_backup_job,
                                trigger=trigger_type,
                                id=job_id,
                                replace_existing=True,
                                args=[app],
                                **trigger_args
                            )
                        else:
                            app.logger.warning(f"Full system backup job ({job_id}) not scheduled due to invalid configuration or trigger_type being None.")

                    except ValueError as e:
                        app.logger.error(f"Error parsing schedule parameters for full system backup job ({job_id}): {e}. Job not scheduled.", exc_info=True)
                    except Exception as e:
                        app.logger.error(f"An unexpected error occurred while configuring full system backup job ({job_id}): {e}. Job not scheduled.", exc_info=True)
                else:
                    app.logger.info(f"Scheduled full system backup job ({DEFAULT_FULL_BACKUP_SCHEDULE.get('id','scheduled_full_system_backup_job')}) is disabled in settings.")
            else:
                app.logger.warning("run_scheduled_backup_job function not found in scheduler_tasks. Full system backup job not added.")

            # LEGACY - Scheduled Azure CSV Backup - Job addition commented out as task is removed/commented.
            # if run_scheduled_booking_csv_backup: # Check if the function exists
            #     # app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] is loaded from a separate file, not scheduler_settings.json
            #     # For consistency, let's assume booking_csv_backup settings are also in scheduler_settings.json
            #     # However, the current code loads it into app.config. For this change, we will keep that,
            #     # but if it were to be unified, it would use all_scheduler_settings.get('booking_csv_backup', ...)
            #     booking_csv_schedule_settings_from_config = app.config.get('BOOKING_CSV_SCHEDULE_SETTINGS', {}) # From app.config
            #
            #     # If we were to use scheduler_settings.json for CSV backups too (ideal future state):
            #     # booking_csv_schedule_settings = all_scheduler_settings.get('booking_csv_backup', DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy())
            #
            #     # Using the existing mechanism for CSV:
            #     if booking_csv_schedule_settings_from_config.get('enabled'):
            #         interval_value = booking_csv_schedule_settings_from_config.get('interval_value', 24)
            #         interval_unit = booking_csv_schedule_settings_from_config.get('interval_unit', 'hours')
            #
            #         job_kwargs = {}
            #         if interval_unit == 'minutes':
            #             job_kwargs['minutes'] = interval_value
            #         elif interval_unit == 'hours':
            #             job_kwargs['hours'] = interval_value
            #         elif interval_unit == 'days':
            #             job_kwargs['days'] = interval_value
            #         else:
            #             app.logger.warning(f"Invalid interval unit '{interval_unit}' from settings. Defaulting to 24 hours.")
            #             job_kwargs['hours'] = 24
            #
            #         scheduler.add_job(
            #             run_scheduled_booking_csv_backup,
            #             'interval',
            #             id='scheduled_booking_csv_backup_job', # Add an ID for later modification/removal
            #             **job_kwargs,
            #             args=[app]
            #         )
            #         app.logger.info(f"Scheduled booking CSV backup job added: Interval {interval_value} {interval_unit}, Range: {booking_csv_schedule_settings_from_config.get('range_type')}.")
            #     else:
            #         app.logger.info("Scheduled booking CSV backup is disabled in settings (from app.config). Job not added.")
            # # else: # LEGACY - run_scheduled_booking_csv_backup was commented out
            # #     app.logger.warning("run_scheduled_booking_csv_backup function not found or commented out in scheduler_tasks. Legacy CSV backup job not added.") # This line and related block removed.

            # Load new unified schedule settings
            # Ensure load_unified_backup_schedule_settings uses current_app or is passed app
            # For now, assuming it uses current_app which is fine if called within app_context
            # or if the function itself is designed to fetch current_app.
            # If app_context is needed: with app.app_context(): unified_schedule_settings = load_unified_backup_schedule_settings()
            # However, load_unified_backup_schedule_settings uses current_app.config directly, which should be fine here.
            unified_schedule_settings = load_unified_backup_schedule_settings()
            app.logger.info(f"Loaded unified backup schedule settings: {unified_schedule_settings}")

            # Remove Old Job Configuration for Incrementals (ID: scheduled_booking_data_protection_job)
            # This was the previous job for run_scheduled_incremental_booking_data_task
            # The new logic below will re-add it with a new ID if enabled.
            # If the old ID was different, adjust here. The old code block for this job is removed.
            app.logger.info("Attempting to remove old incremental backup job (ID: scheduled_booking_data_protection_job) if it exists.")
            scheduler.remove_job('scheduled_booking_data_protection_job', ignore_errors=True)


            # Configure Unified Incremental Backup Job
            if run_scheduled_incremental_booking_data_task:
                incremental_config = unified_schedule_settings.get('unified_incremental_backup', {})
                if incremental_config.get('is_enabled'):
                    try:
                        interval_minutes = int(incremental_config.get('interval_minutes', 30))
                        if interval_minutes <= 0:
                            app.logger.error(f"Invalid interval_minutes ({interval_minutes}) for unified incremental backup. Must be positive. Job not scheduled.")
                        else:
                            scheduler.add_job(
                                func=run_scheduled_incremental_booking_data_task,
                                trigger='interval',
                                minutes=interval_minutes,
                                id='unified_incremental_booking_backup_job', # New ID
                                replace_existing=True,
                                args=[app]
                            )
                            app.logger.info(f"Scheduled unified incremental booking backup job to run every {interval_minutes} minutes.")
                    except ValueError as e:
                        app.logger.error(f"Error parsing interval_minutes for unified incremental backup: {e}. Job not scheduled.", exc_info=True)
                    except Exception as e_job_add:
                         app.logger.error(f"Error adding unified incremental booking backup job to scheduler: {e_job_add}. Job not scheduled.", exc_info=True)
                else:
                    app.logger.info("Unified incremental booking backup is disabled in settings.")
            else:
                app.logger.warning("run_scheduled_incremental_booking_data_task function not found. Unified incremental backup job not added.")

            # Remove Old Hardcoded Job for Full Unified Backup (ID: periodic_full_booking_data_job)
            app.logger.info("Attempting to remove old hardcoded full backup job (ID: periodic_full_booking_data_job) if it exists.")
            scheduler.remove_job('periodic_full_booking_data_job', ignore_errors=True)

            # Configure Unified Full Backup Job
            if run_periodic_full_booking_data_task:
                full_config = unified_schedule_settings.get('unified_full_backup', {})
                if full_config.get('is_enabled'):
                    schedule_type = full_config.get('schedule_type', 'daily')
                    time_of_day_str = full_config.get('time_of_day', '02:00')

                    try:
                        time_parts = time_of_day_str.split(':')
                        hour = int(time_parts[0])
                        minute = int(time_parts[1])
                        if not (0 <= hour <= 23 and 0 <= minute <= 59):
                            raise ValueError("Hour or minute out of range.")

                        trigger_args = {'hour': hour, 'minute': minute}

                        if schedule_type == 'weekly':
                            day_of_week = full_config.get('day_of_week') # Should be 0-6
                            if day_of_week is None or not (0 <= int(day_of_week) <= 6):
                                app.logger.error(f"Invalid day_of_week ({day_of_week}) for weekly unified full backup. Must be 0-6. Job not scheduled.")
                                raise ValueError("Invalid day_of_week for weekly schedule.")
                            trigger_args['day_of_week'] = str(day_of_week)
                            app.logger.info(f"Configuring weekly unified full backup: Day {day_of_week} at {hour:02d}:{minute:02d}.")
                        elif schedule_type == 'monthly':
                            day_of_month = full_config.get('day_of_month') # Should be 1-31
                            if day_of_month is None or not (1 <= int(day_of_month) <= 31):
                                app.logger.error(f"Invalid day_of_month ({day_of_month}) for monthly unified full backup. Must be 1-31. Job not scheduled.")
                                raise ValueError("Invalid day_of_month for monthly schedule.")
                            trigger_args['day'] = str(day_of_month)
                            app.logger.info(f"Configuring monthly unified full backup: Day {day_of_month} at {hour:02d}:{minute:02d}.")
                        elif schedule_type == 'daily':
                             app.logger.info(f"Configuring daily unified full backup at {hour:02d}:{minute:02d}.")
                        else:
                            app.logger.error(f"Unknown schedule_type '{schedule_type}' for unified full backup. Job not scheduled.")
                            raise ValueError(f"Unknown schedule_type: {schedule_type}")

                        scheduler.add_job(
                            func=run_periodic_full_booking_data_task,
                            trigger='cron',
                            id='unified_full_booking_backup_job', # New ID
                            replace_existing=True,
                            args=[app],
                            **trigger_args
                        )
                        app.logger.info(f"Scheduled unified full booking backup job with type '{schedule_type}' and args {trigger_args}.")

                    except ValueError as e:
                        app.logger.error(f"Error parsing schedule parameters for unified full backup: {e}. Job not scheduled.", exc_info=True)
                    except Exception as e_job_add:
                        app.logger.error(f"Error adding unified full backup job to scheduler: {e_job_add}. Job not scheduled.", exc_info=True)
                else:
                    app.logger.info("Unified full booking backup is disabled in settings.")
            else:
                app.logger.warning("run_periodic_full_booking_data_task function not found. Unified full backup job not added.")

            # Add the new auto_checkout_overdue_bookings job
            if auto_checkout_overdue_bookings:
                # Using a default interval of 15 minutes as per prompt example.
                # Replace with app.config.get if a config key is established later.
                checkout_interval = 15
                scheduler.add_job(
                    id='auto_checkout_overdue', # Using the ID from the prompt
                    func=auto_checkout_overdue_bookings,
                    trigger='interval',
                    minutes=checkout_interval,
                    replace_existing=True, # Good practice
                    args=[app]
                )
                app.logger.info(f"Scheduled auto_checkout_overdue_bookings job: Interval {checkout_interval} minutes.")
            else:
                app.logger.warning("auto_checkout_overdue_bookings function not found in scheduler_tasks. Job not added.")

            # Add the new auto_release_unclaimed_bookings job
            if auto_release_unclaimed_bookings:
                release_interval = app.config.get('AUTO_RELEASE_UNCLAIMED_INTERVAL_MINUTES', 10)
                scheduler.add_job(
                    id='auto_release_unclaimed_bookings_job',
                    func=auto_release_unclaimed_bookings,
                    trigger='interval',
                    minutes=release_interval,
                    replace_existing=True,
                    args=[app]
                )
                app.logger.info(f"Scheduled auto_release_unclaimed_bookings job: Interval {release_interval} minutes.")
            else:
                app.logger.warning("auto_release_unclaimed_bookings function not found in scheduler_tasks. Job not added.")

            # Add the new send_checkin_reminders job
            if send_checkin_reminders:
                # Default interval of 5 minutes. Consider making this configurable.
                reminder_interval_minutes = app.config.get('CHECKIN_REMINDER_JOB_INTERVAL_MINUTES', 5)
                scheduler.add_job(
                    id='send_checkin_reminders_task',
                    func=send_checkin_reminders,
                    trigger='interval',
                    minutes=reminder_interval_minutes,
                    replace_existing=True,
                    args=[app]
                )
                app.logger.info(f"Scheduled send_checkin_reminders job: Interval {reminder_interval_minutes} minutes.")
            else:
                app.logger.warning("send_checkin_reminders function not found in scheduler_tasks. Job not added.")

            if azure_backup_if_changed: # Legacy Azure backup, check if function exists
                 scheduler.add_job(azure_backup_if_changed, 'interval', minutes=app.config.get('AZURE_BACKUP_INTERVAL_MINUTES', 60))

            # Start the scheduler only if it's not testing and SCHEDULER_ENABLED is true
            # The outer 'if not testing and app.config.get("SCHEDULER_ENABLED", True):' already covers this.
            try:
                scheduler.start()
                app.logger.info("Background scheduler started.")
            except Exception as e:
                app.logger.exception(f"Failed to start background scheduler: {e}")
            app.scheduler = scheduler
        else: # apscheduler_available_check is False
            app.scheduler = None # Ensure app.scheduler exists
            app.logger.info("APScheduler not installed, so it was not started.")
    else: # Testing or SCHEDULER_ENABLED is False
        app.scheduler = None # Ensure app.scheduler exists but is None
        if testing: # This log is now reachable due to the 'if testing: return app' being removed/changed
            app.logger.info("Scheduler not started in TESTING mode.")
        elif not app.config.get("SCHEDULER_ENABLED", True): # Log if disabled by config
            app.logger.info("Scheduler not started because SCHEDULER_ENABLED is False.")

    if not testing: # Final log message only if not testing
        app.logger.info("Flask app created and configured via factory.")

    return app
