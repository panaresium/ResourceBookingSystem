from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models import User, Role
from werkzeug.security import generate_password_hash

setup_bp = Blueprint('setup', __name__)

@setup_bp.route('/setup', methods=['GET', 'POST'])
def setup_system():
    # Check if setup is already done (admin exists)
    if User.query.filter_by(is_admin=True).first():
        flash('System is already initialized.', 'info')
        return redirect(url_for('ui.index'))

    if request.method == 'POST':
        admin_email = request.form.get('admin_email')
        admin_username = request.form.get('admin_username')
        admin_password = request.form.get('admin_password')
        confirm_password = request.form.get('confirm_password')

        if not all([admin_email, admin_username, admin_password, confirm_password]):
            flash('All fields are required.', 'danger')
            return render_template('setup.html')

        if admin_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('setup.html')

        try:
            # ensure tables exist
            db.create_all()

            # Create Roles
            admin_role = Role.query.filter_by(name="Administrator").first()
            if not admin_role:
                admin_role = Role(name="Administrator", description="Full system access", permissions="all_permissions,view_analytics,manage_bookings,manage_system,manage_users,manage_resources,manage_floor_maps,manage_maintenance")
                db.session.add(admin_role)

            standard_role = Role.query.filter_by(name="StandardUser").first()
            if not standard_role:
                standard_role = Role(name="StandardUser", description="Can make bookings and view resources", permissions="make_bookings,view_resources")
                db.session.add(standard_role)

            db.session.commit()

            # Create Admin User
            new_admin = User(username=admin_username, email=admin_email, is_admin=True)
            new_admin.set_password(admin_password)
            new_admin.roles.append(admin_role)
            db.session.add(new_admin)
            db.session.commit()

            flash('System initialized successfully! Please log in.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Setup failed: {e}", exc_info=True)
            flash(f'An error occurred during setup: {str(e)}', 'danger')

    return render_template('setup.html')
