from flask import (
    Blueprint, render_template, redirect, url_for, current_app
)
from flask_login import login_required, current_user, logout_user
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, current_app, request, session, flash
)
from flask_login import login_required, current_user, logout_user
from datetime import datetime, timezone, timedelta

# Assuming Booking model is in models.py
from models import db, Booking, Resource, User # Added Resource, User, db
# Assuming add_audit_log is in utils.py
from utils import add_audit_log
# Assuming socketio is in extensions.py
from extensions import socketio

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
@login_required
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
    return render_template("profile.html", current_user=current_user)

@ui_bp.route("/profile/edit")
@login_required
def serve_edit_profile_page():
    current_app.logger.info(f"User {current_user.username} accessed edit profile page.")
    return render_template("edit_profile.html", current_user=current_user)

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

@ui_bp.route('/check-in/resource/<int:resource_id>', methods=['GET', 'POST'])
def check_in_at_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    now_utc = datetime.now(timezone.utc)
    grace_period_minutes = current_app.config.get('CHECK_IN_GRACE_MINUTES', 15)
    window_start_offset = timedelta(minutes=grace_period_minutes)

    if request.method == 'POST': # PIN Submission
        if not current_user.is_authenticated:
            flash("Please log in to continue check-in.", "warning")
            # Store intended resource for post-login redirect to PIN form
            session['check_in_intended_resource_id'] = resource_id
            session['post_login_pin_entry_required'] = True
            return redirect(url_for('auth.login', next=url_for('ui.check_in_at_resource', resource_id=resource_id)))

        submitted_pin = request.form.get('pin', '').strip()
        # PIN check should happen IF the resource has a PIN. If not, this step is skipped.
        if resource.current_pin: # Only validate if PIN is set on resource
            if resource.current_pin != submitted_pin:
                flash("Invalid PIN. Please try again.", "danger")
                return render_template('check_in_pin_entry.html', resource=resource, error="Invalid PIN."), 400

        # PIN is correct (or not required), proceed to find booking and check-in
        session.pop('post_login_pin_entry_required', None) # Clear flag
        # User is authenticated (either was already, or just logged in and submitted PIN)
        # Fall through to the common booking check logic below (which is part of GET handling too)
        # This requires the GET part to correctly identify the user and perform check-in

    # Common logic for GET (if authenticated) and POST (after PIN success or if no PIN required initially for user)
    if current_user.is_authenticated:
        # If user just logged in and PIN entry is required for the intended resource
        if request.method == 'GET' and \
           session.get('post_login_pin_entry_required') and \
           session.get('check_in_intended_resource_id') == resource.id: # Compare int with int

            current_app.logger.info(f"User {current_user.username} directed to PIN entry for resource {resource.id} post-login.")
            # Don't pop 'check_in_intended_resource_id' here, POST from PIN form might need it if session expires or for re-validation.
            # 'post_login_pin_entry_required' will be popped by the POST handler after successful PIN.
            return render_template('check_in_pin_entry.html', resource=resource)

        user_name_to_check = current_user.username

        # If coming from POST (PIN success), or GET by authenticated user who might not need PIN (or already passed PIN screen)
        # Find booking for this user and resource within the check-in window
        active_booking = Booking.query.filter(
            Booking.user_name == user_name_to_check,
            Booking.resource_id == resource_id,
            Booking.status == 'approved',
            Booking.checked_in_at.is_(None),
            # Check-in window condition:
            Booking.start_time <= now_utc + window_start_offset,
            Booking.start_time >= now_utc - window_start_offset
        ).order_by(Booking.start_time).first() # Get the earliest one if multiple somehow fit

        if active_booking:
            actual_check_in_window_start = active_booking.start_time - window_start_offset
            actual_check_in_window_end = active_booking.start_time + window_start_offset

            if not (actual_check_in_window_start <= now_utc <= actual_check_in_window_end):
                flash(f"Check-in window for your booking for '{resource.name}' is not currently active.", "warning")
                return render_template('check_in_status.html', success=False, resource_name=resource.name, message=f"Check-in window for your booking ({active_booking.title}) is {actual_check_in_window_start.strftime('%H:%M')} to {actual_check_in_window_end.strftime('%H:%M')}. Current time: {now_utc.strftime('%H:%M')}.")

            try:
                active_booking.checked_in_at = now_utc.replace(tzinfo=None) # Store naive UTC
                db.session.commit()

                add_audit_log(
                    user_id=current_user.id,
                    username=current_user.username,
                    action="CHECK_IN_RESOURCE_SUCCESS",
                    details=f"User '{current_user.username}' checked into resource '{resource.name}' (ID: {resource.id}) for booking ID {active_booking.id}."
                )
                if hasattr(socketio, 'emit'):
                     socketio.emit('booking_updated', {
                        'action': 'checked_in',
                        'booking_id': active_booking.id,
                        'checked_in_at': now_utc.isoformat(),
                        'resource_id': active_booking.resource_id
                    })
                flash(f"Successfully checked into '{resource.name}' for your booking: {active_booking.title}.", "success")
                return render_template('check_in_status.html', success=True, resource_name=resource.name, booking_title=active_booking.title, start_time=active_booking.start_time)
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error during check-in for user {current_user.username}, resource {resource.id}: {e}", exc_info=True)
                flash("An error occurred during check-in. Please try again.", "error")
                return render_template('check_in_status.html', success=False, resource_name=resource.name, message="Server error during check-in."), 500
        else: # No active booking found for authenticated user
            flash(f"No active booking found for you at '{resource.name}' within the check-in window.", "warning")
            return render_template('check_in_status.html', success=False, resource_name=resource.name, message="No active booking found for you at this resource right now, or you are outside the check-in window.")

    else: # Not authenticated (GET request)
        # If resource has a PIN, user needs to log in, then might be shown PIN form.
        # If resource has NO PIN, user needs to log in, then we check their bookings.
        session['check_in_intended_resource_id'] = resource_id
        if resource.current_pin:
            session['post_login_pin_entry_required'] = True # Signal that PIN form should be shown after login
            flash("This resource requires a PIN. Please log in to enter the PIN and check-in.", "info")
        else:
            session.pop('post_login_pin_entry_required', None) # No PIN needed
            flash("Please log in to check-in for this resource.", "info")

        # Redirect to login, then auth logic should handle 'next' and session flags.
        return redirect(url_for('auth.login', next=url_for('ui.check_in_at_resource', resource_id=resource_id, _external=True)))


# Function to register this blueprint in the app factory
def init_ui_routes(app):
    app.register_blueprint(ui_bp)
