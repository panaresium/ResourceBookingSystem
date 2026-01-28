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
from models import db, Booking, Resource, User, BookingSettings, FloorMap # Added Resource, User, db, BookingSettings
# Assuming add_audit_log is in utils.py
from utils import add_audit_log
# Assuming socketio is in extensions.py # Removed: from extensions import socketio

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
        # Define valid statuses for upcoming bookings
        valid_statuses = ['approved', 'checked_in', 'confirmed']
        # Assuming Booking model has a query attribute from db.Model
        now = datetime.now(timezone.utc)
        three_days_from_now = now + timedelta(days=3)
        upcoming_bookings = Booking.query.filter(
            Booking.user_name == current_user.username,
            Booking.start_time > now,
            Booking.start_time <= three_days_from_now,
            Booking.status.in_(valid_statuses)  # Filter by valid statuses
        ).order_by(Booking.start_time.asc()).all()

        # Get global_time_offset_hours
        time_offset_value = 0 # Default
        try:
            booking_settings_record = BookingSettings.query.first()
            if booking_settings_record and booking_settings_record.global_time_offset_hours is not None:
                time_offset_value = booking_settings_record.global_time_offset_hours
        except Exception as e:
            current_app.logger.error(f"Error fetching BookingSettings for index page: {e}", exc_info=True)
            # time_offset_value remains 0

        return render_template("index.html",
                               upcoming_bookings=upcoming_bookings,
                               global_time_offset_hours=time_offset_value)
    else:
        # Redirect to the login page which is now also part of this ui_bp
        return redirect(url_for('ui.serve_login'))

@ui_bp.route("/resources")
@login_required
def serve_resources():
    adjustment_hours = 0  # Default value for past_booking_time_adjustment_hours
    global_offset_hours = 0 # Default value for global_time_offset_hours
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings:
            if booking_settings.past_booking_time_adjustment_hours is not None:
                adjustment_hours = booking_settings.past_booking_time_adjustment_hours
            if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
                global_offset_hours = booking_settings.global_time_offset_hours
        current_app.logger.info(f"Passing past_booking_adjustment_hours: {adjustment_hours} and global_time_offset_hours: {global_offset_hours} to resources.html")
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for /resources page: {e}", exc_info=True)
        # adjustment_hours and global_offset_hours remain at their default values
    return render_template("resources.html",
                           past_booking_adjustment_hours=adjustment_hours,
                           global_time_offset_hours=global_offset_hours)

@ui_bp.route("/login")
def serve_login():
    if current_app.config.get('DB_CONNECTION_FAILED'):
        error_message = current_app.config.get('DB_CONNECTION_ERROR', 'Unknown database connection error')
        flash(f"Database Connection Failed: {error_message}. Please contact the administrator.", "error")
    elif current_app.config.get('DB_TABLES_MISSING'):
        error_message = current_app.config.get('DB_TABLES_ERROR', 'Tables missing')
        flash(f"Database Error: {error_message}. Please contact the administrator to initialize the system.", "error")
    elif current_app.config.get('SETUP_REQUIRED'):
        flash("System setup required. Please contact the administrator to initialize the system at /setup.", "warning")
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
    # Get global_time_offset_hours
    time_offset_value = 0 # Default
    try:
        booking_settings_record = BookingSettings.query.first()
        if booking_settings_record and booking_settings_record.global_time_offset_hours is not None:
            time_offset_value = booking_settings_record.global_time_offset_hours
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for my_bookings page: {e}", exc_info=True)
        # time_offset_value remains 0
    return render_template("my_bookings.html", global_time_offset_hours=time_offset_value)

@ui_bp.route("/calendar")
@login_required
def serve_calendar():
    current_app.logger.info(f"User {current_user.username} accessed Calendar page.")
    # Get global_time_offset_hours and restricted_past status
    time_offset_value = 0 # Default
    restricted_past = True # Always restrict past dates for date picker as per requirement
    allow_multiple = False # Default

    try:
        booking_settings_record = BookingSettings.query.first()
        if booking_settings_record:
            if booking_settings_record.global_time_offset_hours is not None:
                time_offset_value = booking_settings_record.global_time_offset_hours
            allow_multiple = booking_settings_record.allow_multiple_resources_same_time

    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for calendar page: {e}", exc_info=True)
        # time_offset_value remains 0

    floors = FloorMap.query.order_by(FloorMap.display_order).all()
    return render_template("calendar.html",
                           global_time_offset_hours=time_offset_value,
                           floors=floors,
                           restricted_past=restricted_past,
                           allow_multiple=allow_multiple)

@ui_bp.route('/map_view/<int:map_id>')
def serve_map_view(map_id):
    map_opacity = current_app.config.get('MAP_RESOURCE_OPACITY', 0.7) # Default here is a fallback
    return render_template("map_view.html", map_id_from_flask=map_id, map_resource_opacity=map_opacity)

@ui_bp.route('/check-in/resource/<int:resource_id>', methods=['GET', 'POST'])
def check_in_at_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)

    # Fetch booking settings
    booking_settings = BookingSettings.query.first()
    if not booking_settings:
        flash("System error: Booking settings not configured.", "danger")
        return render_template('check_in_status.html', success=False, resource_name=resource.name, message="Booking settings not found."), 500

    global_time_offset_hours = booking_settings.global_time_offset_hours if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0
    check_in_minutes_before = booking_settings.check_in_minutes_before
    check_in_minutes_after = booking_settings.check_in_minutes_after

    # Calculate effective_now_utc
    # Note: Booking.start_time is stored as naive UTC in the database, representing the venue's local time if it were UTC.
    # So, effective_now_utc should also be naive UTC for direct comparison.
    # The current datetime.now(timezone.utc) is aware. We need to adjust it by offset, then make it naive.
    # This matches the logic in utils.get_current_effective_time() which returns an *aware* time,
    # but for comparison with naive DB times, we'd typically convert effective_now_aware to naive UTC.
    # Let's be explicit:
    # All booking times (start_time, end_time) are stored as naive datetime objects representing UTC.
    # Comparisons should happen with naive UTC.

    _now_utc_aware = datetime.now(timezone.utc)
    effective_now_utc_aware = _now_utc_aware + timedelta(hours=global_time_offset_hours)
    # For comparing with Booking.start_time (which is naive UTC), we use naive UTC version of effective_now
    effective_now_naive_utc = effective_now_utc_aware.replace(tzinfo=None)


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
            # Check-in window condition using dynamic settings and effective_now_naive_utc:
            # Booking.start_time is naive UTC. effective_now_naive_utc is also naive UTC.
            Booking.start_time - timedelta(minutes=check_in_minutes_before) <= effective_now_naive_utc,
            Booking.start_time + timedelta(minutes=check_in_minutes_after) >= effective_now_naive_utc
        ).order_by(Booking.start_time).first() # Get the earliest one if multiple somehow fit

        if active_booking:
            # The primary query now correctly determines if a booking is within the dynamic window.
            # The secondary check can be removed or simplified.
            # For clarity, let's proceed with the check-in if active_booking is found.
            # The message "No active booking found..." will be shown if query returns None.

            # Storing check-in time: should use the original _now_utc_aware and make it naive,
            # or effective_now_naive_utc?
            # Standard practice is to record event times in true UTC.
            # Booking.checked_in_at is naive UTC.
            # So, _now_utc_aware.replace(tzinfo=None) is the actual UTC timestamp of the event, made naive.
            # effective_now_naive_utc is the venue's "current time" perception.
            # For an audit field like checked_in_at, actual UTC is better.

            try:
                active_booking.checked_in_at = _now_utc_aware.replace(tzinfo=None) # Store actual naive UTC
                db.session.commit()

                add_audit_log(
                    user_id=current_user.id,
                    username=current_user.username,
                    action="CHECK_IN_RESOURCE_SUCCESS",
                    details=f"User '{current_user.username}' checked into resource '{resource.name}' (ID: {resource.id}) for booking ID {active_booking.id}."
                )
                # if hasattr(socketio, 'emit'): # Removed Socket.IO emit
                #      socketio.emit('booking_updated', {
                #         'action': 'checked_in',
                #         'booking_id': active_booking.id,
                #         'checked_in_at': now_utc.isoformat(),
                #         'resource_id': active_booking.resource_id
                #     })
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
        return redirect(url_for('ui.serve_login', next=url_for('ui.check_in_at_resource', resource_id=resource_id, _external=True)))


@ui_bp.route("/minimal_socket_test")
def serve_minimal_socket_test():
    current_app.logger.info("Serving minimal_socket_test.html")
    return render_template("minimal_socket_test.html")


# Function to register this blueprint in the app factory
def init_ui_routes(app):
    app.register_blueprint(ui_bp)
