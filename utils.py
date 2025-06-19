import os
import json
import logging
import tempfile
import re
from PIL import Image, ImageDraw, ImageFont
import requests
from datetime import datetime, date, timedelta, time, timezone # Ensure all are here
from flask import url_for, jsonify, current_app
from flask_login import current_user
# import csv # Removed as no longer used after CSV function deletions
# import io # Removed as no longer used after CSV function deletions
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from google.oauth2.credentials import Credentials as UserCredentials
import socket
import httplib2
import time as time_module
import io
import zipfile
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from extensions import db
from models import AuditLog, User, Resource, FloorMap, Role, Booking, BookingSettings # Ensure Role is imported
from sqlalchemy import func
from sqlalchemy.sql import func as sqlfunc

# New imports for task management
import uuid
import threading
# from datetime import datetime # Already imported

# Global lists for logging (if these are the sole modifiers)
email_log = []
slack_log = []
teams_log = []

active_booking_statuses_for_conflict = ['approved', 'pending', 'checked_in', 'confirmed']

basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')
SCHEDULER_SETTINGS_FILE_PATH = os.path.join(DATA_DIR, 'scheduler_settings.json')

DEFAULT_FULL_BACKUP_SCHEDULE = {
    "is_enabled": False, "schedule_type": "daily", "day_of_week": None, "time_of_day": "02:00"
}
DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE = {
    "is_enabled": False, "schedule_type": "interval", "interval_minutes": 60,
    "booking_backup_type": "full_export", "range": "all"
}
DEFAULT_SCHEDULER_SETTINGS = {
    "full_backup": DEFAULT_FULL_BACKUP_SCHEDULE.copy(),
    "booking_csv_backup": DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy(),
    "auto_restore_booking_records_on_startup": False
}

# --- Task Management Infrastructure ---
task_statuses = {}
task_lock = threading.Lock()

def create_task(task_type="generic"):
    # Creates a new task entry and returns its ID.
    task_id = uuid.uuid4().hex
    with task_lock:
        task_statuses[task_id] = {
            'type': task_type,
            'status_summary': 'Initializing...', # A brief summary string
            'log_entries': [], # List of log dicts
            'started_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z',
            'is_done': False,
            'success': None, # True, False, or None if not done
            'result_message': None # Final message or error details
        }
    current_app.logger.info(f"Task created with ID: {task_id}, type: {task_type}")
    return task_id

def get_task_status(task_id):
    # Returns the status of a specific task.
    with task_lock:
        return task_statuses.get(task_id) # Returns None if not found

def update_task_log(task_id, message, detail="", level="info"):
    # Adds a log entry to the task.
    with task_lock:
        if task_id in task_statuses:
            entry = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'level': level,
                'message': message,
                'detail': detail
            }
            task_statuses[task_id]['log_entries'].append(entry)
            task_statuses[task_id]['status_summary'] = message # Update summary to the latest message
            task_statuses[task_id]['updated_at'] = datetime.utcnow().isoformat() + 'Z'
            # current_app.logger.debug(f"Task {task_id} log updated: {message} - {detail}") # Can be too verbose
            return True
        current_app.logger.warning(f"Attempted to update log for non-existent task ID: {task_id}")
        return False

def mark_task_done(task_id, success, result_message=""):
    # Marks a task as completed (successfully or failed).
    with task_lock:
        if task_id in task_statuses:
            task_statuses[task_id]['is_done'] = True
            task_statuses[task_id]['success'] = success
            task_statuses[task_id]['result_message'] = result_message
            task_statuses[task_id]['status_summary'] = result_message if result_message else ("Completed successfully" if success else "Failed")
            task_statuses[task_id]['updated_at'] = datetime.utcnow().isoformat() + 'Z'

            final_log_level = "info" if success else "error"
            # Use a temporary list for log entries if update_task_log is called from within the same lock
            # to avoid re-locking if update_task_log is not designed for reentrancy.
            # However, current update_task_log re-acquires the lock, which is fine for non-reentrant locks.
            # For simplicity, direct append might be okay if we ensure no deadlocks,
            # but calling update_task_log is cleaner.
            # The previous implementation of update_task_log re-acquires the lock, so this is fine.
            log_entry_message = "Task finished."
            log_entry_detail = result_message

            # Add final log entry directly to avoid re-locking issues if update_task_log changes
            entry = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'level': final_log_level,
                'message': log_entry_message,
                'detail': log_entry_detail
            }
            task_statuses[task_id]['log_entries'].append(entry)
            current_app.logger.info(f"Task {task_id} marked done. Success: {success}. Message: {result_message}")
            return True
        current_app.logger.warning(f"Attempted to mark non-existent task ID {task_id} as done.")
        return False
# --- End Task Management Infrastructure ---


# --- Assume all other existing functions from utils.py are present here ---
# load_scheduler_settings, save_scheduler_settings, add_audit_log, resource_to_dict, etc.
# Make sure get_current_effective_time() is defined as it was in the previous context:
def get_current_effective_time():
    offset_hours = 0
    try:
        settings = BookingSettings.query.first()
        if settings and settings.global_time_offset_hours is not None:
            offset_hours = settings.global_time_offset_hours
    except Exception as e:
        logger = current_app.logger if current_app else logging.getLogger(__name__)
        logger.error(f"Error fetching time offset from BookingSettings: {e}. Defaulting offset to 0.")
        offset_hours = 0
    utc_now = datetime.now(timezone.utc)
    effective_time = utc_now + timedelta(hours=offset_hours)
    return effective_time

def check_booking_permission(user: User, resource: Resource, logger_instance) -> tuple[bool, str | None]:
    logger_instance.debug(f"Checking permission for user '{user.username}' (Admin: {user.is_admin}) on resource '{resource.name}' (ID: {resource.id}, Restriction: '{resource.booking_restriction}')")

    if user.is_admin:
        logger_instance.debug(f"Permission granted for resource '{resource.name}': User '{user.username}' is admin.")
        return True, "Admin access"

    if resource.booking_restriction == 'admin_only':
        logger_instance.debug(f"Permission denied for resource '{resource.name}': Resource is admin-only and user '{user.username}' is not admin.")
        return False, "Resource is admin-only"

    if resource.booking_restriction == 'restricted_roles':
        resource_allowed_role_ids = {role.id for role in resource.roles}
        if not resource_allowed_role_ids:
            logger_instance.debug(f"Permission denied for resource '{resource.name}': Restricted to roles, but no roles are assigned to the resource.")
            return False, "Resource is role-restricted, but no roles are assigned to it"

        user_role_ids = {role.id for role in user.roles}
        if user_role_ids.isdisjoint(resource_allowed_role_ids):
            logger_instance.debug(f"Permission denied for resource '{resource.name}': User '{user.username}' roles {user_role_ids} do not overlap with resource roles {resource_allowed_role_ids}.")
            return False, "User does not have a required role for this resource"
        else:
            logger_instance.debug(f"Permission granted for resource '{resource.name}': User '{user.username}' roles {user_role_ids} overlap with resource roles {resource_allowed_role_ids}.")
            return True, "User has a required role"

    if resource.booking_restriction == 'specific_users_only':
        if resource.allowed_user_ids and resource.allowed_user_ids.strip():
            try:
                allowed_ids_list = json.loads(resource.allowed_user_ids)
                if not isinstance(allowed_ids_list, list) or not all(isinstance(uid, int) for uid in allowed_ids_list):
                    logger_instance.warning(f"Resource {resource.id} ('{resource.name}') 'allowed_user_ids' ('{resource.allowed_user_ids}') is not a list of integers. Denying access.")
                    return False, "Resource has malformed allowed user list"
                if user.id not in allowed_ids_list:
                    logger_instance.debug(f"Permission denied for resource '{resource.name}': User ID {user.id} not in allowed list {allowed_ids_list}.")
                    return False, "User is not in the allowed list for this resource"
                else:
                    logger_instance.debug(f"Permission granted for resource '{resource.name}': User ID {user.id} is in allowed list {allowed_ids_list}.")
                    return True, "User is in the allowed list"
            except json.JSONDecodeError:
                logger_instance.warning(f"Resource {resource.id} ('{resource.name}') 'allowed_user_ids' ('{resource.allowed_user_ids}') is invalid JSON. Denying access.")
                return False, "Resource has invalid allowed user list format"
        else:
            logger_instance.debug(f"Permission denied for resource '{resource.name}': Restricted to specific users, but allowed list is empty or undefined.")
            return False, "User is not in the allowed list (list is empty or undefined)"

    logger_instance.debug(f"Permission granted for resource '{resource.name}': No specific restrictions denying access to user '{user.username}'.")
    return True, "Permission granted by default (no relevant restrictions)"


def get_detailed_map_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> dict:
    logger_instance.debug(f"get_detailed_map_availability_for_user called for date: {target_date}, user: {user.username}, {len(resources_list)} resources.")
    total_primary_slots_on_map = 0
    available_primary_slots_for_user_on_map = 0

    booking_settings = BookingSettings.query.first()
    global_time_offset_hours = 0
    past_booking_time_adjustment_hours = 0
    allow_multiple_resources_same_time = False

    if booking_settings:
        global_time_offset_hours = booking_settings.global_time_offset_hours if booking_settings.global_time_offset_hours is not None else 0
        past_booking_time_adjustment_hours = booking_settings.past_booking_time_adjustment_hours if booking_settings.past_booking_time_adjustment_hours is not None else 0
        allow_multiple_resources_same_time = booking_settings.allow_multiple_resources_same_time
    else:
        logger_instance.warning("BookingSettings not found. Using default values for availability calculation.")

    now_utc = datetime.now(timezone.utc)
    effective_venue_now_utc = now_utc + timedelta(hours=global_time_offset_hours)
    effective_cutoff_datetime_utc = effective_venue_now_utc - timedelta(hours=past_booking_time_adjustment_hours)

    logger_instance.debug(f"Effective venue now (UTC): {effective_venue_now_utc.isoformat()}, Effective cutoff (UTC): {effective_cutoff_datetime_utc.isoformat()}")
    logger_instance.debug(f"Allow multiple bookings: {allow_multiple_resources_same_time}")

    user_all_bookings_for_date = Booking.query.filter(
        Booking.user_name == user.username,
        func.date(Booking.start_time) == target_date,
        sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_conflict)
    ).all()
    logger_instance.debug(f"User {user.username} has {len(user_all_bookings_for_date)} bookings on {target_date} for conflict checking.")

    for resource in resources_list:
        logger_instance.debug(f"Processing resource: {resource.name} (ID: {resource.id})")
        has_permission, perm_reason = check_booking_permission(user, resource, logger_instance)

        is_resource_unavailable_all_day_due_to_maintenance = resource.is_under_maintenance and \
            (resource.maintenance_until is None or target_date <= resource.maintenance_until.date())

        if is_resource_unavailable_all_day_due_to_maintenance:
            logger_instance.debug(f"Resource {resource.name} is under maintenance for {target_date}.")

        for slot_start_time_obj, slot_end_time_obj in primary_slots:
            total_primary_slots_on_map += 1
            slot_desc = f"{slot_start_time_obj.strftime('%H:%M')}-{slot_end_time_obj.strftime('%H:%M')}"
            logger_instance.debug(f"  Checking slot: {slot_desc} for resource {resource.name}")

            if not has_permission:
                logger_instance.debug(f"    User {user.username} no permission for {resource.name} ({perm_reason}). Slot not counted as available to user.")
                continue

            if is_resource_unavailable_all_day_due_to_maintenance:
                logger_instance.debug(f"    Resource {resource.name} under maintenance. Slot {slot_desc} not available.")
                continue

            slot_start_local_naive = datetime.combine(target_date, slot_start_time_obj)
            slot_end_local_naive = datetime.combine(target_date, slot_end_time_obj)

            slot_start_for_cutoff_check_utc = (slot_start_local_naive - timedelta(hours=global_time_offset_hours)).replace(tzinfo=timezone.utc)

            if effective_cutoff_datetime_utc >= slot_start_for_cutoff_check_utc:
                logger_instance.debug(f"    Slot {slot_desc} on {resource.name} (starts {slot_start_for_cutoff_check_utc.isoformat()} UTC) has passed cutoff {effective_cutoff_datetime_utc.isoformat()}. Not available.")
                continue

            is_generally_booked = Booking.query.filter(
                Booking.resource_id == resource.id,
                Booking.start_time < slot_end_local_naive,
                Booking.end_time > slot_start_local_naive,
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_conflict)
            ).first() is not None

            if is_generally_booked:
                logger_instance.debug(f"    Slot {slot_desc} on {resource.name} is generally booked by someone else. Not available to user.")
                continue

            has_user_conflict = False
            if not allow_multiple_resources_same_time:
                for user_b in user_all_bookings_for_date:
                    if user_b.resource_id != resource.id:
                        if user_b.start_time < slot_end_local_naive and user_b.end_time > slot_start_local_naive:
                            has_user_conflict = True
                            logger_instance.debug(f"    Slot {slot_desc} on {resource.name} conflicts with user's booking ID {user_b.id} on resource {user_b.resource_id}.")
                            break

            if has_user_conflict:
                logger_instance.debug(f"    Slot {slot_desc} on {resource.name} not available due to user conflict (allow_multiple_resources_same_time is False).")
                continue

            available_primary_slots_for_user_on_map += 1
            logger_instance.debug(f"    Slot {slot_desc} on {resource.name} IS AVAILABLE for user {user.username}.")

    logger_instance.info(f"Detailed availability for user {user.username} on date {target_date}: Total Slots on Map = {total_primary_slots_on_map}, Available to User = {available_primary_slots_for_user_on_map}")
    return {'total_primary_slots': total_primary_slots_on_map, 'available_primary_slots_for_user': available_primary_slots_for_user_on_map}


def check_resources_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> bool:
    logger_instance.debug(f"check_resources_availability_for_user called for date: {target_date}, user: {user.username}, {len(resources_list)} resources.")
    detailed_availability = get_detailed_map_availability_for_user(
        resources_list, target_date, user, primary_slots, logger_instance
    )
    available_count = detailed_availability.get('available_primary_slots_for_user', 0)
    is_available = available_count > 0
    logger_instance.info(f"Overall resource availability for user {user.username} on date {target_date}: {is_available} (based on {available_count} available slots).")
    return is_available

def load_scheduler_settings():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    if not os.path.exists(SCHEDULER_SETTINGS_FILE_PATH):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_SCHEDULER_SETTINGS, f, indent=2)
        except IOError as e:
            logger.error(f"Error creating default scheduler settings: {e}")
        return DEFAULT_SCHEDULER_SETTINGS.copy()
    try:
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading scheduler settings: {e}. Returning defaults.")
        return DEFAULT_SCHEDULER_SETTINGS.copy()

def save_scheduler_settings(settings_dict):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving scheduler settings: {e}")

def add_audit_log(action: str, details: str, user_id: int = None, username: str = None):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        log_user_id = user_id
        log_username = username
        if current_user and current_user.is_authenticated:
            if log_user_id is None: log_user_id = current_user.id
            if log_username is None: log_username = current_user.username

        # If still no username but have user_id, try to fetch User (if User model is accessible)
        if log_username is None and log_user_id is not None:
            user_obj = User.query.get(log_user_id)
            if user_obj: log_username = user_obj.username
            else: log_username = f"User ID {log_user_id}"
        elif log_username is None and log_user_id is None:
            log_username = "System"

        log_entry = AuditLog(user_id=log_user_id, username=log_username, action=action, details=details)
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        logger.error(f"Error adding audit log: {e}", exc_info=True)
        db.session.rollback()

def resource_to_dict(resource: Resource) -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    image_url = None
    if resource.image_filename:
        try:
            image_url = url_for('static', filename=f'resource_uploads/{resource.image_filename}', _external=True)
        except RuntimeError: # Outside of application context
            image_url = f"/static/resource_uploads/{resource.image_filename}"

    return {
        'id': resource.id,
        'name': resource.name,
        'capacity': resource.capacity,
        'equipment': resource.equipment,
        'status': resource.status,
        'tags': resource.tags,
        'booking_restriction': resource.booking_restriction,
        'image_url': image_url,
        'published_at': resource.published_at.isoformat() if resource.published_at else None,
        'allowed_user_ids': resource.allowed_user_ids, # Assuming this is already a string or None
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles],
        'floor_map_id': resource.floor_map_id,
        'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
        # Robust parsing for map_allowed_role_ids
        'map_allowed_role_ids': (lambda val: (
            parsed_ids := None,
            (
                parsed_ids := json.loads(val) if val else None,
                (
                    logger.warning(f"Resource ID {resource.id}: map_allowed_role_ids parsed to non-list type ({type(parsed_ids)}). Value: '{val}'. Defaulting to None.")
                    if not isinstance(parsed_ids, list) and parsed_ids is not None else None
                ),
                parsed_ids if isinstance(parsed_ids, list) else None
            )[2] if val else None
        ) catch (json.JSONDecodeError) {
            (
                logger.warning(f"Resource ID {resource.id}: Failed to decode map_allowed_role_ids JSON: '{val}'. Defaulting to None.")
                if val else None # Log only if val was not None/empty
            ),
            None
        })[1])(resource.map_allowed_role_ids),
        'is_under_maintenance': resource.is_under_maintenance,
        'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None,
    }

def generate_booking_image(resource_id: int, map_coordinates_str: str, resource_name: str) -> str | None:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug(f"generate_booking_image called for {resource_name} - STUB")
    return None

def send_email(to_address: str, subject: str, body: str = None, html_body: str = None, attachment_path: str = None):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"send_email called for {to_address} with subject '{subject}' - STUB")
    email_log.append({'to': to_address, 'subject': subject, 'body': body or html_body}) # For testing
    pass

def send_slack_notification(text: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"send_slack_notification: {text} - STUB")
    slack_log.append(text) # For testing
    pass

def send_teams_notification(to_email: str, title: str, text: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"send_teams_notification to {to_email} with title '{title}': {text} - STUB")
    teams_log.append({'to': to_email, 'title': title, 'text': text}) # For testing
    pass

def parse_simple_rrule(rule_str: str):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug(f"parse_simple_rrule for '{rule_str}' - STUB")
    return None, 1 # type: ignore

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'json', 'csv'} # Example
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _parse_iso_datetime(dt_str):
    if not dt_str: return None
    try:
        if dt_str.endswith('Z'): return datetime.fromisoformat(dt_str[:-1] + '+00:00')
        return datetime.fromisoformat(dt_str)
    except ValueError: return None

def _emit_import_progress(socketio_instance, task_id, message, detail='', level='INFO', context_prefix=""):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"SOCKETIO_EMIT (Import Task: {task_id}): {context_prefix}{message} - {detail} ({level})")

def _get_map_configuration_data() -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Exporting map configuration data.")

    maps_list = []
    try:
        all_floor_maps = FloorMap.query.all()
        for floor_map in all_floor_maps:
            maps_list.append({
                'id': floor_map.id,
                'name': floor_map.name,
                'image_filename': floor_map.image_filename,
                # Fields as per prompt, assuming they exist on FloorMap model
                'location': getattr(floor_map, 'location', None), # Use getattr for fields that might not exist
                'floor': getattr(floor_map, 'floor', None),
                'offset_x': getattr(floor_map, 'offset_x', None),
                'offset_y': getattr(floor_map, 'offset_y', None),
                # Prompt specified to omit these, but they were in the import function, including for completeness if they exist
                'description': getattr(floor_map, 'description', None),
                'display_order': getattr(floor_map, 'display_order', 0),
                'is_published': getattr(floor_map, 'is_published', True),
                'map_data_json': getattr(floor_map, 'map_data_json', None)

            })
    except Exception as e:
        logger.error(f"Error fetching FloorMap data: {e}", exc_info=True)
        # Depending on desired behavior, could return error here or empty list
        # For now, proceed with empty list if maps fail, resource processing might still be useful for some cases

    resources_map_info_list = []
    try:
        # Fetch resources that are assigned to a map
        resources_with_map = Resource.query.filter(Resource.floor_map_id.isnot(None)).all()
        for resource in resources_with_map:
            map_x = None
            map_y = None
            if resource.map_coordinates:
                try:
                    coords = json.loads(resource.map_coordinates)
                    map_x = coords.get('x')
                    map_y = coords.get('y')
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in map_coordinates for Resource ID {resource.id}: {resource.map_coordinates}")
                except Exception as e_coords: # Catch other potential errors like coords not being a dict
                    logger.warning(f"Error parsing map_coordinates for Resource ID {resource.id}: {str(e_coords)}")


            resources_map_info_list.append({
                'resource_id': resource.id,
                'map_id': resource.floor_map_id,
                'map_x': map_x,
                'map_y': map_y
            })
    except Exception as e:
        logger.error(f"Error fetching Resource map info data: {e}", exc_info=True)
        # Similar to maps, proceed with empty list if resources fail

    num_maps = len(maps_list)
    num_resources_map_info = len(resources_map_info_list)
    message = f"Map configuration data exported. Found {num_maps} maps and {num_resources_map_info} resource map assignments."
    logger.info(message)

    return {
        'maps': maps_list,
        'resources_map_info': resources_map_info_list,
        'message': message
    }

def _import_map_configuration_data(config_data: dict) -> tuple[dict, int]:
    logger = current_app.logger if current_app else logging.getLogger(__name__)

    maps_data = config_data.get('maps', [])
    resources_map_info_data = config_data.get('resources_map_info', [])

    maps_processed = 0
    maps_created = 0
    maps_updated = 0
    resources_processed = 0
    resources_updated_map_info = 0

    errors = []
    warnings = []
    backup_to_new_map_id_mapping = {}

    # Define valid attributes for FloorMap model based on presumed model definition
    # Excludes 'id' for constructor_args, but can be in map_item for updates (though SQLAlchemy handles PKs)
    # These are fields that are safe to set directly from the input dictionary.
    VALID_FLOOR_MAP_ATTRIBUTES = {
        'name', 'image_filename', 'location', 'floor',
        'offset_x', 'offset_y',
        # The following were previously explicitly set but are now considered non-standard
        # and will only be set if they are valid attributes of the actual model.
        # If they are not valid, setattr would raise an error, so it's safer to omit them
        # or handle them explicitly if they have different names or need transformation.
        # For this task, we will only use the attributes explicitly mentioned as "expected".
        # 'description', 'display_order', 'is_published', 'map_data_json'
    }

    # Process Maps
    for map_item in maps_data:
        maps_processed += 1
        backup_map_id = map_item.get('id')

        if backup_map_id is None:
            errors.append(f"Map item found with no 'id': {map_item.get('name', 'Unknown map')}")
            continue

        try:
            floor_map = db.session.get(FloorMap, backup_map_id)

            if floor_map: # Map exists with this ID
                update_data = {}
                for key, value in map_item.items():
                    if key in VALID_FLOOR_MAP_ATTRIBUTES:
                        update_data[key] = value

                for key, value in update_data.items():
                    setattr(floor_map, key, value)

                # Handle potentially non-standard attributes if they exist on model and are in map_item
                # This part is removed to strictly adhere to only setting confirmed valid attributes.
                # if 'description' in map_item: floor_map.description = map_item.get('description', floor_map.description)
                # if 'display_order' in map_item: floor_map.display_order = map_item.get('display_order', floor_map.display_order)
                # if 'is_published' in map_item: floor_map.is_published = map_item.get('is_published', floor_map.is_published)
                # if 'map_data_json' in map_item: floor_map.map_data_json = map_item.get('map_data_json', floor_map.map_data_json)

                db.session.add(floor_map)
                maps_updated += 1
                backup_to_new_map_id_mapping[backup_map_id] = floor_map.id
            else: # Map with this ID does not exist, create a new one
                constructor_args = {}
                for key, value in map_item.items():
                    if key in VALID_FLOOR_MAP_ATTRIBUTES: # 'id' will be ignored by SQLAlchemy constructor if present
                        constructor_args[key] = value

                # Set defaults for potentially missing valid fields if necessary for constructor
                # (SQLAlchemy might handle nullable fields, but explicit is safer for non-nullable without defaults)
                # For this task, assuming model handles defaults or fields are always present if required.

                new_map = FloorMap(**constructor_args)
                db.session.add(new_map)
                db.session.flush() # Flush to get the new_map.id

                backup_to_new_map_id_mapping[backup_map_id] = new_map.id
                maps_created += 1
                warnings.append(f"Map with backup ID {backup_map_id} ('{new_map.name}') not found. Created as new map with ID {new_map.id}.")
        except Exception as e_map:
            error_msg = f"Error processing map (Backup ID: {backup_map_id}, Name: {map_item.get('name', 'N/A')}): {str(e_map)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)


    # Process Resource Map Info
    for resource_info in resources_map_info_data:
        resources_processed += 1
        resource_id = resource_info.get('resource_id')
        resource_backup_map_id = resource_info.get('map_id') # This is the ID from the backup's maps section
        resource_map_x = resource_info.get('map_x')
        resource_map_y = resource_info.get('map_y')

        if resource_id is None:
            errors.append("Resource map info item found with no 'resource_id'.")
            continue

        try:
            resource = db.session.get(Resource, resource_id)
            if resource:
                actual_db_map_id = None
                if resource_backup_map_id is not None: # If map_id is None/null in backup, it means unassign from map
                    actual_db_map_id = backup_to_new_map_id_mapping.get(resource_backup_map_id)
                    if actual_db_map_id is None and resource_backup_map_id is not None: # Check again if it was explicitly set in backup
                        warnings.append(f"For Resource ID {resource_id}, backed up Map ID {resource_backup_map_id} was not found or could not be mapped to a current map. Map assignment skipped.")

                resource.floor_map_id = actual_db_map_id
                resource.map_x = resource_map_x
                resource.map_y = resource_map_y
                db.session.add(resource)
                resources_updated_map_info += 1
            else:
                errors.append(f"Resource with ID {resource_id} not found. Cannot update its map info.")
        except Exception as e_res:
            error_msg = f"Error processing resource map info (Resource ID: {resource_id}): {str(e_res)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    status_code = 200
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f"Database commit error: {str(e)}")
        logger.error(f"Database commit error during map configuration import: {e}", exc_info=True)
        status_code = 500 # Indicate server error if commit fails

    final_message_parts = [
        f"Maps processed: {maps_processed} (Created: {maps_created}, Updated: {maps_updated}).",
        f"Resources map info processed: {resources_processed} (Updated: {resources_updated_map_info})."
    ]
    if warnings:
        final_message_parts.append(f"Warnings: {'; '.join(warnings)}")
    if errors:
        final_message_parts.append(f"Errors: {'; '.join(errors)}")
        if status_code == 200: # If commit was successful but there were data errors
            status_code = 207 # Multi-Status, as some operations might have failed

    final_message = " ".join(final_message_parts)
    logger.info(f"Map configuration import result: {final_message}")

    summary_dict = {
        'maps_processed': maps_processed,
        'maps_created': maps_created,
        'maps_updated': maps_updated,
        'resources_processed': resources_processed,
        'resources_updated_map_info': resources_updated_map_info,
        'errors': errors,
        'warnings': warnings,
        'message': final_message
        # 'status_code' is now returned as the second element of the tuple
    }

    # Consistently return a tuple: (summary_dict, status_code)
    if not errors and status_code == 200:
        return summary_dict, 200
    else:
        # Ensure status_code reflects the presence of errors/warnings if not already set by commit error
        current_status_code = status_code
        if not errors and warnings and current_status_code == 200: # No errors, but warnings exist, and not a commit error
            current_status_code = 207 # Multi-Status for warnings
        elif errors and current_status_code == 200: # Errors exist, and not a commit error (e.g. bad request not caught)
             current_status_code = 400 # Bad request or processing error if not already 500 or 207

        return summary_dict, current_status_code


def _get_map_configuration_data_zip():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Starting map configuration ZIP export.")

    try:
        export_data = _get_map_configuration_data()
        json_data_str = json.dumps(export_data, indent=4)
    except Exception as e:
        logger.error(f"Error generating map configuration JSON data: {e}", exc_info=True)
        # Depending on how this function is called, might raise e or return None, None
        return None, None # Indicates an error in data generation

    zip_buffer = io.BytesIO()
    image_filenames = set()

    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            logger.debug("Writing map_configuration.json to ZIP.")
            zip_file.writestr('map_configuration.json', json_data_str)

            if 'maps' in export_data and isinstance(export_data['maps'], list):
                for map_item in export_data['maps']:
                    if map_item.get('image_filename'):
                        image_filenames.add(map_item['image_filename'])

            logger.info(f"Found {len(image_filenames)} unique image filenames to include in ZIP.")

            # Determine upload folder path. Uses 'UPLOAD_FOLDER_MAPS' if defined, else a default.
            # Defaulting to a subfolder 'floor_map_uploads' within 'static' or 'uploads'
            # This part might need adjustment based on actual app structure/config
            upload_folder_maps = current_app.config.get('UPLOAD_FOLDER_MAPS')
            if not upload_folder_maps:
                # Fallback logic for upload folder
                static_folder = os.path.join(current_app.root_path, 'static')
                default_map_upload_subpath = 'floor_map_uploads' # Common convention

                # Check if static/floor_map_uploads exists
                potential_path_static = os.path.join(static_folder, default_map_upload_subpath)
                if os.path.isdir(potential_path_static):
                    upload_folder_maps = potential_path_static
                else:
                    # Fallback to app.config['UPLOAD_FOLDER'] if it exists and is valid
                    generic_upload_folder = current_app.config.get('UPLOAD_FOLDER')
                    if generic_upload_folder and os.path.isdir(generic_upload_folder):
                         # Try to see if a common subpath exists or use it directly
                        potential_path_generic = os.path.join(generic_upload_folder, default_map_upload_subpath)
                        if os.path.isdir(potential_path_generic):
                            upload_folder_maps = potential_path_generic
                        else: # If subpath doesn't exist in generic UPLOAD_FOLDER, maybe images are at its root
                            upload_folder_maps = generic_upload_folder
                    else: # Final fallback if no specific or generic upload folder is clearly identifiable
                        upload_folder_maps = os.path.join(static_folder, default_map_upload_subpath) # Default assumption
                        logger.warning(f"UPLOAD_FOLDER_MAPS not configured, and standard fallbacks are not definitively structured. Defaulting to: {upload_folder_maps}. Please verify.")

            logger.info(f"Using image upload folder: {upload_folder_maps}")

            for filename in image_filenames:
                if not filename or not isinstance(filename, str): # Basic validation
                    logger.warning(f"Invalid image filename found: {filename}. Skipping.")
                    continue

                # Sanitize filename to prevent directory traversal issues, though less critical for reads
                # For ZIP archive name, it's usually fine, but for os.path.join, be careful.
                # Assuming filenames from DB are generally safe but good practice to be aware.
                secure_filename = filename # Placeholder if further sanitization like werkzeug.secure_filename is needed
                                          # but that's typically for *saving* uploads, not archive paths.

                image_path = os.path.join(upload_folder_maps, secure_filename)

                if os.path.exists(image_path) and os.path.isfile(image_path):
                    try:
                        with open(image_path, 'rb') as f_img:
                            zip_file.writestr(secure_filename, f_img.read())
                        logger.debug(f"Added image {secure_filename} to ZIP from {image_path}.")
                    except Exception as e_img:
                        logger.error(f"Error reading image file {secure_filename} from {image_path}: {e_img}", exc_info=True)
                else:
                    logger.warning(f"Map image file {secure_filename} not found or is not a file at {image_path} during ZIP export.")

        zip_buffer.seek(0)
        zip_filename = 'map_configuration_export.zip'
        logger.info(f"Successfully created ZIP file '{zip_filename}' in memory.")
        return zip_buffer, zip_filename

    except Exception as e_zip:
        logger.error(f"Error creating ZIP file for map configuration: {e_zip}", exc_info=True)
        return None, None # Indicates an error during ZIP creation


def _get_resource_configurations_data() -> list:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Starting export of resource configurations.")

    resources_export_list = []
    try:
        all_resources = Resource.query.all()
        logger.info(f"Found {len(all_resources)} resources to export.")

        for resource in all_resources:
            current_map_coords_dict = {}
            if resource.map_coordinates:
                try:
                    current_map_coords_dict = json.loads(resource.map_coordinates)
                    if not isinstance(current_map_coords_dict, dict):
                        logger.warning(f"Resource ID {resource.id}: map_coordinates was not a JSON object, re-initializing. Original: {resource.map_coordinates}")
                        current_map_coords_dict = {} # Ensure it's a dict
                except json.JSONDecodeError:
                    logger.warning(f"Resource ID {resource.id}: map_coordinates JSON is invalid, re-initializing. Original: {resource.map_coordinates}")
                    current_map_coords_dict = {} # Ensure it's a dict

            # Get role IDs from the many-to-many relationship
            # This list of role IDs represents the general booking permissions for the resource,
            # not necessarily map-specific permissions.
            # For the export, we are now embedding the resource's general role associations
            # into the 'allowed_role_ids' field within 'map_coordinates' if it's being used as the primary
            # source for such role definitions on import.
            # This aligns with the idea that map_coordinates might become the sole source for these IDs.
            role_ids_for_export = [role.id for role in resource.roles]
            current_map_coords_dict['allowed_role_ids'] = role_ids_for_export

            resource_dict = {
                'id': resource.id,
                'name': resource.name,
                'status': resource.status,
                'capacity': resource.capacity,
                'equipment': resource.equipment,
                'tags': resource.tags,
                'booking_restriction': resource.booking_restriction,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids, # Already a JSON string or None
                'is_under_maintenance': resource.is_under_maintenance,
                'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None,
                'floor_map_id': resource.floor_map_id,
                'map_coordinates': current_map_coords_dict, # This is now a dictionary
                # 'map_allowed_role_ids': json.dumps(role_ids_for_export) if role_ids_for_export else None, # No longer needed as separate field if embedded
                # The 'roles' field (list of role dicts {'id': role.id, 'name': role.name}) for general role assignment
                # is handled by the import function based on the 'roles' key in the input data,
                # which it expects to be a list of role dicts, not just IDs.
                # For this export, we should provide that structure if we want to re-import roles correctly.
                'roles': [{'id': role.id, 'name': role.name} for role in resource.roles]
            }
            resources_export_list.append(resource_dict)

        logger.info(f"Successfully prepared {len(resources_export_list)} resources for export.")
    except Exception as e:
        logger.error(f"Error during resource configuration export: {e}", exc_info=True)
        # Depending on policy, could return empty list or raise error
        # For now, return what has been processed so far, or empty if error was early

    return resources_export_list

def _import_resource_configurations_data(resources_data_list: list): # Return type will be bool or dict
    logger = current_app.logger if current_app else logging.getLogger(__name__)

    resources_processed = 0
    resources_updated = 0
    created_count = 0  # Initialize created_count
    errors = []
    warnings = []

    for resource_data in resources_data_list:
        resources_processed += 1
        backup_id = resource_data.get('id')

        if backup_id is None:
            errors.append(f"Resource data item found with no 'id': {resource_data.get('name', 'Unknown resource')}")
            continue

        try:
            resource = db.session.get(Resource, backup_id)

            if resource:
                # Existing update logic
                resource.name = resource_data.get('name', resource.name)
                resource.capacity = resource_data.get('capacity', resource.capacity)
                resource.equipment = resource_data.get('equipment', resource.equipment)
                resource.status = resource_data.get('status', resource.status)

                # Handle tags (assuming model stores as string, backup might be string or list)
                tags_data = resource_data.get('tags', resource.tags)
                if isinstance(tags_data, list):
                    resource.tags = ",".join(tags_data) # Convert list to comma-separated string
                elif tags_data is None: # If backup explicitly has null tags
                    resource.tags = None
                else: # Is a string or keep existing
                    resource.tags = tags_data

                resource.booking_restriction = resource_data.get('booking_restriction', resource.booking_restriction)

                published_at_str = resource_data.get('published_at')
                if published_at_str: # Only update if provided
                    resource.published_at = _parse_iso_datetime(published_at_str)

                # Handle allowed_user_ids (assuming model stores as JSON string)
                allowed_users_data = resource_data.get('allowed_user_ids', resource.allowed_user_ids)
                if isinstance(allowed_users_data, list): # If backup provides a list
                    resource.allowed_user_ids = json.dumps(allowed_users_data)
                elif allowed_users_data is None: # If backup explicitly has null
                     resource.allowed_user_ids = None
                else: # Is a string (hopefully JSON string) or keep existing
                    resource.allowed_user_ids = allowed_users_data

                resource.is_under_maintenance = resource_data.get('is_under_maintenance', resource.is_under_maintenance)
                maintenance_until_str = resource_data.get('maintenance_until')
                resource.maintenance_until = _parse_iso_datetime(maintenance_until_str)

                # Handle floor_map_id
                resource.floor_map_id = resource_data.get('floor_map_id', resource.floor_map_id)

                # Handle map_coordinates and resource.roles synchronization
                role_ids_for_relationship = None
                map_coords_input_data = resource_data.get('map_coordinates')

                if isinstance(map_coords_input_data, dict):
                    # Make a copy to avoid modifying the input dict if it's reused
                    map_coords_to_store = map_coords_input_data.copy()
                    allowed_role_ids = map_coords_to_store.pop('allowed_role_ids', None) # Remove from dict before storing

                    if allowed_role_ids is not None: # Key was present
                        if isinstance(allowed_role_ids, list):
                            role_ids_for_relationship = allowed_role_ids
                        else:
                            warnings.append(f"Resource ID {backup_id}: 'allowed_role_ids' in 'map_coordinates' is not a list. Type: {type(allowed_role_ids)}. Roles will be cleared.")
                            role_ids_for_relationship = [] # Clear roles due to malformed data
                    # If 'allowed_role_ids' key was missing, role_ids_for_relationship remains None -> roles cleared

                    resource.map_coordinates = json.dumps(map_coords_to_store) # Store the dict without allowed_role_ids
                elif map_coords_input_data is None:
                    resource.map_coordinates = None
                    role_ids_for_relationship = [] # Clear roles
                else: # String or other type
                    resource.map_coordinates = str(map_coords_input_data) # Store as string
                    warnings.append(f"Resource ID {backup_id}: 'map_coordinates' was a {type(map_coords_input_data)}. Stored as string. Roles cannot be parsed and will be cleared.")
                    role_ids_for_relationship = [] # Clear roles as we can't parse them

                # Update resource.roles relationship
                if role_ids_for_relationship is not None: # Includes empty list
                    valid_roles_for_assignment = []
                    if role_ids_for_relationship: # If list is not empty
                        # Filter for valid integer IDs before querying
                        valid_query_ids = [r_id for r_id in role_ids_for_relationship if isinstance(r_id, int)]
                        if len(valid_query_ids) != len(role_ids_for_relationship):
                            warnings.append(f"Resource ID {backup_id}: Some role IDs in 'allowed_role_ids' were not integers and were ignored.")

                        if valid_query_ids:
                            current_roles_in_db = Role.query.filter(Role.id.in_(valid_query_ids)).all()
                            found_role_ids_in_db = {role.id for role in current_roles_in_db}
                            for r_id in valid_query_ids:
                                if r_id not in found_role_ids_in_db:
                                    warnings.append(f"Resource ID {backup_id}: Role ID {r_id} from 'allowed_role_ids' not found in database. Skipping.")
                            valid_roles_for_assignment = current_roles_in_db
                    resource.roles = valid_roles_for_assignment # Assign (empty list if no valid roles or empty input)
                # If role_ids_for_relationship is None (e.g. allowed_role_ids key was missing), this block is skipped,
                # and roles should be cleared. Let's ensure this happens.
                elif role_ids_for_relationship is None: # Explicitly clear if key was missing
                     resource.roles = []


                # Top-level 'roles' field from resource_data is now ignored for populating resource.roles.
                # The 'map_allowed_role_ids' field is also not directly used for populating resource.roles here.

                db.session.add(resource)
                resources_updated += 1
            else:
                # Create new resource
                logger.info(f"Resource with backup ID {backup_id} not found. Creating as new resource.")
                if not isinstance(backup_id, int):
                    errors.append(f"Resource with backup ID {backup_id} ('{resource_data.get('name', 'N/A')}') has a non-integer ID. Cannot create.")
                    continue

                new_resource = Resource()
                new_resource.id = backup_id

                new_resource.name = resource_data.get('name')
                new_resource.capacity = resource_data.get('capacity')
                new_resource.equipment = resource_data.get('equipment')
                new_resource.status = resource_data.get('status', 'draft')
                tags_data = resource_data.get('tags')
                if isinstance(tags_data, list): new_resource.tags = ",".join(tags_data)
                elif tags_data is None: new_resource.tags = None
                else: new_resource.tags = tags_data
                new_resource.booking_restriction = resource_data.get('booking_restriction')
                new_resource.published_at = _parse_iso_datetime(resource_data.get('published_at'))
                allowed_users_data = resource_data.get('allowed_user_ids')
                if isinstance(allowed_users_data, list): new_resource.allowed_user_ids = json.dumps(allowed_users_data)
                elif allowed_users_data is None: new_resource.allowed_user_ids = None
                else: new_resource.allowed_user_ids = allowed_users_data
                new_resource.is_under_maintenance = resource_data.get('is_under_maintenance', False)
                new_resource.maintenance_until = _parse_iso_datetime(resource_data.get('maintenance_until'))

                # Handle floor_map_id for new resource
                new_resource.floor_map_id = resource_data.get('floor_map_id')

                # Handle map_coordinates and resource.roles synchronization for new resource
                role_ids_for_relationship_new = None
                map_coords_input_data_new = resource_data.get('map_coordinates')

                if isinstance(map_coords_input_data_new, dict):
                    map_coords_to_store_new = map_coords_input_data_new.copy()
                    allowed_role_ids_new = map_coords_to_store_new.pop('allowed_role_ids', None)

                    if allowed_role_ids_new is not None:
                        if isinstance(allowed_role_ids_new, list):
                            role_ids_for_relationship_new = allowed_role_ids_new
                        else:
                            warnings.append(f"New Resource (Backup ID {backup_id}): 'allowed_role_ids' in 'map_coordinates' is not a list. Type: {type(allowed_role_ids_new)}. Roles will be empty.")
                            role_ids_for_relationship_new = []
                    new_resource.map_coordinates = json.dumps(map_coords_to_store_new)
                elif map_coords_input_data_new is None:
                    new_resource.map_coordinates = None
                    role_ids_for_relationship_new = []
                else: # String or other
                    new_resource.map_coordinates = str(map_coords_input_data_new)
                    warnings.append(f"New Resource (Backup ID {backup_id}): 'map_coordinates' was a {type(map_coords_input_data_new)}. Stored as string. Roles will be empty.")
                    role_ids_for_relationship_new = []

                new_resource_assigned_roles = []
                if role_ids_for_relationship_new is not None: # Includes empty list
                    if role_ids_for_relationship_new:
                        valid_query_ids_new = [r_id for r_id in role_ids_for_relationship_new if isinstance(r_id, int)]
                        if len(valid_query_ids_new) != len(role_ids_for_relationship_new):
                             warnings.append(f"New Resource (Backup ID {backup_id}): Some role IDs in 'allowed_role_ids' were not integers and were ignored.")
                        if valid_query_ids_new:
                            current_roles_in_db_new = Role.query.filter(Role.id.in_(valid_query_ids_new)).all()
                            found_role_ids_in_db_new = {role.id for role in current_roles_in_db_new}
                            for r_id in valid_query_ids_new:
                                if r_id not in found_role_ids_in_db_new:
                                    warnings.append(f"New Resource (Backup ID {backup_id}): Role ID {r_id} from 'allowed_role_ids' not found in database. Skipping.")
                            new_resource_assigned_roles = current_roles_in_db_new
                new_resource.roles = new_resource_assigned_roles


                db.session.add(new_resource)
                created_count += 1
        except Exception as e_res:
            error_msg = f"Error processing resource (Backup ID: {backup_id}, Name: {resource_data.get('name', 'N/A')}): {str(e_res)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    status_code = 200
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f"Database commit error: {str(e)}")
        logger.error(f"Database commit error during resource configurations import: {e}", exc_info=True)
        status_code = 500

    final_message_parts = [
        f"Resources processed: {resources_processed} (Created: {created_count}, Updated: {resources_updated})."
    ]
    if warnings:
        final_message_parts.append(f"Warnings: {'; '.join(warnings)}")
    if errors:
        final_message_parts.append(f"Errors: {'; '.join(errors)}")
        if status_code == 200: status_code = 207

    final_message = " ".join(final_message_parts)
    logger.info(f"Resource configurations import result: {final_message}")

    if not errors and status_code == 200:
        # Success case: return tuple (updated_count, created_count, errors, warnings, status_code, message)
        return resources_updated, created_count, [], [], 200, final_message
    else:
        # Failure/warnings case: extract details and return tuple
        # The variables final_message, errors, warnings, status_code, resources_updated, created_count are already available.
        return resources_updated, created_count, errors, warnings, status_code, final_message


def _get_user_configurations_data() -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.warning("_get_user_configurations_data is currently a STUB. Exporting user configurations will not provide actual data.")
    return {
        'users': [],
        'roles': [],
        'message': "Stub implementation: No actual user configuration data exported."
    }

def _import_user_configurations_data(user_config_data: dict): # Return type will be bool or dict
    logger = current_app.logger if current_app else logging.getLogger(__name__)

    roles_data = user_config_data.get('roles', [])
    users_data = user_config_data.get('users', [])

    roles_processed = 0
    roles_created = 0
    roles_updated = 0
    users_processed = 0
    users_updated = 0

    errors = []
    warnings = []
    backup_to_new_role_id_mapping = {} # Maps backup role ID to current DB role ID

    # Process Roles
    for role_item in roles_data:
        roles_processed += 1
        backup_role_id = role_item.get('id')
        role_name = role_item.get('name')

        if backup_role_id is None or role_name is None:
            errors.append(f"Role item found with missing 'id' or 'name': {role_item}")
            continue

        try:
            permissions_json_str = role_item.get('permissions', '[]')
            try:
                permissions_list = json.loads(permissions_json_str)
                if not isinstance(permissions_list, list):
                    raise ValueError("Permissions data is not a list.")
            except json.JSONDecodeError as jde:
                errors.append(f"Error decoding permissions JSON for Role ID {backup_role_id} ('{role_name}'): {str(jde)}. Permissions raw: '{permissions_json_str}'")
                continue
            except ValueError as ve:
                errors.append(f"Invalid permissions format for Role ID {backup_role_id} ('{role_name}'): {str(ve)}. Permissions raw: '{permissions_json_str}'")
                continue

            role = db.session.get(Role, backup_role_id)

            if role: # Role exists by ID
                role.name = role_name
                role.permissions = permissions_list
                db.session.add(role)
                roles_updated += 1
                backup_to_new_role_id_mapping[backup_role_id] = role.id
            else: # Role does not exist by ID, try to find by name
                role_by_name = Role.query.filter_by(name=role_name).first()
                if role_by_name:
                    warnings.append(f"Role with backup ID {backup_role_id} not found, but role with name '{role_name}' (ID: {role_by_name.id}) exists. Updating existing role by name.")
                    role_by_name.permissions = permissions_list
                    db.session.add(role_by_name)
                    roles_updated += 1
                    backup_to_new_role_id_mapping[backup_role_id] = role_by_name.id
                else: # Create new role
                    new_role = Role(name=role_name, permissions=permissions_list)
                    db.session.add(new_role)
                    db.session.flush()
                    backup_to_new_role_id_mapping[backup_role_id] = new_role.id
                    roles_created += 1
                    warnings.append(f"Role with backup ID {backup_role_id} ('{role_name}') not found. Created as new role with ID {new_role.id}.")
        except Exception as e_role:
            error_msg = f"Error processing role (Backup ID: {backup_role_id}, Name: {role_name}): {str(e_role)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    # Process Users (Update existing only)
    for user_item in users_data:
        users_processed += 1
        backup_user_id = user_item.get('id')
        username = user_item.get('username')

        if backup_user_id is None or username is None:
            errors.append(f"User item found with missing 'id' or 'username': {user_item}")
            continue

        try:
            user = db.session.get(User, backup_user_id)

            if user:
                user.username = username
                user.email = user_item.get('email', user.email)
                user.is_admin = user_item.get('is_admin', user.is_admin)
                user.status = user_item.get('status', user.status)
                # Password hash is intentionally NOT updated from backup.

                backed_up_user_role_ids_data = user_item.get('role_ids', [])
                if backed_up_user_role_ids_data is not None:
                    backed_up_user_role_ids = {role_id for role_id in backed_up_user_role_ids_data if role_id is not None}
                    actual_db_roles = []

                    for b_role_id in backed_up_user_role_ids:
                        actual_db_role_id = backup_to_new_role_id_mapping.get(b_role_id)
                        if actual_db_role_id:
                            role_obj = db.session.get(Role, actual_db_role_id)
                            if role_obj:
                                actual_db_roles.append(role_obj)
                            else:
                                warnings.append(f"For User '{username}' (Backup ID {backup_user_id}), mapped Role ID {actual_db_role_id} (from backup Role ID {b_role_id}) not found in DB. Skipping assignment.")
                        else:
                            warnings.append(f"For User '{username}' (Backup ID {backup_user_id}), backup Role ID {b_role_id} could not be mapped to a current Role ID. Skipping assignment.")
                    user.roles = actual_db_roles
                # If 'role_ids' key is missing, existing user roles are preserved.

                db.session.add(user)
                users_updated += 1
            else:
                warnings.append(f"User with backup ID {backup_user_id} ('{username}') not found in DB. Skipped (user creation from backup is not supported by this import).")
        except Exception as e_user:
            error_msg = f"Error processing user (Backup ID: {backup_user_id}, Username: {username}): {str(e_user)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    status_code = 200
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f"Database commit error: {str(e)}")
        logger.error(f"Database commit error during user configurations import: {e}", exc_info=True)
        status_code = 500

    final_message_parts = [
        f"Roles processed: {roles_processed} (Created: {roles_created}, Updated: {roles_updated}).",
        f"Users processed: {users_processed} (Updated: {users_updated})."
    ]
    if warnings:
        final_message_parts.append(f"Warnings: {'; '.join(warnings)}")
    if errors:
        final_message_parts.append(f"Errors: {'; '.join(errors)}")
        if status_code == 200: status_code = 207

    final_message = " ".join(final_message_parts)
    logger.info(f"User configurations import result: {final_message}")

    if not errors and status_code == 200:
        return True
    else:
        return {'message': final_message, 'errors': errors, 'warnings': warnings, 'status_code': status_code,
                'roles_processed': roles_processed, 'roles_created': roles_created, 'roles_updated': roles_updated,
                'users_processed': users_processed, 'users_updated': users_updated}

def _load_schedule_from_json():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_load_schedule_from_json STUB")
    return {}

def _save_schedule_to_json(data_to_save):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug(f"_save_schedule_to_json STUB with data: {data_to_save}")
    return True, "Stub save successful"

def load_unified_backup_schedule_settings(app):
    logger = app.logger
    config_file = app.config['UNIFIED_SCHEDULE_CONFIG_FILE']
    default_settings = app.config['DEFAULT_UNIFIED_SCHEDULE_DATA']

    if not os.path.exists(config_file):
        logger.warning(f"Unified backup schedule file '{config_file}' not found. Returning default settings.")
        return default_settings.copy()

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            loaded_settings = json.load(f)
    except (IOError, json.JSONDecodeError, TypeError) as e:
        logger.error(f"Error loading or parsing unified backup schedule file '{config_file}': {e}. Returning default settings.")
        return default_settings.copy()

    updated_settings = default_settings.copy()
    for key, value in loaded_settings.items():
        if key in updated_settings:
            if isinstance(updated_settings[key], dict) and isinstance(value, dict):
                updated_settings[key].update(value)
            else:
                updated_settings[key] = value
        else:
            updated_settings[key] = value

    for main_key, main_value_dict in default_settings.items():
        if main_key not in updated_settings:
            updated_settings[main_key] = main_value_dict.copy()
        elif not isinstance(updated_settings[main_key], dict):
             updated_settings[main_key] = main_value_dict.copy()
        else:
            for sub_key, sub_value in main_value_dict.items():
                if sub_key not in updated_settings[main_key]:
                    updated_settings[main_key][sub_key] = sub_value
    return updated_settings

def save_unified_backup_schedule_settings(data):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    config_file = current_app.config['UNIFIED_SCHEDULE_CONFIG_FILE']
    default_settings = current_app.config['DEFAULT_UNIFIED_SCHEDULE_DATA']

    if not isinstance(data, dict):
        return False, "Invalid data format: settings must be a dictionary."

    validated_data = {}
    full_backup_data = data.get("unified_full_backup", {})
    default_full_backup = default_settings["unified_full_backup"]
    validated_data["unified_full_backup"] = {}

    if not isinstance(full_backup_data.get("is_enabled"), bool):
        return False, "Invalid 'is_enabled' for full backup: must be true or false."
    validated_data["unified_full_backup"]["is_enabled"] = full_backup_data["is_enabled"]

    schedule_type = full_backup_data.get("schedule_type", default_full_backup["schedule_type"])
    if schedule_type not in ["daily", "weekly", "monthly"]:
        return False, "Invalid 'schedule_type' for full backup: must be 'daily', 'weekly', or 'monthly'."
    validated_data["unified_full_backup"]["schedule_type"] = schedule_type

    time_of_day = full_backup_data.get("time_of_day", default_full_backup["time_of_day"])
    if not re.match(r"^\d{2}:\d{2}$", time_of_day):
        return False, "Invalid 'time_of_day' for full backup: must be HH:MM format."
    validated_data["unified_full_backup"]["time_of_day"] = time_of_day

    day_of_week = full_backup_data.get("day_of_week")
    if schedule_type == "weekly":
        if not (isinstance(day_of_week, int) and 0 <= day_of_week <= 6):
            return False, "Invalid 'day_of_week' for weekly full backup: must be an integer between 0 and 6."
    else:
        day_of_week = None
    validated_data["unified_full_backup"]["day_of_week"] = day_of_week

    day_of_month = full_backup_data.get("day_of_month")
    if schedule_type == "monthly":
        if not (isinstance(day_of_month, int) and 1 <= day_of_month <= 31):
            return False, "Invalid 'day_of_month' for monthly full backup: must be an integer between 1 and 31."
    else:
        day_of_month = None
    validated_data["unified_full_backup"]["day_of_month"] = day_of_month

    incremental_backup_data = data.get("unified_incremental_backup", {})
    default_incremental_backup = default_settings["unified_incremental_backup"]
    validated_data["unified_incremental_backup"] = {}

    if not isinstance(incremental_backup_data.get("is_enabled"), bool):
        return False, "Invalid 'is_enabled' for incremental backup: must be true or false."
    validated_data["unified_incremental_backup"]["is_enabled"] = incremental_backup_data["is_enabled"]

    interval_minutes = incremental_backup_data.get("interval_minutes", default_incremental_backup["interval_minutes"])
    if not (isinstance(interval_minutes, int) and interval_minutes > 0):
        return False, "Invalid 'interval_minutes' for incremental backup: must be a positive integer."
    validated_data["unified_incremental_backup"]["interval_minutes"] = interval_minutes

    final_data_to_save = default_settings.copy()
    final_data_to_save["unified_full_backup"].update(validated_data["unified_full_backup"])
    final_data_to_save["unified_incremental_backup"].update(validated_data["unified_incremental_backup"])

    try:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(final_data_to_save, f, indent=4)
        logger.info(f"Unified backup schedule settings saved to '{config_file}'.")
        return True, "Settings saved successfully."
    except IOError as e:
        logger.error(f"Error saving unified backup schedule settings to '{config_file}': {e}")
        return False, f"Failed to write settings to file: {e}"

# TODO: Imports commented out as 'run_scheduled_incremental_booking_data_task' and 'run_periodic_full_booking_data_task' in scheduler_tasks.py are obsolete.
# from scheduler_tasks import run_scheduled_incremental_booking_data_task, run_periodic_full_booking_data_task
from apscheduler.jobstores.base import JobLookupError

def reschedule_unified_backup_jobs(app_instance):
    app_instance.logger.info("Attempting to reschedule unified backup jobs.")
    scheduler = getattr(app_instance, 'scheduler', None)

    if scheduler is None or not scheduler.running:
        app_instance.logger.warning("Scheduler not available or not running. Cannot reschedule unified backup jobs.")
        return

    unified_schedule_settings = load_unified_backup_schedule_settings(app_instance)
    app_instance.logger.info(f"Loaded settings for rescheduling: {unified_schedule_settings}")

    try:
        app_instance.logger.info("Attempting to remove job 'unified_incremental_booking_backup_job' during reschedule.")
        try:
            scheduler.remove_job('unified_incremental_booking_backup_job')
            app_instance.logger.info("Job 'unified_incremental_booking_backup_job' removed successfully during reschedule.")
        except JobLookupError:
            app_instance.logger.info("Job 'unified_incremental_booking_backup_job' not found during reschedule, skipping removal.")
        except Exception as e:
            app_instance.logger.error(f"Error removing job 'unified_incremental_booking_backup_job' during reschedule: {e}")

        incremental_config = unified_schedule_settings.get('unified_incremental_backup', {})
        if incremental_config.get('is_enabled'):
            interval_minutes = int(incremental_config.get('interval_minutes', 30))
            if interval_minutes <= 0:
                app_instance.logger.error(f"Invalid interval_minutes ({interval_minutes}) for unified incremental backup during reschedule. Must be positive. Job not scheduled.")
            else:
                scheduler.add_job(
                    func=run_scheduled_incremental_booking_data_task,
                    trigger='interval',
                    minutes=interval_minutes,
                    id='unified_incremental_booking_backup_job',
                    replace_existing=True,
                    args=[app_instance]
                )
                app_instance.logger.info(f"Rescheduled unified incremental backup job to run every {interval_minutes} minutes.")
        else:
            app_instance.logger.info("Unified incremental booking backup is disabled. Job not rescheduled.")
    except Exception as e:
        app_instance.logger.exception(f"Error rescheduling unified incremental backup job: {e}")

    try:
        app_instance.logger.info("Attempting to remove job 'unified_full_booking_backup_job' during reschedule.")
        try:
            scheduler.remove_job('unified_full_booking_backup_job')
            app_instance.logger.info("Job 'unified_full_booking_backup_job' removed successfully during reschedule.")
        except JobLookupError:
            app_instance.logger.info("Job 'unified_full_booking_backup_job' not found during reschedule, skipping removal.")
        except Exception as e:
            app_instance.logger.error(f"Error removing job 'unified_full_booking_backup_job' during reschedule: {e}")

        full_config = unified_schedule_settings.get('unified_full_backup', {})
        if full_config.get('is_enabled'):
            schedule_type = full_config.get('schedule_type', 'daily')
            time_of_day_str = full_config.get('time_of_day', '02:00')

            time_parts = time_of_day_str.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Hour or minute out of range for full backup reschedule.")

            trigger_args = {'hour': hour, 'minute': minute}

            if schedule_type == 'weekly':
                day_of_week = full_config.get('day_of_week')
                if day_of_week is None or not (0 <= int(day_of_week) <= 6):
                    app_instance.logger.error(f"Invalid day_of_week ({day_of_week}) for weekly unified full backup. Must be 0-6. Job not scheduled.")
                    raise ValueError("Invalid day_of_week for weekly schedule.")
                trigger_args['day_of_week'] = str(day_of_week)
            elif schedule_type == 'monthly':
                day_of_month = full_config.get('day_of_month')
                if day_of_month is None or not (1 <= int(day_of_month) <= 31):
                    app_instance.logger.error(f"Invalid day_of_month ({day_of_month}) for monthly unified full backup. Must be 1-31. Job not scheduled.")
                    raise ValueError("Invalid day_of_month for monthly schedule.")
                trigger_args['day'] = str(day_of_month)
            elif schedule_type != 'daily':
                 app_instance.logger.error(f"Unknown schedule_type '{schedule_type}' for full backup reschedule.")
                 raise ValueError(f"Unknown schedule_type: {schedule_type}")

            scheduler.add_job(
                func=run_periodic_full_booking_data_task,
                trigger='cron',
                id='unified_full_booking_backup_job',
                replace_existing=True,
                args=[app_instance],
                **trigger_args
            )
            app_instance.logger.info(f"Rescheduled unified full backup job with type '{schedule_type}' and args {trigger_args}.")
        else:
            app_instance.logger.info("Unified full booking backup is disabled. Job not rescheduled.")
    except Exception as e:
        app_instance.logger.exception(f"Error rescheduling unified full backup job: {e}")

    app_instance.logger.info("Finished rescheduling unified backup jobs.")

# Ensure all functions that might be used by other modules are explicitly available.
# If utils.py were a package, __all__ would be useful. For a single file, direct imports work.
# However, to be explicit about what this module provides (especially after adding new functions):
__all__ = [
    'create_task', 'get_task_status', 'update_task_log', 'mark_task_done', # New task functions
    'get_current_effective_time', 'check_booking_permission',
    'get_detailed_map_availability_for_user', 'check_resources_availability_for_user',
    'load_scheduler_settings', 'save_scheduler_settings', 'add_audit_log',
    'resource_to_dict', 'generate_booking_image', 'send_email',
    'send_slack_notification', 'send_teams_notification', 'parse_simple_rrule',
    'allowed_file', '_parse_iso_datetime', '_emit_import_progress',
    '_get_map_configuration_data', '_import_map_configuration_data',
    '_get_resource_configurations_data', '_import_resource_configurations_data',
    '_get_user_configurations_data', '_import_user_configurations_data',
    '_load_schedule_from_json', '_save_schedule_to_json',
    'load_unified_backup_schedule_settings', 'save_unified_backup_schedule_settings',
    'reschedule_unified_backup_jobs',
    # Constants if they are meant to be exported
    'email_log', 'slack_log', 'teams_log',
    'active_booking_statuses_for_conflict', 'DATA_DIR',
    'SCHEDULER_SETTINGS_FILE_PATH', 'DEFAULT_SCHEDULER_SETTINGS'
]
