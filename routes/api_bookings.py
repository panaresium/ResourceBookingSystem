from flask import Blueprint, jsonify, request, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from datetime import datetime, timedelta, timezone, time

# Local imports
# Assuming extensions.py contains db, socketio, mail
from extensions import db, socketio, mail
# Assuming models.py contains these model definitions
from models import Booking, Resource, User, WaitlistEntry, BookingSettings
# Assuming utils.py contains these helper functions
from utils import add_audit_log, parse_simple_rrule, send_email, send_slack_notification, send_teams_notification
# Assuming auth.py contains permission_required decorator
from auth import permission_required

# Blueprint Configuration
api_bookings_bp = Blueprint('api_bookings', __name__, url_prefix='/api')

# Initialization function
def init_api_bookings_routes(app):
    app.register_blueprint(api_bookings_bp)

# API Routes will be added below this line

@api_bookings_bp.route('/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.get_json()

    if not data:
        current_app.logger.warning(f"Booking attempt by {current_user.username} with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource_id = data.get('resource_id')
    date_str = data.get('date_str')
    start_time_str = data.get('start_time_str')
    end_time_str = data.get('end_time_str')
    title = data.get('title')
    user_name_for_record = data.get('user_name')
    recurrence_rule_str = data.get('recurrence_rule')

    required_fields = {'resource_id': resource_id, 'date_str': date_str,
                       'start_time_str': start_time_str, 'end_time_str': end_time_str}
    missing_fields = [field for field, value in required_fields.items() if value is None]
    if missing_fields:
        current_app.logger.warning(f"Booking attempt by {current_user.username} missing fields: {', '.join(missing_fields)}")
        return jsonify({'error': f'Missing required field(s): {", ".join(missing_fields)}'}), 400

    if not user_name_for_record: # Though logged_in, ensure user_name for record is present
        current_app.logger.warning(f"Booking attempt by {current_user.username} missing user_name_for_record in payload.")
        return jsonify({'error': 'user_name for the booking record is required in payload.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        current_app.logger.warning(f"Booking attempt by {current_user.username} for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    # Fetch Booking Settings
    booking_settings = BookingSettings.query.first()

    # Define effective settings, using defaults if booking_settings is None or specific values are not set
    allow_past_bookings_effective = booking_settings.allow_past_bookings if booking_settings else False
    max_booking_days_in_future_effective = booking_settings.max_booking_days_in_future if booking_settings and booking_settings.max_booking_days_in_future is not None else None
    allow_multiple_resources_same_time_effective = booking_settings.allow_multiple_resources_same_time if booking_settings else False
    max_bookings_per_user_effective = booking_settings.max_bookings_per_user if booking_settings and booking_settings.max_bookings_per_user is not None else None
    # enable_check_in_out_effective = booking_settings.enable_check_in_out if booking_settings else False # Not used in this function directly

    # Permission Enforcement Logic
    can_book = False
    current_app.logger.info(f"Checking booking permissions for user '{current_user.username}' (ID: {current_user.id}, IsAdmin: {current_user.is_admin}) on resource ID {resource_id} ('{resource.name}').")
    current_app.logger.debug(f"Resource booking_restriction: '{resource.booking_restriction}', Allowed User IDs: '{resource.allowed_user_ids}', Resource Roles: {[role.name for role in resource.roles]}")

    if current_user.is_admin:
        current_app.logger.info(f"Booking permitted for admin user '{current_user.username}' on resource {resource_id}.")
        can_book = True
    elif resource.booking_restriction == 'admin_only':
        current_app.logger.warning(f"Booking denied: Non-admin user '{current_user.username}' attempted to book admin-only resource {resource_id}.")
    else:
        if resource.allowed_user_ids:
            allowed_ids_list = {int(uid.strip()) for uid in resource.allowed_user_ids.split(',') if uid.strip()}
            if current_user.id in allowed_ids_list:
                current_app.logger.info(f"Booking permitted: User '{current_user.username}' (ID: {current_user.id}) is in allowed_user_ids for resource {resource_id}.")
                can_book = True

        if not can_book and resource.roles:
            user_role_ids = {role.id for role in current_user.roles}
            resource_allowed_role_ids = {role.id for role in resource.roles}
            current_app.logger.debug(f"User role IDs: {user_role_ids}, Resource allowed role IDs: {resource_allowed_role_ids}")
            if not user_role_ids.isdisjoint(resource_allowed_role_ids):
                current_app.logger.info(f"Booking permitted: User '{current_user.username}' has a matching role for resource {resource_id}.")
                can_book = True

        if not can_book and \
           not (resource.allowed_user_ids and resource.allowed_user_ids.strip()) and \
           not resource.roles and \
           resource.booking_restriction != 'admin_only':
            current_app.logger.info(f"Booking permitted: Resource {resource_id} is open to all authenticated users (no specific user/role restrictions).")
            can_book = True

    if not can_book:
        current_app.logger.warning(f"Booking denied for user '{current_user.username}' on resource {resource_id} based on evaluated permissions.")
        return jsonify({'error': 'You are not authorized to book this resource based on its permission settings.'}), 403

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_h, start_m = map(int, start_time_str.split(':'))
        end_h, end_m = map(int, end_time_str.split(':'))
        new_booking_start_time = datetime.combine(booking_date, time(start_h, start_m))
        new_booking_end_time = datetime.combine(booking_date, time(end_h, end_m))
        if new_booking_end_time <= new_booking_start_time:
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid time range: {start_time_str} - {end_time_str}")
            return jsonify({'error': 'End time must be after start time.'}), 400
    except ValueError:
        current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid date/time format: {date_str} {start_time_str}-{end_time_str}")
        return jsonify({'error': 'Invalid date or time format.'}), 400

    # Enforce allow_past_bookings
    if not allow_past_bookings_effective:
        # Use datetime.now(timezone.utc).date() for comparison to ensure timezone consistency
        # new_booking_start_time is naive, convert to aware UTC if necessary, or compare dates directly if appropriate
        # Assuming new_booking_start_time is effectively local to server, convert to UTC date or compare with local server date.
        # For simplicity with current naive new_booking_start_time, comparing with datetime.utcnow().date()
        # Updated to compare datetime objects directly, not just dates.
        if new_booking_start_time < datetime.utcnow():
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} in the past ({new_booking_start_time}), not allowed by settings.")
            return jsonify({'error': 'Booking in the past is not allowed.'}), 400

    # Enforce max_booking_days_in_future
    if max_booking_days_in_future_effective is not None:
        max_allowed_date = datetime.utcnow().date() + timedelta(days=max_booking_days_in_future_effective)
        if new_booking_start_time.date() > max_allowed_date:
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} too far in future ({new_booking_start_time.date()}), limit is {max_booking_days_in_future_effective} days.")
            return jsonify({'error': f'Bookings cannot be made more than {max_booking_days_in_future_effective} days in advance.'}), 400

    if resource.is_under_maintenance and (resource.maintenance_until is None or new_booking_start_time < resource.maintenance_until):
        until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else 'until further notice'
        return jsonify({'error': f'Resource under maintenance until {until_str}.'}), 403

    freq, count = parse_simple_rrule(recurrence_rule_str)
    if recurrence_rule_str and freq is None:
        return jsonify({'error': 'Invalid recurrence rule.'}), 400
    if resource.max_recurrence_count is not None and count > resource.max_recurrence_count:
        return jsonify({'error': 'Recurrence exceeds allowed limit for this resource.'}), 400

    occurrences = []
    for i in range(count):
        delta = timedelta(days=i) if freq == 'DAILY' else timedelta(weeks=i) if freq == 'WEEKLY' else timedelta(0)
        occurrences.append((new_booking_start_time + delta, new_booking_end_time + delta))

    # Enforce max_bookings_per_user
    if max_bookings_per_user_effective is not None and occurrences:
        # Count active (non-past, non-cancelled/rejected) bookings for the user
        # Ensure datetime.utcnow() is used for comparison with end_time
        user_booking_count = Booking.query.filter(
            Booking.user_name == current_user.username, # Assuming current_user.username is the correct field
            Booking.end_time > datetime.utcnow(),      # Booking has not ended yet
            Booking.status.notin_(['cancelled', 'rejected']) # Booking is active
        ).count()

        if user_booking_count + len(occurrences) > max_bookings_per_user_effective:
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} would exceed max bookings per user ({max_bookings_per_user_effective}). Current: {user_booking_count}, Requested: {len(occurrences)}.")
            return jsonify({'error': f'Cannot create new booking(s). You would exceed the maximum of {max_bookings_per_user_effective} bookings allowed per user.'}), 400

    if occurrences:
        first_occ_start, first_occ_end = occurrences[0]
        if not allow_multiple_resources_same_time_effective:
            first_slot_user_conflict = Booking.query.filter(
                Booking.user_name == user_name_for_record,
                Booking.start_time < first_occ_end,
                Booking.end_time > first_occ_start,
                Booking.status.notin_(['cancelled', 'rejected'])
            ).first()

            if first_slot_user_conflict:
                conflicting_resource_name = first_slot_user_conflict.resource_booked.name if first_slot_user_conflict.resource_booked else "an unknown resource"
                current_app.logger.info(f"User {user_name_for_record} booking conflict (first slot) with booking {first_slot_user_conflict.id} for resource '{conflicting_resource_name}' due to allow_multiple_resources_same_time=False.")
                return jsonify({'error': f"You already have a booking for resource '{conflicting_resource_name}' from {first_slot_user_conflict.start_time.strftime('%H:%M')} to {first_slot_user_conflict.end_time.strftime('%H:%M')} that overlaps with the requested time slot on {first_occ_start.strftime('%Y-%m-%d')}."}), 409

    for occ_start, occ_end in occurrences:
        conflicting = Booking.query.filter(
            Booking.resource_id == resource_id,
            Booking.start_time < occ_end,
            Booking.end_time > occ_start,
            Booking.status.notin_(['cancelled', 'rejected'])
        ).first()
        if conflicting:
            current_app.logger.info(f"Booking conflict for resource {resource_id} on slot {occ_start}-{occ_end} with existing booking {conflicting.id}.")
            # Waitlist logic (condensed for brevity, assuming it's still desired)
            if WaitlistEntry.query.filter_by(resource_id=resource_id).count() < current_app.config.get('MAX_WAITLIST_PER_RESOURCE', 2): # Example: make max waitlist configurable
                existing_entry = WaitlistEntry.query.filter_by(resource_id=resource_id, user_id=current_user.id).first()
                if not existing_entry:
                    waitlist_entry = WaitlistEntry(resource_id=resource_id, user_id=current_user.id, timestamp=datetime.utcnow())
                    db.session.add(waitlist_entry)
                    # db.session.commit() # Commit waitlist entry separately or with main booking transaction
                    current_app.logger.info(f"Added user {current_user.id} to waitlist for resource {resource_id} due to conflict with booking {conflicting.id}")
            return jsonify({'error': f"This time slot ({occ_start.strftime('%Y-%m-%d %H:%M')} to {occ_end.strftime('%Y-%m-%d %H:%M')}) on resource '{resource.name}' is already booked or conflicts. You may have been added to the waitlist if available."}), 409

        if not allow_multiple_resources_same_time_effective:
            user_conflicting_recurring = Booking.query.filter(
                Booking.user_name == user_name_for_record,
                Booking.resource_id != resource_id, # Check on other resources
                Booking.start_time < occ_end,
                Booking.end_time > occ_start,
                Booking.status.notin_(['cancelled', 'rejected'])
            ).first()

            if user_conflicting_recurring:
                conflicting_resource_name = user_conflicting_recurring.resource_booked.name if user_conflicting_recurring.resource_booked else "an unknown resource"
                current_app.logger.info(f"User {user_name_for_record} booking conflict (recurring slot) with booking {user_conflicting_recurring.id} for resource '{conflicting_resource_name}' due to allow_multiple_resources_same_time=False.")
                return jsonify({'error': f"You already have a booking for resource '{conflicting_resource_name}' from {user_conflicting_recurring.start_time.strftime('%H:%M')} to {user_conflicting_recurring.end_time.strftime('%H:%M')} that overlaps with the requested occurrence on {occ_start.strftime('%Y-%m-%d')}."}), 409

    try:
        created_bookings = []
        for occ_start, occ_end in occurrences:
            new_booking = Booking(
                resource_id=resource_id,
                start_time=occ_start,
                end_time=occ_end,
                title=title,
                user_name=user_name_for_record,
                recurrence_rule=recurrence_rule_str
            )
            db.session.add(new_booking)
            # Defer commit until all bookings in a recurring series are validated and added, or handle rollback for series
        db.session.commit() # Commit all bookings in the series at once

        for new_booking in created_bookings: # Log after successful commit of the series
            add_audit_log(action="CREATE_BOOKING", details=f"Booking ID {new_booking.id} for resource ID {resource_id} ('{resource.name}') created by user '{user_name_for_record}'. Title: '{title}'.")
            socketio.emit('booking_updated', {'action': 'created', 'booking_id': new_booking.id, 'resource_id': resource_id})

        created_data = [{
            'id': b.id,
            'resource_id': b.resource_id,
            'title': b.title,
            'user_name': b.user_name,
            'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'status': b.status,
            'recurrence_rule': b.recurrence_rule
        } for b in created_bookings]
        return jsonify({'bookings': created_data}), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error creating booking series for resource {resource_id} by {current_user.username}: {e}")
        add_audit_log(action="CREATE_BOOKING_FAILED", details=f"Failed to create booking series for resource ID {resource_id} by user '{current_user.username}'. Error: {str(e)}")
        return jsonify({'error': 'Failed to create booking series due to a server error.'}), 500

@api_bookings_bp.route('/bookings/my_bookings', methods=['GET'])
@login_required
def get_my_bookings():
    """
    Fetches all bookings for the currently authenticated user.
    Orders bookings by start_time descending (most recent/upcoming first).
    Also includes a global setting `check_in_out_enabled`.
    """
    try:
        booking_settings = BookingSettings.query.first()
        enable_check_in_out = booking_settings.enable_check_in_out if booking_settings else False

        user_bookings = Booking.query.filter_by(user_name=current_user.username)\
                                     .order_by(Booking.start_time.desc())\
                                     .all()

        bookings_list = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            resource_name = resource.name if resource else "Unknown Resource"
            grace = current_app.config.get('CHECK_IN_GRACE_MINUTES', 15)
            now = datetime.now(timezone.utc)

            # Ensure booking.start_time is offset-aware (UTC) before comparison
            booking_start_time_aware = booking.start_time
            if booking_start_time_aware.tzinfo is None:
                booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

            can_check_in = (
                booking.checked_in_at is None and
                booking_start_time_aware - timedelta(minutes=grace) <= now <= booking_start_time_aware + timedelta(minutes=grace)
            )
            bookings_list.append({
                'id': booking.id,
                'resource_id': booking.resource_id,
                'resource_name': resource_name,
                'user_name': booking.user_name,
                'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end_time': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'title': booking.title,
                'status': booking.status,
                'recurrence_rule': booking.recurrence_rule,
                'admin_deleted_message': booking.admin_deleted_message,
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in
            })

        current_app.logger.info(f"User '{current_user.username}' fetched their bookings. Count: {len(bookings_list)}. Check-in/out enabled: {enable_check_in_out}")
        current_app.logger.info(f"User '{current_user.username}' - Bookings prepared for JSON: {bookings_list}")
        current_app.logger.info(f"User '{current_user.username}' - Check-in/out setting: {enable_check_in_out}")
        current_app.logger.info(f"User '{current_user.username}' - Number of bookings being returned: {len(bookings_list)}")
        return jsonify({
            'bookings': bookings_list,
            'check_in_out_enabled': enable_check_in_out
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching bookings for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch your bookings due to a server error.'}), 500


@api_bookings_bp.route('/bookings/my_bookings_for_date', methods=['GET'])
@login_required
def get_my_bookings_for_date():
    """
    Fetches bookings for the currently authenticated user for a specific date.
    Expects a 'date' query parameter in 'YYYY-MM-DD' format.
    """
    date_str = request.args.get('date')
    if not date_str:
        current_app.logger.warning(f"User '{current_user.username}' called my_bookings_for_date without a date parameter.")
        return jsonify({'error': 'Missing date query parameter. Please provide a date in YYYY-MM-DD format.'}), 400

    try:
        target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        current_app.logger.warning(f"User '{current_user.username}' provided invalid date format '{date_str}' for my_bookings_for_date.")
        return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    try:
        user_bookings_on_date = db.session.query(
                Booking.id, # Added booking ID
                Booking.title, # Added booking title
                Booking.resource_id,
                Resource.name.label('resource_name'),
                Booking.start_time,
                Booking.end_time
            ).join(Resource, Booking.resource_id == Resource.id)\
            .filter(Booking.user_name == current_user.username)\
            .filter(func.date(Booking.start_time) == target_date_obj)\
            .order_by(Booking.start_time.asc())\
            .all()

        bookings_list = []
        for booking_row in user_bookings_on_date:
            bookings_list.append({
                'booking_id': booking_row.id,
                'title': booking_row.title,
                'resource_id': booking_row.resource_id,
                'resource_name': booking_row.resource_name,
                'start_time': booking_row.start_time.strftime('%H:%M:%S'),
                'end_time': booking_row.end_time.strftime('%H:%M:%S')
            })

        current_app.logger.info(f"User '{current_user.username}' fetched their bookings for date {date_str}. Count: {len(bookings_list)}")
        return jsonify(bookings_list), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching bookings for user '{current_user.username}' on date {date_str}:")
        return jsonify({'error': 'Failed to fetch your bookings for the specified date due to a server error.'}), 500


@api_bookings_bp.route('/bookings/calendar', methods=['GET'])
@login_required
def bookings_calendar():
    """Return bookings for the current user in FullCalendar format."""
    try:
        user_bookings = Booking.query.filter_by(user_name=current_user.username).all()
        events = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            title = booking.title or (resource.name if resource else 'Booking')
            events.append({
                'id': booking.id,
                'title': title,
                'start': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'recurrence_rule': booking.recurrence_rule,
                'resource_id': booking.resource_id
            })
        return jsonify(events), 200
    except Exception as e:
        current_app.logger.exception("Error fetching calendar bookings:")
        return jsonify({'error': 'Failed to fetch bookings.'}), 500


@api_bookings_bp.route('/bookings/my_booked_resources', methods=['GET'])
@login_required
def get_my_booked_resources():
    """
    Returns a list of unique resources the current user has booked.
    """
    try:
        # Step 1: Get distinct resource_ids booked by the current user
        # Assuming Booking.user_name stores the username of the user who made the booking.
        booked_resource_ids_query = db.session.query(Booking.resource_id)\
            .filter(Booking.user_name == current_user.username)\
            .distinct()\
            .all()

        booked_resource_ids = [item[0] for item in booked_resource_ids_query]

        if not booked_resource_ids:
            current_app.logger.info(f"User '{current_user.username}' has not booked any resources yet.")
            return jsonify([]), 200

        # Step 2: Fetch the details of these resources
        resources = Resource.query.filter(Resource.id.in_(booked_resource_ids)).all()

        # Step 3: Serialize the resources to dictionary/JSON
        # Using a simplified version here as resource_to_dict might not be directly usable
        # or might need adjustment for blueprint context (e.g. url_for)
        resources_list = []
        for resource in resources:
            resources_list.append({
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity,
                'equipment': resource.equipment,
                'tags': resource.tags,
                'status': resource.status
                # Add other fields as necessary, ensuring they don't require complex objects or external calls
                # e.g., 'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None,
            })

        current_app.logger.info(f"Successfully fetched {len(resources_list)} unique booked resources for user '{current_user.username}'.")
        return jsonify(resources_list), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching booked resources for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch booked resources due to a server error.'}), 500


@api_bookings_bp.route('/bookings/<int:booking_id>', methods=['PUT'])
@login_required
def update_booking_by_user(booking_id):
    """
    Allows an authenticated user to update the title, start_time, or end_time of their own booking.
    Expects start_time and end_time as ISO 8601 formatted datetime strings.
    """
    current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request received. User: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    data = request.get_json()
    current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request JSON data: {data}")

    if not data:
        current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] No JSON data received.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' attempted to update non-existent booking ID.")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.user_name != current_user.username:
            current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' unauthorized attempt to update booking ID owned by '{booking.user_name}'.")
            return jsonify({'error': 'You are not authorized to update this booking.'}), 403

        old_title = booking.title
        old_start_time = booking.start_time
        old_end_time = booking.end_time

        changes_made = False
        change_details_list = []

        if 'title' in data:
            new_title = str(data.get('title', '')).strip()
            if not new_title:
                current_app.logger.warning(f"User '{current_user.username}' provided empty title for booking {booking_id}.")
                return jsonify({'error': 'Title cannot be empty.'}), 400
            if new_title != old_title:
                booking.title = new_title
                changes_made = True
                change_details_list.append(f"title from '{old_title}' to '{new_title}'")

        new_start_iso = data.get('start_time')
        new_end_iso = data.get('end_time')
        time_update_intended = new_start_iso is not None or new_end_iso is not None

        parsed_new_start_time = None
        parsed_new_end_time = None

        if time_update_intended:
            if not new_start_iso or not new_end_iso:
                current_app.logger.warning(f"User '{current_user.username}' provided incomplete time for booking {booking_id}. Start: {new_start_iso}, End: {new_end_iso}")
                return jsonify({'error': 'Both start_time and end_time are required if one is provided.'}), 400
            try:
                # Ensure timezone-aware datetime objects if input strings include timezone info
                # Otherwise, assume naive and they will be treated as UTC by default by fromisoformat
                # If they need to be localized to server's local time first, that's a different logic.
                parsed_new_start_time = datetime.fromisoformat(new_start_iso)
                parsed_new_end_time = datetime.fromisoformat(new_end_iso)

                # If parsed times are naive, assume UTC (or make them UTC)
                if parsed_new_start_time.tzinfo is None:
                    parsed_new_start_time = parsed_new_start_time.replace(tzinfo=timezone.utc)
                if parsed_new_end_time.tzinfo is None:
                    parsed_new_end_time = parsed_new_end_time.replace(tzinfo=timezone.utc)

            except ValueError:
                current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided invalid ISO format. Start: {new_start_iso}, End: {new_end_iso}")
                return jsonify({'error': 'Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS[Z] or YYYY-MM-DDTHH:MM:SS+/-HH:MM).'}), 400

            if parsed_new_start_time >= parsed_new_end_time:
                current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided start_time not before end_time.")
                return jsonify({'error': 'Start time must be before end time.'}), 400

            resource = Resource.query.get(booking.resource_id)
            if not resource:
                current_app.logger.error(f"[API PUT /api/bookings/{booking_id}] Resource ID {booking.resource_id} for booking {booking_id} not found during update.")
                return jsonify({'error': 'Associated resource not found.'}), 500 # Should be 500, as it's a server-side data integrity issue

            # Convert old DB times to aware UTC if they are naive, for correct comparison
            old_start_time_aware = old_start_time.replace(tzinfo=timezone.utc) if old_start_time.tzinfo is None else old_start_time
            old_end_time_aware = old_end_time.replace(tzinfo=timezone.utc) if old_end_time.tzinfo is None else old_end_time

            time_changed = parsed_new_start_time != old_start_time_aware or parsed_new_end_time != old_end_time_aware

            if time_changed and resource.is_under_maintenance:
                maintenance_active = False
                # Ensure maintenance_until is UTC aware if it exists
                maintenance_until_aware = resource.maintenance_until.replace(tzinfo=timezone.utc) if resource.maintenance_until and resource.maintenance_until.tzinfo is None else resource.maintenance_until

                if maintenance_until_aware is None: # Maintenance is indefinite
                    maintenance_active = True
                # Check if new booking period overlaps with maintenance period
                # This logic assumes maintenance_until means "maintained up to but not including this time"
                # or "maintained until the end of this time if it's a date".
                # For datetimes, direct comparison is fine.
                elif parsed_new_start_time < maintenance_until_aware or parsed_new_end_time <= maintenance_until_aware: # Simplified, might need adjustment
                     maintenance_active = True

                if maintenance_active:
                    maint_until_str = maintenance_until_aware.isoformat() if maintenance_until_aware else "indefinitely"
                    current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Booking update conflicts with resource maintenance (until {maint_until_str}).")
                    return jsonify({'error': f'Resource is under maintenance until {maint_until_str} and the new time slot falls within this period.'}), 403

            if time_changed:
                # Convert new times to naive UTC for storage, matching original app's likely behavior
                booking.start_time = parsed_new_start_time.replace(tzinfo=None)
                booking.end_time = parsed_new_end_time.replace(tzinfo=None)

                conflicting_booking = Booking.query.filter(
                    Booking.resource_id == booking.resource_id,
                    Booking.id != booking_id,
                    Booking.start_time < booking.end_time, # Use the new end_time for comparison
                    Booking.end_time > booking.start_time  # Use the new start_time for comparison
                ).first()

                if conflicting_booking:
                    current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Update for user '{current_user.username}' on resource ID {booking.resource_id} "
                                               f"conflicts with existing booking ID {conflicting_booking.id} on the same resource.")
                    # Rollback the time change before returning error
                    booking.start_time = old_start_time
                    booking.end_time = old_end_time
                    return jsonify({'error': 'The updated time slot conflicts with an existing booking on this resource.'}), 409

                # NEW CHECK: User's other bookings conflict on DIFFERENT resources
                # Ensure new times are naive UTC for DB comparison, if not already
                new_start_naive_utc = parsed_new_start_time.replace(tzinfo=None) if parsed_new_start_time.tzinfo else parsed_new_start_time
                new_end_naive_utc = parsed_new_end_time.replace(tzinfo=None) if parsed_new_end_time.tzinfo else parsed_new_end_time

                user_own_conflict = Booking.query.filter(
                    Booking.user_name == current_user.username,
                    Booking.resource_id != booking.resource_id,  # Critical: Different resource
                    Booking.id != booking_id,                   # Critical: Not the current booking
                    Booking.start_time < new_end_naive_utc,
                    Booking.end_time > new_start_naive_utc
                ).first()

                if user_own_conflict:
                    current_app.logger.warning(
                        f"[API PUT /api/bookings/{booking_id}] Update for user '{current_user.username}' "
                        f"conflicts with their own existing booking ID {user_own_conflict.id} "
                        f"for resource '{user_own_conflict.resource_booked.name if user_own_conflict.resource_booked else 'N/A'}' (ID: {user_own_conflict.resource_id})."
                    )
                    # Revert time changes before returning error
                    booking.start_time = old_start_time
                    booking.end_time = old_end_time
                    # No db.session.commit() should have happened for the main update yet.
                    return jsonify({
                        'error': f"The updated time slot conflicts with another of your existing bookings "
                                 f"for resource '{user_own_conflict.resource_booked.name if user_own_conflict.resource_booked else 'unknown resource'}' "
                                 f"from {user_own_conflict.start_time.strftime('%H:%M')} to {user_own_conflict.end_time.strftime('%H:%M')} "
                                 f"on {user_own_conflict.start_time.strftime('%Y-%m-%d')}."
                    }), 409

                # If all checks pass, booking.start_time and booking.end_time are already set to new values
                changes_made = True
                change_details_list.append(f"time from {old_start_time.isoformat()} to {booking.start_time.isoformat()}-{booking.end_time.isoformat()}")

        if not changes_made:
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' submitted update with no actual changes.")
            return jsonify({'error': 'No changes supplied.'}), 400

        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Attempting to commit changes to DB: Title='{booking.title}', Start='{booking.start_time.isoformat()}', End='{booking.end_time.isoformat()}'")
        db.session.commit()
        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] DB commit successful.")

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"

        # Email sending logic
        if mail and current_user.email and any("time from" in change for change in change_details_list):
            try:
                from flask_mail import Message # Ensure Message is available
                msg = Message(
                    subject="Booking Updated",
                    recipients=[current_user.email],
                    body=(
                        f"Your booking for {resource_name} has been updated.\n"
                        f"New Title: {booking.title}\n"
                        f"New Start Time: {booking.start_time.strftime('%Y-%m-%d %H:%M')}\n"
                        f"New End Time: {booking.end_time.strftime('%Y-%m-%d %H:%M')}\n"
                    ),
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER')
                )
                mail.send(msg)
                current_app.logger.info(f"Booking update email sent to {current_user.email} via Flask-Mail.")
            except Exception as mail_e:
                current_app.logger.exception(f"[API PUT /api/bookings/{booking_id}] Failed to send booking update email to {current_user.email} via Flask-Mail: {mail_e}")

        change_summary_text = '; '.join(change_details_list)
        add_audit_log(
            action="UPDATE_BOOKING_USER",
            details=(
                f"User '{current_user.username}' updated booking ID: {booking.id} "
                f"for resource '{resource_name}'. Changes: {change_summary_text}."
            )
        )
        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' successfully updated booking. Changes: {change_summary_text}.")

        response_data = {
            'id': booking.id,
            'resource_id': booking.resource_id,
            'resource_name': resource_name,
            'user_name': booking.user_name,
            'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'title': booking.title
        }
        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Sending successful response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[API PUT /api/bookings/{booking_id}] Critical error during booking update for user '{current_user.username if current_user.is_authenticated else 'Anonymous'}'. Error: {str(e)}")
        add_audit_log(action="UPDATE_BOOKING_USER_FAILED", details=f"User '{current_user.username if current_user.is_authenticated else 'Anonymous'}' failed to update booking ID: {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to update booking due to a server error.'}), 500


@api_bookings_bp.route('/bookings/<int:booking_id>', methods=['DELETE'])
@login_required
def delete_booking_by_user(booking_id):
    """
    Allows an authenticated user to delete their own booking.
    """
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"User '{current_user.username}' attempted to delete non-existent booking ID: {booking_id}")
            return jsonify({'error': 'Booking not found.'}), 404

        # Authorization: User can only delete their own bookings.
        if booking.user_name != current_user.username:
            current_app.logger.warning(f"User '{current_user.username}' unauthorized attempt to delete booking ID: {booking_id} owned by '{booking.user_name}'.")
            return jsonify({'error': 'You are not authorized to delete this booking.'}), 403

        # For audit log: get resource name before deleting booking
        resource_name = "Unknown Resource"
        if booking.resource_booked: # Check if backref is populated
            resource_name = booking.resource_booked.name

        booking_start = booking.start_time
        booking_end = booking.end_time
        booking_details_for_log = (
            f"Booking ID: {booking.id}, "
            f"Resource: {resource_name} (ID: {booking.resource_id}), "
            f"Title: '{booking.title}', "
            f"Original User: '{booking.user_name}', "
            f"Time: {booking_start.isoformat()} to {booking_end.isoformat()}"
        )

        db.session.delete(booking)
        db.session.commit()

        if current_user.email:
            send_teams_notification(
                current_user.email,
                "Booking Cancelled",
                f"Your booking for {resource_name} starting at {booking_start.strftime('%Y-%m-%d %H:%M')} has been cancelled."
            )


        # Notify next user on waitlist, if any
        next_entry = (
            WaitlistEntry.query.filter_by(resource_id=booking.resource_id)
            .order_by(WaitlistEntry.timestamp.asc())
            .first()
        )
        if next_entry:
            user_to_notify = User.query.get(next_entry.user_id)
            db.session.delete(next_entry)
            db.session.commit() # Commit deletion of waitlist entry
            if user_to_notify:
                send_email( # Assuming send_email is imported
                    user_to_notify.email,
                    f"Slot available for {resource_name}",
                    f"The slot you requested for {resource_name} is now available.",
                )
                if user_to_notify.email: # Ensure user_to_notify.email is not None or empty before sending Teams notification
                    send_teams_notification( # Assuming send_teams_notification is imported
                        user_to_notify.email,
                        "Waitlist Slot Released",
                        f"A slot for {resource_name} is now available to book."
                    )


        add_audit_log(
            action="CANCEL_BOOKING_USER",
            details=f"User '{current_user.username}' cancelled their booking. {booking_details_for_log}"
        )
        # Assuming socketio is imported
        socketio.emit('booking_updated', {'action': 'deleted', 'booking_id': booking_id, 'resource_id': booking.resource_id})
        current_app.logger.info(f"User '{current_user.username}' successfully deleted booking ID: {booking_id}. Details: {booking_details_for_log}")
        return jsonify({'message': 'Booking cancelled successfully.'}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error deleting booking ID {booking_id} for user '{current_user.username}':")
        add_audit_log(action="CANCEL_BOOKING_USER_FAILED", details=f"User '{current_user.username}' failed to cancel booking ID: {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to cancel booking due to a server error.'}), 500


@api_bookings_bp.route('/bookings/<int:booking_id>/check_in', methods=['POST'])
@login_required
def check_in_booking(booking_id):
    """
    Allows an authenticated user to check into their booking.
    """
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            current_app.logger.warning(f"Check-in attempt for non-existent booking ID: {booking_id} by user {current_user.username}")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.user_name != current_user.username:
            # Admin/manager override could be a feature, handled by a different endpoint or permission.
            current_app.logger.warning(f"User {current_user.username} unauthorized check-in attempt for booking {booking_id} owned by {booking.user_name}.")
            return jsonify({'error': 'You are not authorized to check into this booking.'}), 403

        if booking.checked_in_at:
            current_app.logger.info(f"User {current_user.username} attempt to check-in to already checked-in booking {booking_id} at {booking.checked_in_at.isoformat()}")
            return jsonify({'message': 'Already checked in.', 'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat()}), 200 # Or 409 Conflict

        grace_period_minutes = current_app.config.get('CHECK_IN_GRACE_MINUTES', 15)
        now = datetime.now(timezone.utc)

        # Ensure booking.start_time is offset-aware for comparison
        booking_start_time_aware = booking.start_time
        if booking_start_time_aware.tzinfo is None: # Should be UTC from DB
            booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

        if not (booking_start_time_aware - timedelta(minutes=grace_period_minutes) <= now <= booking_start_time_aware + timedelta(minutes=grace_period_minutes)):
            current_app.logger.warning(f"User {current_user.username} check-in attempt for booking {booking_id} outside of allowed window. Booking starts at {booking_start_time_aware.isoformat()}, current time {now.isoformat()}")
            return jsonify({'error': f'Check-in is only allowed within {grace_period_minutes} minutes of the booking start time.'}), 403

        booking.checked_in_at = now
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        add_audit_log(action="CHECK_IN_SUCCESS", details=f"User '{current_user.username}' checked into booking ID {booking.id} for resource '{resource_name}'.")
        socketio.emit('booking_updated', {'action': 'checked_in', 'booking_id': booking.id, 'checked_in_at': now.isoformat(), 'resource_id': booking.resource_id})
        current_app.logger.info(f"User '{current_user.username}' successfully checked into booking ID: {booking_id} at {now.isoformat()}")

        if current_user.email:
            send_teams_notification(
                current_user.email,
                "Booking Checked In",
                f"You have successfully checked into your booking for {resource_name} at {now.strftime('%Y-%m-%d %H:%M')}."
            )

        return jsonify({
            'message': 'Check-in successful.',
            'checked_in_at': now.replace(tzinfo=timezone.utc).isoformat(),
            'booking_id': booking.id
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during check-in for booking ID {booking_id} by user {current_user.username}:")
        add_audit_log(action="CHECK_IN_FAILED", details=f"User '{current_user.username}' failed to check into booking ID {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to check in due to a server error.'}), 500


@api_bookings_bp.route('/bookings/<int:booking_id>/check_out', methods=['POST'])
@login_required
def check_out_booking(booking_id):
    """
    Allows an authenticated user to check out of their booking.
    """
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            current_app.logger.warning(f"Check-out attempt for non-existent booking ID: {booking_id} by user {current_user.username}")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.user_name != current_user.username:
            current_app.logger.warning(f"User {current_user.username} unauthorized check-out attempt for booking {booking_id} owned by {booking.user_name}.")
            return jsonify({'error': 'You are not authorized to check out of this booking.'}), 403

        if not booking.checked_in_at:
            current_app.logger.warning(f"User {current_user.username} attempt to check-out of booking {booking_id} that was never checked into.")
            return jsonify({'error': 'Cannot check out of a booking that was not checked into.'}), 403 # Or 409 Conflict

        if booking.checked_out_at:
            current_app.logger.info(f"User {current_user.username} attempt to check-out of already checked-out booking {booking_id} at {booking.checked_out_at.isoformat()}")
            return jsonify({'message': 'Already checked out.', 'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat()}), 200 # Or 409 Conflict

        now = datetime.now(timezone.utc)
        booking.checked_out_at = now
        # Optional: Adjust booking end_time if an early check-out should free up the resource.
        # booking.end_time = now
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        add_audit_log(action="CHECK_OUT_SUCCESS", details=f"User '{current_user.username}' checked out of booking ID {booking.id} for resource '{resource_name}'.")
        socketio.emit('booking_updated', {'action': 'checked_out', 'booking_id': booking.id, 'checked_out_at': now.isoformat(), 'resource_id': booking.resource_id})
        current_app.logger.info(f"User '{current_user.username}' successfully checked out of booking ID: {booking_id} at {now.isoformat()}")

        if current_user.email:
             send_teams_notification(
                current_user.email,
                "Booking Checked Out",
                f"You have successfully checked out of your booking for {resource_name} at {now.strftime('%Y-%m-%d %H:%M')}."
            )

        return jsonify({
            'message': 'Check-out successful.',
            'checked_out_at': now.replace(tzinfo=timezone.utc).isoformat(),
            'booking_id': booking.id
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during check-out for booking ID {booking_id} by user {current_user.username}:")
        add_audit_log(action="CHECK_OUT_FAILED", details=f"User '{current_user.username}' failed to check out of booking ID {booking_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to check out due to a server error.'}), 500


@api_bookings_bp.route('/admin/bookings/pending', methods=['GET'])
@login_required
@permission_required('manage_bookings')
def list_pending_bookings():
    # No longer need: if not current_user.is_admin: return abort(403)
    # The @permission_required decorator handles auth and permission.
    pending = Booking.query.filter_by(status='pending').all()
    result = []
    for b in pending:
        result.append({
            'id': b.id,
            'resource_id': b.resource_id,
            'resource_name': b.resource_booked.name if b.resource_booked else None,
            'user_name': b.user_name,
            'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'title': b.title,
        })
    return jsonify(result), 200


@api_bookings_bp.route('/admin/bookings/<int:booking_id>/approve', methods=['POST'])
@login_required
@permission_required('manage_bookings') # Replaces is_admin check
def approve_booking_admin(booking_id):
    # Removed: if not current_user.is_admin: return abort(403)
    booking = Booking.query.get_or_404(booking_id) # Uses current_app.extensions['sqlalchemy'].get_or_404 with new setup
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'approved'
    db.session.commit() # Uses current_app.extensions['sqlalchemy'].session
    user = User.query.filter_by(username=booking.user_name).first()
    if user and user.email: # Added check for user.email
        # Use imported send_email utility
        send_email(user.email, 'Booking Approved',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been approved.")
    # Use imported send_slack_notification utility
    send_slack_notification(f"Booking {booking.id} approved by {current_user.username}")
    # Use current_app.logger
    current_app.logger.info(f"Booking {booking.id} approved by admin {current_user.username}.")
    add_audit_log(action="APPROVE_BOOKING_ADMIN", details=f"Admin {current_user.username} approved booking ID {booking.id}.")
    socketio.emit('booking_updated', {'action': 'approved', 'booking_id': booking.id, 'status': 'approved', 'resource_id': booking.resource_id})
    return jsonify({'success': True}), 200


@api_bookings_bp.route('/admin/bookings/<int:booking_id>/reject', methods=['POST'])
@login_required
@permission_required('manage_bookings') # Replaces is_admin check
def reject_booking_admin(booking_id):
    # Removed: if not current_user.is_admin: return abort(403)
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'rejected'
    db.session.commit()
    user = User.query.filter_by(username=booking.user_name).first()
    if user and user.email: # Added check for user.email
        send_email(user.email, 'Booking Rejected',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been rejected.")
    send_slack_notification(f"Booking {booking.id} rejected by {current_user.username}")
    current_app.logger.info(f"Booking {booking.id} rejected by admin {current_user.username}.")
    add_audit_log(action="REJECT_BOOKING_ADMIN", details=f"Admin {current_user.username} rejected booking ID {booking.id}.")
    socketio.emit('booking_updated', {'action': 'rejected', 'booking_id': booking.id, 'status': 'rejected', 'resource_id': booking.resource_id})
    return jsonify({'success': True}), 200


@api_bookings_bp.route('/admin/bookings/<int:booking_id>/delete', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_delete_booking(booking_id):
    current_app.logger.info(f"Admin user {current_user.username} attempting to delete booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Admin delete attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        # Store details for audit log BEFORE deleting the booking
        original_status = booking.status # Keep for audit log context if needed
        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        booking_title = booking.title or "N/A"
        user_name_of_booking = booking.user_name
        resource_id_of_booking = booking.resource_id
        # booking_date_str = booking.start_time.strftime('%Y-%m-%d') # Not strictly needed for delete log

        # No need to check terminal_statuses if we are deleting,
        # unless there's a business rule against deleting already "terminated" bookings.
        # For now, allowing deletion regardless of status.

        db.session.delete(booking)
        db.session.commit()

        audit_details = (
            f"Admin '{current_user.username}' DELETED booking ID {booking_id}. "
            f"Original status was: '{original_status}'. "
            f"Booked by: '{user_name_of_booking}'. "
            f"Resource: '{resource_name}' (ID: {resource_id_of_booking}). "
            f"Title: '{booking_title}'."
        )
        add_audit_log(action="ADMIN_DELETE_BOOKING", details=audit_details)

        socketio.emit('booking_updated', {
            'action': 'deleted_by_admin', # New action
            'booking_id': booking_id,
            'resource_id': resource_id_of_booking
            # No status or admin_deleted_message needed as it's deleted
        })

        current_app.logger.info(f"Admin user {current_user.username} successfully DELETED booking ID: {booking_id}.")
        return jsonify({'message': 'Booking deleted successfully by admin.', 'booking_id': booking_id}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during admin deletion of booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_DELETE_BOOKING_FAILED", # New action name
            details=f"Admin '{current_user.username}' failed to DELETE booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to delete booking due to a server error.'}), 500


@api_bookings_bp.route('/bookings/<int:booking_id>/clear_admin_message', methods=['POST'])
@login_required
def clear_admin_deleted_message(booking_id):
    """
    Clears the admin_deleted_message for a specific booking.
    Accessible by the booking owner or an admin with 'manage_bookings' permission.
    """
    current_app.logger.info(f"Attempt to clear admin_deleted_message for booking ID: {booking_id} by user '{current_user.username}'.")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Clear admin message attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        # Authorization check: User must be the owner or have 'manage_bookings' permission
        if not (current_user.username == booking.user_name or current_user.has_permission('manage_bookings')):
            current_app.logger.warning(
                f"User '{current_user.username}' unauthorized to clear admin message for booking ID {booking_id} "
                f"(Owner: '{booking.user_name}', User has manage_bookings: {current_user.has_permission('manage_bookings')})."
            )
            return jsonify({'error': 'You are not authorized to perform this action on this booking.'}), 403

        if booking.admin_deleted_message is None:
            current_app.logger.info(f"Admin message for booking ID {booking_id} is already clear. No action taken.")
            return jsonify({'message': 'Admin message was already clear.'}), 200 # Or 304 Not Modified, but 200 is fine

        booking.admin_deleted_message = None
        db.session.commit()

        add_audit_log(
            action="CLEAR_ADMIN_MESSAGE",
            details=f"User '{current_user.username}' cleared admin_deleted_message for booking ID {booking.id}."
        )
        current_app.logger.info(f"Admin message for booking ID {booking.id} cleared successfully by user '{current_user.username}'.")

        # Optionally, emit a socket event if frontend needs to react to this change
        socketio.emit('booking_updated', {
            'action': 'admin_message_cleared',
            'booking_id': booking.id,
            'resource_id': booking.resource_id
        })

        return jsonify({'message': 'Admin message cleared successfully.'}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error clearing admin_deleted_message for booking ID {booking_id} by user '{current_user.username}':")
        add_audit_log(
            action="CLEAR_ADMIN_MESSAGE_FAILED",
            details=f"User '{current_user.username}' failed to clear admin_deleted_message for booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to clear admin message due to a server error.'}), 500


@api_bookings_bp.route('/admin/bookings/<int:booking_id>/clear_admin_message', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_clear_booking_message(booking_id):
    current_app.logger.info(f"Admin user '{current_user.username}' attempting to clear admin message for booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Admin clear message attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.status != 'cancelled_by_admin':
            current_app.logger.warning(
                f"Admin clear message attempt: Booking ID {booking_id} is not in 'cancelled_by_admin' state (current: '{booking.status}')."
            )
            return jsonify({'error': "Message can only be cleared for bookings cancelled by an admin."}), 400

        booking.admin_deleted_message = None
        booking.status = 'cancelled_admin_acknowledged' # New status
        db.session.commit()

        add_audit_log(
            action="ADMIN_CLEAR_BOOKING_MESSAGE",
            details=(
                f"Admin '{current_user.username}' cleared cancellation message for booking ID {booking.id}. "
                f"Status changed to 'cancelled_admin_acknowledged'."
            )
        )
        current_app.logger.info(
            f"Admin '{current_user.username}' cleared message for booking ID {booking.id}. Status set to 'cancelled_admin_acknowledged'."
        )

        # Emit a socket event to inform clients (e.g., admin dashboard) about the update
        socketio.emit('booking_updated', {
            'action': 'admin_message_cleared_by_admin', # More specific action name
            'booking_id': booking.id,
            'resource_id': booking.resource_id,
            'new_status': booking.status,
            'admin_deleted_message': None # Explicitly send None
        })

        return jsonify({
            'message': 'Admin message cleared and booking acknowledged.',
            'new_status': booking.status
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during admin clearing message for booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_CLEAR_BOOKING_MESSAGE_FAILED",
            details=f"Admin '{current_user.username}' failed to clear message for booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to clear admin message due to a server error.'}), 500
