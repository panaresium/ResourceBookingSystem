from flask import Flask, jsonify, request # jsonify for error handler, request for error handlers
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import json # Added for json.load and json.dumps
import logging

# Import configurations, extensions, and initialization functions
import config
from extensions import db, login_manager, oauth, csrf, migrate # Removed mail, socketio
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
from routes.admin_api_maintenance import admin_api_maintenance_bp
from routes.api_system_settings import init_api_system_settings_routes
from routes.api_public import init_api_public_routes
from routes.gmail_auth import init_gmail_auth_routes # Added for Gmail OAuth flow

# For scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from scheduler_tasks import (
    cancel_unchecked_bookings,
    apply_scheduled_resource_status_changes,
    run_scheduled_backup_job,
    auto_checkout_overdue_bookings,
    auto_release_unclaimed_bookings,
    send_checkin_reminders,
    run_scheduled_incremental_booking_data_task,
    run_periodic_full_booking_data_task,
)
# Conditional import for azure_backup
# Only import 'backup_if_changed' as 'perform_startup_restore_sequence' is no longer used here.
try:
    from azure_backup import backup_if_changed as azure_backup_if_changed
    azure_backup_if_changed_available = True # More specific flag name
except ImportError as e_import_azure_bifc: # Capture the exception
    logging.getLogger(__name__).warning(f"Failed to import 'backup_if_changed' from azure_backup.py. Legacy Azure backup job may be unavailable. Error: {e_import_azure_bifc}")
    azure_backup_if_changed = None # Ensure it's None if import fails
    azure_backup_if_changed_available = False # More specific flag name


# New diagnostic logging block
# Assuming app.logger is available after the create_app's initial error log.
# If app_factory is imported before create_app() is called and fully configured, these might not show as expected.
# For safety, these logs are now inside create_app, after app.logger is more likely to be configured.
# This section will be moved into create_app() later if direct logging here is problematic.

# Imports for processing downloaded configs during startup restore
from utils import (
    load_scheduler_settings,  # Added for new setting
    DEFAULT_FULL_BACKUP_SCHEDULE,  # Added for full backup job scheduling
    _import_map_configuration_data,
    _import_resource_configurations_data,
    _import_user_configurations_data,
    add_audit_log,
    send_email,
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

def create_app(config_object=config, testing=False, start_scheduler=True): # Added start_scheduler parameter
    app = Flask(__name__, template_folder='templates', static_folder='static')
    # Corrected template_folder and static_folder paths assuming app_factory.py is in root.
    # If app_factory is in a sub-directory, these might need adjustment (e.g. app.Flask('instance', ...))

    # NEW LOGS HERE:
    # Note: app.logger might not be fully configured with handlers/levels yet,
    # but messages sent to it should be buffered or handled once logging is set up.
    # For immediate critical output if needed, standard print() or logging.warning() could be used
    # before app.logger is reliably configured. However, standard practice is to use app.logger.
    # Ensure early logs are emitted at INFO level
    app.logger.setLevel(logging.INFO)
    app.logger.info("ERROR_DIAG: APP_FACTORY - create_app function entered.")
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
    # Initialize Migrate immediately after DB and App, and before startup restore sequence
    migrate.init_app(app, db)

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

    # The logic for determining 'should_attempt_restore' and logging related messages
    # about Azure restore being moved to init_setup.py is now removed from app_factory.py,
    # as it's no longer relevant here. init_setup.py handles its own restore triggering.
    # app_factory.py will just create the app; init_setup.py will decide to use it for restore.

    # Old incremental booking restore block is removed.

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
    # socketio.init_app(app) has been removed as SocketIO is no longer used.
    # migrate.init_app(app, db) # MOVED EARLIER

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

    # CSRF exemption for Socket.IO paths has been removed as Socket.IO is no longer used.

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
    app.register_blueprint(admin_api_maintenance_bp)
    init_api_system_settings_routes(app) # Register new blueprint
    init_api_public_routes(app)
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
    # Also respect the new start_scheduler parameter
    if not testing and app.config.get("SCHEDULER_ENABLED", True) and start_scheduler:
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

            # Configure unified booking data backup jobs using simple config flags
            if app.config.get("UNIFIED_INCREMENTAL_BACKUP_ENABLED", False):
                try:
                    interval = int(app.config.get("UNIFIED_INCREMENTAL_BACKUP_INTERVAL_MINUTES", 30))
                    scheduler.add_job(
                        func=run_scheduled_incremental_booking_data_task,
                        trigger="interval",
                        minutes=interval,
                        id="unified_incremental_booking_backup_job",
                        replace_existing=True,
                        args=[app],
                    )
                    app.logger.info(
                        f"Scheduled unified incremental booking backup job to run every {interval} minutes."
                    )
                except Exception as e:
                    app.logger.error(
                        f"Error scheduling unified incremental booking backup job: {e}",
                        exc_info=True,
                    )
            else:
                app.logger.info("Unified incremental booking backup job disabled in configuration.")

            if app.config.get("UNIFIED_FULL_BACKUP_ENABLED", False):
                time_of_day = app.config.get("UNIFIED_FULL_BACKUP_TIME_OF_DAY", "02:00")
                try:
                    hour, minute = [int(x) for x in time_of_day.split(":")]
                    scheduler.add_job(
                        func=run_periodic_full_booking_data_task,
                        trigger="cron",
                        id="unified_full_booking_backup_job",
                        replace_existing=True,
                        args=[app],
                        hour=hour,
                        minute=minute,
                    )
                    app.logger.info(
                        f"Scheduled unified full booking backup job daily at {hour:02d}:{minute:02d}."
                    )
                except Exception as e:
                    app.logger.error(
                        f"Error scheduling unified full booking backup job: {e}",
                        exc_info=True,
                    )
            else:
                app.logger.info("Unified full booking backup job disabled in configuration.")

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

            # Use the more specific azure_backup_if_changed_available flag
            if azure_backup_if_changed and azure_backup_if_changed_available: # Legacy Azure backup
                 scheduler.add_job(azure_backup_if_changed, 'interval', minutes=app.config.get('AZURE_BACKUP_INTERVAL_MINUTES', 60), args=[app]) # Added args=[app]

            # Start the scheduler only if it's not testing and SCHEDULER_ENABLED is true
            # The outer 'if not testing and app.config.get("SCHEDULER_ENABLED", True) and start_scheduler:' already covers this.
            try:
                scheduler.start()
                app.logger.info("Background scheduler started.")
            except Exception as e:
                app.logger.exception(f"Failed to start background scheduler: {e}")
            app.scheduler = scheduler
        else: # apscheduler_available_check is False
            app.scheduler = None # Ensure app.scheduler exists
            app.logger.info("APScheduler not installed, so it was not started.")
    else: # Testing or SCHEDULER_ENABLED is False or start_scheduler is False
        app.scheduler = None # Ensure app.scheduler exists but is None
        if testing:
            app.logger.info("Scheduler not started in TESTING mode.")
        elif not app.config.get("SCHEDULER_ENABLED", True):
            app.logger.info("Scheduler not started because SCHEDULER_ENABLED is False in config.")
        elif not start_scheduler:
            app.logger.info("Scheduler not started because start_scheduler parameter was False (e.g., for init_setup.py restore context).")

    if not testing: # Final log message only if not testing
        app.logger.info("Flask app created and configured via factory.")

    return app
