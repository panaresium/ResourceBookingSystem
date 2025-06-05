import os
import json
from datetime import datetime, date, time, timedelta, timezone
from flask import Blueprint, jsonify, request, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

# Assuming db is initialized in extensions.py
from extensions import db
# Assuming models are defined in models.py
from models import Resource, Booking, FloorMap, Role # Added Role
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
            func.date(Booking.start_time) == target_date_obj
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
    if Resource.query.filter(func.lower(Resource.name) == func.lower(name.strip())).first():
        return jsonify({'error': f"Resource with name '{name}' already exists."}), 409
    capacity = data.get('capacity')
    try:
        if capacity is not None: capacity = int(capacity)
    except (ValueError, TypeError): return jsonify({'error': 'Capacity must be an integer or null.'}), 400

    new_resource = Resource(name=name.strip(), capacity=capacity, equipment=data.get('equipment'), tags=data.get('tags'))
    try:
        db.session.add(new_resource)
        db.session.commit()
        add_audit_log(action="CREATE_RESOURCE", details=f"Resource '{new_resource.name}' created by {current_user.username}")
        return jsonify(resource_to_dict(new_resource)), 201
    except Exception as e:
        db.session.rollback()
        logger.exception("Error creating resource:")
        return jsonify({'error': 'Failed to create resource due to a server error.'}), 500

@api_resources_bp.route('/admin/resources/<int:resource_id>', methods=['GET'])
@login_required
@permission_required('manage_resources')
def get_resource_details_admin(resource_id):
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    return jsonify(resource_to_dict(resource)), 200

@api_resources_bp.route('/admin/resources/<int:resource_id>', methods=['PUT'])
@login_required
@permission_required('manage_resources')
def update_resource_details_admin(resource_id):
    logger = current_app.logger
    resource = Resource.query.get(resource_id)
    if not resource: return jsonify({'error': 'Resource not found.'}), 404
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    # Simplified field updates, add more validation as needed
    allowed_fields = ['name', 'capacity', 'equipment', 'status', 'tags', 'booking_restriction', 'allowed_user_ids', 'is_under_maintenance', 'maintenance_until', 'max_recurrence_count', 'scheduled_status', 'scheduled_status_at', 'floor_map_id', 'map_coordinates']
    for field in allowed_fields:
        if field in data:
            if field == 'map_coordinates':
                map_coords_payload = data[field] # data[field] is safe due to 'if field in data'
                if map_coords_payload is not None and isinstance(map_coords_payload, dict):
                    # Extract allowed_role_ids and remove it from the payload for map_coordinates
                    roles_list = map_coords_payload.pop('allowed_role_ids', None)

                    # Set map_allowed_role_ids
                    resource.map_allowed_role_ids = json.dumps(roles_list) if roles_list is not None else None

                    # Set map_coordinates with the remaining data (now without allowed_role_ids)
                    resource.map_coordinates = json.dumps(map_coords_payload)
                    current_app.logger.debug(f"Processed map_coordinates. Roles: {resource.map_allowed_role_ids}, Coords: {resource.map_coordinates}")

                else: # Handles map_coords_payload being None or not a dict
                    resource.map_coordinates = None
                    resource.map_allowed_role_ids = None
                    current_app.logger.debug("map_coordinates payload was None or not a dict, clearing DB fields.")
            else: # For fields other than 'map_coordinates'
                setattr(resource, field, data[field])

    if 'role_ids' in data and isinstance(data['role_ids'], list):
        new_roles = [Role.query.get(r_id) for r_id in data['role_ids'] if Role.query.get(r_id)]
        resource.roles = new_roles

    try:
        db.session.commit()
        add_audit_log(action="UPDATE_RESOURCE", details=f"Resource ID {resource.id} ('{resource.name}') updated by {current_user.username}. Data: {data}")
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
    created, updated, errors = _import_resource_configurations_data(resources_data, db)

    summary = f"Import completed. Created: {created}, Updated: {updated}, Errors: {len(errors)}."
    add_audit_log(action="IMPORT_RESOURCES", details=f"User {current_user.username} imported resources. {summary} Errors: {errors}")
    if errors:
        return jsonify({'message': summary, 'created': created, 'updated': updated, 'errors': errors}), 207
    return jsonify({'message': summary, 'created': created, 'updated': updated}), 200


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


def init_api_resources_routes(app):
    app.register_blueprint(api_resources_bp)
