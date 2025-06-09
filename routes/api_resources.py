import os
import json
from datetime import datetime, date, time, timedelta, timezone
from flask import Blueprint, jsonify, request, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
import secrets # For PIN generation
import string # For PIN generation

# Assuming db is initialized in extensions.py
from extensions import db
# Assuming models are defined in models.py
from models import User, Resource, Booking, FloorMap, Role, ResourcePIN, BookingSettings # Added User, Role, ResourcePIN, BookingSettings
# Assuming utility functions are in utils.py
from utils import add_audit_log, resource_to_dict, allowed_file, _import_resource_configurations_data
# Assuming permission_required is in auth.py
from auth import permission_required

api_resources_bp = Blueprint('api_resources', __name__, url_prefix='/api')

@api_resources_bp.route('/resources', methods=['GET'])
def get_resources():
    logger = current_app.logger
    try:
        query = Resource.query.filter_by(status='published')
        capacity = request.args.get('capacity', type=int)
        if capacity is not None:
            query = query.filter(Resource.capacity >= capacity)
        equipment = request.args.get('equipment')
        if equipment:
            for item in [e.strip().lower() for e in equipment.split(',') if e.strip()]:
                query = query.filter(Resource.equipment.ilike(f'%{item}%'))
        tags = request.args.get('tags')
        if tags:
            for tag in [t.strip().lower() for t in tags.split(',') if t.strip()]:
                query = query.filter(Resource.tags.ilike(f'%{tag}%'))

        resources_list = [resource_to_dict(r) for r in query.all()]
        logger.info("Successfully fetched published resources.")
        return jsonify(resources_list), 200
    except Exception as e:
        logger.exception("Error fetching resources:")
        return jsonify({'error': 'Failed to fetch resources due to a server error.'}), 500

@api_resources_bp.route('/resources/<int:resource_id>/availability', methods=['GET'])
def get_resource_availability(resource_id):
    logger = current_app.logger
    active_booking_statuses = ['approved', 'pending', 'checked_in', 'confirmed'] # Define active statuses

    date_str = request.args.get('date')
    target_date_obj = None
    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            logger.warning(f"Invalid date format provided: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        resource = Resource.query.get(resource_id)
        if not resource:
            logger.warning(f"Resource availability check for non-existent ID: {resource_id}")
            return jsonify({'error': 'Resource not found.'}), 404
        if resource.is_under_maintenance and (resource.maintenance_until is None or target_date_obj <= resource.maintenance_until.date()):
            until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else 'until further notice'
            return jsonify({'error': f'Resource under maintenance until {until_str}.'}), 403

        bookings_on_date = Booking.query.filter(
            Booking.resource_id == resource_id,
            func.date(Booking.start_time) == target_date_obj,
            func.trim(func.lower(Booking.status)).in_(active_booking_statuses)
        ).all()
        booked_slots = []
        for booking in bookings_on_date:
            grace = current_app.config.get('CHECK_IN_GRACE_MINUTES', 15)
            now = datetime.now(timezone.utc)
            booking_start_time_aware = booking.start_time.replace(tzinfo=timezone.utc) if booking.start_time.tzinfo is None else booking.start_time
            can_check_in = (booking.checked_in_at is None and
                            booking_start_time_aware - timedelta(minutes=grace) <= now <= booking_start_time_aware + timedelta(minutes=grace))
            booked_slots.append({
                'title': booking.title, 'user_name': booking.user_name,
                'start_time': booking.start_time.strftime('%H:%M:%S'), 'end_time': booking.end_time.strftime('%H:%M:%S'),
                'booking_id': booking.id,
                'checked_in_at': booking.checked_in_at.isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.isoformat() if booking.checked_out_at else None,
                'can_check_in': can_check_in
            })
        return jsonify(booked_slots), 200
    except Exception as e:
        logger.exception(f"Error fetching availability for resource {resource_id} on {target_date_obj}:")
        return jsonify({'error': 'Failed to fetch resource availability due to a server error.'}), 500

@api_resources_bp.route('/resources/<int:resource_id>/available_slots', methods=['GET'])
@login_required
def get_resource_available_slots(resource_id):
    logger = current_app.logger
    date_str = request.args.get('date')
    if not date_str:
        logger.warning(f"Missing date for available_slots for resource ID: {resource_id}")
        return jsonify({'error': 'Date query parameter is required (YYYY-MM-DD).'}), 400
    try:
        target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        logger.warning(f"Invalid date format '{date_str}' for available_slots for ID: {resource_id}")
        return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    if resource.status != 'published': return jsonify({'error': f'Resource not available (status: {resource.status}).'}), 403
    if resource.is_under_maintenance and (resource.maintenance_until is None or target_date_obj <= resource.maintenance_until.date()):
        until_str = resource.maintenance_until.isoformat() if resource.maintenance_until else 'indefinitely'
        return jsonify({'error': f'Resource under maintenance until {until_str}. No slots available.'}), 403

    bookings_on_date = Booking.query.filter(Booking.resource_id == resource_id, func.date(Booking.start_time) == target_date_obj).all()
    available_slots = []
    slot_start_hour, slot_start_minute, slot_duration_minutes = 0, 0, 30
    while slot_start_hour < 24:
        slot_start_dt = datetime.combine(target_date_obj, time(slot_start_hour, slot_start_minute))
        slot_end_dt = slot_start_dt + timedelta(minutes=slot_duration_minutes)
        if slot_end_dt.date() > target_date_obj: break
        is_available = not any((slot_start_dt < b.end_time) and (slot_end_dt > b.start_time) for b in bookings_on_date)
        if is_available:
            available_slots.append({'start_time': slot_start_dt.strftime('%H:%M'), 'end_time': slot_end_dt.strftime('%H:%M')})
        new_minute = slot_start_minute + slot_duration_minutes
        slot_start_hour += new_minute // 60
        slot_start_minute = new_minute % 60
        if slot_start_hour >= 24: break
    logger.info(f"Generated {len(available_slots)} slots for resource {resource_id} on {date_str}.")
    return jsonify(available_slots), 200


@api_resources_bp.route('/resources/unavailable_dates', methods=['GET'])
@login_required
def get_unavailable_dates():
    logger = current_app.logger
    user_id_str = request.args.get("user_id")
    if not user_id_str:
        logger.warning("get_unavailable_dates: user_id missing")
        return jsonify({"error": "user_id is required"}), 400

    try:
        user_id = int(user_id_str)
    except ValueError:
        logger.warning(f"get_unavailable_dates: invalid user_id format '{user_id_str}'")
        return jsonify({"error": "user_id must be an integer"}), 400

    # Ensure the current user can view this information (e.g., is the user_id or an admin)
    # For now, let's assume only the user themselves or an admin with 'manage_bookings' can query.
    # This part needs to be adjusted based on actual permission requirements.
    # Assuming User model is imported: from models import User
    if not (current_user.id == user_id or current_user.has_permission('manage_bookings')):
        logger.warning(f"get_unavailable_dates: User {current_user.id} not authorized for user_id {user_id}")
        return jsonify({"error": "Not authorized"}), 403

    target_user = User.query.get(user_id)
    if not target_user:
        logger.info(f"get_unavailable_dates: User with id {user_id} not found.")
        return jsonify({"error": "User not found"}), 404

    try:
        unavailable_dates_set = set()
        now = datetime.now(timezone.utc) # Use timezone-aware datetime

        # Fetch booking settings
        booking_settings = BookingSettings.query.first()
        if not booking_settings:
            # Use default settings if none are configured
            booking_settings = BookingSettings(allow_past_bookings=False, past_booking_time_adjustment_hours=0)
            logger.info("get_unavailable_dates: No BookingSettings found, using defaults.")


        # Generate Date Range
        start_range_date = now.date().replace(day=1)
        month_offset = 2
        future_month_year = start_range_date.year
        future_month_month = start_range_date.month + month_offset
        if future_month_month > 12:
            future_month_year += (future_month_month - 1) // 12
            future_month_month = (future_month_month - 1) % 12 + 1

        next_future_month_year = future_month_year
        next_future_month_month = future_month_month + 1
        if next_future_month_month > 12:
            next_future_month_year += 1
            next_future_month_month = 1

        first_day_of_next_future_month = date(next_future_month_year, next_future_month_month, 1)
        end_range_date = first_day_of_next_future_month - timedelta(days=1)

        # Fetch all published resources once
        all_published_resources = Resource.query.filter_by(status='published').all()
        total_published_resources = len(all_published_resources) # Ensure this is defined

        if total_published_resources == 0:
            logger.info("get_unavailable_dates: No published resources available. Result will depend on past date rules.")

        # Define Standard Slots
        STANDARD_SLOTS = [{'start': time(8,0), 'end': time(12,0)}, {'start': time(13,0), 'end': time(17,0)}]

        # Loop through the generated date range
        current_iter_date = start_range_date
        while current_iter_date <= end_range_date:
            current_processing_date = current_iter_date

            # a. Past Date Check
            date_is_past = current_processing_date < now.date()
            if date_is_past:
                if not booking_settings.allow_past_bookings:
                    unavailable_dates_set.add(current_processing_date.strftime('%Y-%m-%d'))
                    logger.debug(f"Date {current_processing_date} is past and allow_past_bookings is false. Added to unavailable.")
                    current_iter_date += timedelta(days=1)
                    continue

                effective_cutoff = datetime.combine(current_processing_date + timedelta(days=1), time.min, tzinfo=timezone.utc) - timedelta(hours=booking_settings.past_booking_time_adjustment_hours)
                if now > effective_cutoff:
                    unavailable_dates_set.add(current_processing_date.strftime('%Y-%m-%d'))
                    logger.debug(f"Date {current_processing_date} is past. Now: {now}, Effective Cutoff: {effective_cutoff}. Added to unavailable.")
                    current_iter_date += timedelta(days=1)
                    continue

            # b. User's Existing Bookings for the Day (for conflict checking against other resources)
            user_bookings_on_this_date = Booking.query.filter(
                Booking.user_name == target_user.username,
                func.date(Booking.start_time) <= current_processing_date,
                func.date(Booking.end_time) >= current_processing_date,
                Booking.status.in_(['approved', 'pending', 'checked_in', 'confirmed'])
            ).all()

            # c. Check User's Booking Possibility
            any_slot_bookable_for_user_this_date = False
            active_resources_for_date = []
            # Corrected variable name here:
            for res_loop_item in all_published_resources:
                if not (res_loop_item.is_under_maintenance and (res_loop_item.maintenance_until is None or current_processing_date <= res_loop_item.maintenance_until.date())):
                    active_resources_for_date.append(res_loop_item)

            if not active_resources_for_date:
                if total_published_resources > 0 : # Use the defined total_published_resources
                    unavailable_dates_set.add(current_processing_date.strftime('%Y-%m-%d'))
                    logger.debug(f"No active resources (all under maintenance or none published) on {current_processing_date}. Added to unavailable.")
                else:
                    logger.debug(f"No published resources in system for date {current_processing_date}. Not marking as unavailable based on this rule.")
                current_iter_date += timedelta(days=1)
                continue

            for resource_to_check in active_resources_for_date:
                for slot_def in STANDARD_SLOTS:
                    # Ensure time objects are combined with current_processing_date and made timezone-aware for comparison
                    slot_start_dt = datetime.combine(current_processing_date, slot_def['start'])
                    slot_end_dt = datetime.combine(current_processing_date, slot_def['end'])
                    if slot_start_dt.tzinfo is None: slot_start_dt = slot_start_dt.replace(tzinfo=timezone.utc)
                    if slot_end_dt.tzinfo is None: slot_end_dt = slot_end_dt.replace(tzinfo=timezone.utc)


                    # Conflict Check 1: Resource Slot Generally Booked?
                    is_generally_booked = Booking.query.filter(
                        Booking.resource_id == resource_to_check.id,
                        Booking.start_time < slot_end_dt,
                        Booking.end_time > slot_start_dt,
                        Booking.status.in_(['approved', 'pending', 'checked_in', 'confirmed'])
                    ).first() is not None

                    if is_generally_booked:
                        logger.debug(f"Slot {slot_def['start']}-{slot_def['end']} on {resource_to_check.name} for {current_processing_date} is generally booked.")
                        continue # Next slot

                    # Conflict Check 2: User's Own Schedule Conflicts with this Potential Slot?
                    user_schedule_conflicts = False
                    for user_booking in user_bookings_on_this_date:
                        if user_booking.resource_id != resource_to_check.id:
                            user_booking_start_dt = user_booking.start_time.replace(tzinfo=timezone.utc) if user_booking.start_time.tzinfo is None else user_booking.start_time
                            user_booking_end_dt = user_booking.end_time.replace(tzinfo=timezone.utc) if user_booking.end_time.tzinfo is None else user_booking.end_time

                            if user_booking_start_dt < slot_end_dt and user_booking_end_dt > slot_start_dt:
                                user_schedule_conflicts = True
                                logger.debug(f"User {target_user.username} has conflict for slot {slot_def['start']}-{slot_def['end']} on {current_processing_date} due to booking ID {user_booking.id} on resource ID {user_booking.resource_id}.")
                                break

                    if user_schedule_conflicts:
                        continue # Next slot

                    any_slot_bookable_for_user_this_date = True
                    logger.debug(f"Found bookable slot for user {target_user.username} on {current_processing_date}: Resource {resource_to_check.name}, Slot {slot_def['start']}-{slot_def['end']}.")
                    break

                if any_slot_bookable_for_user_this_date:
                    break

            # d. Final Decision for the Date
            if not any_slot_bookable_for_user_this_date:
                unavailable_dates_set.add(current_processing_date.strftime('%Y-%m-%d'))
                logger.debug(f"Date {current_processing_date} determined unavailable for user {target_user.username} (no bookable standard slots found). Added to unavailable.")

            current_iter_date += timedelta(days=1)

        logger.info(f"Returning {len(unavailable_dates_set)} unavailable dates for user {user_id}.")
        return jsonify(sorted(list(unavailable_dates_set)))

    except Exception as e:
        logger.exception(f"Error in get_unavailable_dates for user_id {user_id_str}: {e}")
        return jsonify({"error": "An internal server error occurred while fetching unavailable dates."}), 500


@api_resources_bp.route('/admin/resources', methods=['GET'])
@login_required
@permission_required('manage_resources')
def get_all_resources_admin():
    logger = current_app.logger
    try:
        map_id_str = request.args.get('map_id')
        query = Resource.query

        if map_id_str:
            try:
                map_id = int(map_id_str)
                query = query.filter(Resource.floor_map_id == map_id)
            except ValueError:
                logger.warning(f"Invalid map_id format: {map_id_str}. Must be an integer.")
                return jsonify({'error': f"Invalid map_id format: '{map_id_str}'. Must be an integer."}), 400

        resources = query.all()
        resources_list = [resource_to_dict(r) for r in resources]
        return jsonify(resources_list), 200
    except Exception as e:
        logger.exception("Error fetching all resources for admin:")
        return jsonify({'error': 'Failed to fetch resources due to a server error.'}), 500

@api_resources_bp.route('/admin/resources', methods=['POST'])
@login_required
@permission_required('manage_resources')
def create_resource():
    logger = current_app.logger
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid input. JSON data expected.'}), 400
    name = data.get('name')
    if not name or not name.strip(): return jsonify({'error': 'Name is required.'}), 400
    name = name.strip() # Use stripped name from now on
    if Resource.query.filter(func.lower(Resource.name) == func.lower(name)).first():
        return jsonify({'error': f"Resource with name '{name}' already exists."}), 409

    capacity = data.get('capacity')
    try:
        if capacity is not None and str(capacity).strip() != "":
            capacity = int(capacity)
        else:
            capacity = None # Explicitly set to None if empty or only whitespace
    except (ValueError, TypeError): return jsonify({'error': 'Capacity must be an integer or null.'}), 400

    pin = data.get('current_pin', '').strip()
    current_pin_to_set = pin if pin else None

    new_resource = Resource(
        name=name,
        capacity=capacity,
        equipment=data.get('equipment'),
        tags=data.get('tags'),
        current_pin=current_pin_to_set
    )
    try:
        db.session.add(new_resource)
        db.session.commit()
        audit_details = f"Resource '{new_resource.name}' (ID: {new_resource.id}) created by {current_user.username}."
        if new_resource.current_pin:
            audit_details += " PIN set."
        add_audit_log(action="CREATE_RESOURCE", details=audit_details)
        return jsonify(resource_to_dict(new_resource)), 201
    except Exception as e:
        db.session.rollback()
        logger.exception("Error creating resource:")
        return jsonify({'error': 'Failed to create resource due to a server error.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>', methods=['GET'])
@login_required
@permission_required('manage_resources')
def get_resource_details_admin(resource_id):
    resource = Resource.query.get_or_404(resource_id) # Use get_or_404 for convenience
    resource_data = resource_to_dict(resource) # Assuming this helper serializes main resource fields

    # Fetch and serialize associated PINs
    pins_data = [{
        'id': pin.id,
        'pin_value': pin.pin_value,
        'is_active': pin.is_active,
        'created_at': pin.created_at.isoformat() if pin.created_at else None,
        'notes': pin.notes
    } for pin in resource.pins.order_by(ResourcePIN.created_at.desc()).all()]

    resource_data['pins'] = pins_data
    return jsonify(resource_data), 200

@api_resources_bp.route('/admin/resources/<int:resource_id>', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resource_details_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    old_pin = resource.current_pin
    pin_changed = False

    # Handle current_pin separately to manage audit logging for it specifically
    if 'current_pin' in data:
        new_pin_from_data = data.get('current_pin', '')
        # Ensure new_pin_from_data is treated as a string before stripping
        new_pin_stripped = str(new_pin_from_data).strip() if new_pin_from_data is not None else ''

        resource.current_pin = new_pin_stripped if new_pin_stripped else None
        if old_pin != resource.current_pin:
            pin_changed = True

    # Simplified field updates, add more validation as needed
    # Exclude 'current_pin' from this loop as it's handled above
    allowed_fields = ['name', 'capacity', 'equipment', 'status', 'tags', 'booking_restriction', 'allowed_user_ids', 'is_under_maintenance', 'maintenance_until', 'max_recurrence_count', 'scheduled_status', 'scheduled_status_at', 'floor_map_id', 'map_coordinates']
    for field in allowed_fields:
        if field in data:
            if field == 'capacity': # Special handling for capacity to allow null
                capacity_val = data.get('capacity')
                if capacity_val is not None and str(capacity_val).strip() != "":
                    try:
                        setattr(resource, field, int(capacity_val))
                    except (ValueError, TypeError):
                        return jsonify({'error': f"Capacity must be an integer or null. Invalid value: {capacity_val}"}), 400
                else:
                    setattr(resource, field, None) # Set to None if empty string or null
            elif field == 'map_coordinates':
                map_coords_payload = data[field] # data[field] is safe due to 'if field in data'
                if map_coords_payload is not None and isinstance(map_coords_payload, dict):
                    # Extract allowed_role_ids and remove it from the payload for map_coordinates
                    roles_list = map_coords_payload.pop('allowed_role_ids', None)

                    # Set map_allowed_role_ids
                    resource.map_allowed_role_ids = json.dumps(roles_list) if roles_list is not None else None

                    # Set map_coordinates with the remaining data (now without allowed_role_ids)
                    resource.map_coordinates = json.dumps(map_coords_payload)

                else: # Handles map_coords_payload being None or not a dict
                    resource.map_coordinates = None
                    resource.map_allowed_role_ids = None
            else: # For fields other than 'map_coordinates'
                setattr(resource, field, data[field])

    if 'role_ids' in data and isinstance(data['role_ids'], list):
        new_roles = [Role.query.get(r_id) for r_id in data['role_ids'] if Role.query.get(r_id)]
        resource.roles = new_roles

    try:
        db.session.commit()
        # Basic audit log for general update
        # More detailed logging for specific fields like 'status' or 'name' change could be added if needed
        add_audit_log(action="UPDATE_RESOURCE", details=f"Resource ID {resource.id} ('{resource.name}') general details updated by {current_user.username}.")

        if pin_changed:
            if resource.current_pin:
                add_audit_log(action="UPDATE_RESOURCE_PIN", details=f"Resource ID {resource.id} ('{resource.name}') PIN updated by {current_user.username}.")
            else:
                add_audit_log(action="CLEAR_RESOURCE_PIN", details=f"Resource ID {resource.id} ('{resource.name}') PIN cleared by {current_user.username}.")

        return jsonify(resource_to_dict(resource)), 200
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error updating resource {resource_id}:")
        return jsonify({'error': 'Failed to update resource due to a server error.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>', methods=['DELETE'])
@login_required
@permission_required('manage_resources')
def delete_resource_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    resource_name_for_log = resource.name
    try:
        if resource.image_filename:
            old_path = os.path.join(current_app.config['RESOURCE_UPLOAD_FOLDER'], resource.image_filename)
            if os.path.exists(old_path): os.remove(old_path)
        db.session.delete(resource) # Bookings cascade delete
        db.session.commit()
        add_audit_log(action="DELETE_RESOURCE", details=f"Resource ID {resource_id} ('{resource_name_for_log}') deleted by {current_user.username}.")
        return jsonify({'message': f"Resource '{resource_name_for_log}' deleted."}), 200
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting resource {resource_id}:")
        return jsonify({'error': 'Failed to delete resource due to a server error.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>/publish', methods=['POST'])
@login_required
@permission_required('manage_resources')
def publish_resource_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    if resource.status == 'published': return jsonify({'message': 'Resource already published.'}), 200
    if resource.status != 'draft': return jsonify({'error': f'Cannot publish from status: {resource.status}.'}), 400
    resource.status = 'published'
    resource.published_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
        add_audit_log(action="PUBLISH_RESOURCE", details=f"Resource {resource_id} ('{resource.name}') published by {current_user.username}.")
        return jsonify({'message': 'Resource published.', 'resource': resource_to_dict(resource)}), 200
    except Exception as e:
        db.session.rollback(); logger.exception(f"Error publishing resource {resource_id}:")
        return jsonify({'error': 'Failed to publish resource.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>/image', methods=['POST'])
@login_required
@permission_required('manage_resources')
def upload_resource_image_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    if 'resource_image' not in request.files: return jsonify({'error': 'No resource_image file part.'}), 400
    file = request.files['resource_image']
    if file.filename == '': return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename): # allowed_file needs ALLOWED_EXTENSIONS from config
        filename = secure_filename(file.filename)
        # Prevent filename collision if another resource uses it (optional, depends on desired behavior)
        # existing_by_filename = Resource.query.filter_by(image_filename=filename).first()
        # if existing_by_filename and existing_by_filename.id != resource_id:
        #     return jsonify({'error': 'A resource with this image filename already exists.'}), 409

        file_path = os.path.join(current_app.config['RESOURCE_UPLOAD_FOLDER'], filename)
        old_image_path = None
        if resource.image_filename and resource.image_filename != filename:
             old_image_path = os.path.join(current_app.config['RESOURCE_UPLOAD_FOLDER'], resource.image_filename)
        try:
            file.save(file_path)
            resource.image_filename = filename
            db.session.commit()
            if old_image_path and os.path.exists(old_image_path):
                os.remove(old_image_path)
            add_audit_log(action="UPLOAD_RESOURCE_IMAGE", details=f"Image for resource ID {resource.id} uploaded by {current_user.username}.")
            return jsonify({'message': 'Image uploaded.', 'image_url': url_for('static', filename=f'resource_uploads/{filename}')}), 200
        except Exception as e:
            db.session.rollback()
            if os.path.exists(file_path): os.remove(file_path) # Clean up if save failed
            logger.exception(f"Error uploading image for resource {resource_id}:")
            return jsonify({'error': 'Failed to upload image.'}), 500
    else:
        return jsonify({'error': 'File type not allowed.'}), 400

@api_resources_bp.route('/admin/resources/export', methods=['GET'])
@login_required
@permission_required('manage_resources')
def export_all_resources_admin():
    logger = current_app.logger
    try:
        resources_list = [resource_to_dict(r) for r in Resource.query.all()]
        response = jsonify(resources_list)
        response.headers['Content-Disposition'] = 'attachment; filename=resources_export.json'
        response.mimetype = 'application/json'
        add_audit_log(action="EXPORT_ALL_RESOURCES", details=f"User {current_user.username} exported all resources.")
        return response
    except Exception as e:
        logger.exception("Error exporting all resources:")
        return jsonify({'error': 'Failed to export resources.'}), 500

@api_resources_bp.route('/admin/resources/import', methods=['POST'])
@login_required
@permission_required('manage_resources')
def import_resources_admin():
    # This function relies on _import_resource_configurations_data from utils.py
    # which is already designed to handle the logic.
    # For simplicity, we'll call it directly if it's adapted for blueprint context or make a wrapper.
    # Assuming _import_resource_configurations_data is available via from utils import ...
    # _import_resource_configurations_data # Ensure it's imported # No longer needed here

    logger = current_app.logger
    if 'file' not in request.files: return jsonify({'error': 'No file part.'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'No selected file.'}), 400
    if not file.filename.endswith('.json'): return jsonify({'error': 'File must be JSON.'}), 400
    try:
        resources_data = json.load(file)
    except json.JSONDecodeError: return jsonify({'error': 'Invalid JSON.'}), 400
    if not isinstance(resources_data, list): return jsonify({'error': 'JSON must be a list.'}), 400

    # Pass db instance from extensions
    created, updated, errors = _import_resource_configurations_data(resources_data)

    summary = f"Import completed. Created: {created}, Updated: {updated}, Errors: {len(errors)}."
    add_audit_log(action="IMPORT_RESOURCES", details=f"User {current_user.username} imported resources. {summary} Errors: {errors}")
    if errors:
        return jsonify({'message': summary, 'created': created, 'updated': updated, 'errors': errors}), 207
    return jsonify({'message': summary, 'created': created, 'updated': updated}), 200


# Helper function for bulk updates
def _apply_resource_changes(resource: Resource, changes: dict, resource_errors: list, logger_instance, db_session):
    """
    Applies a set of changes to a single resource object.
    Validates data types and existence of related entities.
    Appends errors to resource_errors list.

    Args:
        resource: The Resource instance to update.
        changes (dict): A dictionary of field names to new values.
        resource_errors (list): A list to append error dictionaries to.
        logger_instance: The logger instance.
        db_session: The SQLAlchemy database session.

    Returns:
        bool: True if all applied changes were valid, False otherwise.
    """
    has_errored_on_field = False # This variable is part of the helper now

    # The main loop for iterating resource_ids and applying changes
    for resource_id_item in resource_ids: # Renamed to avoid conflict with outer resource_id
        current_resource_errors = [] # Errors specific to this resource_id
        resource_id_val = None # To store the validated int resource_id

        if not isinstance(resource_id_item, int):
            errors.append({'id': str(resource_id_item), 'error': 'Invalid resource ID type, must be integer.'})
            continue # Skip to the next resource_id

        resource_id_val = resource_id_item
        resource = Resource.query.get(resource_id_val)

        if not resource:
            errors.append({'id': resource_id_val, 'error': 'Resource not found.'})
            continue # Skip to the next resource_id

        # Call the helper to apply changes to this specific resource
        # Pass db.session for potential DB queries within the helper (e.g., validating Role IDs)
        if _apply_resource_changes(resource, changes_to_apply, current_resource_errors, logger, db.session):
            updated_ids.append(resource_id_val)
        else:
            # Add specific errors for this resource to the main errors list
            for err_detail in current_resource_errors:
                errors.append({
                    'id': resource_id_val,
                    'field': err_detail['field'],
                    'error': err_detail['error']
                })

    if updated_ids: # Only commit if there were successful updates prepped
        try:
            db.session.commit()
            logger.info(f"User {current_user.username} bulk updated resources. IDs successfully processed (pre-commit): {updated_ids}. Changes attempted: {changes_to_apply}. Errors for other resources: {errors}")
            add_audit_log(action="BULK_UPDATE_RESOURCES", details=f"User {current_user.username} bulk updated resources. IDs successfully updated: {updated_ids}. Changes applied: {changes_to_apply}. Errors during process: {errors}")
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error committing bulk resource update by {current_user.username}:")
            # Mark all intended updates as failed due to commit error
            commit_error_msg = f'Failed to commit changes due to server error: {str(e)}'
            for uid in updated_ids: # These were thought to be successful but failed at commit
                # Check if this ID already has other errors logged
                if not any(err.get('id') == uid and err.get('error') != commit_error_msg for err in errors):
                     # If not, or if existing errors are different, add/replace with commit error
                    # This logic can be refined to preserve original errors and add a general commit error
                    errors.append({'id': uid, 'error': commit_error_msg})
            updated_ids = [] # Reset as commit failed

    response_data = {'updated_count': len(updated_ids), 'updated_ids': updated_ids, 'errors': errors}
    status_code = 207 if errors else 200
    return jsonify(response_data), status_code

@api_resources_bp.route('/admin/resources/bulk', methods=['POST'])
@login_required
@permission_required('manage_resources')
def create_resources_bulk_admin():
    logger = current_app.logger
    data = request.get_json()
    # Basic validation, more can be added
    if not data or 'count' not in data : return jsonify({'error': 'Invalid input.'}), 400

    prefix = data.get('prefix', '')
    suffix = data.get('suffix', '')
    start = data.get('start', 1)
    count = data.get('count')
    padding = data.get('padding', 0)
    capacity = data.get('capacity')
    equipment = data.get('equipment')
    tags = data.get('tags')
    status = data.get('status', 'draft')

    created_resources = []
    skipped = []
    for i in range(int(count)):
        number_str = str(int(start) + i).zfill(int(padding))
        name = f"{prefix}{number_str}{suffix}"
        if Resource.query.filter(func.lower(Resource.name) == func.lower(name.strip())).first():
            skipped.append(name)
            continue
        r = Resource(name=name.strip(), capacity=capacity, equipment=equipment, status=status, tags=tags)
        db.session.add(r)
        created_resources.append(r)
    try:
        db.session.commit()
        add_audit_log(action="BULK_CREATE_RESOURCES", details=f"{len(created_resources)} resources created by {current_user.username}. Skipped: {len(skipped)}.")
        return jsonify({'created': [resource_to_dict(r) for r in created_resources], 'skipped': skipped}), 201
    except Exception as e:
        db.session.rollback(); logger.exception("Error bulk creating resources:")
        return jsonify({'error': 'Server error during bulk create.'}), 500

@api_resources_bp.route('/admin/resources/bulk', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resources_bulk_admin():
    logger = current_app.logger
    data = request.get_json()

    if not data or 'ids' not in data or 'changes' not in data:
        return jsonify({'error': 'Invalid input. "ids" (list) and "changes" (dict) are required.'}), 400

    resource_ids = data.get('ids')
    changes_to_apply = data.get('changes')

    if not isinstance(resource_ids, list) or not isinstance(changes_to_apply, dict):
        return jsonify({'error': '"ids" must be a list and "changes" must be a dictionary.'}), 400

    if not resource_ids:
        return jsonify({'error': '"ids" list cannot be empty.'}), 400

    updated_ids = []
    errors = []

    for resource_id in resource_ids:
        if not isinstance(resource_id, int):
            errors.append({'id': resource_id, 'error': 'Invalid resource ID type, must be integer.'})
            continue

        resource = Resource.query.get(resource_id)
        if not resource:
            errors.append({'id': resource_id, 'error': 'Resource not found.'})
            continue

        current_resource_had_error = False

        if 'tags' in changes_to_apply:
            tags_val = changes_to_apply['tags']
            if isinstance(tags_val, str) or tags_val is None:
                resource.tags = tags_val
            else:
                errors.append({'id': resource_id, 'field': 'tags', 'error': 'Must be a string or null.'})
                current_resource_had_error = True


        if 'status' in changes_to_apply:
            status_val = changes_to_apply['status']
            if isinstance(status_val, str):
                resource.status = status_val
                if status_val == 'published' and resource.published_at is None:
                    resource.published_at = datetime.now(timezone.utc)
            else:
                errors.append({'id': resource_id, 'field': 'status', 'error': 'Must be a string.'})
                current_resource_had_error = True

        if 'booking_restriction' in changes_to_apply:
            br_val = changes_to_apply['booking_restriction']
            if isinstance(br_val, str) or br_val is None:
                resource.booking_restriction = br_val
            else:
                errors.append({'id': resource_id, 'field': 'booking_restriction', 'error': 'Must be a string or null.'})
                current_resource_had_error = True

        if 'is_under_maintenance' in changes_to_apply:
            ium_val = changes_to_apply['is_under_maintenance']
            if not isinstance(ium_val, bool):
                errors.append({'id': resource_id, 'field': 'is_under_maintenance', 'error': 'Must be boolean.'})
                current_resource_had_error = True
            else:
                resource.is_under_maintenance = ium_val

        if 'maintenance_until' in changes_to_apply:
            mu_val = changes_to_apply['maintenance_until']
            if mu_val is None:
                resource.maintenance_until = None
            else:
                try:
                    # Attempt to parse ISO format string
                    parsed_datetime = datetime.fromisoformat(str(mu_val).replace('Z', '+00:00'))
                    # Ensure it's offset-naive or UTC for DB consistency
                    if parsed_datetime.tzinfo:
                        resource.maintenance_until = parsed_datetime.astimezone(timezone.utc).replace(tzinfo=None)
                    else: # If naive, assume it's intended as UTC
                        resource.maintenance_until = parsed_datetime
                except ValueError:
                    errors.append({'id': resource_id, 'field': 'maintenance_until', 'error': 'Invalid datetime format. Use ISO 8601.'})
                    current_resource_had_error = True

        if 'floor_map_id' in changes_to_apply:
            fm_id_val = changes_to_apply['floor_map_id']
            if fm_id_val is None:
                resource.floor_map_id = None
            else:
                try:
                    fm_id = int(fm_id_val)
                    if FloorMap.query.get(fm_id) is None:
                        errors.append({'id': resource_id, 'field': 'floor_map_id', 'error': f'FloorMap with ID {fm_id} not found.'})
                        current_resource_had_error = True
                    else:
                        resource.floor_map_id = fm_id
                except (ValueError, TypeError):
                    errors.append({'id': resource_id, 'field': 'floor_map_id', 'error': 'Must be an integer or null.'})
                    current_resource_had_error = True

        if 'role_ids' in changes_to_apply:
            role_ids_val = changes_to_apply['role_ids']
            if not isinstance(role_ids_val, list):
                errors.append({'id': resource_id, 'field': 'role_ids', 'error': 'Must be a list.'})
                current_resource_had_error = True
            else:
                new_roles = []
                roles_valid = True
                for r_id in role_ids_val:
                    if not isinstance(r_id, int):
                        errors.append({'id': resource_id, 'field': 'role_ids', 'error': f'Invalid role ID type: {r_id}. Must be integer.'})
                        roles_valid = False
                        break
                    role = Role.query.get(r_id)
                    if not role:
                        errors.append({'id': resource_id, 'field': 'role_ids', 'error': f'Role with ID {r_id} not found.'})
                        roles_valid = False
                        break
                    new_roles.append(role)
                if roles_valid:
                    resource.roles = new_roles
                else:
                    current_resource_had_error = True # Error already added

        if not current_resource_had_error:
            updated_ids.append(resource_id)

    if updated_ids: # Only commit if there were attempts to update valid resources that didn't have pre-commit errors
        try:
            db.session.commit()
            logger.info(f"User {current_user.username} bulk updated resources. IDs: {updated_ids}. Changes: {changes_to_apply}. Errors: {errors}")
            add_audit_log(action="BULK_UPDATE_RESOURCES", details=f"User {current_user.username} bulk updated resources. IDs: {updated_ids}. Changes applied: {changes_to_apply}. Errors: {errors}")
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error committing bulk resource update by {current_user.username}:")
            # Add errors for all intended-to-be-updated IDs because commit failed globally
            for uid in updated_ids:
                 # Avoid duplicating if an error for this ID was already there
                if not any(err['id'] == uid for err in errors):
                    errors.append({'id': uid, 'error': f'Failed to commit changes due to server error: {str(e)}'})
            # Clear updated_ids as the commit failed
            updated_ids = []


    response_data = {'updated_count': len(updated_ids), 'updated_ids': updated_ids, 'errors': errors}
    status_code = 207 if errors else 200
    return jsonify(response_data), status_code

@api_resources_bp.route('/admin/resources/bulk', methods=['DELETE'])
@login_required
@permission_required('manage_resources')
def delete_resources_bulk_admin():
    logger = current_app.logger
    data = request.get_json()

    if not data or 'ids' not in data:
        return jsonify({'error': 'Invalid input. "ids" (list) is required.'}), 400

    resource_ids = data.get('ids')

    if not isinstance(resource_ids, list) or not resource_ids:
        return jsonify({'error': '"ids" must be a non-empty list.'}), 400

    deleted_ids = []
    errors = []

    for resource_id in resource_ids:
        if not isinstance(resource_id, int):
            errors.append({'id': str(resource_id), 'error': 'Invalid ID format. Must be integer.'})
            continue

        resource = Resource.query.get(resource_id)
        if not resource:
            errors.append({'id': resource_id, 'error': 'Resource not found.'})
            continue

        resource_name_for_log = resource.name
        image_filename_for_log = resource.image_filename

        if image_filename_for_log:
            try:
                # Use RESOURCE_IMAGE_UPLOAD_FOLDER from config.py
                image_path = os.path.join(current_app.config['RESOURCE_IMAGE_UPLOAD_FOLDER'], image_filename_for_log)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    logger.info(f"Successfully deleted image file {image_path} for resource ID {resource_id} ('{resource_name_for_log}').")
                else:
                    logger.warning(f"Image file {image_path} not found for resource ID {resource_id} ('{resource_name_for_log}').")
            except Exception as e_img:
                logger.error(f"Error deleting image file for resource ID {resource_id} ('{resource_name_for_log}'): {str(e_img)}")
                # Do not add to errors list for API response, as DB deletion is more critical

        try:
            db.session.delete(resource)
            # We don't commit here yet, commit all at once after the loop
            deleted_ids.append(resource_id)
            # Individual audit log for each successful prep for deletion (actual deletion on commit)
            # add_audit_log(action="PREPARE_BULK_DELETE_RESOURCE", details=f"Resource ID {resource_id} ('{resource_name_for_log}') prepared for bulk deletion by {current_user.username}.")
        except Exception as e_db_delete:
            # This case should be rare if query.get worked, but good for safety
            db.session.rollback() # Rollback this specific failed delete attempt from session
            errors.append({'id': resource_id, 'error': f'Error preparing resource for deletion: {str(e_db_delete)}'})
            logger.error(f"Error preparing resource ID {resource_id} for deletion: {str(e_db_delete)}")


    if not deleted_ids and not errors: # Should not happen if input validation is correct
        return jsonify({'message': 'No resource IDs provided or processed.'}), 400

    if deleted_ids:
        try:
            db.session.commit()
            logger.info(f"User {current_user.username} successfully bulk deleted resources. IDs: {deleted_ids}.")
            add_audit_log(action="BULK_DELETE_RESOURCES", details=f"User {current_user.username} bulk deleted resources. IDs: {deleted_ids}. Errors during process: {errors}")
        except Exception as e_commit:
            db.session.rollback()
            logger.exception(f"Error committing bulk resource deletion by {current_user.username}:")
            # Add errors for all IDs that were meant to be deleted as the commit failed
            for r_id in deleted_ids:
                if not any(err['id'] == r_id for err in errors): # Avoid duplicate error for same ID
                    errors.append({'id': r_id, 'error': f'Commit failed: {str(e_commit)}'})
            # Reset deleted_ids because the commit failed for all of them
            deleted_ids = []
            return jsonify({'error': 'Failed to delete resources due to a server error during commit.', 'details': errors}), 500

    response_data = {'deleted_count': len(deleted_ids), 'deleted_ids': deleted_ids, 'errors': errors}
    status_code = 207 if errors else 200
    return jsonify(response_data), status_code


@api_resources_bp.route('/resources/<int:resource_id>/all_bookings', methods=['GET'])
@login_required # Or public, depending on requirements
def get_all_bookings_for_resource_api(resource_id):
    logger = current_app.logger
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if not start_str or not end_str: return jsonify({'error': 'Start/end parameters required.'}), 400

    try:
        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        try: # Fallback for YYYY-MM-DD
            start_dt = datetime.combine(datetime.strptime(start_str, '%Y-%m-%d').date(), time.min)
            end_dt = datetime.combine(datetime.strptime(end_str, '%Y-%m-%d').date(), time.max)
        except ValueError:
            return jsonify({'error': 'Invalid date format.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404

    bookings = Booking.query.filter(
        Booking.resource_id == resource_id,
        Booking.start_time < end_dt,
        Booking.end_time > start_dt
    ).all()
    events = [{'id': b.id, 'title': b.title or resource.name,
               'start': b.start_time.isoformat(), 'end': b.end_time.isoformat()} for b in bookings]
    return jsonify(events), 200

@api_resources_bp.route('/admin/resources/<int:resource_id>/map_info', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resource_map_info_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid input.'}), 400

    # Update fields like floor_map_id, map_coordinates, booking_restriction, allowed_user_ids, role_ids
    if 'floor_map_id' in data: resource.floor_map_id = data['floor_map_id']
    if 'coordinates' in data: resource.map_coordinates = json.dumps(data['coordinates']) if data['coordinates'] else None
    # ... (other fields from original app.py's update_resource_map_info)

    try:
        db.session.commit()
        add_audit_log(action="UPDATE_RESOURCE_MAP_INFO", details=f"Map info for resource ID {resource.id} updated by {current_user.username}.")
        return jsonify(resource_to_dict(resource)), 200
    except Exception as e:
        db.session.rollback(); logger.exception(f"Error updating map info for resource {resource_id}:")
        return jsonify({'error': 'Failed to update map info.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>/map_info', methods=['DELETE'])
@login_required
@permission_required('manage_resources')
def delete_resource_map_info_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404

    resource.floor_map_id = None
    resource.map_coordinates = None
    try:
        db.session.commit()
        add_audit_log(action="DELETE_RESOURCE_MAP_INFO", details=f"Map info for resource ID {resource.id} deleted by {current_user.username}.")
        return jsonify({'message': 'Map information deleted.'}), 200
    except Exception as e:
        db.session.rollback(); logger.exception(f"Error deleting map info for resource {resource_id}:")
        return jsonify({'error': 'Failed to delete map info.'}), 500

# --- Resource PIN Management Endpoints ---

def generate_unique_pin(resource_id, length):
    """Helper function to generate a unique PIN for a given resource."""
    while True:
        new_pin = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        if not ResourcePIN.query.filter_by(resource_id=resource_id, pin_value=new_pin).first():
            return new_pin

@api_resources_bp.route('/resources/<int:resource_id>/pins', methods=['POST'])
@login_required
@permission_required('manage_resources')
def add_resource_pin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get_or_404(resource_id)
    data = request.get_json() or {} # Ensure data is a dict even if no JSON body

    manual_pin_value = data.get('pin_value', '').strip()
    notes = data.get('notes', '').strip()

    booking_settings = BookingSettings.query.first()
    pin_auto_generation_enabled = booking_settings.pin_auto_generation_enabled if booking_settings else True
    pin_length = booking_settings.pin_length if booking_settings else 6
    pin_allow_manual = booking_settings.pin_allow_manual_override if booking_settings else True

    final_pin_value = None

    if manual_pin_value:
        if not pin_allow_manual:
            logger.warning(f"User {current_user.username} attempted to set manual PIN for resource {resource_id} when not allowed.")
            return jsonify({'error': 'Manual PIN setting is disabled by global settings.'}), 403
        # Validate manual PIN (e.g., length, characters, uniqueness for this resource)
        if len(manual_pin_value) < 4 or len(manual_pin_value) > 32 : # Example validation
             return jsonify({'error': 'Manual PIN length must be between 4 and 32 characters.'}), 400
        if not all(c in string.ascii_uppercase + string.digits for c in manual_pin_value): # Basic alphanumeric check
             return jsonify({'error': 'Manual PIN must be alphanumeric (A-Z, 0-9).'}), 400
        if ResourcePIN.query.filter_by(resource_id=resource_id, pin_value=manual_pin_value).first():
            return jsonify({'error': 'This PIN value already exists for this resource.'}), 409
        final_pin_value = manual_pin_value
    elif pin_auto_generation_enabled:
        final_pin_value = generate_unique_pin(resource_id, pin_length)
    else:
        logger.warning(f"User {current_user.username} tried to add PIN for resource {resource_id}, but auto-generation is off and no manual PIN provided.")
        return jsonify({'error': 'Auto-generation of PINs is disabled and no manual PIN was provided.'}), 400

    if not final_pin_value: # Should not happen if logic above is correct
        logger.error(f"Failed to determine PIN value for resource {resource_id} under user {current_user.username}.")
        return jsonify({'error': 'Could not determine PIN value.'}), 500

    try:
        new_pin = ResourcePIN(
            resource_id=resource_id,
            pin_value=final_pin_value,
            is_active=True, # New PINs are active by default
            notes=notes if notes else None,
            created_at=datetime.utcnow()
        )
        db.session.add(new_pin)
        db.session.commit()

        # Update the resource's current_pin if this is the only active PIN or if it's preferred
        # For simplicity, let's set it if no other active PIN exists or if this is the first one.
        active_pins_count = ResourcePIN.query.filter_by(resource_id=resource_id, is_active=True).count()
        if active_pins_count == 1: # This new PIN is the only active one
            resource.current_pin = final_pin_value
            db.session.commit()

        add_audit_log(action="ADD_RESOURCE_PIN", details=f"PIN created for resource ID {resource_id} ('{resource.name}') by {current_user.username}. PIN: {new_pin.pin_value[:3]}...") # Log truncated PIN
        logger.info(f"PIN created for resource {resource_id} by user {current_user.username}.")
        return jsonify({
            'id': new_pin.id,
            'pin_value': new_pin.pin_value,
            'is_active': new_pin.is_active,
            'created_at': new_pin.created_at.isoformat(),
            'notes': new_pin.notes,
            'resource_current_pin': resource.current_pin # Reflect if resource.current_pin was updated
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error adding PIN for resource {resource_id} by user {current_user.username}: {e}")
        return jsonify({'error': 'Failed to add PIN due to a server error.'}), 500

@api_resources_bp.route('/resources/<int:resource_id>/pins/<int:pin_id>', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resource_pin(resource_id, pin_id):
    logger = current_app.logger
    pin = ResourcePIN.query.filter_by(id=pin_id, resource_id=resource_id).first_or_404()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    updated_fields = []
    if 'is_active' in data:
        new_is_active = data['is_active']
        if not isinstance(new_is_active, bool):
            return jsonify({'error': 'Invalid type for is_active, boolean expected.'}), 400
        if pin.is_active != new_is_active:
            pin.is_active = new_is_active
            updated_fields.append('is_active')

    if 'notes' in data:
        new_notes = data.get('notes', '').strip()
        if pin.notes != (new_notes if new_notes else None): # Compare with None if new_notes is empty
            pin.notes = new_notes if new_notes else None
            updated_fields.append('notes')

    if not updated_fields:
        return jsonify({'message': 'No changes detected or applied.'}), 200 # Or 304 Not Modified

    try:
        db.session.commit()

        # Logic to update resource.current_pin based on is_active changes
        resource = Resource.query.get(resource_id) # Fetch the parent resource
        if 'is_active' in updated_fields:
            if pin.is_active:
                # If this PIN was activated, and it's the only active one, or if no current_pin is set on resource, make it current.
                # More complex logic might be needed if multiple active PINs are allowed and one needs to be "primary".
                # For now, if resource has no current_pin or the deactivated PIN was the current one, set this one.
                # Or, always set the most recently activated PIN as current if no other active PIN is already current.
                other_active_pins = ResourcePIN.query.filter(
                    ResourcePIN.resource_id == resource_id,
                    ResourcePIN.is_active == True,
                    ResourcePIN.id != pin.id # Exclude the current pin being processed
                ).count()

                # If this is the only active PIN, or if the resource's current_pin is now inactive or empty, set this one.
                current_pin_is_this_newly_active_one = (resource.current_pin == pin.pin_value)

                if other_active_pins == 0: # This is now the only active PIN
                     resource.current_pin = pin.pin_value
                elif not resource.current_pin: # Resource had no current PIN set
                     resource.current_pin = pin.pin_value
                # If the pin that was just activated was already the current_pin, no change needed for resource.current_pin.
                # If another pin is active and is resource.current_pin, this logic doesn't change it.
                # This logic can be refined based on desired behavior for multiple active PINs.

            elif not pin.is_active and resource.current_pin == pin.pin_value: # This PIN was deactivated and was the current one
                # Find another active PIN to set as current, if any
                next_active_pin = ResourcePIN.query.filter_by(resource_id=resource_id, is_active=True).order_by(ResourcePIN.created_at.desc()).first()
                resource.current_pin = next_active_pin.pin_value if next_active_pin else None
            db.session.commit() # Commit changes to resource.current_pin

        add_audit_log(action="UPDATE_RESOURCE_PIN", details=f"PIN ID {pin_id} for resource ID {resource_id} updated by {current_user.username}. Changes: {', '.join(updated_fields)}.")
        logger.info(f"PIN {pin_id} for resource {resource_id} updated by user {current_user.username}. Fields: {', '.join(updated_fields)}")
        return jsonify({
            'id': pin.id,
            'pin_value': pin.pin_value,
            'is_active': pin.is_active,
            'created_at': pin.created_at.isoformat() if pin.created_at else None,
            'notes': pin.notes,
            'resource_current_pin': resource.current_pin
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error updating PIN {pin_id} for resource {resource_id} by user {current_user.username}: {e}")
        return jsonify({'error': 'Failed to update PIN due to a server error.'}), 500

@api_resources_bp.route('/resources/<int:resource_id>/pins/<int:pin_id>', methods=['DELETE'])
@login_required
@permission_required('manage_resources')
def delete_resource_pin(resource_id, pin_id):
    logger = current_app.logger
    pin = ResourcePIN.query.filter_by(id=pin_id, resource_id=resource_id).first()

    if not pin:
        logger.warning(f"Attempt to delete non-existent PIN ID {pin_id} for resource ID {resource_id} by user {current_user.username}.")
        return jsonify({'error': 'PIN not found for this resource.'}), 404

    resource = Resource.query.get(resource_id) # Should exist if pin was found, but good to have for name and current_pin update
    if not resource: # Should ideally not happen if PIN was found and correctly associated
        logger.error(f"Resource ID {resource_id} not found for PIN ID {pin_id} during deletion attempt by {current_user.username}.")
        return jsonify({'error': 'Associated resource not found.'}), 500 # Server-side inconsistency

    deleted_pin_value_for_log = pin.pin_value # Store before deleting
    resource_name_for_log = resource.name

    try:
        db.session.delete(pin)

        # Update Resource.current_pin if the deleted PIN was the current one
        if resource.current_pin == deleted_pin_value_for_log:
            next_active_pin = ResourcePIN.query.filter(
                ResourcePIN.resource_id == resource_id,
                ResourcePIN.is_active == True
                # No need to filter out pin_id as it's already marked for deletion from session
            ).order_by(ResourcePIN.created_at.desc()).first()
            resource.current_pin = next_active_pin.pin_value if next_active_pin else None

        db.session.commit()

        # Truncate PIN value for logging to avoid storing full PINs in logs
        log_pin_display = deleted_pin_value_for_log[:3] + "..." if len(deleted_pin_value_for_log) > 3 else deleted_pin_value_for_log

        add_audit_log(
            action="DELETE_RESOURCE_PIN",
            details=(
                f"PIN ID {pin_id} (value starting with {log_pin_display}) for resource "
                f"ID {resource_id} ('{resource_name_for_log}') deleted by {current_user.username}."
            )
        )
        logger.info(f"PIN ID {pin_id} for resource {resource_id} deleted by user {current_user.username}.")

        return jsonify({
            'message': 'PIN deleted successfully',
            'deleted_pin_id': pin_id,
            'resource_current_pin': resource.current_pin # Return the new current_pin of the resource
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting PIN {pin_id} for resource {resource_id} by user {current_user.username}: {e}")
        return jsonify({'error': 'Failed to delete PIN due to a server error.'}), 500

def init_api_resources_routes(app):
    app.register_blueprint(api_resources_bp)


# --- Bulk Resource PIN Actions ---
def _update_resource_current_pin(resource_obj):
    """
    Helper to intelligently set or clear the resource.current_pin.
    Sets to the most recently created active PIN if any exist, otherwise clears it.
    """
    if not resource_obj:
        return

    latest_active_pin = ResourcePIN.query.filter_by(
        resource_id=resource_obj.id,
        is_active=True
    ).order_by(ResourcePIN.created_at.desc()).first()

    if latest_active_pin:
        resource_obj.current_pin = latest_active_pin.pin_value
    else:
        resource_obj.current_pin = None
    # Caller is responsible for db.session.commit()


@api_resources_bp.route('/resources/pins/bulk_action', methods=['POST'])
@login_required
@permission_required('manage_resources')
def bulk_resource_pin_action():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource_ids = data.get('resource_ids')
    action = data.get('action')

    if not resource_ids or not isinstance(resource_ids, list):
        return jsonify({'error': 'Missing or invalid "resource_ids" (must be a list).'}), 400
    if not all(isinstance(rid, int) for rid in resource_ids):
        return jsonify({'error': 'All resource_ids must be integers.'}), 400
    if not action:
        return jsonify({'error': 'Missing "action".'}), 400

    allowed_actions = ['auto_generate_new_pin', 'deactivate_all_pins', 'activate_all_pins']
    if action not in allowed_actions:
        return jsonify({'error': f'Invalid action. Allowed actions are: {", ".join(allowed_actions)}'}), 400

    booking_settings = BookingSettings.query.first() # Needed for pin_length
    pin_length = booking_settings.pin_length if booking_settings and booking_settings.pin_length else 6

    processed_count = 0
    error_count = 0
    action_details = []

    resources_to_process = Resource.query.filter(Resource.id.in_(resource_ids)).all()

    if not resources_to_process:
        return jsonify({'error': 'No valid resources found for the provided IDs.'}), 404

    for resource in resources_to_process:
        try:
            if action == 'auto_generate_new_pin':
                if not (booking_settings and booking_settings.pin_auto_generation_enabled):
                    action_details.append({'resource_id': resource.id, 'status': 'skipped', 'reason': 'Auto-generation disabled in settings.'})
                    error_count += 1
                    continue

                new_pin_val = generate_unique_pin(resource.id, pin_length) # Uses helper from this file
                new_pin_obj = ResourcePIN(
                    resource_id=resource.id,
                    pin_value=new_pin_val,
                    is_active=True,
                    notes="Auto-generated via bulk action",
                    created_at=datetime.utcnow()
                )
                db.session.add(new_pin_obj)
                _update_resource_current_pin(resource) # Update current_pin
                action_details.append({'resource_id': resource.id, 'status': 'success', 'new_pin': new_pin_val, 'current_pin': resource.current_pin})

            elif action == 'deactivate_all_pins':
                pins_updated_count = ResourcePIN.query.filter_by(resource_id=resource.id, is_active=True).update({'is_active': False})
                resource.current_pin = None
                action_details.append({'resource_id': resource.id, 'status': 'success', 'deactivated_count': pins_updated_count, 'current_pin': None})

            elif action == 'activate_all_pins':
                pins_updated_count = ResourcePIN.query.filter_by(resource_id=resource.id, is_active=False).update({'is_active': True})
                _update_resource_current_pin(resource) # Update current_pin
                action_details.append({'resource_id': resource.id, 'status': 'success', 'activated_count': pins_updated_count, 'current_pin': resource.current_pin})

            processed_count += 1
        except Exception as e:
            logger.error(f"Error processing action '{action}' for resource {resource.id}: {str(e)}")
            error_count +=1
            action_details.append({'resource_id': resource.id, 'status': 'error', 'reason': str(e)})
            # db.session.rollback() # Rollback for this specific resource if needed, or handle globally

    try:
        db.session.commit()
        log_message = f"Bulk PIN action '{action}' completed for user {current_user.username}. Processed: {processed_count}, Errors/Skipped: {error_count}. Details: {action_details}"
        add_audit_log(action="BULK_PIN_ACTION", details=log_message)
        logger.info(log_message)
        return jsonify({
            'message': f'Bulk action "{action}" applied. Processed: {processed_count}. Errors/Skipped: {error_count}.',
            'details': action_details
        }), 200 if error_count == 0 else 207
    except Exception as e_commit:
        db.session.rollback()
        logger.exception(f"Error committing bulk PIN action '{action}' by user {current_user.username}: {e_commit}")
        return jsonify({'error': f'Failed to commit bulk PIN action due to a server error: {str(e_commit)}'}), 500
