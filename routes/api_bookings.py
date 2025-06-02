from flask import Blueprint, jsonify, request, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from datetime import datetime, timedelta, timezone, time

# Local imports
# Assuming extensions.py contains db, socketio, mail
from ..extensions import db, socketio, mail
# Assuming models.py contains these model definitions
from ..models import Booking, Resource, User, WaitlistEntry
# Assuming utils.py contains these helper functions
from ..utils import add_audit_log, parse_simple_rrule, send_email, send_slack_notification, send_teams_notification
# Assuming auth.py contains permission_required decorator
from ..auth import permission_required

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

    if occurrences:
        first_occ_start, first_occ_end = occurrences[0]
        first_slot_user_conflict = Booking.query.filter(
            Booking.user_name == user_name_for_record,
            Booking.start_time < first_occ_end,
            Booking.end_time > first_occ_start
        ).first()

        if first_slot_user_conflict:
            conflicting_resource_name = first_slot_user_conflict.resource_booked.name if first_slot_user_conflict.resource_booked else "an unknown resource"
            return jsonify({'error': f"You already have a booking for resource '{conflicting_resource_name}' from {first_slot_user_conflict.start_time.strftime('%H:%M')} to {first_slot_user_conflict.end_time.strftime('%H:%M')} that overlaps with the requested time slot on {first_occ_start.strftime('%Y-%m-%d')}."}), 409

    for occ_start, occ_end in occurrences:
        conflicting = Booking.query.filter(
            Booking.resource_id == resource_id,
            Booking.start_time < occ_end,
            Booking.end_time > occ_start
        ).first()
        if conflicting:
            existing_waitlist_count = WaitlistEntry.query.filter_by(resource_id=resource_id).count()
            if existing_waitlist_count < 2:
                waitlist_entry = WaitlistEntry(resource_id=resource_id, user_id=current_user.id)
                db.session.add(waitlist_entry)
                current_app.logger.info(f"Added user {current_user.id} to waitlist for resource {resource_id} due to conflict with booking {conflicting.id}")
            return jsonify({'error': f"This time slot ({occ_start.strftime('%Y-%m-%d %H:%M')} to {occ_end.strftime('%Y-%m-%d %H:%M')}) on resource '{resource.name}' is already booked or conflicts. You may have been added to the waitlist if available."}), 409

        user_conflicting_recurring = Booking.query.filter(
            Booking.user_name == user_name_for_record,
            Booking.resource_id != resource_id,
            Booking.start_time < occ_end,
            Booking.end_time > occ_start
        ).first()

        if user_conflicting_recurring:
            conflicting_resource_name = user_conflicting_recurring.resource_booked.name if user_conflicting_recurring.resource_booked else "an unknown resource"
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
            db.session.commit() # Commit each booking to get ID for audit log and socketio
            created_bookings.append(new_booking)
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
        current_app.logger.exception(f"Error creating booking for resource {resource_id} by {current_user.username}:")
        add_audit_log(action="CREATE_BOOKING_FAILED", details=f"Failed to create booking for resource ID {resource_id} by user '{current_user.username}'. Error: {str(e)}")
        return jsonify({'error': 'Failed to create booking due to a server error.'}), 500

@api_bookings_bp.route('/bookings/my_bookings', methods=['GET'])
@login_required
def get_my_bookings():
    """
    Fetches all bookings for the currently authenticated user.
    Orders bookings by start_time descending (most recent/upcoming first).
    """
    try:
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
                'recurrence_rule': booking.recurrence_rule,
                'checked_in_at': booking.checked_in_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in
            })

        current_app.logger.info(f"User '{current_user.username}' fetched their bookings. Count: {len(bookings_list)}")
        return jsonify(bookings_list), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching bookings for user '{current_user.username}':")
        return jsonify({'error': 'Failed to fetch your bookings due to a server error.'}), 500
