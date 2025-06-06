from flask import Blueprint, jsonify, request, current_app, abort, render_template, url_for
from flask_login import login_required, current_user
import json # Added json import
from sqlalchemy import func
from sqlalchemy.sql import func as sqlfunc # Explicit import for sqlalchemy.sql.func
from translations import _ # For translations
import secrets
from datetime import datetime, timedelta, timezone, time

# Local imports
# Assuming extensions.py contains db, socketio, mail
from extensions import db, socketio, mail
# Assuming models.py contains these model definitions
from models import Booking, Resource, User, WaitlistEntry, BookingSettings, ResourcePIN # Added ResourcePIN
# Assuming utils.py contains these helper functions
from utils import add_audit_log, parse_simple_rrule, send_email, send_teams_notification, check_booking_permission
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
    # Define lists of active statuses (lowercase)
    # These statuses are considered "active" for conflict checks or quota counting.
    active_conflict_statuses = ['approved', 'pending', 'checked_in', 'confirmed']
    active_quota_statuses = ['approved', 'pending', 'checked_in', 'confirmed']

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
    effective_past_booking_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings and booking_settings.past_booking_time_adjustment_hours is not None else 0
    max_booking_days_in_future_effective = booking_settings.max_booking_days_in_future if booking_settings and booking_settings.max_booking_days_in_future is not None else None
    allow_multiple_resources_same_time_effective = booking_settings.allow_multiple_resources_same_time if booking_settings else False
    max_bookings_per_user_effective = booking_settings.max_bookings_per_user if booking_settings and booking_settings.max_bookings_per_user is not None else None
    # enable_check_in_out_effective = booking_settings.enable_check_in_out if booking_settings else False # Not used in this function directly

    # Permission Enforcement Logic
    can_book, permission_error_message = check_booking_permission(current_user, resource, current_app.logger)
    if not can_book:
        # The logger calls are now inside check_booking_permission
        return jsonify({'error': permission_error_message}), 403

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
    # The effective_past_booking_hours will be negative to restrict further, positive to allow more into the past.
    # A value of 0 means standard behavior (booking up to current time if allow_past_bookings_effective is true).
    # If allow_past_bookings_effective is false, this entire block is skipped, and past bookings are disallowed.
    if allow_past_bookings_effective:
        # Calculate the cutoff time: current time MINUS the adjustment.
        # If adjustment is positive (e.g., 2 hours), cutoff is 2 hours ago (allowing bookings up to 2 hours in past).
        # If adjustment is negative (e.g., -1 hour), cutoff is 1 hour in the future (restricting bookings to start at least 1 hour from now).
        past_booking_cutoff_time = datetime.utcnow() - timedelta(hours=effective_past_booking_hours)
        if new_booking_start_time < past_booking_cutoff_time:
            current_app.logger.warning(
                f"Booking attempt by {current_user.username} for resource {resource_id} at {new_booking_start_time} "
                f"is before the allowed cutoff time of {past_booking_cutoff_time} "
                f"(current time: {datetime.utcnow()}, adjustment: {effective_past_booking_hours} hours)."
            )
            return jsonify({'error': 'Booking time is outside the allowed window for past or future bookings as per current settings.'}), 400
    elif new_booking_start_time < datetime.utcnow(): # If past bookings are generally disallowed
        current_app.logger.warning(
            f"Booking attempt by {current_user.username} for resource {resource_id} in the past ({new_booking_start_time}), "
            f"and past bookings are disabled."
        )
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
            sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_quota_statuses) # Booking is active
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
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_conflict_statuses)
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
            sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_conflict_statuses)
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
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_conflict_statuses)
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
            created_bookings.append(new_booking)
            # Defer commit until all bookings in a recurring series are validated and added, or handle rollback for series
        db.session.commit() # Commit all bookings in the series at once

        # Generate check-in tokens and set expiry
        for new_booking in created_bookings:
            new_booking.check_in_token = secrets.token_urlsafe(32)
            token_validity_hours = current_app.config.get('CHECK_IN_TOKEN_VALIDITY_HOURS', 48)
            # Ensure end_time is timezone-aware before adding timedelta.
            # Assuming new_booking.end_time is naive UTC as stored in DB.
            # If it were already aware, this replace might not be necessary or could be harmful.
            # However, datetime.combine results in naive datetime.
            aware_end_time = new_booking.end_time.replace(tzinfo=timezone.utc)
            new_booking.check_in_token_expires_at = aware_end_time + timedelta(hours=token_validity_hours)
            # Convert back to naive UTC if DB stores naive times
            new_booking.check_in_token_expires_at = new_booking.check_in_token_expires_at.replace(tzinfo=None)

        db.session.commit() # Commit updates for tokens and expiry times

        for new_booking in created_bookings: # Log after successful commit of the series
            add_audit_log(action="CREATE_BOOKING", details=f"Booking ID {new_booking.id} for resource ID {resource_id} ('{resource.name}') created by user '{user_name_for_record}'. Title: '{title}'. Token generated.")
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
    Fetches all bookings for the currently authenticated user, categorized into
    upcoming and past bookings, and sorted accordingly.
    Accepts 'status_filter' and 'date_filter_value' query parameters.
    Also includes a global setting `check_in_out_enabled`.
    """
    try:
        status_filter = request.args.get('status_filter')
        date_filter_value_str = request.args.get('date_filter_value')

        booking_settings = BookingSettings.query.first()
        enable_check_in_out = booking_settings.enable_check_in_out if booking_settings else False
        check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings else 15
        check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings else 15
        if not booking_settings:
             current_app.logger.warning("BookingSettings not found in DB, using default check-in window (15/15 mins) for get_my_bookings.")

        # Base query
        user_bookings_query = Booking.query.filter_by(user_name=current_user.username)

        # Apply Status Filter
        if status_filter and status_filter.lower() != 'all':
            user_bookings_query = user_bookings_query.filter(
                sqlfunc.trim(sqlfunc.lower(Booking.status)) == status_filter.lower()
            )

        # Apply Date Filter
        if date_filter_value_str:
            try:
                target_date_obj = datetime.strptime(date_filter_value_str, '%Y-%m-%d').date()
                user_bookings_query = user_bookings_query.filter(
                    sqlfunc.date(Booking.start_time) == target_date_obj
                )
            except ValueError:
                current_app.logger.warning(f"Invalid date_filter_value format: {date_filter_value_str}. Ignoring date filter.")

        user_all_bookings = user_bookings_query.all() # Execute the query

        upcoming_bookings_data = []
        past_bookings_data = []
        now_utc = datetime.now(timezone.utc)

        for booking in user_all_bookings:
            resource = Resource.query.get(booking.resource_id)
            resource_name = resource.name if resource else "Unknown Resource"

            booking_start_time_aware = booking.start_time
            if booking_start_time_aware.tzinfo is None: # Assuming DB stores naive UTC
                booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

            can_check_in = (
                enable_check_in_out and # Only if feature is enabled
                booking.checked_in_at is None and
                booking.status == 'approved' and # Only for approved bookings
                booking_start_time_aware - timedelta(minutes=check_in_minutes_before) <= now_utc <= \
                booking_start_time_aware + timedelta(minutes=check_in_minutes_after)
            )

            display_check_in_token = None
            if booking.check_in_token and booking.checked_in_at is None and booking.status == 'approved':
                token_expires_at_aware = booking.check_in_token_expires_at
                if token_expires_at_aware and token_expires_at_aware.tzinfo is None:
                    token_expires_at_aware = token_expires_at_aware.replace(tzinfo=timezone.utc)

                booking_end_time_aware = booking.end_time
                if booking_end_time_aware.tzinfo is None:
                    booking_end_time_aware = booking_end_time_aware.replace(tzinfo=timezone.utc)

                if token_expires_at_aware and token_expires_at_aware > now_utc and booking_end_time_aware > now_utc:
                    display_check_in_token = booking.check_in_token

            booking_dict = {
                'id': booking.id,
                'resource_id': booking.resource_id,
                'resource_name': resource_name,
                'user_name': booking.user_name,
                'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(), # Ensure ISO format with Z
                'end_time': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),   # Ensure ISO format with Z
                'title': booking.title,
                'status': booking.status,
                'recurrence_rule': booking.recurrence_rule,
                'admin_deleted_message': booking.admin_deleted_message, # Keep for potential internal use, JS should hide it
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in,
                'check_in_token': display_check_in_token
            }

            if booking_start_time_aware >= now_utc:
                upcoming_bookings_data.append(booking_dict)
            else:
                past_bookings_data.append(booking_dict)

        # Sort upcoming bookings chronologically (nearest first)
        upcoming_bookings_data.sort(key=lambda b: b['start_time'])
        # Sort past bookings reverse chronologically (most recent past first)
        past_bookings_data.sort(key=lambda b: b['start_time'], reverse=True)

        current_app.logger.info(f"User '{current_user.username}' fetched their bookings. Upcoming: {len(upcoming_bookings_data)}, Past: {len(past_bookings_data)}. Check-in/out enabled: {enable_check_in_out}")

        return jsonify({
            'upcoming_bookings': upcoming_bookings_data,
            'past_bookings': past_bookings_data,
            'check_in_out_enabled': enable_check_in_out
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching bookings for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch your bookings due to a server error.'}), 500


@api_bookings_bp.route('/bookings/my_bookings_for_date', methods=['GET'])
@login_required
def get_my_bookings_for_date():
    active_booking_statuses_for_user_schedule = ['approved', 'pending', 'checked_in', 'confirmed']

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
            .filter(sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_user_schedule))\
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
    """Return bookings for the current user in FullCalendar format, optionally filtered by status."""
    try:
        status_filter_str = request.args.get('status_filter')

        query = Booking.query.filter_by(user_name=current_user.username)

        if status_filter_str:
            # Handle comma-separated statuses for groups like 'cancelled'
            statuses_to_filter = [status.strip().lower() for status in status_filter_str.split(',')]
            # Basic validation: ensure all provided statuses are strings
            if not all(isinstance(s, str) for s in statuses_to_filter):
                current_app.logger.warning(f"Invalid status value in status_filter: {status_filter_str}")
                return jsonify({'error': 'Invalid status value provided in filter.'}), 400
            query = query.filter(Booking.status.in_(statuses_to_filter))
        else:
            # Default behavior: if no status_filter is provided, show active/relevant bookings
            default_active_statuses = ['approved', 'pending', 'checked_in', 'confirmed']
            query = query.filter(Booking.status.in_(default_active_statuses))

        user_bookings = query.all()

        events = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            title = booking.title or (resource.name if resource else 'Booking')
            resource_name = resource.name if resource else "Unknown Resource" # Get resource name
            events.append({
                'id': booking.id,
                'title': title,
                'start': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end': booking.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'recurrence_rule': booking.recurrence_rule,
                'resource_id': booking.resource_id,
                'resource_name': resource_name, # Include resource name
                'status': booking.status # Include status
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
    Optionally accepts a 'pin' in the JSON body for PIN-based check-in.
    """
    data = request.get_json(silent=True) # Use silent=True to not fail if no JSON body
    provided_pin = data.get('pin') if data else None

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

        booking_settings = BookingSettings.query.first()
        if booking_settings:
            check_in_minutes_before = booking_settings.check_in_minutes_before
            check_in_minutes_after = booking_settings.check_in_minutes_after
        else:
            current_app.logger.warning(f"BookingSettings not found for check_in_booking {booking_id}, using default window (15/15 mins).")
            check_in_minutes_before = 15
            check_in_minutes_after = 15

        now = datetime.now(timezone.utc)

        # Ensure booking.start_time is offset-aware for comparison
        booking_start_time_aware = booking.start_time
        if booking_start_time_aware.tzinfo is None: # Should be UTC from DB
            booking_start_time_aware = booking_start_time_aware.replace(tzinfo=timezone.utc)

        if not (booking_start_time_aware - timedelta(minutes=check_in_minutes_before) <= now <= booking_start_time_aware + timedelta(minutes=check_in_minutes_after)):
            current_app.logger.warning(f"User {current_user.username} check-in attempt for booking {booking_id} outside of allowed window. Booking starts at {booking_start_time_aware.isoformat()}, current time {now.isoformat()}")
            return jsonify({'error': f'Check-in is only allowed from {check_in_minutes_before} minutes before to {check_in_minutes_after} minutes after the booking start time.'}), 403

        # PIN Validation if provided
        if provided_pin:
            resource = booking.resource_booked # Assuming backref is 'resource_booked'
            if not resource:
                current_app.logger.error(f"Resource not found for booking {booking_id} during PIN check-in attempt by {current_user.username}.")
                return jsonify({'error': 'Associated resource not found for this booking.'}), 500

            active_pin = ResourcePIN.query.filter_by(
                resource_id=resource.id,
                pin_value=provided_pin,
                is_active=True
            ).first()

            if not active_pin:
                current_app.logger.warning(f"User {current_user.username} failed PIN check-in for booking {booking_id}. Invalid PIN: {provided_pin} for resource {resource.id}")
                add_audit_log(action="CHECK_IN_FAILED_INVALID_PIN", user_id=current_user.id, username=current_user.username, details=f"Booking ID {booking_id}, Resource ID {resource.id}, Attempted PIN: {provided_pin}")
                return jsonify({'error': 'Invalid or inactive PIN provided.'}), 403

            current_app.logger.info(f"User {current_user.username} provided valid PIN {provided_pin} for check-in to booking {booking_id} for resource {resource.id}.")
            # PIN is valid, proceed with check-in

        booking.checked_in_at = now.replace(tzinfo=None) # Store as naive UTC
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        audit_details = f"User '{current_user.username}' checked into booking ID {booking.id} for resource '{resource_name}'."
        if provided_pin:
            audit_details += f" Using PIN." # PIN value itself should not be in general audit log for security.
                                         # Specific PIN attempt logs could be separate if needed.
        add_audit_log(action="CHECK_IN_SUCCESS", details=audit_details)

        socketio.emit('booking_updated', {'action': 'checked_in', 'booking_id': booking.id, 'checked_in_at': now.isoformat(), 'resource_id': booking.resource_id})
        current_app.logger.info(f"User '{current_user.username}' successfully checked into booking ID: {booking_id} at {now.isoformat()}{' using PIN' if provided_pin else ''}.")

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
        booking.status = 'completed' # Set status to completed
        # Optional: Adjust booking end_time if an early check-out should free up the resource.
        # booking.end_time = now
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        add_audit_log(action="CHECK_OUT_SUCCESS", details=f"User '{current_user.username}' checked out of booking ID {booking.id} for resource '{resource_name}'. Status set to completed.")
        socketio.emit('booking_updated', {'action': 'checked_out', 'booking_id': booking.id, 'checked_out_at': now.isoformat(), 'resource_id': booking.resource_id, 'status': 'completed'})
        current_app.logger.info(f"User '{current_user.username}' successfully checked out of booking ID: {booking_id} at {now.isoformat()}. Status set to completed.")

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


@api_bookings_bp.route('/bookings/check-in-qr/<string:token>', methods=['GET'])
def qr_check_in(token):
    """
    Allows check-in to a booking using a time-limited token (e.g., from a QR code).
    This endpoint does not require user login.
    """
    booking = Booking.query.filter_by(check_in_token=token).first()
    if not booking:
        current_app.logger.warning(f"QR Check-in attempt with invalid token: {token}")
        return jsonify({'error': 'Invalid or expired check-in token.'}), 404

    now_utc = datetime.now(timezone.utc)

    # Ensure booking.check_in_token_expires_at is treated as UTC if naive
    token_expires_at_utc = booking.check_in_token_expires_at
    if token_expires_at_utc and token_expires_at_utc.tzinfo is None: # Check if not None before accessing tzinfo
        token_expires_at_utc = token_expires_at_utc.replace(tzinfo=timezone.utc)

    if booking.check_in_token_expires_at is None or token_expires_at_utc < now_utc:
        current_app.logger.warning(f"QR Check-in attempt with expired token ID {token} for booking {booking.id}. Token expiry: {booking.check_in_token_expires_at}, Now: {now_utc}")
        # Invalidate the token to prevent reuse if it's just expired
        booking.check_in_token = None
        booking.check_in_token_expires_at = None
        db.session.commit()
        return jsonify({'error': 'Invalid or expired check-in token.'}), 400 # 400 for expired, 404 for invalid

    if booking.checked_in_at:
        current_app.logger.info(f"QR Check-in attempt for already checked-in booking {booking.id} with token {token}")
        return jsonify({
            'message': 'Already checked in.',
            'resource_name': booking.resource_booked.name if booking.resource_booked else "Unknown Resource",
            'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat()
        }), 200 # Successfully identified already checked-in state

    if booking.status != 'approved':
        current_app.logger.warning(f"QR Check-in attempt for booking {booking.id} with status '{booking.status}' using token {token}")
        return jsonify({'error': f'Booking is not active (status: {booking.status}). Cannot check in.'}), 403

    booking_settings = BookingSettings.query.first()
    if booking_settings:
        check_in_minutes_before = booking_settings.check_in_minutes_before
        check_in_minutes_after = booking_settings.check_in_minutes_after
    else:
        current_app.logger.warning(f"BookingSettings not found for qr_check_in booking {booking.id}, using default window (15/15 mins).")
        check_in_minutes_before = 15
        check_in_minutes_after = 15

    booking_start_time_utc = booking.start_time
    if booking_start_time_utc.tzinfo is None: # DB stores naive UTC
        booking_start_time_utc = booking_start_time_utc.replace(tzinfo=timezone.utc)

    check_in_window_start = booking_start_time_utc - timedelta(minutes=check_in_minutes_before)
    check_in_window_end = booking_start_time_utc + timedelta(minutes=check_in_minutes_after)

    if not (check_in_window_start <= now_utc <= check_in_window_end):
        current_app.logger.warning(f"QR Check-in for booking {booking.id} (token {token}) outside allowed window. Booking Start: {booking_start_time_utc.isoformat()}, Window: {check_in_window_start.isoformat()} to {check_in_window_end.isoformat()}, Now: {now_utc.isoformat()}")
        return jsonify({'error': f'Check-in is only allowed from {check_in_minutes_before} minutes before to {check_in_minutes_after} minutes after the booking start time. (Current time: {now_utc.strftime("%H:%M:%S %Z")}, Booking start: {booking_start_time_utc.strftime("%H:%M:%S %Z")})'}), 403

    try:
        booking.checked_in_at = now_utc.replace(tzinfo=None) # Store as naive UTC
        booking.check_in_token = None # Invalidate token after use
        booking.check_in_token_expires_at = None # Clear expiry too
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"

        # For audit log, use a placeholder for username since no user is logged in
        audit_username = f"QR_TOKEN_{token[:8]}..." # Truncated token for some anonymity

        add_audit_log(
            user_id=None,
            username=audit_username,
            action="QR_CHECK_IN_SUCCESS",
            details=f"Booking ID {booking.id} for resource '{resource_name}' (User: {booking.user_name}) checked in via QR code."
        )

        if hasattr(socketio, 'emit'): # Check if socketio is available and configured
            socketio.emit('booking_updated', {
                'action': 'checked_in',
                'booking_id': booking.id,
                'checked_in_at': now_utc.isoformat(), # Send aware UTC time
                'resource_id': booking.resource_id
            })
        current_app.logger.info(f"Booking {booking.id} successfully checked in via QR token {token} by user {booking.user_name}")

        return jsonify({
            'message': 'Check-in successful!',
            'resource_name': resource_name,
            'booking_title': booking.title,
            'user_name': booking.user_name, # Include the original user_name for context
            'start_time': booking.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'checked_in_at': now_utc.isoformat() # Send aware UTC time
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during QR check-in for booking {booking.id} (token {token}): {e}")
        # For audit log, use a placeholder for username
        audit_username = f"QR_TOKEN_{token[:8]}..."
        add_audit_log(
            user_id=None,
            username=audit_username,
            action="QR_CHECK_IN_FAILED",
            details=f"Failed QR check-in for booking {booking.id} (User: {booking.user_name}). Error: {str(e)}"
        )
        return jsonify({'error': 'Check-in failed due to a server error.'}), 500

@api_bookings_bp.route('/r/<int:resource_id>/checkin', methods=['GET'])
def resource_pin_check_in(resource_id):
    logger = current_app.logger
    pin_value = request.args.get('pin')

    resource = Resource.query.get(resource_id) # Changed to get for custom 404
    if not resource:
        logger.warning(f"PIN check-in attempt for non-existent resource ID: {resource_id}")
        return render_template('check_in_status_public.html', message=_('Resource not found.'), status='error'), 404

    if not pin_value:
        logger.warning(f"PIN check-in attempt for resource {resource_id} without PIN.")
        return render_template('check_in_status_public.html', message=_('PIN is required for check-in.'), status='error'), 400

    # Validate PIN
    verified_pin = ResourcePIN.query.filter_by(resource_id=resource_id, pin_value=pin_value, is_active=True).first()
    if not verified_pin:
        logger.warning(f"Invalid or inactive PIN '{pin_value}' used for resource {resource_id}.")
        # Check if the PIN exists but is inactive
        inactive_pin_exists = ResourcePIN.query.filter_by(resource_id=resource_id, pin_value=pin_value, is_active=False).first()
        if inactive_pin_exists:
            msg = _('The PIN provided is currently inactive. Please use an active PIN.')
        else:
            msg = _('The PIN provided is invalid for this resource.')
        return render_template('check_in_status_public.html', message=msg, status='error'), 403

    # Fetch BookingSettings
    booking_settings = BookingSettings.query.first()
    if not booking_settings:
        logger.error("BookingSettings not found in DB! Using default values for PIN check-in.")
        requires_login = True
        check_in_minutes_before = 15
        check_in_minutes_after = 15
    else:
        requires_login = booking_settings.resource_checkin_url_requires_login
        check_in_minutes_before = booking_settings.check_in_minutes_before
        check_in_minutes_after = booking_settings.check_in_minutes_after

    if requires_login and not current_user.is_authenticated:
        logger.info(f"PIN check-in for resource {resource_id} requires login.")
        login_url = url_for('ui.serve_login', next=request.url) # Assuming 'ui.serve_login' is your login route
        return render_template('check_in_status_public.html',
                               message=_('Login is required to perform this check-in. Please log in and try again.'),
                               status='error',
                               show_login_link=True, # Keep this, maybe for fallback or if JS fails
                               login_url=login_url,
                               show_embedded_login=True, # New flag
                               original_check_in_url=request.url # Pass the original URL
                              ), 401

    # Find the booking to check in
    target_booking = None
    now_utc = datetime.now(timezone.utc) # Use a single 'now' for all comparisons in this block

    potential_bookings_query = Booking.query.filter(
        Booking.resource_id == resource_id,
        Booking.status == 'approved',
        Booking.checked_in_at.is_(None)
    )

    if current_user.is_authenticated: # If login is required or user is simply logged in
        potential_bookings_query = potential_bookings_query.filter_by(user_name=current_user.username)

    # Iterate to find a booking within the check-in window
    # Order by start_time to get the most relevant (e.g., soonest) booking.
    potential_bookings = potential_bookings_query.order_by(Booking.start_time.asc()).all()

    for b in potential_bookings:
        start_time_aware = b.start_time.replace(tzinfo=timezone.utc) if b.start_time.tzinfo is None else b.start_time

        check_in_window_start = start_time_aware - timedelta(minutes=check_in_minutes_before)
        check_in_window_end = start_time_aware + timedelta(minutes=check_in_minutes_after)

        if check_in_window_start <= now_utc <= check_in_window_end:
            target_booking = b
            break

    if not target_booking:
        user_identifier_for_log = current_user.username if current_user.is_authenticated else "anonymous/public"
        logger.warning(f"PIN check-in for resource {resource_id} (PIN: {pin_value}): No active booking found within check-in window for user '{user_identifier_for_log}'.")
        return render_template('check_in_status_public.html', message=_('No active booking found for this resource within the check-in window for your session.'), status='error'), 404

    if target_booking.checked_in_at:
        logger.info(f"PIN check-in attempt for already checked-in booking {target_booking.id} (Resource {resource_id}, PIN {pin_value}).")
        booking_details = {
            'title': target_booking.title,
            'resource_name': resource.name,
            'user_name': target_booking.user_name,
            'checked_in_at_formatted': target_booking.checked_in_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        return render_template('check_in_status_public.html',
                               message=_('This booking has already been checked in.'),
                               status='success', # Or 'info'
                               booking_details=booking_details), 200 # 200 as it's a valid state

    # Perform Check-in
    try:
        target_booking.checked_in_at = datetime.utcnow() # Stored as naive UTC
        # Optional: Deactivate PIN if single-use
        # verified_pin.is_active = False
        db.session.commit()

        user_identifier_for_audit = current_user.username if current_user.is_authenticated else f"PIN_USER_({verified_pin.id})"
        add_audit_log(action="CHECK_IN_VIA_RESOURCE_URL", # Changed action name for clarity vs direct user check-in
                      details=f"User '{user_identifier_for_audit}' checked into booking ID {target_booking.id} for resource '{resource.name}' using PIN {verified_pin.pin_value}.",
                      user_id=current_user.id if current_user.is_authenticated else None)

        logger.info(f"Successfully checked in booking ID {target_booking.id} for resource {resource.id} using PIN {pin_value}.")

        booking_details_success = {
            'title': target_booking.title,
            'resource_name': resource.name,
            'user_name': target_booking.user_name,
            'checked_in_at_formatted': target_booking.checked_in_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        return render_template('check_in_status_public.html',
                               message=_('Check-in successful!'),
                               status='success',
                               booking_details=booking_details_success), 200

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error during PIN check-in for booking {target_booking.id} (Resource {resource_id}, PIN {pin_value}):")
        return render_template('check_in_status_public.html', message=_('Failed to process PIN check-in due to a server error.'), status='error'), 500
