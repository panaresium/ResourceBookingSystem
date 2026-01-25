from app_factory import create_app
from extensions import db
from models import User, Role
import os

app = create_app(start_scheduler=False)

def seed():
    with app.app_context():
        print("Seeding database...")

        # Create Roles
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", description="Full system access", permissions="all_permissions,view_analytics,manage_bookings,manage_system,manage_users,manage_resources,manage_floor_maps,manage_maintenance")
            db.session.add(admin_role)
            print("Created Administrator role.")

        standard_role = Role.query.filter_by(name="StandardUser").first()
        if not standard_role:
            standard_role = Role(name="StandardUser", description="Can make bookings and view resources", permissions="make_bookings,view_resources")
            db.session.add(standard_role)
            print("Created StandardUser role.")

        db.session.commit()

        # Create Admin User
        admin_email = app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
        # Check by username 'admin' as well to avoid duplicates if email matches but username doesn't or vice versa
        admin_user = User.query.filter((User.email == admin_email) | (User.username == 'admin')).first()

        if not admin_user:
            admin_password = app.config.get('DEFAULT_ADMIN_PASSWORD', 'admin')
            admin_user = User(
                username='admin',
                email=admin_email,
                is_admin=True
            )
            admin_user.set_password(admin_password)
            admin_user.roles.append(admin_role)
            db.session.add(admin_user)
            print(f"Created default admin user: {admin_email}")
            db.session.commit()
        else:
            print(f"Admin user already exists.")

if __name__ == "__main__":
    seed()
