from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models import User, Role
from werkzeug.security import generate_password_hash

setup_bp = Blueprint('setup', __name__)

@setup_bp.route('/setup', methods=['GET', 'POST'])
def setup_system():
    # Check if setup is already done (admin exists)
    try:
        if User.query.filter_by(is_admin=True).first():
            flash('System is already initialized.', 'info')
            return redirect(url_for('ui.index'))
    except Exception:
        # If tables don't exist, this check will fail.
        # We catch it and proceed to setup logic.
        pass

    # Pre-fill form with defaults from environment if available
    default_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', '')
    # Password is not pre-filled for security, unless explicitly desired for this specific setup flow

    if request.method == 'POST':
        action = request.form.get('action')

        # Admin Confirmation Flow
        if action == 'confirm_init':
            # This is the "Ask Admin" confirmation button
            # We verify the provided password against the DEFAULT_ADMIN_PASSWORD env var
            admin_password_input = request.form.get('admin_password_confirmation')
            default_admin_password = current_app.config.get('DEFAULT_ADMIN_PASSWORD')

            if not default_admin_password:
                 flash('System is misconfigured: DEFAULT_ADMIN_PASSWORD not set. Cannot authorize initialization.', 'danger')
                 return render_template('setup.html', require_confirmation=True)

            if admin_password_input != default_admin_password:
                flash('Incorrect Admin Password. Initialization authorization failed.', 'danger')
                return render_template('setup.html', require_confirmation=True)

            # Authorization successful. Proceed to initialize standard structure (roles/etc)
            # and potentially create the user provided in the *other* form fields,
            # OR just re-render the standard setup form if we want to split the steps.
            # However, the requirement is "Ask admin to confirm if the admin wants to initialized".

            # Let's combine it: The user fills the setup form AND provides the confirmation password.
            pass # Fall through to standard setup logic below

        # Standard Setup Logic
        admin_email = request.form.get('admin_email')
        admin_username = request.form.get('admin_username')
        admin_password = request.form.get('admin_password')
        confirm_password = request.form.get('confirm_password')

        # If this is the "Ask Admin" flow, we might also need the confirmation password here
        # depending on if we require it for *every* setup or just when DB is empty/broken.
        # But here, we are AT the setup page because the DB is empty/broken.

        # Check authorization if "Ask Admin" is strictly required
        admin_password_confirmation = request.form.get('admin_password_confirmation')
        default_admin_password = current_app.config.get('DEFAULT_ADMIN_PASSWORD')

        if default_admin_password and admin_password_confirmation != default_admin_password:
             flash('Authorization failed: Incorrect Default Admin Password.', 'danger')
             return render_template('setup.html', require_confirmation=True, default_email=default_email)

        if not all([admin_email, admin_username, admin_password, confirm_password]):
            flash('All fields are required.', 'danger')
            return render_template('setup.html', require_confirmation=True, default_email=default_email)

        if admin_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('setup.html', require_confirmation=True, default_email=default_email)

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
            return redirect(url_for('ui.serve_login'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Setup failed: {e}", exc_info=True)
            flash(f'An error occurred during setup: {str(e)}', 'danger')

    # If GET, show the setup form.
    # We add 'require_confirmation=True' to instruct the template to show an extra password field
    # for "Default Admin Password" to authorize the setup.
    return render_template('setup.html', require_confirmation=True, default_email=default_email)
