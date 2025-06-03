import os
from app_factory import create_app
from extensions import db
from models import User, Role, Resource, Booking, FloorMap, AuditLog, WaitlistEntry, BookingSettings, UserMessage # Ensure all models are imported
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError, OperationalError
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = create_app()

def initialize_database(drop_existing=False):
    """
    Initializes the database: drops existing tables (optional),
    creates all tables, and sets up default admin role and user.
    """
    with app.app_context():
        logging.info("Starting database initialization...")

        if 'sqlite' in app.config.get('SQLALCHEMY_DATABASE_URI', '') and app.instance_path:
            if not os.path.exists(app.instance_path):
                try:
                    os.makedirs(app.instance_path)
                    logging.info(f"Created instance folder at: {app.instance_path}")
                except OSError as e:
                    logging.error(f"Could not create instance folder {app.instance_path}: {e}")

        if drop_existing:
            try:
                logging.info("Dropping all existing tables...")
                db.drop_all()
                db.session.commit()
                logging.info("All tables dropped successfully.")
            except OperationalError as e:
                db.session.rollback()
                logging.warning(f"Could not drop tables (might be first run or DB issue): {e}")
            except Exception as e:
                db.session.rollback()
                logging.error(f"An unexpected error occurred during drop_all: {e}")
                return

        try:
            logging.info("Creating all tables based on models...")
            db.create_all()
            db.session.commit()
            logging.info("All tables created successfully.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating tables: {e}")
            return

        try:
            admin_role_name = "Administrator"
            admin_role = Role.query.filter_by(name=admin_role_name).first()
            if not admin_role:
                admin_role = Role(
                    name=admin_role_name,
                    description="Full system access",
                    permissions="all_permissions"
                )
                db.session.add(admin_role)
                db.session.commit()
                logging.info(f"Role '{admin_role_name}' created successfully.")
            else:
                if admin_role.permissions != "all_permissions":
                    admin_role.permissions = "all_permissions"
                    db.session.commit()
                    logging.info(f"Role '{admin_role_name}' permissions updated to 'all_permissions'.")
                else:
                    logging.info(f"Role '{admin_role_name}' already exists with correct permissions.")
        except IntegrityError:
            db.session.rollback()
            logging.warning(f"Role '{admin_role_name}' may have been created in a concurrent session. Fetching existing.")
            admin_role = Role.query.filter_by(name=admin_role_name).first()
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating or updating role '{admin_role_name}': {e}")
            return

        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'ChangeMe123!')
        if admin_password == 'ChangeMe123!':
            logging.warning("Using default admin password. Please change this or set ADMIN_PASSWORD environment variable.")

        try:
            admin_user = User.query.filter_by(username=admin_username).first()
            if not admin_user:
                admin_user = User(
                    username=admin_username,
                    email=admin_email,
                    is_admin=True
                )
                admin_user.set_password(admin_password)
                db.session.add(admin_user)
                db.session.commit()
                logging.info(f"Admin user '{admin_username}' created successfully.")

                if admin_role:
                    if admin_role not in admin_user.roles:
                        admin_user.roles.append(admin_role)
                        db.session.commit()
                        logging.info(f"Assigned '{admin_role.name}' role to admin user '{admin_username}'.")
                else:
                    logging.warning(f"Administrator role not found. Cannot assign to admin user '{admin_username}'.")
            else:
                logging.info(f"Admin user '{admin_username}' already exists.")
                if not admin_user.is_admin:
                    admin_user.is_admin = True
                if admin_role and admin_role not in admin_user.roles:
                    admin_user.roles.append(admin_role)
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            logging.warning(f"Admin user '{admin_username}' or email '{admin_email}' might already exist (IntegrityError).")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating or updating admin user '{admin_username}': {e}")
            return

        logging.info("Database initialization process completed.")

if __name__ == '__main__':
    # Default to not dropping tables in non-interactive environments
    initialize_database(drop_existing=False)
    logging.info("Defaulting to non-destructive database initialization.")
