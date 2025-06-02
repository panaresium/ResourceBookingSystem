from flask import (
    Blueprint, render_template, redirect, url_for, current_app
)
from flask_login import login_required, current_user, logout_user
from datetime import datetime, timezone

# Assuming Booking model is in models.py
from models import Booking
# Assuming add_audit_log is in utils.py
from utils import add_audit_log

# The template_folder is specified relative to the blueprint's location.
# If app.py sets a global template_folder, and this blueprint's templates
# are within that global folder (e.g., templates/ui/...),
# then Flask's default discovery might work without `template_folder='../templates'`.
# However, to be explicit or if ui templates are in a subdir of the main templates folder:
# ui_bp = Blueprint('ui', __name__, template_folder='ui', url_prefix='/')
# If templates are directly in the main 'templates' folder:
ui_bp = Blueprint('ui', __name__, template_folder='../templates')


@ui_bp.route("/")
def serve_index():
    if current_user.is_authenticated:
        # Assuming Booking model has a query attribute from db.Model
        upcoming_bookings = Booking.query.filter(
            Booking.user_name == current_user.username,
            Booking.start_time > datetime.now(timezone.utc)
        ).order_by(Booking.start_time.asc()).all()
        return render_template("index.html", upcoming_bookings=upcoming_bookings)
    else:
        # Redirect to the login page which is now also part of this ui_bp
        return redirect(url_for('ui.serve_login'))

@ui_bp.route("/resources")
def serve_resources():
    return render_template("resources.html")

@ui_bp.route("/login")
def serve_login():
    return render_template("login.html")

@ui_bp.route('/logout')
def logout_and_redirect():
    logger = current_app.logger
    user_identifier = current_user.username if current_user.is_authenticated else "Anonymous"
    user_id_for_log = current_user.id if current_user.is_authenticated else None
    try:
        logout_user() # This function is from flask_login
        logger.info(f"User '{user_identifier}' logged out via /logout.")
        add_audit_log(action="LOGOUT_SUCCESS",
                     details=f"User '{user_identifier}' logged out.",
                     user_id=user_id_for_log,
                     username=user_identifier)
    except Exception as e:
        logger.exception(f"Error during logout for user {user_identifier}:")
        add_audit_log(action="LOGOUT_FAILED",
                     details=f"Logout attempt failed for user '{user_identifier}'. Error: {str(e)}",
                     user_id=user_id_for_log,
                     username=user_identifier)
    return redirect(url_for('ui.serve_resources')) # Redirect to public resources page

@ui_bp.route("/profile")
@login_required # from flask_login
def serve_profile_page():
    current_app.logger.info(f"User {current_user.username} accessed their profile page.")
    return render_template("profile.html",
                           username=current_user.username,
                           email=current_user.email)

@ui_bp.route("/profile/edit")
@login_required
def serve_edit_profile_page():
    current_app.logger.info(f"User {current_user.username} accessed edit profile page.")
    return render_template("edit_profile.html", email=current_user.email)

@ui_bp.route("/my_bookings")
@login_required
def serve_my_bookings_page():
    current_app.logger.info(f"User {current_user.username} accessed My Bookings page.")
    return render_template("my_bookings.html")

@ui_bp.route("/calendar")
@login_required
def serve_calendar():
    current_app.logger.info(f"User {current_user.username} accessed Calendar page.")
    return render_template("calendar.html")

@ui_bp.route('/map_view/<int:map_id>')
def serve_map_view(map_id):
    return render_template("map_view.html", map_id_from_flask=map_id)

# Function to register this blueprint in the app factory
def init_ui_routes(app):
    app.register_blueprint(ui_bp)
