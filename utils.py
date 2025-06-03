import os
import json
import logging # Added for fallback logger
import requests
from datetime import datetime, date, timedelta, time, timezone
from flask import url_for, jsonify, current_app
from flask_login import current_user
from flask_mail import Message # For send_email
import csv
import io

# Assuming db and mail are initialized in extensions.py
from extensions import db, mail
# Assuming models are defined in models.py
from models import AuditLog, User, Resource, FloorMap, Role, Booking # Added Booking

# Global lists for logging (if these are the sole modifiers)
email_log = []
slack_log = []
teams_log = []

# Configuration constants that will be imported from config.py later
# For now, define them here if they are used by functions being moved.
# Example: ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
# SCHEDULE_CONFIG_FILE = "data/backup_schedule.json"
# DEFAULT_SCHEDULE_DATA = { ... }
# UPLOAD_FOLDER = "static/floor_map_uploads"

# This will be imported from config.py in the app factory context
# For now, if a util needs it directly and utils.py is at root:
# basedir = os.path.abspath(os.path.dirname(__file__))
# DATA_DIR = os.path.join(basedir, 'data')
# SCHEDULE_CONFIG_FILE = os.path.join(DATA_DIR, 'backup_schedule.json')
# DEFAULT_SCHEDULE_DATA = {
# "is_enabled": False,
# "schedule_type": "daily",
# "day_of_week": None,
# "time_of_day": "02:00"
# }


def add_audit_log(action: str, details: str, user_id: int = None, username: str = None):
    """Adds an entry to the audit log."""
    try:
        log_user_id = user_id
        log_username = username

        if current_user and current_user.is_authenticated:
            if log_user_id is None:
                log_user_id = current_user.id
            if log_username is None:
                log_username = current_user.username

        if log_user_id is not None and log_username is None:
            user = User.query.get(log_user_id)
            if user:
                log_username = user.username
            else:
                log_username = f"User ID {log_user_id}"

        if log_user_id is None and log_username is None:
            log_username = "System"

        log_entry = AuditLog(
            user_id=log_user_id,
            username=log_username,
            action=action,
            details=details
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        # Use current_app.logger if available and configured
        logger = current_app.logger if current_app else logging.getLogger(__name__)
        logger.error(f"Error adding audit log: {e}", exc_info=True)
        db.session.rollback()

def resource_to_dict(resource: Resource) -> dict:
    # url_for needs an app context. If called outside a request, this will fail.
    # Consider passing url_for or generating URLs differently if used in background tasks.
    try:
        image_url = url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None
    except RuntimeError: # Outside of application context
        image_url = None # Or some placeholder

    return {
        'id': resource.id,
        'name': resource.name,
        'capacity': resource.capacity,
        'equipment': resource.equipment,
        'status': resource.status,
        'tags': resource.tags,
        'booking_restriction': resource.booking_restriction,
        'image_url': image_url,
        'published_at': resource.published_at.replace(tzinfo=timezone.utc).isoformat() if resource.published_at else None,
        'allowed_user_ids': resource.allowed_user_ids,
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles],
        'floor_map_id': resource.floor_map_id,
        'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
        'is_under_maintenance': resource.is_under_maintenance,
        'maintenance_until': resource.maintenance_until.replace(tzinfo=timezone.utc).isoformat() if resource.maintenance_until else None,
        'max_recurrence_count': resource.max_recurrence_count,
        'scheduled_status': resource.scheduled_status,
        'scheduled_status_at': resource.scheduled_status_at.replace(tzinfo=timezone.utc).isoformat() if resource.scheduled_status_at else None
    }

def send_email(to_address: str, subject: str, body: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    email_entry = {
        'to': to_address,
        'subject': subject,
        'body': body,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    email_log.append(email_entry)
    logger.info(f"Email queued to {to_address}: {subject}")

    if mail.app: # Check if mail is initialized with an app
        try:
            msg = Message(
                subject=subject,
                recipients=[to_address],
                body=body,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )
            mail.send(msg)
            logger.info(f"Email successfully sent to {to_address} via Flask-Mail.")
        except Exception as e:
            logger.error(f"Failed to send email to {to_address} via Flask-Mail: {e}", exc_info=True)
    else:
        logger.info("Flask-Mail not available or not initialized with app, email not sent via external server.")


def send_slack_notification(text: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    slack_log.append({'message': text, 'timestamp': datetime.now(timezone.utc).isoformat()})
    logger.info(f"Slack notification logged: {text}")


def send_teams_notification(to_email: str, title: str, text: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    log_entry = {
        'to': to_email,
        'title': title,
        'text': text,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    teams_log.append(log_entry)
    webhook = os.environ.get('TEAMS_WEBHOOK_URL') # Consider moving to app.config
    if webhook and to_email:
        try:
            payload = {'title': title, 'text': f"{to_email}: {text}"}
            requests.post(webhook, json=payload, timeout=5)
            logger.info(f"Teams notification sent to {to_email}")
        except Exception:
            logger.exception(f"Failed to send Teams notification to {to_email}")
    else:
        logger.info(f"Teams notification for {to_email} logged. Webhook not configured or no email provided.")


def parse_simple_rrule(rule_str: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    if not rule_str:
        return None, 1
    parts = {}
    for part in rule_str.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k.upper()] = v
    freq = parts.get('FREQ', '').upper()
    try:
        count = int(parts.get('COUNT', '1')) if parts.get('COUNT') else 1
    except (ValueError, TypeError):
        logger.warning(f"Invalid COUNT value in RRULE '{rule_str}'")
        return None, 1
    if freq not in {'DAILY', 'WEEKLY'}:
        return None, 1
    return freq, max(1, count)

def allowed_file(filename):
    # ALLOWED_EXTENSIONS will be imported from config.py
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_EXTENSIONS', set())

def _get_map_configuration_data() -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    floor_maps = FloorMap.query.all()
    floor_maps_data = []
    for fm in floor_maps:
        floor_maps_data.append({
            'id': fm.id,
            'name': fm.name,
            'image_filename': fm.image_filename,
            'location': fm.location,
            'floor': fm.floor
        })

    mapped_resources = Resource.query.filter(Resource.floor_map_id.isnot(None)).all()
    mapped_resources_data = []
    for r in mapped_resources:
        mapped_resources_data.append({
            'id': r.id,
            'name': r.name,
            'floor_map_id': r.floor_map_id,
            'map_coordinates': json.loads(r.map_coordinates) if r.map_coordinates else None,
            'booking_restriction': r.booking_restriction,
            'allowed_user_ids': r.allowed_user_ids,
            'role_ids': [role.id for role in r.roles]
        })
    logger.info(f"Data for map configuration backup: Found {len(floor_maps_data)} floor_maps and {len(mapped_resources_data)} mapped_resources.")
    return {
        'floor_maps': floor_maps_data,
        'mapped_resources': mapped_resources_data
    }

def _get_resource_configurations_data() -> list:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        resources = Resource.query.all()
        resources_data = []
        for r in resources:
            published_at_iso = r.published_at.isoformat() if r.published_at else None
            maintenance_until_iso = r.maintenance_until.isoformat() if r.maintenance_until else None
            scheduled_status_at_iso = r.scheduled_status_at.isoformat() if r.scheduled_status_at else None
            resources_data.append({
                'id': r.id, 'name': r.name, 'capacity': r.capacity, 'equipment': r.equipment,
                'tags': r.tags, 'status': r.status, 'published_at': published_at_iso,
                'booking_restriction': r.booking_restriction, 'allowed_user_ids': r.allowed_user_ids,
                'image_filename': r.image_filename, 'is_under_maintenance': r.is_under_maintenance,
                'maintenance_until': maintenance_until_iso, 'max_recurrence_count': r.max_recurrence_count,
                'scheduled_status': r.scheduled_status, 'scheduled_status_at': scheduled_status_at_iso,
                'floor_map_id': r.floor_map_id, 'map_coordinates': r.map_coordinates,
                'role_ids': [role.id for role in r.roles]
            })
        logger.info(f"Successfully gathered configuration data for {len(resources_data)} resources.")
        return resources_data
    except Exception:
        logger.exception("Error in _get_resource_configurations_data:")
        return []

def _get_user_configurations_data() -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    final_data = {'roles': [], 'users': []}
    try:
        roles = Role.query.all()
        roles_data = [{'id': r.id, 'name': r.name, 'description': r.description, 'permissions': r.permissions} for r in roles]
        final_data['roles'] = roles_data
        logger.info(f"Successfully gathered configuration data for {len(roles_data)} roles.")

        users = User.query.all()
        users_data = [{
            'id': u.id, 'username': u.username, 'email': u.email,
            'password_hash': u.password_hash, 'is_admin': u.is_admin,
            'google_id': u.google_id, 'google_email': u.google_email,
            'role_ids': [role.id for role in u.roles]
        } for u in users]
        final_data['users'] = users_data
        logger.info(f"Successfully gathered configuration data for {len(users_data)} users.")
        return final_data
    except Exception:
        logger.exception("Error in _get_user_configurations_data:")
        if 'roles' not in final_data: final_data['roles'] = []
        if 'users' not in final_data: final_data['users'] = []
        return final_data

def _import_user_configurations_data(user_config_data: dict) -> tuple[int, int, int, int, list]:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    roles_created, roles_updated, users_created, users_updated = 0, 0, 0, 0
    errors = []

    # Import Roles
    if 'roles' in user_config_data and isinstance(user_config_data['roles'], list):
        for role_data in user_config_data['roles']:
            action = "PROCESS_ROLE_VIA_RESTORE" # Initialize action
            try:
                role = None
                if 'id' in role_data and role_data['id'] is not None:
                    role = db.session.query(Role).get(role_data['id'])
                if not role and 'name' in role_data:
                    role = db.session.query(Role).filter_by(name=role_data['name']).first()

                action = "UPDATE_ROLE_VIA_RESTORE"
                if not role:
                    role = Role()
                    action = "CREATE_ROLE_VIA_RESTORE"

                role.name = role_data.get('name', role.name)
                role.description = role_data.get('description', role.description)
                role.permissions = role_data.get('permissions', role.permissions)

                if action == "CREATE_ROLE_VIA_RESTORE":
                    db.session.add(role)
                    roles_created +=1
                else:
                    roles_updated +=1
                db.session.commit() # Commit each role
                add_audit_log(action=action, details=f"Role '{role.name}' (ID: {role.id}) processed from backup by system.")
            except Exception as e:
                db.session.rollback()
                err_detail = f"Error processing role '{role_data.get('name', 'N/A')}': {str(e)}"
                logger.error(err_detail, exc_info=True)
                errors.append({'role_name': role_data.get('name', 'N/A'), 'error': str(e)})
                if action == "CREATE_ROLE_VIA_RESTORE": roles_created -=1
                elif action == "UPDATE_ROLE_VIA_RESTORE": roles_updated -=1

    # Import Users
    # Get all existing role IDs once to avoid repeated DB queries for roles
    existing_role_ids = {role.id for role in db.session.query(Role.id).all()}
    if 'users' in user_config_data and isinstance(user_config_data['users'], list):
        for user_data in user_config_data['users']:
            action = "PROCESS_USER_VIA_RESTORE" # Initialize action
            try:
                user = None
                if 'id' in user_data and user_data['id'] is not None:
                    user = db.session.query(User).get(user_data['id'])
                if not user and 'username' in user_data:
                    user = db.session.query(User).filter_by(username=user_data['username']).first()

                action = "UPDATE_USER_VIA_RESTORE"
                if not user:
                    user = User()
                    action = "CREATE_USER_VIA_RESTORE"

                user.username = user_data.get('username', user.username)
                user.email = user_data.get('email', user.email)
                # IMPORTANT: Password hashes should be restored as is.
                # The User model's set_password method is for hashing plain text passwords.
                if 'password_hash' in user_data:
                    user.password_hash = user_data['password_hash']

                user.is_admin = user_data.get('is_admin', user.is_admin)
                user.google_id = user_data.get('google_id', user.google_id)
                user.google_email = user_data.get('google_email', user.google_email)

                if 'role_ids' in user_data and isinstance(user_data['role_ids'], list):
                    valid_roles_for_user = []
                    for role_id in user_data['role_ids']:
                        if role_id in existing_role_ids:
                            role_obj = db.session.query(Role).get(role_id) # Fetch role object
                            if role_obj: valid_roles_for_user.append(role_obj)
                            else: errors.append({'user_name': user_data.get('username'), 'error': f"Role ID {role_id} for user not found despite being in existing_role_ids."})
                        else:
                            errors.append({'user_name': user_data.get('username'), 'error': f"Role ID {role_id} for user does not exist in roles table."})
                    user.roles = valid_roles_for_user

                if action == "CREATE_USER_VIA_RESTORE":
                    db.session.add(user)
                    users_created +=1
                else:
                    users_updated +=1
                db.session.commit() # Commit each user
                add_audit_log(action=action, details=f"User '{user.username}' (ID: {user.id}) processed from backup by system.")
            except Exception as e:
                db.session.rollback()
                err_detail = f"Error processing user '{user_data.get('username', 'N/A')}': {str(e)}"
                logger.error(err_detail, exc_info=True)
                errors.append({'user_name': user_data.get('username', 'N/A'), 'error': str(e)})
                if action == "CREATE_USER_VIA_RESTORE": users_created -=1
                elif action == "UPDATE_USER_VIA_RESTORE": users_updated -=1

    return roles_created, roles_updated, users_created, users_updated, errors


def _import_resource_configurations_data(resources_data_list: list) -> tuple[int, int, list]:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    created_count = 0
    updated_count = 0
    errors = []
    existing_role_ids = {role.id for role in db.session.query(Role.id).all()}

    for res_data in resources_data_list:
        resource = None
        original_resource_name_for_log = res_data.get('name', 'UnknownResource')
        try:
            if 'id' in res_data and res_data['id'] is not None:
                resource = db.session.query(Resource).get(res_data['id'])
            if not resource and 'name' in res_data and res_data['name']:
                resource = db.session.query(Resource).filter_by(name=res_data['name']).first()

            if resource: # Existing resource found
                _ = resource.bookings # Load bookings to prevent delete-orphan cascade

            action_taken = "UPDATE_RESOURCE_VIA_RESTORE"
            if not resource:
                action_taken = "CREATE_RESOURCE_VIA_RESTORE"
                resource = Resource()
                if 'id' in res_data and res_data['id'] is not None:
                    resource.id = res_data['id']

            resource.name = res_data.get('name', resource.name)
            resource.capacity = res_data.get('capacity', resource.capacity)
            resource.equipment = res_data.get('equipment', resource.equipment)
            resource.tags = res_data.get('tags', resource.tags)
            resource.status = res_data.get('status', resource.status)
            published_at_str = res_data.get('published_at')
            resource.published_at = datetime.fromisoformat(published_at_str) if published_at_str else None
            resource.booking_restriction = res_data.get('booking_restriction', resource.booking_restriction)
            resource.allowed_user_ids = res_data.get('allowed_user_ids', resource.allowed_user_ids)
            resource.image_filename = res_data.get('image_filename', resource.image_filename)
            resource.is_under_maintenance = res_data.get('is_under_maintenance', resource.is_under_maintenance)
            maintenance_until_str = res_data.get('maintenance_until')
            resource.maintenance_until = datetime.fromisoformat(maintenance_until_str) if maintenance_until_str else None
            resource.max_recurrence_count = res_data.get('max_recurrence_count', resource.max_recurrence_count)
            resource.scheduled_status = res_data.get('scheduled_status', resource.scheduled_status)
            scheduled_status_at_str = res_data.get('scheduled_status_at')
            resource.scheduled_status_at = datetime.fromisoformat(scheduled_status_at_str) if scheduled_status_at_str else None
            resource.floor_map_id = res_data.get('floor_map_id', resource.floor_map_id)
            resource.map_coordinates = res_data.get('map_coordinates', resource.map_coordinates)

            # Revised role assignment logic
            if 'role_ids' in res_data and isinstance(res_data['role_ids'], list):
                selected_roles_for_this_resource = []
                for role_id in res_data['role_ids']:
                    # Querying Role directly to ensure we get fresh objects or ones managed by this session
                    role_obj = db.session.query(Role).get(role_id)
                    if role_obj:
                        selected_roles_for_this_resource.append(role_obj)
                    else:
                        # Log error: role_id from backup data not found in current DB
                        errors.append({'resource_name': original_resource_name_for_log, 'id': res_data.get('id'), 'error': f"Role ID {role_id} specified in backup not found in database."})
                
                # For existing resources, clear old roles before assigning new ones to prevent IntegrityError
                if action_taken == "UPDATE_RESOURCE_VIA_RESTORE":
                    resource.roles.clear() # Clear existing associations
                    db.session.flush() # Ensure the clear is processed before adding new ones

                resource.roles = selected_roles_for_this_resource # Assign the new set of roles
            
            elif action_taken == "UPDATE_RESOURCE_VIA_RESTORE": # role_ids not in res_data or is empty
                # If role_ids is not provided or empty for an existing resource,
                # it means all roles should be removed from it.
                resource.roles.clear()
                # No flush needed here if we are just clearing and not adding immediately after in this branch

            if action_taken == "CREATE_RESOURCE_VIA_RESTORE":
                db.session.add(resource)
                created_count += 1
            else:
                updated_count += 1

            db.session.commit()
            add_audit_log(action=action_taken, details=f"Resource '{resource.name}' (ID: {resource.id}) processed from backup by system.")
        except Exception as e:
            db.session.rollback()
            error_detail = f"Error processing resource '{original_resource_name_for_log}' (ID: {res_data.get('id')}): {str(e)}"
            logger.error(error_detail, exc_info=True)
            errors.append({'resource_name': original_resource_name_for_log, 'id': res_data.get('id'), 'error': str(e)})
            if action_taken == "CREATE_RESOURCE_VIA_RESTORE": created_count -=1
            elif action_taken == "UPDATE_RESOURCE_VIA_RESTORE": updated_count -=1
    return created_count, updated_count, errors

def _import_map_configuration_data(config_data: dict) -> tuple[dict, int]:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    if not isinstance(config_data, dict) or 'floor_maps' not in config_data or 'mapped_resources' not in config_data:
        return {'error': 'Invalid configuration format.'}, 400

    maps_created, maps_updated, resource_updates = 0, 0, 0
    maps_errors, resource_errors, image_reminders = [], [], []

    if isinstance(config_data.get('floor_maps'), list):
        for fm_data in config_data['floor_maps']:
            try:
                fm = FloorMap.query.get(fm_data['id']) if fm_data.get('id') is not None else None
                if not fm and fm_data.get('name'): fm = FloorMap.query.filter_by(name=fm_data['name']).first()
                action = "UPDATE_FLOOR_MAP_VIA_IMPORT"
                if not fm:
                    fm = FloorMap()
                    action = "CREATE_FLOOR_MAP_VIA_IMPORT"
                    if not fm_data.get('name') or not fm_data.get('image_filename'):
                        maps_errors.append({'error': 'Missing name or image_filename for new map.', 'data': fm_data})
                        continue
                fm.name = fm_data.get('name', fm.name)
                fm.image_filename = fm_data.get('image_filename', fm.image_filename)
                fm.location = fm_data.get('location', fm.location)
                fm.floor = fm_data.get('floor', fm.floor)
                if fm.image_filename and not os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], fm.image_filename)):
                    image_reminders.append(f"Ensure image '{fm.image_filename}' for map '{fm.name}' exists.")
                if action == "CREATE_FLOOR_MAP_VIA_IMPORT": db.session.add(fm); maps_created += 1
                else: maps_updated += 1
                db.session.commit()
                fm_data['processed_id'] = fm.id
                username_for_audit_fm = current_user.username if current_user and current_user.is_authenticated else "System_Startup"
                add_audit_log(action=action, details=f"FloorMap '{fm.name}' (ID: {fm.id}) processed by import by {username_for_audit_fm}.")
            except Exception as e:
                db.session.rollback()
                maps_errors.append({'error': f"Error processing floor map '{fm_data.get('name', 'N/A')}': {str(e)}", 'data': fm_data})

    if isinstance(config_data.get('mapped_resources'), list):
        for res_map_data in config_data['mapped_resources']:
            try:
                resource = Resource.query.get(res_map_data['id']) if res_map_data.get('id') is not None else None
                if not resource and res_map_data.get('name'): resource = Resource.query.filter_by(name=res_map_data['name']).first()

                if not resource:
                    resource_errors.append({'error': f"Resource not found: '{res_map_data.get('name') or res_map_data.get('id', 'N/A')}'", 'data': res_map_data})
                    continue
                else: # Resource found
                    _ = resource.bookings # Load bookings to prevent delete-orphan cascade

                imported_floor_map_id = res_map_data.get('floor_map_id')
                target_floor_map = None
                if imported_floor_map_id is not None:
                    processed_map_entry = next((m for m in config_data['floor_maps'] if m.get('id') == imported_floor_map_id and 'processed_id' in m), None)
                    if processed_map_entry: target_floor_map = FloorMap.query.get(processed_map_entry['processed_id'])
                    else: target_floor_map = FloorMap.query.get(imported_floor_map_id)

                if target_floor_map: resource.floor_map_id = target_floor_map.id
                elif imported_floor_map_id is not None: resource_errors.append({'error': f"FloorMap ID '{imported_floor_map_id}' not found for resource '{resource.name}'.", 'data': res_map_data})

                if 'map_coordinates' in res_map_data: resource.map_coordinates = json.dumps(res_map_data['map_coordinates']) if res_map_data['map_coordinates'] else None
                if 'booking_restriction' in res_map_data: resource.booking_restriction = res_map_data['booking_restriction']
                if 'allowed_user_ids' in res_map_data: resource.allowed_user_ids = res_map_data['allowed_user_ids']
                if 'role_ids' in res_map_data and isinstance(res_map_data['role_ids'], list):
                    new_roles = [Role.query.get(r_id) for r_id in res_map_data['role_ids'] if Role.query.get(r_id)]
                    resource.roles = new_roles # Filtered for valid roles
                resource_updates +=1
                username_for_audit_res = current_user.username if current_user and current_user.is_authenticated else "System_Startup"
                add_audit_log(action="UPDATE_RESOURCE_MAP_INFO_VIA_IMPORT", details=f"Resource '{resource.name}' (ID: {resource.id}) map info updated by import by {username_for_audit_res}.")
            except Exception as e:
                db.session.rollback()
                resource_errors.append({'error': f"Error processing resource mapping for '{res_map_data.get('name', 'N/A')}': {str(e)}", 'data': res_map_data})
        try:
            db.session.commit()
        except Exception as e_commit_res:
            db.session.rollback(); resource_errors.append({'error': f"DB error on resource mappings: {str(e_commit_res)}"})

    summary = {'message': "Map config import processed.", 'maps_created': maps_created, 'maps_updated': maps_updated, 'maps_errors': maps_errors,
               'resource_mappings_updated': resource_updates, 'resource_mapping_errors': resource_errors, 'image_reminders': image_reminders}
    status_code = 207 if maps_errors or resource_errors else 200
    if status_code == 207: summary['message'] += " Some entries had errors."
    username_for_log = current_user.username if current_user and current_user.is_authenticated else "System_Startup"
    logger.log(logging.WARNING if status_code == 207 else logging.INFO, f"Map config import by {username_for_log} summary: {summary}")
    username_for_audit_final = current_user.username if current_user and current_user.is_authenticated else "System_Startup"
    add_audit_log(action="IMPORT_MAP_CONFIGURATION_COMPLETED", details=f"User {username_for_audit_final} completed map config import. Summary: {str(summary)}")
    return summary, status_code


def export_bookings_to_csv_string(bookings_iterable) -> str:
    """
    Exports an iterable of Booking model objects to a CSV formatted string.

    Args:
        bookings_iterable: An iterable of Booking model objects.

    Returns:
        A string containing the CSV data.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Define CSV header
    header = [
        'id', 'resource_id', 'user_name', 'start_time', 'end_time',
        'title', 'checked_in_at', 'checked_out_at', 'status', 'recurrence_rule'
    ]
    writer.writerow(header)

    for booking in bookings_iterable:
        row = [
            booking.id,
            booking.resource_id,
            booking.user_name,
            booking.start_time.isoformat() if booking.start_time else '',
            booking.end_time.isoformat() if booking.end_time else '',
            booking.title,
            booking.checked_in_at.isoformat() if booking.checked_in_at else '',
            booking.checked_out_at.isoformat() if booking.checked_out_at else '',
            booking.status,
            booking.recurrence_rule if booking.recurrence_rule is not None else ''
        ]
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()
    return csv_data

# Helper function for parsing ISO datetime strings
def _parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        # Handle 'Z' for UTC explicitly
        if dt_str.endswith('Z'):
            # Python's fromisoformat in some versions doesn't like 'Z' directly for parsing,
            # but it's fine for output. Replace 'Z' with '+00:00' for robust parsing.
            return datetime.fromisoformat(dt_str[:-1] + '+00:00')
        dt_obj = datetime.fromisoformat(dt_str)
        # If the datetime object is naive, assume UTC.
        # This might be needed if strings like "2023-01-01T12:00:00" (without Z or offset) are possible.
        # However, if all inputs are strictly ISO 8601 with offset/Z, this might not be necessary.
        # For now, let's assume inputs will have timezone info if not UTC 'Z'.
        # if dt_obj.tzinfo is None:
        #     return dt_obj.replace(tzinfo=timezone.utc) # Or handle as an error/log warning
        return dt_obj
    except ValueError:
        # Log error or handle as per requirements. For now, returning None.
        # Consider logging: logger.warning(f"Could not parse datetime string: {dt_str}", exc_info=True)
        return None

def import_bookings_from_csv_file(csv_file_path, app):
    """
    Imports bookings from a CSV file.

    Args:
        csv_file_path (str): The path to the CSV file.
        app: The Flask application object for app context.

    Returns:
        dict: A summary of the import process.
    """
    logger = app.logger # Use app's logger

    bookings_processed = 0
    bookings_created = 0
    bookings_skipped_duplicate = 0
    errors = []

    try:
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            # Expected header: id,resource_id,user_name,start_time,end_time,title,checked_in_at,checked_out_at,status,recurrence_rule
            # The 'id' column from CSV will be ignored for new bookings.

            with app.app_context():
                for row in reader:
                    bookings_processed += 1
                    line_num = reader.line_num

                    try:
                        resource_id_str = row.get('resource_id')
                        if not resource_id_str:
                            errors.append(f"Row {line_num}: Missing resource_id.")
                            continue
                        try:
                            resource_id = int(resource_id_str)
                        except ValueError:
                            errors.append(f"Row {line_num}: Invalid resource_id '{resource_id_str}'. Must be an integer.")
                            continue

                        user_name = row.get('user_name', '').strip()
                        if not user_name: # user_name is mandatory for a booking
                            errors.append(f"Row {line_num}: Missing user_name.")
                            continue

                        title = row.get('title', '').strip()
                        if not title: # title is mandatory for a booking
                            errors.append(f"Row {line_num}: Missing title.")
                            continue

                        start_time_str = row.get('start_time')
                        end_time_str = row.get('end_time')

                        start_time = _parse_iso_datetime(start_time_str)
                        end_time = _parse_iso_datetime(end_time_str)

                        if not start_time or not end_time:
                            errors.append(f"Row {line_num}: Invalid or missing start_time or end_time format.")
                            continue

                        if start_time >= end_time:
                            errors.append(f"Row {line_num}: Start time must be before end time.")
                            continue

                        status = row.get('status', 'approved').strip().lower()
                        # Basic validation for status, can be expanded
                        if status not in ['pending', 'approved', 'cancelled', 'rejected', 'completed']:
                             errors.append(f"Row {line_num}: Invalid status value '{row.get('status')}'. Defaulting to 'approved' if not critical, or skip.")
                             status = 'approved' # Or skip: continue

                        recurrence_rule = row.get('recurrence_rule')
                        if recurrence_rule == '': # Treat empty string as None
                            recurrence_rule = None

                        # Optional datetime fields
                        checked_in_at = _parse_iso_datetime(row.get('checked_in_at'))
                        checked_out_at = _parse_iso_datetime(row.get('checked_out_at'))

                        # Check for existing resource
                        resource = db.session.get(Resource, resource_id)
                        if not resource:
                            errors.append(f"Row {line_num}: Resource with ID {resource_id} not found.")
                            continue

                        # Check for duplicate booking (based on resource, user, start, and end time)
                        # This is a simple check; more complex rules might be needed (e.g., overlapping bookings)
                        existing_booking = Booking.query.filter_by(
                            resource_id=resource_id,
                            user_name=user_name,
                            start_time=start_time,
                            end_time=end_time
                        ).first()

                        if existing_booking:
                            bookings_skipped_duplicate += 1
                            logger.info(f"Row {line_num}: Skipping duplicate booking for resource {resource_id}, user '{user_name}' at {start_time}.")
                            continue

                        # Create new booking
                        new_booking = Booking(
                            resource_id=resource_id,
                            user_name=user_name,
                            start_time=start_time,
                            end_time=end_time,
                            title=title,
                            status=status,
                            recurrence_rule=recurrence_rule,
                            checked_in_at=checked_in_at,
                            checked_out_at=checked_out_at
                            # id is auto-generated by DB
                        )
                        db.session.add(new_booking)
                        bookings_created += 1
                        logger.info(f"Row {line_num}: Staged new booking for resource {resource_id}, user '{user_name}' from {start_time} to {end_time}.")

                    except Exception as e_row:
                        # Catch any other unexpected error during row processing
                        errors.append(f"Row {line_num}: Unexpected error processing row: {str(e_row)}")
                        logger.error(f"Row {line_num}: Unexpected error processing row: {row} - {str(e_row)}", exc_info=True)
                        # Depending on severity, may or may not want to rollback here or just skip the row
                        continue # Skip to next row

                if bookings_created > 0: # Only commit if new bookings were added
                    try:
                        db.session.commit()
                        logger.info(f"Successfully committed {bookings_created} new bookings to the database.")
                    except Exception as e_commit:
                        db.session.rollback()
                        errors.append(f"Database commit failed: {str(e_commit)}")
                        logger.error(f"Database commit failed after processing CSV: {str(e_commit)}", exc_info=True)
                        # Reset bookings_created if commit fails, as they weren't actually saved.
                        bookings_created = 0 # Or adjust based on how to report this
                elif not errors: # No new bookings created, and no errors encountered during processing
                    logger.info("No new bookings to create from CSV file.")


    except FileNotFoundError:
        error_msg = f"CSV file not found at path: {csv_file_path}"
        errors.append(error_msg)
        logger.error(error_msg)
    except Exception as e_file:
        # Catch other potential errors like permission issues, CSV parsing errors not caught by row loop
        error_msg = f"Error opening or reading CSV file {csv_file_path}: {str(e_file)}"
        errors.append(error_msg)
        logger.error(error_msg, exc_info=True)
        # If db session was active and an error occurs here, ensure rollback
        if 'app' in locals() and app: # Check if app context was even reached
             with app.app_context():
                 db.session.rollback()


    summary = {
        'processed': bookings_processed,
        'created': bookings_created,
        'skipped_duplicates': bookings_skipped_duplicate,
        'errors': errors
    }
    logger.info(f"Booking CSV import summary: {summary}")
    return summary

def _load_schedule_from_json():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    # SCHEDULE_CONFIG_FILE and DEFAULT_SCHEDULE_DATA should be imported from config.py
    schedule_config_file = current_app.config['SCHEDULE_CONFIG_FILE']
    default_schedule_data = current_app.config['DEFAULT_SCHEDULE_DATA']

    if not os.path.exists(schedule_config_file):
        _save_schedule_to_json(default_schedule_data)
        return default_schedule_data.copy()
    try:
        with open(schedule_config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for key, default_value in default_schedule_data.items():
            data.setdefault(key, default_value)
        return data
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading schedule from JSON '{schedule_config_file}': {e}. Returning defaults.")
        _save_schedule_to_json(default_schedule_data)
        return default_schedule_data.copy()

def _save_schedule_to_json(data_to_save):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    schedule_config_file = current_app.config['SCHEDULE_CONFIG_FILE']
    default_schedule_data = current_app.config['DEFAULT_SCHEDULE_DATA']
    try:
        validated_data = {}
        validated_data['is_enabled'] = bool(data_to_save.get('is_enabled', default_schedule_data['is_enabled']))
        validated_data['schedule_type'] = data_to_save.get('schedule_type', default_schedule_data['schedule_type'])
        if validated_data['schedule_type'] not in ['daily', 'weekly']:
            validated_data['schedule_type'] = default_schedule_data['schedule_type']

        day_of_week = data_to_save.get('day_of_week')
        if validated_data['schedule_type'] == 'weekly':
            if isinstance(day_of_week, int) and 0 <= day_of_week <= 6:
                validated_data['day_of_week'] = day_of_week
            else: validated_data['day_of_week'] = 0
        else: validated_data['day_of_week'] = None

        time_str = data_to_save.get('time_of_day', default_schedule_data['time_of_day'])
        try: datetime.strptime(time_str, '%H:%M'); validated_data['time_of_day'] = time_str
        except ValueError: validated_data['time_of_day'] = default_schedule_data['time_of_day']

        with open(schedule_config_file, 'w', encoding='utf-8') as f:
            json.dump(validated_data, f, indent=4)
        return True, "Schedule saved successfully to JSON."
    except IOError as e:
        logger.error(f"Error saving schedule to JSON '{schedule_config_file}': {e}")
        return False, f"Error saving schedule to JSON: {e}"
