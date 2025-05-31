#!/usr/bin/env python3

import sys
import os
import pathlib
from app import (
    app,
    db,
    User,
    Resource,
    Booking,
    Role,
    AuditLog,
    FloorMap,
    resource_roles_table,
    user_roles_table,
)
from werkzeug.security import generate_password_hash
from datetime import datetime, date, timedelta, time
from add_resource_tags_column import add_tags_column

AZURE_PRIMARY_STORAGE = bool(os.environ.get("AZURE_PRIMARY_STORAGE"))
if AZURE_PRIMARY_STORAGE:
    try:
        from azure_storage import (
            download_database,
            download_media,
            upload_database,
            upload_media,
        )
    except Exception as exc:  # pragma: no cover - optional
        print(f"Warning: Azure storage unavailable: {exc}")
        AZURE_PRIMARY_STORAGE = False

MIN_PYTHON_VERSION = (3, 7)
DATA_DIR_NAME = "data"
STATIC_DIR_NAME = "static"
FLOOR_MAP_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "floor_map_uploads")
RESOURCE_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "resource_uploads")
DB_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), DATA_DIR_NAME, 'site.db')

if AZURE_PRIMARY_STORAGE:
    print("Downloading database from Azure storage...")
    try:
        download_database()
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
    """Creates the data directory and floor map uploads directory if they don't exist."""
    # Create data directory
    data_dir = pathlib.Path(__file__).resolve().parent / DATA_DIR_NAME
    print(f"Checking for '{DATA_DIR_NAME}' directory...")
    if not data_dir.exists():
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{data_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{data_dir}' directory: {e}")
            sys.exit(1)
    else:
        print(f"'{data_dir}' directory already exists.")

    # Create static directory if it doesn't exist
    static_dir = pathlib.Path(__file__).resolve().parent / STATIC_DIR_NAME
    if not static_dir.exists():
        try:
            static_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{static_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{static_dir}' directory: {e}")
            # Decide if this is fatal, for now, we'll let it pass if data_dir was created
            # sys.exit(1) 
    else:
        print(f"'{static_dir}' directory already exists (good).")
       
    # Create floor map uploads directory
    floor_map_uploads_dir = pathlib.Path(__file__).resolve().parent / FLOOR_MAP_UPLOADS_DIR_NAME
    print(f"Checking for '{FLOOR_MAP_UPLOADS_DIR_NAME}' directory...")
    if not floor_map_uploads_dir.exists():
        try:
            floor_map_uploads_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{floor_map_uploads_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{floor_map_uploads_dir}' directory: {e}")
            # Decide if this is fatal
            # sys.exit(1) 
    else:
        print(f"'{floor_map_uploads_dir}' directory already exists.")

    resource_uploads_dir = pathlib.Path(__file__).resolve().parent / RESOURCE_UPLOADS_DIR_NAME
    print(f"Checking for '{RESOURCE_UPLOADS_DIR_NAME}' directory...")
    if not resource_uploads_dir.exists():
        try:
            resource_uploads_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{resource_uploads_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{resource_uploads_dir}' directory: {e}")
    else:
        print(f"'{resource_uploads_dir}' directory already exists.")

    if AZURE_PRIMARY_STORAGE:
        print("Downloading media from Azure storage...")
        try:
            download_media()
        except Exception as exc:
            print(f"Failed to download media from Azure: {exc}")

    return True

def ensure_tags_column():
    """Ensure the 'tags' column exists in the resource table."""
    if not os.path.exists(DB_PATH):
        print("Database file not found, skipping 'tags' column check.")
        return

    try:
        add_tags_column()
    except Exception as exc:
        print(f"Failed to ensure 'tags' column exists: {exc}")

def ensure_resource_image_column():
    """Ensure the 'image_filename' column exists in the resource table."""
    if not os.path.exists(DB_PATH):
        print("Database file not found, skipping 'image_filename' column check.")
        return

    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(resource)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'image_filename' not in columns:
            print("Adding 'image_filename' column to 'resource' table...")
            cursor.execute("ALTER TABLE resource ADD COLUMN image_filename VARCHAR(255)")
            conn.commit()
            print("'image_filename' column added.")
        else:
            print("'image_filename' column already exists. No action taken.")
    except Exception as exc:
        print(f"Failed to ensure 'image_filename' column exists: {exc}")
    finally:
        if 'conn' in locals():
            conn.close()

def ensure_floor_map_columns():
    """Ensure the 'location' and 'floor' columns exist in the floor_map table."""
    if not os.path.exists(DB_PATH):
        print("Database file not found, skipping floor_map column checks.")
        return

    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(floor_map)")
        columns = [info[1] for info in cursor.fetchall()]
        to_commit = False

        if 'location' not in columns:
            print("Adding 'location' column to 'floor_map' table...")
            cursor.execute("ALTER TABLE floor_map ADD COLUMN location VARCHAR(100)")
            to_commit = True
        else:
            print("'location' column already exists. No action taken for this column.")

        if 'floor' not in columns:
            print("Adding 'floor' column to 'floor_map' table...")
            cursor.execute("ALTER TABLE floor_map ADD COLUMN floor VARCHAR(50)")
            to_commit = True
        else:
            print("'floor' column already exists. No action taken for this column.")

        if to_commit:
            conn.commit()
            print("Floor map column additions committed.")
    except Exception as exc:
        print(f"Failed to ensure floor_map columns exist: {exc}")
    finally:
        if 'conn' in locals():
            conn.close()

def ensure_scheduled_status_columns():
    """Ensure the 'scheduled_status' and 'scheduled_status_at' columns exist in the resource table."""
    if not os.path.exists(DB_PATH):
        print("Database file not found, skipping scheduled status column checks.")
        return

    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(resource)")
        columns = [info[1] for info in cursor.fetchall()]
        to_commit = False

        if 'scheduled_status' not in columns:
            print("Adding 'scheduled_status' column to 'resource' table...")
            cursor.execute("ALTER TABLE resource ADD COLUMN scheduled_status VARCHAR(50)")
            to_commit = True
        else:
            print("'scheduled_status' column already exists. No action taken for this column.")

        if 'scheduled_status_at' not in columns:
            print("Adding 'scheduled_status_at' column to 'resource' table...")
            cursor.execute("ALTER TABLE resource ADD COLUMN scheduled_status_at DATETIME")
            to_commit = True
        else:
            print("'scheduled_status_at' column already exists. No action taken for this column.")

        if to_commit:
            conn.commit()
            print("Scheduled status column additions committed.")
    except Exception as exc:
        print(f"Failed to ensure scheduled status columns exist: {exc}")
    finally:
        if 'conn' in locals():
            conn.close()

def verify_db_schema():
    """Check if the existing database has the expected tables and columns."""
    if not os.path.exists(DB_PATH):
        return False

    import sqlite3

    expected_schema = {
        'user': {
            'id', 'username', 'email', 'password_hash', 'is_admin',
            'google_id', 'google_email'
        },
        'role': {
            'id', 'name', 'description', 'permissions'
        },
        'user_roles': {'user_id', 'role_id'},
        'floor_map': {
            'id', 'name', 'image_filename', 'location', 'floor'
        },
        'resource': {
            'id', 'name', 'capacity', 'equipment', 'tags',
            'booking_restriction', 'status', 'published_at',
            'allowed_user_ids', 'image_filename', 'is_under_maintenance',
            'maintenance_until', 'max_recurrence_count',
            'scheduled_status', 'scheduled_status_at',
            'floor_map_id', 'map_coordinates'
        },
        'resource_roles': {'resource_id', 'role_id'},
        'booking': {
            'id', 'resource_id', 'user_name', 'start_time',
            'end_time', 'title', 'checked_in_at', 'checked_out_at',
            'status', 'recurrence_rule'
        },
        'waitlist_entry': {'id', 'resource_id', 'user_id', 'timestamp'},
        'audit_log': {'id', 'timestamp', 'user_id', 'username', 'action', 'details'}
    }

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
        return True
    except Exception as exc:
        print(f"Error verifying database schema: {exc}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()


# Moved from app.py
def init_db(force=False):
    with app.app_context():
        app.logger.info("Starting database initialization...")

        app.logger.info("Creating database tables (if they don't exist)...")
        db.create_all()
        app.logger.info("Database tables creation/verification step completed.")

        if not force:
            existing = any([
                db.session.query(User.id).first(),
                db.session.query(Resource.id).first(),
                db.session.query(Role.id).first(),
                db.session.query(Booking.id).first(),
            ])
            if existing:
                app.logger.warning(
                    "init_db aborted: existing data detected. "
                    "Pass force=True to reset database."
                )
                return

        app.logger.info("Attempting to delete existing data in corrected order...")
        # Corrected Deletion Order: AuditLog -> Booking -> resource_roles_table -> Resource -> FloorMap -> user_roles_table -> User -> Role
        app.logger.info("Deleting existing AuditLog entries...")
        num_audit_logs_deleted = db.session.query(AuditLog).delete()
        app.logger.info(f"Deleted {num_audit_logs_deleted} AuditLog entries.")

        app.logger.info("Deleting existing Bookings...")
        num_bookings_deleted = db.session.query(Booking).delete()
        app.logger.info(f"Deleted {num_bookings_deleted} Bookings.")

        app.logger.info("Deleting existing Resource-Role associations...")
        db.session.execute(resource_roles_table.delete())  # Clear association table
        app.logger.info("Resource-Role associations deleted.")

        app.logger.info("Deleting existing Resources...")
        num_resources_deleted = db.session.query(Resource).delete()
        app.logger.info(f"Deleted {num_resources_deleted} Resources.")

        app.logger.info("Deleting existing FloorMaps...")
        num_floormaps_deleted = db.session.query(FloorMap).delete()
        app.logger.info(f"Deleted {num_floormaps_deleted} FloorMaps.")

        app.logger.info("Deleting existing User-Role associations...")
        db.session.execute(user_roles_table.delete())  # Clear association table
        app.logger.info("User-Role associations deleted.")

        app.logger.info("Deleting existing Users...")
        num_users_deleted = db.session.query(User).delete()
        app.logger.info(f"Deleted {num_users_deleted} Users.")

        app.logger.info("Deleting existing Roles...")
        num_roles_deleted = db.session.query(Role).delete()
        app.logger.info(f"Deleted {num_roles_deleted} Roles.")

        try:
            db.session.commit()
            app.logger.info("Successfully committed deletions of existing data.")
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error committing deletions during DB initialization:")

        # Create default roles and admin account if starting from an empty DB
        admin_role = Role(name="Administrator", description="Admin role", permissions="all_permissions")
        standard_role = Role(name="StandardUser", description="Basic user role")
        db.session.add_all([admin_role, standard_role])
        db.session.commit()

        default_admin = User(username="admin", email="admin@example.com", is_admin=True)
        default_admin.set_password("admin")
        default_admin.roles.append(admin_role)
        db.session.add(default_admin)
        db.session.commit()


        admin_user_for_perms = User.query.filter_by(username='admin').first()
        standard_user_for_perms = User.query.filter_by(username='user').first()

        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1"
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2"

        # Fetch roles for sample data assignment
        admin_role_for_resource = Role.query.filter_by(name="Administrator").first()
        standard_role_for_resource = Role.query.filter_by(name="StandardUser").first()

        app.logger.info("Adding sample resources...")
        try:
            res_alpha = Resource(
                name="Conference Room Alpha",
                capacity=10,
                equipment="Projector,Whiteboard,Teleconference",
                tags="large,video",
                booking_restriction=None,
                status='published',
                published_at=datetime.utcnow(),
                allowed_user_ids=None,
            )  # No specific user IDs, open to roles
            if standard_role_for_resource:
                res_alpha.roles.append(standard_role_for_resource)
            if admin_role_for_resource:  # Admins can also book
                res_alpha.roles.append(admin_role_for_resource)

            res_beta = Resource(
                name="Meeting Room Beta",
                capacity=6,
                equipment="Teleconference,Whiteboard",
                tags="medium",
                booking_restriction='all_users',
                status='published',
                published_at=datetime.utcnow(),  # 'all_users' might be redundant now
                allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}",
            )  # Can keep user_ids for specific overrides
            # No specific roles assigned to Beta, relies on allowed_user_ids or booking_restriction logic

            res_gamma = Resource(
                name="Focus Room Gamma",
                capacity=2,
                equipment="Whiteboard",
                tags="quiet",
                booking_restriction='admin_only',
                status='draft',
                published_at=None,  # admin_only might be redundant
                allowed_user_ids=None,
            )
            if admin_role_for_resource:
                res_gamma.roles.append(admin_role_for_resource)

            res_delta = Resource(
                name="Quiet Pod Delta",
                capacity=1,
                equipment=None,
                tags="quiet,small",
                booking_restriction=None,
                status='draft',
                published_at=None,
                allowed_user_ids=None,
            )
            if standard_role_for_resource:
                res_delta.roles.append(standard_role_for_resource)
            # If admin should also have access by default to standard_user resources, add admin_role too.
            # Or rely on a global admin override in permission checking logic.

            res_omega = Resource(
                name="Archived Room Omega",
                capacity=5,
                equipment="Old Projector",
                tags="archived",
                booking_restriction=None,
                status='archived',
                published_at=datetime.utcnow() - timedelta(days=30),
                allowed_user_ids=None,
            )
            # Typically archived resources don't need role assignments unless there's a use case.

            sample_resources_list = [res_alpha, res_beta, res_gamma, res_delta, res_omega]
            db.session.add_all(sample_resources_list)
            db.session.commit()
            app.logger.info(
                f"Successfully added {len(sample_resources_list)} sample resources with roles."
            )
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error adding sample resources during DB initialization:")

        app.logger.info("Adding sample bookings...")
        resource_alpha = Resource.query.filter_by(name="Conference Room Alpha").first()
        resource_beta = Resource.query.filter_by(name="Meeting Room Beta").first()

        if resource_alpha and resource_beta:
            try:
                sample_bookings = [
                    Booking(
                        resource_id=resource_alpha.id,
                        user_name="user1",
                        title="Team Sync Alpha",
                        start_time=datetime.combine(date.today(), time(9, 0)),
                        end_time=datetime.combine(date.today(), time(10, 0)),
                    ),
                    Booking(
                        resource_id=resource_alpha.id,
                        user_name="user2",
                        title="Client Meeting",
                        start_time=datetime.combine(date.today(), time(11, 0)),
                        end_time=datetime.combine(date.today(), time(12, 30)),
                    ),
                    Booking(
                        resource_id=resource_alpha.id,
                        user_name="user1",
                        title="Project Update Alpha",
                        start_time=datetime.combine(date.today() + timedelta(days=1), time(14, 0)),
                        end_time=datetime.combine(date.today() + timedelta(days=1), time(15, 0)),
                    ),
                    Booking(
                        resource_id=resource_beta.id,
                        user_name="user3",
                        title="Quick Chat Beta",
                        start_time=datetime.combine(date.today(), time(10, 0)),
                        end_time=datetime.combine(date.today(), time(10, 30)),
                    ),
                    Booking(
                        resource_id=resource_beta.id,
                        user_name="user1",
                        title="Planning Session Beta",
                        start_time=datetime.combine(date.today(), time(14, 0)),
                        end_time=datetime.combine(date.today(), time(16, 0)),
                    ),
                ]
                db.session.bulk_save_objects(sample_bookings)
                db.session.commit()
                app.logger.info(
                    f"Successfully added {len(sample_bookings)} sample bookings."
                )
            except Exception as e:
                db.session.rollback()
                app.logger.exception(
                    "Error adding sample bookings during DB initialization:"
                )
        else:
            app.logger.warning(
                "Could not find sample resources 'Conference Room Alpha' or 'Meeting Room Beta' to create bookings for. Skipping sample booking addition."
            )

        app.logger.info("Database initialization script completed.")

        if AZURE_PRIMARY_STORAGE:
            print("Uploading database and media to Azure storage...")
            try:
                upload_database(versioned=False)
                upload_media()
            except Exception as exc:
                print(f"Failed to upload data to Azure: {exc}")

def main():
    """Main function to run setup checks and tasks."""
    print("Starting project initialization...")
    
    check_python_version()
    print("-" * 30)
    create_required_directories()
    # Ensure configuration JSON exists
#    cfg = load_config()
#    save_config(cfg)
    print("-" * 30)

    if os.path.exists(DB_PATH):
        print(f"Existing database found at {DB_PATH}. Verifying structure...")
        if verify_db_schema():
            print("Database structure looks correct. No action needed.")
            return
        else:
            print("Database structure invalid or outdated. Recreating database...")
            try:
                os.remove(DB_PATH)
            except OSError as exc:
                print(f"Unable to remove old database: {exc}")
                sys.exit(1)

    print("Initializing database...")
    try:
        init_db()
        print("Database initialization process completed.")
    except Exception as e:
        print(f"An error occurred during database initialization: {e}")
        print("Please check the output from init_db for more details, or run this script again if issues persist.")
        sys.exit(1)  # Exit if DB initialization fails

    print("-" * 30)
    print("Project initialization script completed successfully.")
    print("Remember to activate your virtual environment if you haven't already.")
    print("Next steps (if applicable):")
    print("  - Install dependencies: pip install -r requirements.txt")
    print("  - Run the application (see README.md for details)")

if __name__ == "__main__":
    main()
