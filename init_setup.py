#!/usr/bin/env python3

import sys
import os
import pathlib
import json
from werkzeug.security import generate_password_hash
from datetime import datetime, date, timedelta, time

# Refactored imports for application factory pattern
from app_factory import create_app
from extensions import db
from models import (
    User,
    Resource,
    Booking,
    Role,
    AuditLog,
    FloorMap,
    WaitlistEntry,
    resource_roles_table, # Assuming these are still relevant and defined in models.py
    user_roles_table    # or directly in extensions.py if preferred for table instances
)
# `add_tags_column` seems to be a custom migration script.
# Ensure it's compatible or adjust its import/execution.
# For now, assuming it works independently or is adapted elsewhere.
from add_resource_tags_column import add_tags_column


AZURE_PRIMARY_STORAGE = bool(os.environ.get("AZURE_PRIMARY_STORAGE"))
if AZURE_PRIMARY_STORAGE:
    try:
        from azure_storage import ( # This is a separate, pre-existing module
            download_database,
            download_media,
            upload_database,
            upload_media,
        )
    except Exception as exc:  # pragma: no cover - optional
        print(f"Warning: Azure storage unavailable: {exc}")
        AZURE_PRIMARY_STORAGE = False

MIN_PYTHON_VERSION = (3, 7)
# Project root directory
BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR_NAME = "data"
STATIC_DIR_NAME = "static"
FLOOR_MAP_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "floor_map_uploads")
RESOURCE_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "resource_uploads")
DB_PATH = BASE_DIR / DATA_DIR_NAME / 'site.db' # Using pathlib for consistency

if AZURE_PRIMARY_STORAGE:
    print("Downloading database from Azure storage...")
    try:
        download_database() # Assumes this function knows DB_PATH or configured path
    except Exception as exc:
        print(f"Failed to download database from Azure: {exc}")

def check_python_version():
    """Checks if the current Python version meets the minimum requirement."""
    print("Checking Python version...")
    if sys.version_info < MIN_PYTHON_VERSION:
        print(
            f"Error: Your Python version is {sys.version_info.major}.{sys.version_info.minor}."
            f" This project requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher."
        )
        sys.exit(1)
    print(f"Python version {sys.version_info.major}.{sys.version_info.minor} is sufficient.")
    return True

def create_required_directories():
    """Creates the data directory and other necessary static subdirectories if they don't exist."""
    dirs_to_create = [
        BASE_DIR / DATA_DIR_NAME,
        BASE_DIR / STATIC_DIR_NAME,
        BASE_DIR / FLOOR_MAP_UPLOADS_DIR_NAME,
        BASE_DIR / RESOURCE_UPLOADS_DIR_NAME,
        BASE_DIR / "logs" # Assuming logs directory is also desired at root
    ]
    for dir_path in dirs_to_create:
        print(f"Checking for '{dir_path}' directory...")
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created '{dir_path}' directory.")
            except OSError as e:
                print(f"Error: Could not create '{dir_path}' directory: {e}")
                if dir_path == BASE_DIR / DATA_DIR_NAME: # Data directory is critical
                    sys.exit(1)
        else:
            print(f"'{dir_path}' directory already exists.")

    if AZURE_PRIMARY_STORAGE:
        print("Downloading media from Azure storage...")
        try:
            download_media() # Assumes this knows target paths like FLOOR_MAP_UPLOADS_DIR_NAME
        except Exception as exc:
            print(f"Failed to download media from Azure: {exc}")
    return True

def ensure_tags_column():
    """Ensure the 'tags' column exists in the resource table."""
    if not DB_PATH.exists():
        print(f"Database file not found at {DB_PATH}, skipping 'tags' column check.")
        return
    try:
        # add_tags_column likely uses Flask-Migrate or direct SQL that needs app context if it uses SQLAlchemy
        # For simplicity, if it's raw SQL on DB_PATH, it's fine.
        # If it uses SQLAlchemy models, it needs an app context.
        # Assuming add_tags_column is self-contained or adapted for this.
        current_app = create_app()
        with current_app.app_context():
            print(f"Ensuring 'tags' column via add_tags_column. DB: {current_app.config['SQLALCHEMY_DATABASE_URI']}")
            add_tags_column() # This function needs to be callable and use the app context if using SQLAlchemy
    except Exception as exc:
        print(f"Failed to ensure 'tags' column exists: {exc}")


def ensure_db_column(table_name, column_name, column_type):
    """Generic function to ensure a column exists in a table."""
    if not DB_PATH.exists():
        print(f"Database file not found at {DB_PATH}, skipping '{column_name}' column check for table '{table_name}'.")
        return

    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        if column_name not in columns:
            print(f"Adding '{column_name}' column to '{table_name}' table...")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
            print(f"'{column_name}' column added to '{table_name}'.")
        else:
            print(f"'{column_name}' column already exists in '{table_name}'. No action taken.")
    except Exception as exc:
        print(f"Failed to ensure '{column_name}' column in '{table_name}': {exc}")
    finally:
        if conn:
            conn.close()

def ensure_all_migrations():
    """Runs all schema check/migration functions."""
    # `ensure_tags_column` will create its own app context if it needs one.
    ensure_tags_column() # Needs careful review of its implementation
    ensure_db_column('resource', 'image_filename', 'VARCHAR(255)')
    ensure_db_column('floor_map', 'location', 'VARCHAR(100)')
    ensure_db_column('floor_map', 'floor', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status_at', 'DATETIME')


def verify_db_schema():
    """Check if the existing database has the expected tables and columns."""
    if not DB_PATH.exists():
        print(f"Database file {DB_PATH} not found for schema verification.")
        return False

    import sqlite3
    # Expected schema definition remains the same
    expected_schema = {
        'user': {'id', 'username', 'email', 'password_hash', 'is_admin', 'google_id', 'google_email'},
        'role': {'id', 'name', 'description', 'permissions'},
        'user_roles': {'user_id', 'role_id'},
        'floor_map': {'id', 'name', 'image_filename', 'location', 'floor'},
        'resource': {'id', 'name', 'capacity', 'equipment', 'tags', 'booking_restriction', 'status', 'published_at', 'allowed_user_ids', 'image_filename', 'is_under_maintenance', 'maintenance_until', 'max_recurrence_count', 'scheduled_status', 'scheduled_status_at', 'floor_map_id', 'map_coordinates'},
        'resource_roles': {'resource_id', 'role_id'},
        'booking': {'id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'checked_in_at', 'checked_out_at', 'status', 'recurrence_rule'},
        'waitlist_entry': {'id', 'resource_id', 'user_id', 'timestamp'},
        'audit_log': {'id', 'timestamp', 'user_id', 'username', 'action', 'details'}
    }
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for table, cols in expected_schema.items():
            cursor.execute(f"PRAGMA table_info({table})")
            info = cursor.fetchall()
            if not info:
                print(f"Missing table: {table}")
                return False
            existing = {row[1] for row in info}
            if not cols.issubset(existing):
                missing = cols - existing
                print(f"Table '{table}' missing columns: {', '.join(missing)}")
                return False
        print("Database schema verification successful.")
        return True
    except Exception as exc:
        print(f"Error verifying database schema: {exc}")
        return False
    finally:
        if conn:
            conn.close()

def init_db(force=False):
    current_app = create_app() # Create an app instance for context
    with current_app.app_context():
        current_app.logger.info(f"Database URI used by init_db: {current_app.config.get('SQLALCHEMY_DATABASE_URI')}")
        current_app.logger.info("Starting database initialization...")

        # Run schema migrations/checks before create_all if DB exists, or after if creating new
        # If DB_PATH exists, it implies create_all might not do anything if tables are there.
        # If it doesn't exist, create_all makes them, then we might not need these.
        # For robustness, call ensure_all_migrations. If tables don't exist, they'll error gracefully.
        # This is better handled by proper migration tools like Alembic usually.
        current_app.logger.info("Creating database tables (db.create_all())...")
        db.create_all() # This creates tables based on models if they don't exist.
        current_app.logger.info("Database tables creation/verification step completed.")

        # Now that tables are guaranteed to exist, run migrations/column checks.
        # This is relevant whether the DB file existed before or was just created.
        current_app.logger.info("Ensuring all schema elements (columns) are present after table creation.")
        ensure_all_migrations()

        if not force:
            # Check if any of the core tables have data
            query = "SELECT 1 FROM user LIMIT 1" # Simple query for existence
            try:
                result = db.session.execute(db.text(query)).scalar_one_or_none()
                if result is not None:
                    current_app.logger.warning(
                        "init_db aborted: existing data detected in 'user' table (or other tables). "
                        "Pass force=True to reset database."
                    )
                    return
            except Exception as e: # Table might not exist if it's a completely fresh DB
                current_app.logger.info(f"Could not check for existing data (table might be new): {e}")


        current_app.logger.info("Attempting to delete existing data in corrected order (if force=True or no data check passed)...")
        # Order: AuditLog -> WaitlistEntry -> Booking -> resource_roles_table -> Resource
        # -> FloorMap -> user_roles_table -> User -> Role
        db.session.query(AuditLog).delete()
        db.session.query(WaitlistEntry).delete()
        db.session.query(Booking).delete()
        db.session.execute(resource_roles_table.delete())
        db.session.query(Resource).delete()
        db.session.query(FloorMap).delete()
        db.session.execute(user_roles_table.delete())
        db.session.query(User).delete()
        db.session.query(Role).delete()

        try:
            db.session.commit()
            current_app.logger.info("Successfully committed deletions of existing data.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error committing deletions during DB initialization:")
            raise # Re-raise after logging if this is critical

        current_app.logger.info("Creating default roles and users...")
        try:
            # Default Admin User from config or hardcoded fallback
            default_admin_username = current_app.config.get('DEFAULT_ADMIN_USERNAME', 'admin')
            default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
            default_admin_password = current_app.config.get('DEFAULT_ADMIN_PASSWORD', 'ChangeMe123!')

            admin_role = Role(name="Administrator", description="Full system access", permissions="all_permissions,view_analytics,manage_bookings,manage_system,manage_users,manage_resources,manage_floor_maps")
            standard_role = Role(name="StandardUser", description="Can make bookings and view resources", permissions="make_bookings,view_resources")

            admin_user = User(username=default_admin_username, email=default_admin_email, is_admin=True)
            admin_user.set_password(default_admin_password) # Use the method to hash password

            standard_user = User(username="user", email="user@example.com", is_admin=False)
            standard_user.set_password("userpass")

            admin_user.roles.append(admin_role)
            standard_user.roles.append(standard_role)
            db.session.add_all([admin_role, standard_role, admin_user, standard_user])
            db.session.commit()
            current_app.logger.warning(
                f"IMPORTANT SECURITY WARNING: A default admin user ('{default_admin_username}') with a password "
                f"has been created. This password MUST be changed immediately in a production environment."
            )
            current_app.logger.info("Default roles and users created.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating default roles or users:")
            raise

        # Sample Resources and Bookings
        admin_user_for_perms = User.query.filter_by(username=default_admin_username).first()
        standard_user_for_perms = User.query.filter_by(username='user').first()
        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1" # Fallback if not found
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2"

        admin_role_for_resource = Role.query.filter_by(name="Administrator").first()
        standard_role_for_resource = Role.query.filter_by(name="StandardUser").first()

        current_app.logger.info("Adding sample resources...")
        try:
            res_list = [
                Resource(name="Conference Room Alpha", capacity=10, equipment="Projector,Whiteboard", tags="large,video", status='published', published_at=datetime.utcnow(), roles=[standard_role_for_resource, admin_role_for_resource] if standard_role_for_resource and admin_role_for_resource else []),
                Resource(name="Meeting Room Beta", capacity=6, equipment="Teleconference", tags="medium", status='published', published_at=datetime.utcnow(), allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}"),
                Resource(name="Focus Room Gamma", capacity=2, equipment="Whiteboard", tags="quiet,small", status='draft', roles=[admin_role_for_resource] if admin_role_for_resource else []),
                Resource(name="Archived Room Omega", capacity=5, status='archived', published_at=datetime.utcnow() - timedelta(days=30))
            ]
            db.session.add_all(res_list)
            db.session.commit()
            current_app.logger.info(f"Successfully added {len(res_list)} sample resources.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error adding sample resources:")

        resource_alpha = Resource.query.filter_by(name="Conference Room Alpha").first()
        if resource_alpha:
            current_app.logger.info("Adding sample bookings...")
            try:
                bookings_list = [
                    Booking(resource_id=resource_alpha.id, user_name="user", title="Team Sync Alpha", start_time=datetime.combine(date.today(), time(9,0)), end_time=datetime.combine(date.today(), time(10,0))),
                    Booking(resource_id=resource_alpha.id, user_name="admin", title="Client Meeting Alpha", start_time=datetime.combine(date.today(), time(11,0)), end_time=datetime.combine(date.today(), time(12,30))),
                ]
                db.session.add_all(bookings_list)
                db.session.commit()
                current_app.logger.info(f"Successfully added {len(bookings_list)} sample bookings.")
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception("Error adding sample bookings:")
        else:
            current_app.logger.warning("Conference Room Alpha not found, skipping sample bookings for it.")

        current_app.logger.info("Ensuring default backup schedule JSON file exists...")
        data_dir_for_json = BASE_DIR / DATA_DIR_NAME
        schedule_config_file_path = data_dir_for_json / 'backup_schedule.json'
        default_schedule_data = current_app.config.get('DEFAULT_SCHEDULE_DATA', {"is_enabled": False, "schedule_type": "daily", "time_of_day": "02:00"})

        if not schedule_config_file_path.exists():
            try:
                data_dir_for_json.mkdir(parents=True, exist_ok=True)
                with open(schedule_config_file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_schedule_data, f, indent=4)
                current_app.logger.info(f"Created default backup schedule file: {schedule_config_file_path}")
            except IOError as e:
                current_app.logger.error(f"Error creating default backup schedule JSON file '{schedule_config_file_path}': {e}")
        else:
            current_app.logger.info(f"Backup schedule JSON file already exists: {schedule_config_file_path}")

        current_app.logger.info("Database initialization script completed within app context.")

        if AZURE_PRIMARY_STORAGE:
            print("Uploading database and media to Azure storage...")
            try:
                upload_database(versioned=False) # Assumes knows DB_PATH
                upload_media() # Assumes knows media paths
            except Exception as exc:
                print(f"Failed to upload data to Azure: {exc}")

def main(force_init=False):
    """Main function to run setup checks and tasks."""
    print("Starting project initialization...")
    
    check_python_version()
    print("-" * 30)
    create_required_directories()
    print("-" * 30)

    # Database initialization logic
    if force_init:
        print(f"Force initializing database at {DB_PATH}...")
        init_db(force=True)
        print("Database force initialization process completed.")
    elif DB_PATH.exists():
        print(f"Existing database found at {DB_PATH}. Verifying structure...")
        if verify_db_schema():
            print("Database structure looks correct. No re-initialization needed.")
            print("If you need to re-initialize, run: python init_setup.py --force")
        else:
            print("Database structure invalid or outdated. Recreating database...")
            # os.remove(DB_PATH) # Removing the DB if schema is bad might be too destructive.
            # Better to let init_db(force=True) handle it if user wants.
            print("Schema issues found. To attempt recreation, run: python init_setup.py --force")
            # init_db(force=True) # Or just proceed to recreate. For safety, require explicit --force.
    else:
        print(f"No database found at {DB_PATH}. Initializing database...")
        init_db(force=False) # force=False should still init if no DB exists
        print("Database initialization process completed.")

    print("-" * 30)
    print("Project initialization script completed successfully.")

if __name__ == "__main__":
    force_flag = '--force' in sys.argv
    main(force_init=force_flag)
