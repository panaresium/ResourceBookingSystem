from flask import Blueprint, jsonify, request, current_app, abort, render_template, url_for
from flask_login import login_required, current_user
import json # Added json import
from sqlalchemy import func
from sqlalchemy.sql import func as sqlfunc # Explicit import for sqlalchemy.sql.func
from sqlalchemy.exc import IntegrityError # Added for unique constraint handling
from translations import _ # For translations
import secrets
from datetime import datetime, timedelta, timezone, time

# Local imports
# Assuming extensions.py contains db, socketio, mail
from extensions import db, socketio # Removed mail
# Assuming models.py contains these model definitions
from models import Booking, Resource, User, WaitlistEntry, BookingSettings, ResourcePIN, FloorMap # Added ResourcePIN & FloorMap
# Assuming utils.py contains these helper functions
from utils import add_audit_log, parse_simple_rrule, send_email, send_teams_notification, check_booking_permission, generate_booking_image, get_current_effective_time # Added get_current_effective_time
# Assuming auth.py contains permission_required decorator
from auth import permission_required

# Blueprint Configuration
api_bookings_bp = Blueprint('api_bookings', __name__, url_prefix='/api')

# Initialization function
def init_api_bookings_routes(app):
    app.register_blueprint(api_bookings_bp)

# Helper function to fetch and paginate user bookings
def _fetch_user_bookings_data(user_name, booking_type, page, per_page, status_filter, resource_name_filter, date_filter_str, logger):
    """
    Helper function to fetch, filter, sort, and paginate bookings for a user.
    """
    try:
        booking_settings = BookingSettings.query.first()
        enable_check_in_out = booking_settings.enable_check_in_out if booking_settings else False
        if booking_settings:
            logger.info(f"BookingSettings found. enable_check_in_out determined as: {enable_check_in_out}")
        else:
            logger.info(f"BookingSettings NOT found. enable_check_in_out determined as: {enable_check_in_out}")
        allow_check_in_without_pin_setting = booking_settings.allow_check_in_without_pin if booking_settings and hasattr(booking_settings, 'allow_check_in_without_pin') else True # Default True
        check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings and booking_settings.check_in_minutes_before is not None else 15
        check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings and booking_settings.check_in_minutes_after is not None else 15
        past_booking_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings and booking_settings.past_booking_time_adjustment_hours is not None else 0
        current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0
        if not booking_settings: # This check might be redundant if individual attributes are checked with hasattr, but kept for general warning.
            logger.warning("BookingSettings not found or some settings are missing, using default values for _fetch_user_bookings_data.")

        base_query = Booking.query.filter_by(user_name=user_name)

        if status_filter and status_filter.lower() != 'all' and status_filter.lower() != '':
            base_query = base_query.filter(
                sqlfunc.trim(sqlfunc.lower(Booking.status)) == status_filter.lower()
            )

        if resource_name_filter:
            base_query = base_query.join(Resource).filter(Resource.name.ilike(f"%{resource_name_filter}%"))

        if date_filter_str:
            try:
                selected_date = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
                # Booking.start_time is naive venue local. To filter by a specific date,
                # it's generally fine to use sqlfunc.date() directly if the DB handles it well.
                # Or, convert selected_date to a range in venue local time if more precision is needed.
                # For now, assume sqlfunc.date(Booking.start_time) works as intended for local times.
                base_query = base_query.filter(sqlfunc.date(Booking.start_time) == selected_date)
            except ValueError:
                logger.warning(f"Invalid date_filter format: '{date_filter_str}'. Ignoring date filter.")
                pass

        all_user_bookings_from_db = base_query.all()

        relevant_bookings_dicts = []
        effective_now_aware = get_current_effective_time() # This is aware (UTC or with offset)
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # For comparison with naive local DB times

        for booking in all_user_bookings_from_db:
            resource = Resource.query.get(booking.resource_id)
            resource_name = resource.name if resource else "Unknown Resource"

            # Booking.start_time is naive venue local
            booking_start_local_naive = booking.start_time

            # Check-in window calculation in local naive time
            effective_check_in_base_time_local_naive = booking_start_local_naive
            check_in_window_start_local_naive = effective_check_in_base_time_local_naive - timedelta(minutes=check_in_minutes_before)
            check_in_window_end_local_naive = effective_check_in_base_time_local_naive + timedelta(minutes=check_in_minutes_after)

            is_upcoming = booking.end_time > effective_now_local_naive

            if (booking_type == 'upcoming' and not is_upcoming) or \
               (booking_type == 'past' and is_upcoming):
                continue # Skip if not matching the requested type

            # Log variables for can_check_in calculation
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: booking.status = {booking.status}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: booking.checked_in_at = {booking.checked_in_at}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: booking_start_local_naive = {booking_start_local_naive}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: past_booking_adjustment_hours = {past_booking_adjustment_hours}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: effective_check_in_base_time_local_naive = {effective_check_in_base_time_local_naive}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: check_in_minutes_before = {check_in_minutes_before}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: check_in_minutes_after = {check_in_minutes_after}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: check_in_window_start_local_naive = {check_in_window_start_local_naive}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: check_in_window_end_local_naive = {check_in_window_end_local_naive}")
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: effective_now_local_naive = {effective_now_local_naive}")

            window_comparison_result = (check_in_window_start_local_naive <= effective_now_local_naive <= check_in_window_end_local_naive)
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: window_comparison_result = {window_comparison_result}")

            can_check_in = (
                enable_check_in_out and
                booking.checked_in_at is None and
                booking.status == 'approved' and
                window_comparison_result
            )
            # logger.info(f"[Booking ID: {booking.id}] Check-in Calc: FINAL can_check_in = {can_check_in}")

            display_check_in_token = None
            if booking.check_in_token and booking.checked_in_at is None and booking.status == 'approved':
                # booking.check_in_token_expires_at is naive UTC
                # booking.end_time is naive venue local
                # effective_now_aware is aware (system effective time)

                aware_utc_token_expiry = None
                if booking.check_in_token_expires_at:
                    aware_utc_token_expiry = booking.check_in_token_expires_at.replace(tzinfo=timezone.utc)

                # Convert booking.end_time (naive venue local) to aware UTC for comparison
                aware_utc_booking_end = (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)

                if aware_utc_token_expiry and aware_utc_token_expiry > effective_now_aware and aware_utc_booking_end > effective_now_aware:
                    display_check_in_token = booking.check_in_token

            resource_has_active_pin = False
            if resource:
                resource_has_active_pin = ResourcePIN.query.filter_by(resource_id=resource.id, is_active=True).first() is not None

            # Removed 'pin': current_resource_pin_value ... from here
            # The old 'pin_required_for_resource' was also removed as it was not fully implemented.
            # Replaced by 'resource_has_active_pin'.

            booking_dict = {
                'id': booking.id,
                'resource_id': booking.resource_id,
                'resource_name': resource_name,
                'user_name': booking.user_name,
                'start_time': (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
                'end_time': (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
                'title': booking.title,
                'status': booking.status,
                'recurrence_rule': booking.recurrence_rule,
                'admin_deleted_message': booking.admin_deleted_message,
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None, # Assuming checked_in_at is stored as naive UTC
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None, # Assuming checked_out_at is stored as naive UTC
                'can_check_in': can_check_in,
                'check_in_token': display_check_in_token,
                'resource_has_active_pin': resource_has_active_pin,
                'booking_display_start_time': booking.booking_display_start_time.strftime('%H:%M') if booking.booking_display_start_time else None,
                'booking_display_end_time': booking.booking_display_end_time.strftime('%H:%M') if booking.booking_display_end_time else None
            }
            relevant_bookings_dicts.append(booking_dict)

        # Sort based on booking_type
        if booking_type == 'upcoming':
            relevant_bookings_dicts.sort(key=lambda b: b['start_time'])
        else: # past
            relevant_bookings_dicts.sort(key=lambda b: b['start_time'], reverse=True)

        total_items = len(relevant_bookings_dicts)
        total_pages = (total_items + per_page - 1) // per_page if per_page > 0 else 0
        if total_pages == 0 and total_items > 0: total_pages = 1 # Ensure at least one page if items exist

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_bookings = relevant_bookings_dicts[start_idx:end_idx]

        pagination_info = {
            'current_page': page,
            'per_page': per_page,
            'total_items': total_items,
            'total_pages': total_pages,
        }

        return paginated_bookings, pagination_info, enable_check_in_out, allow_check_in_without_pin_setting

    except Exception as e:
        logger.exception(f"Error in _fetch_user_bookings_data for user {user_name}, type {booking_type}: {e}")
        raise # Re-raise to be caught by the calling route


# API Routes will be added below this line

@api_bookings_bp.route('/bookings/upcoming', methods=['GET'])
@login_required
def get_upcoming_bookings():
    logger = current_app.logger
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', current_app.config.get('DEFAULT_ITEMS_PER_PAGE', 5), type=int)
        status_filter = request.args.get('status_filter')
        resource_name_filter = request.args.get('resource_name_filter')
        date_filter = request.args.get('date_filter') # Added date_filter

        my_bookings_per_page_options = current_app.config.get('MY_BOOKINGS_ITEMS_PER_PAGE_OPTIONS', [5, 10, 25, 50])
        if per_page not in my_bookings_per_page_options:
             per_page = my_bookings_per_page_options[0]


        paginated_bookings, pagination_info, check_in_out_enabled, allow_check_in_without_pin = _fetch_user_bookings_data(
            current_user.username, 'upcoming', page, per_page, status_filter, resource_name_filter, date_filter, logger
        )

        pagination_info['per_page_options'] = my_bookings_per_page_options


        logger.info(f"User '{current_user.username}' fetched UPCOMING bookings. Page {page}/{pagination_info['total_pages']}, Items {len(paginated_bookings)}/{pagination_info['total_items']}.")
        return jsonify({
            'success': True,
            'bookings': paginated_bookings,
            'pagination': pagination_info,
            'check_in_out_enabled': check_in_out_enabled,
            'allow_check_in_without_pin': allow_check_in_without_pin
        }), 200

    except Exception as e:
        logger.exception(f"Error fetching UPCOMING bookings for user '{current_user.username}': {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch upcoming bookings due to a server error.'}), 500


@api_bookings_bp.route('/bookings/past', methods=['GET'])
@login_required
def get_past_bookings():
    logger = current_app.logger
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', current_app.config.get('DEFAULT_ITEMS_PER_PAGE', 5), type=int)
        status_filter = request.args.get('status_filter')
        resource_name_filter = request.args.get('resource_name_filter')
        date_filter = request.args.get('date_filter') # Added date_filter

        my_bookings_per_page_options = current_app.config.get('MY_BOOKINGS_ITEMS_PER_PAGE_OPTIONS', [5, 10, 25, 50])
        if per_page not in my_bookings_per_page_options:
             per_page = my_bookings_per_page_options[0]

        paginated_bookings, pagination_info, check_in_out_enabled, allow_check_in_without_pin = _fetch_user_bookings_data(
            current_user.username, 'past', page, per_page, status_filter, resource_name_filter, date_filter, logger
        )

        pagination_info['per_page_options'] = my_bookings_per_page_options

        logger.info(f"User '{current_user.username}' fetched PAST bookings. Page {page}/{pagination_info['total_pages']}, Items {len(paginated_bookings)}/{pagination_info['total_items']}.")
        return jsonify({
            'success': True,
            'bookings': paginated_bookings,
            'pagination': pagination_info,
            'check_in_out_enabled': check_in_out_enabled,
            'allow_check_in_without_pin': allow_check_in_without_pin
        }), 200

    except Exception as e:
        logger.exception(f"Error fetching PAST bookings for user '{current_user.username}': {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch past bookings due to a server error.'}), 500


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

    # Get the global offset for converting to UTC for storage
    current_offset_hours = 0
    if booking_settings and booking_settings.global_time_offset_hours is not None:
        current_offset_hours = booking_settings.global_time_offset_hours

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

    effective_now = get_current_effective_time()
    # For comparisons with naive new_booking_start_time, and for date() operations like in max_booking_days_in_future
    now_for_logic = effective_now.replace(tzinfo=None) # This is naive local "now"

    if allow_past_bookings_effective:
        # Past bookings are allowed.
        # `past_booking_time_adjustment_hours` does not restrict how far in the past a booking can be made here.
        # If new_booking_start_time is genuinely in the past (i.e., < now_utc), it's permitted.
        # If new_booking_start_time is in the future, other rules (like max_booking_days_in_future) will apply.
        # No specific error related to past booking limits is raised if allow_past_bookings_effective is true.
        pass
    else:
        # allow_past_bookings_effective is FALSE.
        # Past bookings are generally disallowed, but past_booking_time_adjustment_hours defines the precise boundary.
        # This means effective_past_booking_hours determines how many hours "ago" is the cutoff.
        # A positive value allows bookings slightly in the past.
        # A zero or negative value means bookings must be now or in the future relative to the adjustment.
        past_booking_cutoff_time = now_for_logic - timedelta(hours=effective_past_booking_hours)

        if new_booking_start_time < past_booking_cutoff_time:
            current_app.logger.warning(
                f"Booking attempt by {current_user.username} for resource {resource_id} at {new_booking_start_time} "
                f"is before the allowed cutoff time of {past_booking_cutoff_time} "
                f"(current time (effective): {now_for_logic}, adjustment: {effective_past_booking_hours} hours, and past bookings are generally disabled)."
            )
            return jsonify({'error': 'Booking time is outside the allowed window for past or future bookings as per current settings.'}), 400

    # Enforce max_booking_days_in_future
    if max_booking_days_in_future_effective is not None:
        max_allowed_date = now_for_logic.date() + timedelta(days=max_booking_days_in_future_effective)
        if new_booking_start_time.date() > max_allowed_date:
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} too far in future ({new_booking_start_time.date()}), limit is {max_booking_days_in_future_effective} days.")
            return jsonify({'error': f'Bookings cannot be made more than {max_booking_days_in_future_effective} days in advance.'}), 400

    if resource.is_under_maintenance:
        maintenance_until_local_naive = None
        if resource.maintenance_until:
            # Assuming resource.maintenance_until is naive UTC
            maint_utc = resource.maintenance_until.replace(tzinfo=timezone.utc)
            maint_local_aware = maint_utc + timedelta(hours=current_offset_hours)
            maintenance_until_local_naive = maint_local_aware.replace(tzinfo=None)

        if maintenance_until_local_naive is None or new_booking_start_time < maintenance_until_local_naive:
            until_str = maintenance_until_local_naive.isoformat() if maintenance_until_local_naive else 'until further notice'
            # It might be better to format until_str more nicely, e.g., .strftime('%Y-%m-%d %H:%M')
            current_app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} during maintenance period (until {until_str} local).")
            return jsonify({'error': f'Resource is under maintenance until {until_str} (venue local time). Booking not allowed.'}), 403

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
        user_booking_count = Booking.query.filter(
            Booking.user_name == current_user.username, # Assuming current_user.username is the correct field
            Booking.end_time > now_for_logic,      # Booking has not ended yet (compare naive to naive)
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
        for occ_start_local, occ_end_local in occurrences: # occ_start_local, occ_end_local are from user's perspective (effective local time)
            # occ_start_local and occ_end_local are already naive datetime objects representing venue time
            # No conversion to UTC needed here as we want to store them directly.

            new_booking = Booking(
                resource_id=resource_id,
                start_time=occ_start_local, # Store venue local time directly
                end_time=occ_end_local,   # Store venue local time directly
                title=title,
                user_name=user_name_for_record,
                recurrence_rule=recurrence_rule_str,
                booking_display_start_time=occ_start_local.time(),
                booking_display_end_time=occ_end_local.time()
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

        # Prepare and log email data for each booking
        for new_booking in created_bookings:
            try:
                user = User.query.filter_by(username=new_booking.user_name).first()
                if not user or not user.email:
                    current_app.logger.warning(f"User {new_booking.user_name} not found or has no email. Skipping confirmation email data preparation for booking {new_booking.id}.")
                    continue

                resource_for_email = Resource.query.get(new_booking.resource_id) # Renamed to avoid conflict with outer scope 'resource'
                if not resource_for_email:
                    current_app.logger.warning(f"Resource {new_booking.resource_id} not found. Skipping confirmation email data preparation for booking {new_booking.id}.")
                    continue

                floor_map_location = "N/A"
                floor_map_floor = "N/A"
                if resource_for_email.floor_map_id:
                    floor_map = FloorMap.query.get(resource_for_email.floor_map_id)
                    if floor_map:
                        floor_map_location = floor_map.location
                        floor_map_floor = floor_map.floor
                    else:
                        current_app.logger.warning(f"FloorMap {resource_for_email.floor_map_id} not found for resource {resource_for_email.id}. Using N/A for location/floor for booking {new_booking.id}.")

                check_in_url = None # Default to None
                if new_booking.check_in_token:
                     check_in_url = url_for('api_bookings.qr_check_in', token=new_booking.check_in_token, _external=True)
                else:
                    current_app.logger.warning(f"No check_in_token found for booking {new_booking.id}. Check-in URL will be None.")

                email_data = {
                    'user_name': new_booking.user_name,
                    'user_email': user.email,
                    'booking_title': new_booking.title,
                    'resource_name': resource_for_email.name,
                    'start_time': new_booking.start_time.strftime('%Y-%m-%d %H:%M'),
                    'end_time': new_booking.end_time.strftime('%Y-%m-%d %H:%M'),
                    'location': floor_map_location,
                    'floor': floor_map_floor,
                    'resource_image_filename': resource_for_email.image_filename,
                    'map_coordinates': resource_for_email.map_coordinates,
                    'check_in_url': check_in_url,
                    'booking_confirmation_message': f"Your booking for {resource_for_email.name} has been confirmed."
                }
                # current_app.logger.info(f"Email data for booking {new_booking.id}: {email_data}") # Old log line

                # Generate image with resource area marked
                processed_image_path = None # Initialize
                if resource_for_email and resource_for_email.map_coordinates and resource_for_email.floor_map_id:
                    # generate_booking_image now sources its own logger via current_app
                    processed_image_path = generate_booking_image(
                        resource_for_email.id, # Pass resource ID
                        resource_for_email.map_coordinates, # Pass map_coordinates string
                        resource_for_email.name # Pass resource name
                    )
                elif resource_for_email.image_filename: # Check resource_for_email directly
                    current_app.logger.info(f"Booking {new_booking.id}: Resource image filename present but no map coordinates for resource {resource_for_email.id}. No attachment image will be generated.")
                else:
                    current_app.logger.info(f"Booking {new_booking.id}: No resource image filename. No image will be generated or attached.")

                # Render HTML email body
                # Ensure render_template is imported: from flask import render_template
                html_email_body = render_template('email/booking_confirmation.html', **email_data)

                # Plain text body (fallback)
                plain_text_body = (
                    f"Dear {email_data['user_name']},\n\n"
                    f"{email_data['booking_confirmation_message']}\n\n"
                    f"Booking Details:\n"
                    f"- Resource: {email_data['resource_name']}\n"
                    f"- Title: {email_data['booking_title']}\n"
                    f"- Date & Time: {email_data['start_time']} - {email_data['end_time']}\n"
                    f"- Location: {email_data['location']}\n" # Adjusted to match template
                    f"- Floor: {email_data['floor']}\n\n"     # Adjusted to match template
                    f"Check-in URL: {email_data['check_in_url']}\n\n"
                    f"Thank you!"
                )

                send_email(
                    to_address=email_data['user_email'],
                    subject=f"Booking Confirmed: {email_data['resource_name']} - {email_data['booking_title']}",
                    body=plain_text_body,
                    html_body=html_email_body,
                    attachment_path=processed_image_path # This will be None if image generation failed or wasn't applicable
                )
                current_app.logger.info(f"Booking confirmation email initiated for booking {new_booking.id} to {email_data['user_email']}.")

            except Exception as e_email: # Changed variable name from 'e' to 'e_email'
                current_app.logger.error(f"Error processing or sending confirmation email for booking {new_booking.id}: {e_email}", exc_info=True)

        # Audit logging loop
        for audit_booking in created_bookings: # Use a different loop variable
            resource_for_audit = Resource.query.get(audit_booking.resource_id)
            resource_name_for_audit = resource_for_audit.name if resource_for_audit else "Unknown Resource"
            # Ensure user_name_for_record and title are correctly scoped or fetched if necessary.
            # Using audit_booking.user_name and audit_booking.title for consistency with the booking object.
            add_audit_log(action="CREATE_BOOKING", details=f"Booking ID {audit_booking.id} for resource ID {audit_booking.resource_id} ('{resource_name_for_audit}') created by user '{audit_booking.user_name}'. Title: '{audit_booking.title}'. Token generated.")
            socketio.emit('booking_updated', {'action': 'created', 'booking_id': audit_booking.id, 'resource_id': audit_booking.resource_id})

        created_data = [{
            'id': b.id,
            'resource_id': b.resource_id,
            'title': b.title,
            'user_name': b.user_name,
                'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
                'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
                'status': b.status,
                'recurrence_rule': b.recurrence_rule,
                'booking_display_start_time': b.booking_display_start_time.strftime('%H:%M') if b.booking_display_start_time else None,
                'booking_display_end_time': b.booking_display_end_time.strftime('%H:%M') if b.booking_display_end_time else None
        } for b in created_bookings]
        return jsonify({'bookings': created_data}), 201

    except IntegrityError as ie: # Catch specific IntegrityError
        db.session.rollback()
        current_app.logger.warning(f"IntegrityError during booking creation by {current_user.username} for resource {resource_id}: {ie}")
        # Construct a user-friendly representation of the first attempted slot for the audit log
        # Note: occurrences, date_str, start_time_str, end_time_str are from the outer scope of create_booking
        first_occ_start_local, _ = occurrences[0] if occurrences else (None, None)
        slot_time_for_log = f"{date_str} {start_time_str}-{end_time_str}" # Original request data
        if first_occ_start_local: # If occurrences were generated, use the first actual slot time
             slot_time_for_log = f"{first_occ_start_local.strftime('%Y-%m-%d %H:%M')}-{occurrences[0][1].strftime('%H:%M')}"

        add_audit_log(action="CREATE_BOOKING_FAILED_DUPLICATE", details=f"User '{current_user.username}' attempted to book a duplicate slot for resource ID {resource_id}. Slot: {slot_time_for_log}.")
        return jsonify({'error': 'This time slot appears to have just been booked or conflicts with an existing booking. Please try a different slot or refresh.'}), 409 # 409 Conflict

    except Exception as e: # Catch other general exceptions
        db.session.rollback()
        current_app.logger.exception(f"Error creating booking series for resource {resource_id} by {current_user.username}: {e}")
        add_audit_log(action="CREATE_BOOKING_FAILED", details=f"Failed to create booking series for resource ID {resource_id} by user '{current_user.username}'. Error: {str(e)}")
        return jsonify({'error': 'Failed to create booking series due to a server error.'}), 500

@api_bookings_bp.route('/bookings/my_bookings', methods=['GET'])
@login_required
def get_my_bookings():
    logger = current_app.logger
    try:
        # Pagination parameters for upcoming bookings
        page_upcoming = request.args.get('page_upcoming', 1, type=int)
        per_page_upcoming = request.args.get('per_page_upcoming', 5, type=int) # Default from JS

        # Pagination parameters for past bookings
        page_past = request.args.get('page_past', 1, type=int)
        per_page_past = request.args.get('per_page_past', 5, type=int) # Default from JS

        my_bookings_per_page_options = [5, 10, 25, 50] # From JS

        if per_page_upcoming not in my_bookings_per_page_options:
            per_page_upcoming = my_bookings_per_page_options[0]
        if per_page_past not in my_bookings_per_page_options:
            per_page_past = my_bookings_per_page_options[0]

        status_filter = request.args.get('status_filter')
        # date_filter_value_str = request.args.get('date_filter_value') # This seems to be from an older version, new JS uses resource_name_filter
        resource_name_filter = request.args.get('resource_name_filter') # Added for new filter

        booking_settings = BookingSettings.query.first()
        enable_check_in_out = booking_settings.enable_check_in_out if booking_settings else False
        allow_check_in_without_pin_setting = booking_settings.allow_check_in_without_pin if booking_settings and hasattr(booking_settings, 'allow_check_in_without_pin') else True
        check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings and booking_settings.check_in_minutes_before is not None else 15
        check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings and booking_settings.check_in_minutes_after is not None else 15
        past_booking_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings and booking_settings.past_booking_time_adjustment_hours is not None else 0
        current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0
        if not booking_settings: # General warning if settings are missing
             logger.warning("BookingSettings not found or some settings are missing, using default values for get_my_bookings.")

        user_bookings_query = Booking.query.filter_by(user_name=current_user.username)

        if status_filter and status_filter.lower() != 'all' and status_filter.lower() != '':
            user_bookings_query = user_bookings_query.filter(
                sqlfunc.trim(sqlfunc.lower(Booking.status)) == status_filter.lower()
            )

        if resource_name_filter: # New filter for resource name
            user_bookings_query = user_bookings_query.join(Resource).filter(Resource.name.ilike(f"%{resource_name_filter}%"))

        # Note: date_filter_value_str is not used by current JS, but kept for compatibility if needed.
        # if date_filter_value_str:
        #     try:
        #         target_date_obj = datetime.strptime(date_filter_value_str, '%Y-%m-%d').date()
        #         user_bookings_query = user_bookings_query.filter(
        #             sqlfunc.date(Booking.start_time) == target_date_obj
        #         )
        #     except ValueError:
        #         logger.warning(f"Invalid date_filter_value format: {date_filter_value_str}. Ignoring date filter.")

        # Fetch ALL bookings matching filters first
        all_user_bookings_from_db = user_bookings_query.all()

        all_upcoming_bookings_dicts = []
        all_past_bookings_dicts = []
        effective_now_aware = get_current_effective_time() # Aware (UTC or with offset)
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive local for DB comparisons

        for booking in all_user_bookings_from_db:
            resource = Resource.query.get(booking.resource_id)
            resource_name = resource.name if resource else "Unknown Resource"

            booking_start_local_naive = booking.start_time # Naive venue local

            # Check-in window calculation in local naive time
            effective_check_in_base_time_local_naive = booking_start_local_naive + timedelta(hours=past_booking_adjustment_hours)
            check_in_window_start_local_naive = effective_check_in_base_time_local_naive - timedelta(minutes=check_in_minutes_before)
            check_in_window_end_local_naive = effective_check_in_base_time_local_naive + timedelta(minutes=check_in_minutes_after)

            can_check_in = (
                enable_check_in_out and
                booking.checked_in_at is None and
                booking.status == 'approved' and
                (check_in_window_start_local_naive <= effective_now_local_naive <= check_in_window_end_local_naive)
            )

            display_check_in_token = None
            if booking.check_in_token and booking.checked_in_at is None and booking.status == 'approved':
                aware_utc_token_expiry = None
                if booking.check_in_token_expires_at: # naive UTC
                    aware_utc_token_expiry = booking.check_in_token_expires_at.replace(tzinfo=timezone.utc)

                # Convert booking.end_time (naive venue local) to aware UTC for comparison
                aware_utc_booking_end = (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)

                if aware_utc_token_expiry and aware_utc_token_expiry > effective_now_aware and aware_utc_booking_end > effective_now_aware:
                    display_check_in_token = booking.check_in_token

            booking_dict = {
                'id': booking.id,
                'resource_id': booking.resource_id,
                'resource_name': resource_name,
                'user_name': booking.user_name,
                'start_time': (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
                'end_time': (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
                'title': booking.title,
                'status': booking.status,
                'recurrence_rule': booking.recurrence_rule,
                'admin_deleted_message': booking.admin_deleted_message,
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None, # Assuming checked_in_at is naive UTC
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None, # Assuming checked_out_at is naive UTC
                'can_check_in': can_check_in,
                'check_in_token': display_check_in_token
            }

            if booking_start_local_naive >= effective_now_local_naive:
                all_upcoming_bookings_dicts.append(booking_dict)
            else:
                all_past_bookings_dicts.append(booking_dict)

        # Sort before pagination
        all_upcoming_bookings_dicts.sort(key=lambda b: b['start_time'])
        all_past_bookings_dicts.sort(key=lambda b: b['start_time'], reverse=True)

        # Python-side pagination for upcoming bookings
        total_items_upcoming = len(all_upcoming_bookings_dicts)
        total_pages_upcoming = (total_items_upcoming + per_page_upcoming - 1) // per_page_upcoming if per_page_upcoming > 0 else 0
        if total_pages_upcoming == 0 and total_items_upcoming > 0: total_pages_upcoming = 1
        start_idx_upcoming = (page_upcoming - 1) * per_page_upcoming
        end_idx_upcoming = start_idx_upcoming + per_page_upcoming
        paginated_upcoming_bookings = all_upcoming_bookings_dicts[start_idx_upcoming:end_idx_upcoming]

        # Python-side pagination for past bookings
        total_items_past = len(all_past_bookings_dicts)
        total_pages_past = (total_items_past + per_page_past - 1) // per_page_past if per_page_past > 0 else 0
        if total_pages_past == 0 and total_items_past > 0: total_pages_past = 1
        start_idx_past = (page_past - 1) * per_page_past
        end_idx_past = start_idx_past + per_page_past
        paginated_past_bookings = all_past_bookings_dicts[start_idx_past:end_idx_past]

        logger.info(f"User '{current_user.username}' fetched MyBookings. Upcoming: page {page_upcoming}/{total_pages_upcoming}, items {len(paginated_upcoming_bookings)}/{total_items_upcoming}. Past: page {page_past}/{total_pages_past}, items {len(paginated_past_bookings)}/{total_items_past}.")

        return jsonify({
            'success': True, # Added for consistency
            'upcoming_bookings': paginated_upcoming_bookings,
            'upcoming_pagination': {
                'current_page': page_upcoming,
                'per_page': per_page_upcoming,
                'total_items': total_items_upcoming,
                'total_pages': total_pages_upcoming,
                'per_page_options': my_bookings_per_page_options # Send options to JS
            },
            'past_bookings': paginated_past_bookings,
            'past_pagination': {
                'current_page': page_past,
                'per_page': per_page_past,
                'total_items': total_items_past,
                'total_pages': total_pages_past,
                'per_page_options': my_bookings_per_page_options # Send options to JS
            },
            'check_in_out_enabled': enable_check_in_out
        }), 200
    except Exception as e:
        logger.exception(f"Error fetching bookings for user '{current_user.username}':")
        # Return consistent error structure
        return jsonify({
            'success': False,
            'error': 'Failed to fetch your bookings due to a server error.',
            'upcoming_pagination': None, # Or default pagination objects
            'past_pagination': None,
            'allow_check_in_without_pin': True # Default if error before settings are fetched
        }), 500


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
        user_bookings_on_date = (
            db.session.query(
                Booking.id,
                Booking.title,
                Booking.resource_id,
                Resource.name.label('resource_name'),
                Booking.start_time,
                Booking.end_time
            )
            .join(Resource, Booking.resource_id == Resource.id)
            .filter(Booking.user_name == current_user.username)
            .filter(func.date(Booking.start_time) == target_date_obj)
            .filter(
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(
                    active_booking_statuses_for_user_schedule
                )
            )
            .order_by(Booking.start_time.asc())
            .all()
        )

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

        # Fetch current_offset_hours for converting to UTC for JSON response
        booking_settings_calendar = BookingSettings.query.first() # Renamed to avoid conflict if outer scope has it
        current_offset_hours_calendar = 0
        if booking_settings_calendar and hasattr(booking_settings_calendar, 'global_time_offset_hours') and booking_settings_calendar.global_time_offset_hours is not None:
            current_offset_hours_calendar = booking_settings_calendar.global_time_offset_hours
        else:
            current_app.logger.warning("BookingSettings not found or global_time_offset_hours not set for bookings_calendar, using 0 offset for UTC conversion.")


        events = []
        for booking in user_bookings:
            resource = Resource.query.get(booking.resource_id)
            title = booking.title or (resource.name if resource else 'Booking')
            resource_name = resource.name if resource else "Unknown Resource" # Get resource name
            events.append({
                'id': booking.id,
                'title': title,
                'start': (booking.start_time - timedelta(hours=current_offset_hours_calendar)).replace(tzinfo=timezone.utc).isoformat(),
                'end': (booking.end_time - timedelta(hours=current_offset_hours_calendar)).replace(tzinfo=timezone.utc).isoformat(),
                'recurrence_rule': booking.recurrence_rule,
                'resource_id': booking.resource_id,
                'resource_name': resource_name, # Include resource name
                'status': booking.status, # Include status
                'booking_display_start_time': booking.booking_display_start_time.strftime('%H:%M') if booking.booking_display_start_time else None,
                'booking_display_end_time': booking.booking_display_end_time.strftime('%H:%M') if booking.booking_display_end_time else None
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
    Input times can be offset-aware or naive. If naive, they are assumed to be in venue local time.
    If offset-aware, they are converted to venue local time.
    Booking times are stored as naive venue local times.
    """
    current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request received. User: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    data = request.get_json()
    current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Request JSON data: {data}")

    if not data:
        current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] No JSON data received.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    try:
        # Fetch Booking Settings for global_time_offset_hours
        booking_settings = BookingSettings.query.first()
        current_offset_hours = 0
        if booking_settings and booking_settings.global_time_offset_hours is not None:
            current_offset_hours = booking_settings.global_time_offset_hours
        else:
            current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] BookingSettings not found or global_time_offset_hours not set, using 0 offset.")

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
                parsed_new_start_time = datetime.fromisoformat(new_start_iso)
                parsed_new_end_time = datetime.fromisoformat(new_end_iso)

                # Convert to Naive Venue Local Time
                if parsed_new_start_time.tzinfo is not None:
                    utc_dt_start = parsed_new_start_time.astimezone(timezone.utc)
                    venue_local_dt_start = utc_dt_start + timedelta(hours=current_offset_hours)
                    parsed_new_start_time = venue_local_dt_start.replace(tzinfo=None)
                # Else: naive, assume it's already venue local time

                if parsed_new_end_time.tzinfo is not None:
                    utc_dt_end = parsed_new_end_time.astimezone(timezone.utc)
                    venue_local_dt_end = utc_dt_end + timedelta(hours=current_offset_hours)
                    parsed_new_end_time = venue_local_dt_end.replace(tzinfo=None)
                # Else: naive, assume it's already venue local time

            except ValueError:
                current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided invalid ISO format. Start: {new_start_iso}, End: {new_end_iso}")
                return jsonify({'error': 'Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS[Z] or YYYY-MM-DDTHH:MM:SS+/-HH:MM).'}), 400

            if parsed_new_start_time >= parsed_new_end_time:
                current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' provided start_time not before end_time.")
                return jsonify({'error': 'Start time must be before end time.'}), 400

            resource = Resource.query.get(booking.resource_id)
            if not resource:
                current_app.logger.error(f"[API PUT /api/bookings/{booking_id}] Resource ID {booking.resource_id} for booking {booking_id} not found during update.")
                return jsonify({'error': 'Associated resource not found.'}), 500

            # old_start_time and old_end_time from DB are naive venue local (after migration)
            # parsed_new_start_time and parsed_new_end_time are now also naive venue local

            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] ---- Time Change Check Debug ----")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Original DB old_start_time (naive venue local): {old_start_time.isoformat() if old_start_time else 'None'}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Original DB old_end_time (naive venue local): {old_end_time.isoformat() if old_end_time else 'None'}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Incoming new_start_iso from request: {new_start_iso}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Incoming new_end_iso from request: {new_end_iso}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] current_offset_hours: {current_offset_hours}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Parsed new_start_time (naive venue local): {parsed_new_start_time.isoformat() if parsed_new_start_time else 'None'}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Parsed new_end_time (naive venue local): {parsed_new_end_time.isoformat() if parsed_new_end_time else 'None'}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] ---- End Time Change Check Debug ----")

            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] --- Detailed Time Comparison ---")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Comparing old_start_time: {old_start_time.isoformat() if old_start_time else 'None'} (type: {type(old_start_time)}) with parsed_new_start_time: {parsed_new_start_time.isoformat() if parsed_new_start_time else 'None'} (type: {type(parsed_new_start_time)})")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Result of (parsed_new_start_time != old_start_time): {parsed_new_start_time != old_start_time if parsed_new_start_time and old_start_time else 'Comparison N/A'}")

            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Comparing old_end_time: {old_end_time.isoformat() if old_end_time else 'None'} (type: {type(old_end_time)}) with parsed_new_end_time: {parsed_new_end_time.isoformat() if parsed_new_end_time else 'None'} (type: {type(parsed_new_end_time)})")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Result of (parsed_new_end_time != old_end_time): {parsed_new_end_time != old_end_time if parsed_new_end_time and old_end_time else 'Comparison N/A'}")
            time_changed = parsed_new_start_time != old_start_time or parsed_new_end_time != old_end_time
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Final time_changed value: {time_changed}")
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] --- End Detailed Time Comparison ---")

            if time_changed and resource.is_under_maintenance:
                maintenance_active = False
                maintenance_until_venue_local_naive = None
                if resource.maintenance_until:
                    # Assuming resource.maintenance_until is stored as naive UTC or is UTC if aware
                    maintenance_until_utc = resource.maintenance_until
                    if maintenance_until_utc.tzinfo is None:
                        maintenance_until_utc = maintenance_until_utc.replace(tzinfo=timezone.utc)
                    else:
                        maintenance_until_utc = maintenance_until_utc.astimezone(timezone.utc)

                    maintenance_until_venue_local = maintenance_until_utc + timedelta(hours=current_offset_hours)
                    maintenance_until_venue_local_naive = maintenance_until_venue_local.replace(tzinfo=None)

                if maintenance_until_venue_local_naive is None and resource.is_under_maintenance: # Indefinite maintenance
                    maintenance_active = True
                elif maintenance_until_venue_local_naive and \
                     (parsed_new_start_time < maintenance_until_venue_local_naive or \
                      parsed_new_end_time <= maintenance_until_venue_local_naive): # Check against venue local maintenance time
                     maintenance_active = True

                if maintenance_active:
                    maint_until_str = maintenance_until_venue_local_naive.isoformat() if maintenance_until_venue_local_naive else "indefinitely"
                    current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Booking update conflicts with resource maintenance (until {maint_until_str} venue local).")
                    return jsonify({'error': f'Resource is under maintenance until {maint_until_str} (venue local) and the new time slot falls within this period.'}), 403

            if time_changed:
                # Assign processed naive venue local times
                booking.start_time = parsed_new_start_time
                booking.end_time = parsed_new_end_time

                conflicting_booking = Booking.query.filter(
                    Booking.resource_id == booking.resource_id,
                    Booking.id != booking_id,
                    Booking.start_time < booking.end_time, # Compares new venue local end time
                    Booking.end_time > booking.start_time  # Compares new venue local start time
                ).first()

                if conflicting_booking:
                    current_app.logger.warning(f"[API PUT /api/bookings/{booking_id}] Update for user '{current_user.username}' on resource ID {booking.resource_id} "
                                               f"conflicts with existing booking ID {conflicting_booking.id} on the same resource.")
                    # Rollback the time change before returning error
                    booking.start_time = old_start_time
                    booking.end_time = old_end_time
                    return jsonify({'error': 'The updated time slot conflicts with an existing booking on this resource.'}), 409

                # NEW CHECK: User's other bookings conflict on DIFFERENT resources
                # parsed_new_start_time and parsed_new_end_time are already naive venue local
                user_own_conflict = Booking.query.filter(
                    Booking.user_name == current_user.username,
                    Booking.resource_id != booking.resource_id,  # Critical: Different resource
                    Booking.id != booking_id,                   # Critical: Not the current booking
                    Booking.start_time < parsed_new_end_time,   # Compare against naive venue local
                    Booking.end_time > parsed_new_start_time    # Compare against naive venue local
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

            # NEW CHECK: User's other bookings conflict (ANY resource)
            # This check is to prevent a user from being double-booked with themselves,
            # regardless of the resource or the allow_multiple_resources_same_time setting.
            # Define active_conflict_statuses if not already available in this scope,
            # or use a direct list like ['approved', 'pending', 'checked_in', 'confirmed'].
            active_conflict_statuses_for_self_check = ['approved', 'pending', 'checked_in', 'confirmed']
            user_self_conflict_check = Booking.query.filter(
                Booking.user_name == current_user.username,
                Booking.id != booking_id,  # Exclude the booking being updated itself
                Booking.start_time < parsed_new_end_time,  # New end time of the booking being updated
                Booking.end_time > parsed_new_start_time,   # New start time of the booking being updated
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_conflict_statuses_for_self_check)
            ).first()

            if user_self_conflict_check:
                current_app.logger.warning(
                    f"[API PUT /api/bookings/{booking_id}] Update for user '{current_user.username}' "
                    f"conflicts with THEIR OWN existing booking ID {user_self_conflict_check.id} "
                    f"for resource '{user_self_conflict_check.resource_booked.name if user_self_conflict_check.resource_booked else 'N/A'}' (ID: {user_self_conflict_check.resource_id}) "
                    f"during the new self-conflict check."
                )
                # Revert time changes before returning error
                booking.start_time = old_start_time
                booking.end_time = old_end_time
                # No db.session.commit() should have happened for the main update yet.
                return jsonify({
                    'error': f"The updated time slot conflicts with another of your existing bookings "
                             f"for resource '{user_self_conflict_check.resource_booked.name if user_self_conflict_check.resource_booked else 'unknown resource'}' "
                             f"from {user_self_conflict_check.start_time.strftime('%H:%M')} to {user_self_conflict_check.end_time.strftime('%H:%M')} "
                             f"on {user_self_conflict_check.start_time.strftime('%Y-%m-%d')}."
                }), 409

            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] All conflict checks passed or were not applicable. Setting changes_made=True for time change.")
            changes_made = True
            change_details_list.append(f"time from {old_start_time.isoformat()} to {booking.start_time.isoformat()}-{booking.end_time.isoformat()}")

        if not changes_made:
            current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] User '{current_user.username}' submitted update with no actual changes.")
            return jsonify({'error': 'No changes supplied.'}), 400

        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] Attempting to commit changes to DB: Title='{booking.title}', Start='{booking.start_time.isoformat()}', End='{booking.end_time.isoformat()}'")
        db.session.commit()
        current_app.logger.info(f"[API PUT /api/bookings/{booking_id}] DB commit successful.")

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"

        # Send update email notification
        if current_user.email:
            try:
                resource_for_email = booking.resource_booked
                floor_map_location = "N/A"
                floor_map_floor = "N/A"
                floor_map_name = "N/A" # Added for completeness, though not directly in template
                if resource_for_email and resource_for_email.floor_map_id:
                    floor_map = FloorMap.query.get(resource_for_email.floor_map_id)
                    if floor_map:
                        floor_map_location = floor_map.location
                        floor_map_floor = floor_map.floor
                        floor_map_name = floor_map.name # Added
                    else:
                        current_app.logger.warning(f"FloorMap {resource_for_email.floor_map_id} not found for resource {resource_for_email.id} during update email prep for booking {booking.id}.")

                check_in_url = None
                if booking.check_in_token: # Use existing token if available
                    check_in_url = url_for('api_bookings.qr_check_in', token=booking.check_in_token, _external=True)
                else: # Or generate a new one if it makes sense for updates (e.g. if time changed significantly)
                    # For now, let's assume existing token or None is sufficient.
                    # If a new token is needed upon update, logic similar to create_booking would be here.
                    current_app.logger.info(f"No check_in_token found or regenerated for updated booking {booking.id}. Check-in URL will be None in email.")


                update_summary_for_email = f"Your booking for '{resource_name}' was updated. "
                if any("title from" in change for change in change_details_list):
                    update_summary_for_email += f"The title is now '{booking.title}'. "
                if any("time from" in change for change in change_details_list):
                    update_summary_for_email += f"The new time is {booking.start_time.strftime('%Y-%m-%d %H:%M')} to {booking.end_time.strftime('%Y-%m-%d %H:%M')}. "

                email_data = {
                    'user_name': current_user.username,
                    'booking_title': booking.title,
                    'resource_name': resource_name,
                    'start_time': booking.start_time.strftime('%Y-%m-%d %H:%M'),
                    'end_time': booking.end_time.strftime('%Y-%m-%d %H:%M'),
                    'location': floor_map_location,
                    'floor': floor_map_floor,
                    'floor_map_name': floor_map_name, # Added
                    'check_in_url': check_in_url,
                    'update_summary': update_summary_for_email.strip()
                }

                processed_image_path = None
                if resource_for_email and resource_for_email.map_coordinates and resource_for_email.floor_map_id:
                    processed_image_path = generate_booking_image(
                        resource_for_email.id,
                        resource_for_email.map_coordinates,
                        resource_for_email.name
                    )
                elif resource_for_email and resource_for_email.image_filename:
                     current_app.logger.info(f"Booking update {booking.id}: Resource image available but no map_coordinates for resource {resource_for_email.id}. No attachment image generated.")
                else:
                    current_app.logger.info(f"Booking update {booking.id}: No resource image or map_coordinates for resource {resource_for_email.id if resource_for_email else 'N/A'}. No attachment image generated.")


                html_email_body = render_template('email/booking_update_notification.html', **email_data)
                plain_text_body = (
                    f"Hello {email_data['user_name']},\n\n"
                    f"{email_data['update_summary']}\n\n"
                    f"New Booking Details:\n"
                    f"- Title: {email_data['booking_title']}\n"
                    f"- Resource: {email_data['resource_name']}\n"
                    f"- Date & Time: {email_data['start_time']} - {email_data['end_time']}\n"
                    f"- Location: {email_data['location']}\n"
                    f"- Floor: {email_data['floor']}\n\n"
                    f"Check-in URL (if applicable): {email_data['check_in_url']}\n\n"
                    f"Thank you!"
                )

                translated_update_subject_format = _("Booking Updated: %(resource_name)s - %(booking_title)s")
                update_subject = translated_update_subject_format % {'resource_name': email_data['resource_name'], 'booking_title': email_data['booking_title']}

                send_email(
                    to_address=current_user.email,
                    subject=update_subject,
                    body=plain_text_body,
                    html_body=html_email_body,
                    attachment_path=processed_image_path
                )
                current_app.logger.info(f"Booking update email initiated for booking {booking.id} to {current_user.email}.")

            except Exception as e_email:
                current_app.logger.error(f"Error sending update email for booking {booking.id} to {current_user.email}: {e_email}", exc_info=True)
        else:
            current_app.logger.warning(f"User {current_user.username} (booking {booking.id}) has no email address. Skipping update email.")


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
            # start_time and end_time are now naive venue local; for ISO format, client might expect UTC or offset.
            # For now, sending as is, assuming client will handle or it's for internal state.
            # To send as UTC ISO: booking.start_time.replace(tzinfo=timezone.utc).isoformat()
            # To send as venue local with offset: (booking.start_time.replace(tzinfo=pytz.timezone(venue_timezone_str)).isoformat())
            # This part depends on API contract, for now, keep it simple, adjust if client needs specific format.
            'start_time': (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(), # Convert back to UTC for client
            'end_time': (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),     # Convert back to UTC for client
            'title': booking.title,
            'booking_display_start_time': booking.booking_display_start_time.strftime('%H:%M') if booking.booking_display_start_time else None,
            'booking_display_end_time': booking.booking_display_end_time.strftime('%H:%M') if booking.booking_display_end_time else None
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
        original_booking_title = booking.title # Capture before deletion
        original_start_time = booking.start_time
        original_end_time = booking.end_time
        original_user_name = booking.user_name # Should be current_user.username
        original_resource_id = booking.resource_id

        if booking.resource_booked: # Check if backref is populated
            resource_name = booking.resource_booked.name
            resource_obj = booking.resource_booked # Keep a reference for floor map details

        booking_details_for_log = (
            f"Booking ID: {booking.id}, "
            f"Resource: {resource_name} (ID: {original_resource_id}), "
            f"Title: '{original_booking_title}', "
            f"Original User: '{original_user_name}', "
            f"Time: {original_start_time.isoformat()} to {original_end_time.isoformat()}"
        )

        # Store user email before booking object is potentially altered by deletion context
        user_email_for_cancellation = current_user.email


        db.session.delete(booking)
        db.session.commit()
        current_app.logger.info(f"Booking ID {booking_id} deleted from DB by user '{current_user.username}'.")


        # Send cancellation email to the user
        if user_email_for_cancellation:
            try:
                floor_map_location = "N/A"
                floor_map_floor = "N/A"
                floor_map_name = "N/A"
                # Try to get FloorMap details from the resource_obj captured earlier
                if resource_obj and resource_obj.floor_map_id:
                    floor_map = FloorMap.query.get(resource_obj.floor_map_id)
                    if floor_map:
                        floor_map_location = floor_map.location
                        floor_map_floor = floor_map.floor
                        floor_map_name = floor_map.name
                    else:
                        current_app.logger.warning(f"FloorMap {resource_obj.floor_map_id} not found for resource {resource_obj.id} during cancellation email prep for former booking {booking_id}.")

                email_data = {
                    'user_name': original_user_name,
                    'booking_title': original_booking_title,
                    'resource_name': resource_name,
                    'start_time': original_start_time.strftime('%Y-%m-%d %H:%M'),
                    'end_time': original_end_time.strftime('%Y-%m-%d %H:%M'),
                    'location': floor_map_location,
                    'floor': floor_map_floor,
                    'floor_map_name': floor_map_name
                }

                html_email_body = render_template('email/booking_cancellation_notification.html', **email_data)
                plain_text_body = (
                    f"Hello {email_data['user_name']},\n\n"
                    f"This email confirms that your booking for resource {email_data['resource_name']} has been cancelled.\n\n"
                    f"Cancelled Booking Details:\n"
                    f"- Title: {email_data['booking_title']}\n"
                    f"- Resource: {email_data['resource_name']}\n"
                    f"- Original Date & Time: {email_data['start_time']} - {email_data['end_time']}\n"
                    f"- Location: {email_data['location']}\n"
                    f"- Floor: {email_data['floor']}\n\n"
                    f"Thank you."
                )

                translated_subject_format = _("Booking Cancelled: %(resource_name)s - %(booking_title)s")
                subject=translated_subject_format % {'resource_name': email_data['resource_name'], 'booking_title': email_data['booking_title']}

                send_email(
                    to_address=user_email_for_cancellation,
                    subject=subject,
                    body=plain_text_body,
                    html_body=html_email_body
                    # No attachment for cancellation
                )
                current_app.logger.info(f"Booking cancellation email initiated for former booking {booking_id} to {user_email_for_cancellation}.")

            except Exception as e_email:
                current_app.logger.error(f"Error sending cancellation email for former booking {booking_id} to {user_email_for_cancellation}: {e_email}", exc_info=True)
        else:
            current_app.logger.warning(f"User {original_user_name} (former booking {booking_id}) has no email address. Skipping cancellation email.")

        # Existing Teams notification can remain if desired
        if current_user.email: # This uses current_user.email, which should be same as user_email_for_cancellation
            send_teams_notification(
                current_user.email,
                "Booking Cancelled",
                f"Your booking for {resource_name} starting at {original_start_time.strftime('%Y-%m-%d %H:%M')} has been cancelled."
            )

        # Notify next user on waitlist, if any
        # This logic should use original_resource_id
        next_entry = (
            WaitlistEntry.query.filter_by(resource_id=original_resource_id) # Use original_resource_id
            .order_by(WaitlistEntry.timestamp.asc())
            .first()
        )
        if next_entry:
            user_to_notify = User.query.get(next_entry.user_id)
            # Resource name for waitlist notification should be the same 'resource_name' as used above
            db.session.delete(next_entry)
            # It's better to commit waitlist changes separately or ensure the main transaction is robust.
            # For now, let's assume it will be committed.
            db.session.commit() # Commit deletion of waitlist entry
            current_app.logger.info(f"Removed user {next_entry.user_id} from waitlist for resource {original_resource_id} after booking {booking_id} cancellation.")
            if user_to_notify and user_to_notify.email: # Check email exists
                try:
                    # For waitlist, a simpler email without image might be fine.
                    # Or generate a generic image for the resource if desired.
                    waitlist_email_data = {
                        'user_name': user_to_notify.username,
                        'resource_name': resource_name, # Name of the resource that became available
                        'notification_message': f"A slot for the resource '{resource_name}' that you were waitlisted for has become available. Please try booking it again if you are still interested."
                    }
                    # Using booking_confirmation as a generic template here, ideally a dedicated waitlist_notification.html
                    html_waitlist_body = render_template('email/booking_confirmation.html', # Consider a specific template
                                                        user_name=user_to_notify.username,
                                                        booking_title=f"Slot Available for {resource_name}",
                                                        resource_name=resource_name,
                                                        start_time="N/A (Slot now open)", # Specific times not relevant for waitlist notification
                                                        end_time="",
                                                        location=floor_map_location if 'floor_map_location' in locals() else "N/A", # Use details if available
                                                        floor=floor_map_floor if 'floor_map_floor' in locals() else "N/A",
                                                        booking_confirmation_message=waitlist_email_data['notification_message']
                                                        )
                    plain_waitlist_body = f"Hello {user_to_notify.username},\n\n{waitlist_email_data['notification_message']}\n\nThank you."

                    send_email(
                        to_address=user_to_notify.email,
                        subject=f"Slot Available: {resource_name}",
                        body=plain_waitlist_body,
                        html_body=html_waitlist_body
                    )
                    current_app.logger.info(f"Sent waitlist availability email to {user_to_notify.email} for resource {resource_name}.")

                    # Optional: Send Teams notification for waitlist as well
                    send_teams_notification(
                        user_to_notify.email,
                        "Waitlist Slot Released",
                        f"A slot for {resource_name} that you were waitlisted for is now available to book."
                    )
                except Exception as e_waitlist_email:
                    current_app.logger.error(f"Error sending waitlist notification email to {user_to_notify.email} for resource {resource_name}: {e_waitlist_email}", exc_info=True)
            elif user_to_notify:
                current_app.logger.warning(f"User {user_to_notify.username} (ID: {user_to_notify.id}) on waitlist for resource {original_resource_id} has no email. Skipping email notification.")


        add_audit_log(
            action="CANCEL_BOOKING_USER",
            details=f"User '{current_user.username}' cancelled their booking. {booking_details_for_log}"
        )
        # Assuming socketio is imported
        socketio.emit('booking_updated', {'action': 'deleted', 'booking_id': booking_id, 'resource_id': original_resource_id}) # Use original_resource_id
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

        if booking.checked_in_at: # checked_in_at is naive UTC
            current_app.logger.info(f"User {current_user.username} attempt to check-in to already checked-in booking {booking_id} at {booking.checked_in_at.isoformat()} UTC")
            return jsonify({'message': 'Already checked in.', 'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat()}), 200

        booking_settings = BookingSettings.query.first()
        check_in_minutes_before = 15
        check_in_minutes_after = 15
        past_booking_adjustment_hours = 0
        allow_check_in_without_pin_setting = True
        # current_offset_hours is not strictly needed here if checked_in_at stores naive local "now",
        # but fetching for consistency or if other conversions were added later.
        # current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0


        if booking_settings:
            check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings.check_in_minutes_before is not None else 15
            check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings.check_in_minutes_after is not None else 15
            past_booking_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings.past_booking_time_adjustment_hours is not None else 0
            if hasattr(booking_settings, 'allow_check_in_without_pin'):
                allow_check_in_without_pin_setting = booking_settings.allow_check_in_without_pin
        else:
            current_app.logger.warning(f"BookingSettings not found for check_in_booking {booking_id}, using defaults.")

        effective_now_aware = get_current_effective_time()
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None)

        booking_start_local_naive = booking.start_time # Naive venue local
        effective_check_in_base_time_local_naive = booking_start_local_naive + timedelta(hours=past_booking_adjustment_hours)
        check_in_window_start_local_naive = effective_check_in_base_time_local_naive - timedelta(minutes=check_in_minutes_before)
        check_in_window_end_local_naive = effective_check_in_base_time_local_naive + timedelta(minutes=check_in_minutes_after)

        if not (check_in_window_start_local_naive <= effective_now_local_naive <= check_in_window_end_local_naive):
            current_app.logger.warning(f"User {current_user.username} check-in attempt for booking {booking_id} outside of allowed window. Booking start (local): {booking_start_local_naive.isoformat()}, Effective base (local): {effective_check_in_base_time_local_naive.isoformat()}, Window (local): {check_in_window_start_local_naive.isoformat()} to {check_in_window_end_local_naive.isoformat()}, Current time (local naive): {effective_now_local_naive.isoformat()}")
            return jsonify({'error': f'Check-in is only allowed from {check_in_minutes_before} minutes before to {check_in_minutes_after} minutes after the effective booking start time (considering adjustments).'}), 403

        resource = booking.resource_booked
        if not resource:
            current_app.logger.error(f"Resource not found for booking {booking_id} during check-in attempt by {current_user.username}.")
            return jsonify({'error': 'Associated resource not found for this booking.'}), 500

        if not allow_check_in_without_pin_setting:
            # PIN is enforced by global setting
            resource_has_active_pin = ResourcePIN.query.filter_by(resource_id=resource.id, is_active=True).first() is not None

            if resource_has_active_pin and not provided_pin:
                current_app.logger.warning(f"User {current_user.username} check-in attempt for booking {booking_id} without PIN, but resource {resource.id} requires one and global setting enforces PINs.")
                add_audit_log(action="CHECK_IN_FAILED_PIN_REQUIRED", user_id=current_user.id, username=current_user.username, details=f"Booking ID {booking_id}, Resource ID {resource.id}. PIN required but not provided.")
                return jsonify({'error': 'A PIN is required for this resource and check-in method.'}), 403 # PIN required but not provided

            if provided_pin: # If a PIN was provided, it must be validated (even if resource_has_active_pin was false, this implies an attempt to use a PIN)
                active_pin_match = ResourcePIN.query.filter_by(
                    resource_id=resource.id,
                    pin_value=provided_pin,
                    is_active=True
                ).first()
                if not active_pin_match:
                    current_app.logger.warning(f"User {current_user.username} failed PIN check-in for booking {booking_id}. Invalid PIN: {provided_pin} for resource {resource.id} (Global PIN enforcement).")
                    add_audit_log(action="CHECK_IN_FAILED_INVALID_PIN", user_id=current_user.id, username=current_user.username, details=f"Booking ID {booking_id}, Resource ID {resource.id}, Attempted PIN: {provided_pin}")
                    return jsonify({'error': 'Invalid or inactive PIN provided.'}), 403
                current_app.logger.info(f"User {current_user.username} provided valid PIN {provided_pin} for check-in to booking {booking_id} for resource {resource.id} (Global PIN enforcement).")
            # If resource does not have an active PIN, and no PIN was provided, it's allowed to proceed here.

        # If allow_check_in_without_pin_setting is True, we bypass all the above PIN checks.

        booking.checked_in_at = effective_now_local_naive # Store naive local "now"
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        audit_details = f"User '{current_user.username}' checked into booking ID {booking.id} for resource '{resource_name}'."
        if provided_pin:
            audit_details += f" Using PIN."
        add_audit_log(action="CHECK_IN_SUCCESS", details=audit_details)

        socketio.emit('booking_updated', {'action': 'checked_in', 'booking_id': booking.id, 'checked_in_at': effective_now_aware.isoformat(), 'resource_id': booking.resource_id})
        current_app.logger.info(f"User '{current_user.username}' successfully checked into booking ID: {booking_id} at {effective_now_aware.isoformat()}{' using PIN' if provided_pin else ''}.")

        # Send Email Notification for Check-in
        user = User.query.filter_by(username=booking.user_name).first()
        resource_details = Resource.query.get(booking.resource_id) # Renamed to avoid conflict

        current_app.logger.info(f"Preparing to send check-in email for booking ID {booking.id} to user {booking.user_name}.")
        if not user: # Added check for user object itself
            current_app.logger.warning(f"User object not found for username {booking.user_name}. Skipping check-in email for booking {booking.id}.")
        elif not user.email:
            current_app.logger.warning(f"User {user.username} (ID: {user.id}) does not have an email address. Skipping check-in email for booking {booking.id}.")
        elif not resource_details: # Added check for resource_details
            current_app.logger.warning(f"Resource {booking.resource_id} not found. Skipping check-in email for booking {booking.id}.")
        else:
            try:
                floor_map_location = "N/A"
                floor_map_floor = "N/A"
                if resource_details.floor_map_id:
                    floor_map = FloorMap.query.get(resource_details.floor_map_id)
                    if floor_map:
                        floor_map_location = floor_map.location
                        floor_map_floor = floor_map.floor
                    else:
                        current_app.logger.warning(f"FloorMap {resource_details.floor_map_id} not found for resource {resource_details.id} during check-in email prep for booking {booking.id}.")

                # booking.checked_in_at is naive local. For display in UTC as per existing format:
                # Convert naive local checked_in_at to aware UTC for email.
                # However, emails should ideally show local time. For now, let's keep UTC as per existing format.
                # If current_offset_hours was fetched:
                # checked_in_at_utc_for_email = (booking.checked_in_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)
                # For now, if booking.checked_in_at is effective_now_local_naive, then to get UTC:
                checked_in_at_utc_for_email = (effective_now_local_naive - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc) if hasattr(booking_settings, 'global_time_offset_hours') else booking.checked_in_at.replace(tzinfo=timezone.utc)


                email_data = {
                    'user_name': user.username,
                    'booking_title': booking.title,
                    'resource_name': resource_details.name,
                    'start_time': booking.start_time.strftime('%Y-%m-%d %H:%M'), # Naive local, correct for email
                    'end_time': booking.end_time.strftime('%Y-%m-%d %H:%M'),     # Naive local, correct for email
                    'checked_in_at_time': checked_in_at_utc_for_email.strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'location': floor_map_location,
                    'floor': floor_map_floor,
                }

                subject = f"Check-in Confirmed: {email_data['resource_name']} - {email_data['booking_title']}"
                current_app.logger.info(f"Attempting to send check-in email to {user.email} for booking {booking.id}. Subject: {subject}")

                html_body = render_template('email/check_in_confirmation.html', **email_data)
                # Basic plain text version
                body = (
                    f"Dear {email_data['user_name']},\n\n"
                    f"You have successfully checked in for your booking.\n\n"
                    f"Booking Details:\n"
                    f"- Resource: {email_data['resource_name']}\n"
                    f"- Title: {email_data['booking_title']}\n"
                    f"- Original Start Time: {email_data['start_time']}\n"
                    f"- Original End Time: {email_data['end_time']}\n"
                    f"- Actual Check-in Time: {email_data['checked_in_at_time']}\n"
                    f"- Location: {email_data['location']}\n"
                    f"- Floor: {email_data['floor']}\n\n"
                    f"Thank you for using our booking system!"
                )

                send_email(
                    to_address=user.email,
                    subject=subject,
                    html_body=html_body,
                    body=body
                )
                current_app.logger.info(f"Check-in email for booking {booking.id} to {user.email} initiated successfully.")
            except Exception as e_email:
                # Ensure user.email is available for logging, might need to fetch user again if not available in this scope for some reason
                user_email_for_log = user.email if user and hasattr(user, 'email') else "unknown_email"
                current_app.logger.error(f"Error sending check-in email for booking {booking.id} to {user_email_for_log}: {e_email}", exc_info=True)
        # End of Email Notification Logic

        if current_user.email: # Existing Teams notification
            send_teams_notification(
                current_user.email,
                "Booking Checked In",
                f"You have successfully checked into your booking for {resource_name} at {effective_now_aware.strftime('%Y-%m-%d %H:%M')}." # Use aware time for notification
            )

        return jsonify({
            'message': 'Check-in successful.',
            'checked_in_at': effective_now_aware.isoformat(), # Send aware UTC time
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

        if booking.checked_out_at: # checked_out_at is naive UTC
            current_app.logger.info(f"User {current_user.username} attempt to check-out of already checked-out booking {booking_id} at {booking.checked_out_at.isoformat()} UTC")
            return jsonify({'message': 'Already checked out.', 'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat()}), 200

        effective_now_aware = get_current_effective_time()
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive local "now"

        booking_settings = BookingSettings.query.first() # For offset, if needed for email formatting
        current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0


        booking.checked_out_at = effective_now_local_naive # Store naive local "now"
        booking.status = 'completed'
        # Optional: Adjust booking end_time to effective_now_local_naive if an early check-out should free up the resource.
        # booking.end_time = effective_now_local_naive
        db.session.commit()

        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        add_audit_log(action="CHECK_OUT_SUCCESS", details=f"User '{current_user.username}' checked out of booking ID {booking.id} for resource '{resource_name}'. Status set to completed.")
        socketio.emit('booking_updated', {'action': 'checked_out', 'booking_id': booking.id, 'checked_out_at': effective_now_aware.isoformat(), 'resource_id': booking.resource_id, 'status': 'completed'})
        current_app.logger.info(f"User '{current_user.username}' successfully checked out of booking ID: {booking_id} at {effective_now_aware.isoformat()}. Status set to completed.")

        # Send Email Notification for Check-out
        user = User.query.filter_by(username=booking.user_name).first()
        resource_details = Resource.query.get(booking.resource_id) # Renamed

        current_app.logger.info(f"Preparing to send check-out email for booking ID {booking.id} to user {booking.user_name}.")
        if not user: # Added check for user object itself
            current_app.logger.warning(f"User object not found for username {booking.user_name}. Skipping check-out email for booking {booking.id}.")
        elif not user.email:
            current_app.logger.warning(f"User {user.username} (ID: {user.id}) does not have an email address. Skipping check-out email for booking {booking.id}.")
        elif not resource_details: # Added check for resource_details
            current_app.logger.warning(f"Resource {booking.resource_id} not found. Skipping check-out email for booking {booking.id}.")
        else:
            try:
                floor_map_location = "N/A"
                floor_map_floor = "N/A"
                if resource_details.floor_map_id:
                    floor_map = FloorMap.query.get(resource_details.floor_map_id)
                    if floor_map:
                        floor_map_location = floor_map.location
                        floor_map_floor = floor_map.floor
                    else:
                        current_app.logger.warning(f"FloorMap {resource_details.floor_map_id} not found for resource {resource_details.id} during check-out email prep for booking {booking.id}.")

                # booking.checked_out_at is naive local. For display in UTC as per existing format:
                # Convert naive local checked_out_at to aware UTC for email.
                checked_out_at_utc_for_email = (booking.checked_out_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc) if hasattr(booking_settings, 'global_time_offset_hours') else booking.checked_out_at.replace(tzinfo=timezone.utc)

                email_data = {
                    'user_name': user.username,
                    'booking_title': booking.title,
                    'resource_name': resource_details.name,
                    'start_time': booking.start_time.strftime('%Y-%m-%d %H:%M'), # Naive local, correct for email
                    'end_time': booking.end_time.strftime('%Y-%m-%d %H:%M'),     # Naive local, correct for email
                    'checked_out_at_time': checked_out_at_utc_for_email.strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'location': floor_map_location,
                    'floor': floor_map_floor,
                }

                subject = f"Check-out Confirmed: {email_data['resource_name']} - {email_data['booking_title']}"
                current_app.logger.info(f"Attempting to send check-out email to {user.email} for booking {booking.id}. Subject: {subject}")

                html_body = render_template('email/check_out_confirmation.html', **email_data)
                # Basic plain text version
                body = (
                    f"Dear {email_data['user_name']},\n\n"
                    f"You have successfully checked out from your booking.\n\n"
                    f"Booking Details:\n"
                    f"- Resource: {email_data['resource_name']}\n"
                    f"- Title: {email_data['booking_title']}\n"
                    f"- Original Start Time: {email_data['start_time']}\n"
                    f"- Original End Time: {email_data['end_time']}\n"
                    f"- Actual Check-out Time: {email_data['checked_out_at_time']}\n"
                    f"- Location: {email_data['location']}\n"
                    f"- Floor: {email_data['floor']}\n\n"
                    f"Thank you for using our booking system!"
                )

                send_email(
                    to_address=user.email,
                    subject=subject,
                    html_body=html_body,
                    body=body
                )
                current_app.logger.info(f"Check-out email for booking {booking.id} to {user.email} initiated successfully.")
            except Exception as e_email:
                user_email_for_log = user.email if user and hasattr(user, 'email') else "unknown_email"
                current_app.logger.error(f"Error sending check-out email for booking {booking.id} to {user_email_for_log}: {e_email}", exc_info=True)
        # End of Email Notification Logic

        if current_user.email: # Existing Teams notification
             send_teams_notification(
                current_user.email,
                "Booking Checked Out",
                f"You have successfully checked out of your booking for {resource_name} at {effective_now_aware.strftime('%Y-%m-%d %H:%M')}." # Use aware time
            )

        return jsonify({
            'message': 'Check-out successful.',
            'checked_out_at': effective_now_aware.isoformat(), # Send aware UTC time
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

    effective_now_aware = get_current_effective_time() # Aware
    effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive local

    # booking.check_in_token_expires_at is naive UTC
    aware_utc_token_expiry = None
    if booking.check_in_token_expires_at:
        aware_utc_token_expiry = booking.check_in_token_expires_at.replace(tzinfo=timezone.utc)

    if aware_utc_token_expiry is None or aware_utc_token_expiry < effective_now_aware:
        current_app.logger.warning(f"QR Check-in attempt with expired token ID {token} for booking {booking.id}. Token expiry (UTC): {aware_utc_token_expiry.isoformat() if aware_utc_token_expiry else 'None'}, Now (aware): {effective_now_aware.isoformat()}")
        booking.check_in_token = None # Invalidate token
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
    check_in_minutes_before = 15
    check_in_minutes_after = 15
    past_booking_adjustment_hours = 0
    current_offset_hours = 0 # For converting booking start_time to UTC for JSON response
    if booking_settings:
        check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings.check_in_minutes_before is not None else 15
        check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings.check_in_minutes_after is not None else 15
        past_booking_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings.past_booking_time_adjustment_hours is not None else 0
        current_offset_hours = booking_settings.global_time_offset_hours if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0
    else:
        current_app.logger.warning(f"BookingSettings not found for qr_check_in booking {booking.id}, using defaults.")

    booking_start_local_naive = booking.start_time # Naive venue local
    effective_check_in_base_time_local_naive = booking_start_local_naive + timedelta(hours=past_booking_adjustment_hours)
    check_in_window_start_local_naive = effective_check_in_base_time_local_naive - timedelta(minutes=check_in_minutes_before)
    check_in_window_end_local_naive = effective_check_in_base_time_local_naive + timedelta(minutes=check_in_minutes_after)

    if not (check_in_window_start_local_naive <= effective_now_local_naive <= check_in_window_end_local_naive):
        current_app.logger.warning(f"QR Check-in for booking {booking.id} (token {token}) outside allowed window. Booking Start (local): {booking_start_local_naive.isoformat()}, Effective Base (local): {effective_check_in_base_time_local_naive.isoformat()}, Window (local): {check_in_window_start_local_naive.isoformat()} to {check_in_window_end_local_naive.isoformat()}, Now (local naive): {effective_now_local_naive.isoformat()}")
        return jsonify({'error': f'Check-in is only allowed from {check_in_minutes_before} minutes before to {check_in_minutes_after} minutes after the effective booking start time (considering adjustments). (Current time: {effective_now_aware.strftime("%H:%M:%S %Z")}, Effective start (local): {effective_check_in_base_time_local_naive.strftime("%H:%M:%S")})'}), 403

    try:
        booking.checked_in_at = effective_now_local_naive # Store naive local "now"
        booking.check_in_token = None
        booking.check_in_token_expires_at = None
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
                'checked_in_at': effective_now_aware.isoformat(),
                'resource_id': booking.resource_id
            })
        current_app.logger.info(f"Booking {booking.id} successfully checked in via QR token {token} by user {booking.user_name}")

        return jsonify({
            'message': 'Check-in successful!',
            'resource_name': resource_name,
            'booking_title': booking.title,
            'user_name': booking.user_name,
            'start_time': (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(), # Convert to UTC ISO
            'checked_in_at': effective_now_aware.isoformat()
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
    requires_login = True # Default
    check_in_minutes_before = 15
    check_in_minutes_after = 15
    past_booking_adjustment_hours = 0
    allow_check_in_without_pin_setting = True
    # current_offset_hours is not directly used here unless for converting something to UTC for display/logic not present
    # current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0


    if not booking_settings:
        logger.error("BookingSettings not found in DB! Using default values for PIN check-in.")
    else:
        requires_login = booking_settings.resource_checkin_url_requires_login
        check_in_minutes_before = booking_settings.check_in_minutes_before if booking_settings.check_in_minutes_before is not None else 15
        check_in_minutes_after = booking_settings.check_in_minutes_after if booking_settings.check_in_minutes_after is not None else 15
        past_booking_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings.past_booking_time_adjustment_hours is not None else 0
        if hasattr(booking_settings, 'allow_check_in_without_pin'):
            allow_check_in_without_pin_setting = booking_settings.allow_check_in_without_pin

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
    effective_now_aware = get_current_effective_time()
    effective_now_local_naive = effective_now_aware.replace(tzinfo=None)

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
        booking_start_local_naive = b.start_time # Naive venue local
        effective_check_in_base_time_local_naive = booking_start_local_naive + timedelta(hours=past_booking_adjustment_hours)
        check_in_window_start_local_naive = effective_check_in_base_time_local_naive - timedelta(minutes=check_in_minutes_before)
        check_in_window_end_local_naive = effective_check_in_base_time_local_naive + timedelta(minutes=check_in_minutes_after)

        if check_in_window_start_local_naive <= effective_now_local_naive <= check_in_window_end_local_naive:
            target_booking = b
            break

    if not target_booking:
        user_identifier_for_log = current_user.username if current_user.is_authenticated else "anonymous/public"
        logger.warning(f"PIN check-in for resource {resource_id} (PIN: {pin_value}): No active booking found within adjusted check-in window for user '{user_identifier_for_log}'. Window based on effective start after adjustment. Current effective time (local naive): {effective_now_local_naive.isoformat()}")
        return render_template('check_in_status_public.html', message=_('No active booking found for this resource within the check-in window for your session.'), status='error'), 404

    if target_booking.checked_in_at: # This is naive UTC, convert to local for display if needed, or display as UTC.
        logger.info(f"PIN check-in attempt for already checked-in booking {target_booking.id} (Resource {resource_id}, PIN {pin_value}).")
        # checked_in_at is stored as naive local "now", so strftime will format it as local.
        # If it were naive UTC, it would be target_booking.checked_in_at.replace(tzinfo=timezone.utc).strftime(...)
        # or converted to local then strftime.
        # Since it's now stored as naive local, direct strftime is fine for local display.
        # For consistency with UTC display in emails, convert:
        checked_in_at_utc_display = (target_booking.checked_in_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if hasattr(booking_settings, 'global_time_offset_hours') else target_booking.checked_in_at.strftime('%Y-%m-%d %H:%M:%S Local')

        booking_details = {
            'title': target_booking.title,
            'resource_name': resource.name,
            'user_name': target_booking.user_name,
            'checked_in_at_formatted': checked_in_at_utc_display
        }
        return render_template('check_in_status_public.html',
                               message=_('This booking has already been checked in.'),
                               status='success',
                               booking_details=booking_details), 200

    # Perform Check-in
    try:
        target_booking.checked_in_at = effective_now_local_naive # Store naive local "now"
        # Optional: Deactivate PIN if single-use
        # verified_pin.is_active = False
        db.session.commit()

        user_identifier_for_audit = current_user.username if current_user.is_authenticated else f"PIN_USER_({verified_pin.id})"
        add_audit_log(action="CHECK_IN_VIA_RESOURCE_URL", # Changed action name for clarity vs direct user check-in
                      details=f"User '{user_identifier_for_audit}' checked into booking ID {target_booking.id} for resource '{resource.name}' using PIN {verified_pin.pin_value}.",
                      user_id=current_user.id if current_user.is_authenticated else None)

        logger.info(f"Successfully checked in booking ID {target_booking.id} for resource {resource.id} using PIN {pin_value}. Checked in at {effective_now_local_naive.isoformat()} local.")

        # For display, format the naive local checked_in_at time.
        # Or convert to UTC for display if that's the standard.
        checked_in_at_utc_display_success = (target_booking.checked_in_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if hasattr(booking_settings, 'global_time_offset_hours') else target_booking.checked_in_at.strftime('%Y-%m-%d %H:%M:%S Local')

        booking_details_success = {
            'title': target_booking.title,
            'resource_name': resource.name,
            'user_name': target_booking.user_name,
            'checked_in_at_formatted': checked_in_at_utc_display_success
        }
        return render_template('check_in_status_public.html',
                               message=_('Check-in successful!'),
                               status='success',
                               booking_details=booking_details_success), 200

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error during PIN check-in for booking {target_booking.id} (Resource {resource_id}, PIN {pin_value}):")
        return render_template('check_in_status_public.html', message=_('Failed to process PIN check-in due to a server error.'), status='error'), 500
