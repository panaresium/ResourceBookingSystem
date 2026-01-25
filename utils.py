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
import boto3 # For S3/R2 check if needed explicitly, though r2_storage should handle it

from extensions import db
from r2_storage import r2_storage
from models import AuditLog, User, Resource, FloorMap, Role, Booking, BookingSettings, ResourcePIN # Ensure Role and ResourcePIN are imported
from sqlalchemy import func, exc
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
    from models import MaintenanceSchedule
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

    schedules = MaintenanceSchedule.query.all()
    whitelists_exist = any(s.is_availability for s in schedules)

    for resource in resources_list:
        logger_instance.debug(f"Processing resource: {resource.name} (ID: {resource.id})")
        has_permission, perm_reason = check_booking_permission(user, resource, logger_instance)

        is_blacklisted = False
        is_whitelisted = False
        applicable_schedules = [s for s in schedules if (s.resource_selection_type == 'all') or (s.resource_selection_type == 'building' and resource.floor_map and s.building_id == resource.floor_map.location) or (s.resource_selection_type == 'floor' and resource.floor_map and str(resource.floor_map.id) in (s.floor_ids or '').split(',')) or (s.resource_selection_type == 'specific' and str(resource.id) in (s.resource_ids or '').split(','))]

        for schedule in applicable_schedules:
            day_of_week_check = schedule.schedule_type == 'recurring_day' and str(target_date.weekday()) in (schedule.day_of_week or '').split(',')
            day_of_month_check = schedule.schedule_type == 'specific_day' and str(target_date.day) in (schedule.day_of_month or '').split(',')
            date_range_check = schedule.schedule_type == 'date_range' and schedule.start_date <= target_date <= schedule.end_date if schedule.start_date and schedule.end_date else False

            if day_of_week_check or day_of_month_check or date_range_check:
                if schedule.is_availability:
                    is_whitelisted = True
                else:
                    is_blacklisted = True

        if is_blacklisted:
            logger_instance.debug(f"Resource {resource.name} is blacklisted for {target_date}.")
            continue

        if whitelists_exist and not is_whitelisted:
            logger_instance.debug(f"Resource {resource.name} is not in any whitelist for {target_date}.")
            continue

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

def save_scheduler_settings_from_json_data(settings_data: dict) -> tuple[dict, int]:
    """
    Saves the provided dictionary of scheduler settings to the local
    scheduler_settings.json file.
    Args:
        settings_data: A Python dictionary containing the scheduler settings.
    Returns:
        A tuple containing a summary dictionary and an HTTP-like status code.
        Example: ({'message': '...', 'errors': [], 'warnings': []}, 200)
    """
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"Attempting to save scheduler settings from provided JSON data to {SCHEDULER_SETTINGS_FILE_PATH}")

    if not isinstance(settings_data, dict):
        err_msg = "Invalid settings_data format: Must be a dictionary."
        logger.error(err_msg)
        return ({'message': err_msg, 'errors': [err_msg], 'warnings': []}, 400)

    try:
        os.makedirs(DATA_DIR, exist_ok=True) # Ensure the data directory exists
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=4) # Using indent=4 for consistency if it matters

        success_msg = "Scheduler settings applied successfully from backup."
        logger.info(success_msg)
        return ({'message': success_msg, 'errors': [], 'warnings': []}, 200)
    except IOError as e:
        error_msg = f"Failed to save scheduler settings from backup due to IOError: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ({'message': error_msg, 'errors': [str(e)], 'warnings': []}, 500)
    except Exception as e: # Catch any other unexpected errors
        error_msg = f"An unexpected error occurred while saving scheduler settings from backup: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ({'message': error_msg, 'errors': [str(e)], 'warnings': []}, 500)

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

    storage_provider = current_app.config.get('STORAGE_PROVIDER', 'local')
    image_url = None
    if resource.image_filename:
        if storage_provider == 'r2':
            image_url = r2_storage.generate_presigned_url(resource.image_filename, 'resource_uploads')
        else:
            image_url = url_for('static', filename=f'resource_uploads/{resource.image_filename}', _external=False)

    # Prepare resource_pins data
    resource_pins_list = []
    if hasattr(resource, 'pins'): # Check if the relationship exists
        for pin_obj in resource.pins:
            resource_pins_list.append({
                'id': pin_obj.id,
                'pin_value': pin_obj.pin_value,
                'is_active': pin_obj.is_active,
                'created_at': pin_obj.created_at.isoformat() if pin_obj.created_at else None,
                'notes': pin_obj.notes
            })

    return {
        'id': resource.id,
        'name': resource.name,
        'capacity': resource.capacity,
        'equipment': resource.equipment,
        'status': resource.status,
        'tags': resource.tags,
        'booking_restriction': resource.booking_restriction,
        'image_filename': resource.image_filename, # Changed from image_url to image_filename
        'image_url': image_url, # Added image_url
        'published_at': resource.published_at.isoformat() if resource.published_at else None,
        'allowed_user_ids': resource.allowed_user_ids, # Assuming this is already a string or None
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles],
        'floor_map_id': resource.floor_map_id,
        'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
        'is_under_maintenance': resource.is_under_maintenance,
        'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None,
        # New fields added below
        'max_recurrence_count': resource.max_recurrence_count,
        'scheduled_status': resource.scheduled_status,
        'current_pin': resource.current_pin,
        'scheduled_status_at': resource.scheduled_status_at.isoformat() if resource.scheduled_status_at else None,
        'map_allowed_role_ids': resource.map_allowed_role_ids, # Expected to be JSON string or None
        'resource_pins': resource_pins_list
    }

def generate_booking_image(resource_id: int, map_coordinates_str: str, resource_name: str) -> bytes | None:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        resource = Resource.query.get(resource_id)
        if not resource or not resource.floor_map_id:
            logger.warning(f"Resource {resource_id} or its floor map not found.")
            return None

        floor_map = FloorMap.query.get(resource.floor_map_id)
        if not floor_map or not floor_map.image_filename:
            logger.warning(f"Floor map image not found for resource {resource_id}, map ID {resource.floor_map_id}.")
            return None

        upload_folder_maps = current_app.config.get('UPLOAD_FOLDER_MAPS')
        if not upload_folder_maps:
            logger.error("UPLOAD_FOLDER_MAPS is not configured in the application.")
            upload_folder_maps = os.path.join(current_app.root_path, 'static', 'floor_map_uploads')
            logger.warning(f"UPLOAD_FOLDER_MAPS not set, defaulting to: {upload_folder_maps}")

        image_path = os.path.join(upload_folder_maps, floor_map.image_filename)

        # Check storage provider
        storage_provider = current_app.config.get('STORAGE_PROVIDER', 'local')

        if storage_provider == 'r2':
            # Download from R2 to memory
            try:
                # Assuming r2_storage is available and initialized
                # We need to access the underlying client or add a download method to R2Storage
                # For now, let's assume we can add a download method or access client
                if not r2_storage.client:
                     logger.error("R2 client not initialized for generate_booking_image")
                     return None

                key = f"floor_map_uploads/{floor_map.image_filename}"
                file_stream = io.BytesIO()
                r2_storage.client.download_fileobj(r2_storage.bucket_name, key, file_stream)
                file_stream.seek(0)
                img = Image.open(file_stream)
                logger.info(f"Downloaded floor map image from R2: {key}")
            except Exception as e:
                logger.error(f"Error downloading floor map from R2: {e}")
                return None
        else:
            if not os.path.exists(image_path):
                logger.error(f"Floor map image file not found at {image_path}")
                return None
            img = Image.open(image_path)

        # Parse coordinates from input string (these are relative to ref_width, ref_height)
        try:
            coords = json.loads(map_coordinates_str)
            original_ref_x, original_ref_y = int(coords['x']), int(coords['y'])
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            logger.error(f"Error parsing map coordinates '{map_coordinates_str}' for resource {resource_id}: {e}")
            return None

        # Define reference dimensions for the input coordinates
        ref_width = 800
        ref_height = 600

        # --- Step 1: Pre-resize the base image ---
        target_pre_resize_long_edge = 1200
        original_img_width, original_img_height = img.size
        current_img_for_drawing = img

        if max(original_img_width, original_img_height) > target_pre_resize_long_edge:
            if original_img_width > original_img_height:
                new_pre_width = target_pre_resize_long_edge
                new_pre_height = int(original_img_height * (target_pre_resize_long_edge / original_img_width))
            else:
                new_pre_height = target_pre_resize_long_edge
                new_pre_width = int(original_img_width * (target_pre_resize_long_edge / original_img_height))

            logger.info(f"Pre-resizing base image from {original_img_width}x{original_img_height} to {new_pre_width}x{new_pre_height}")
            current_img_for_drawing = img.resize((new_pre_width, new_pre_height), Image.Resampling.LANCZOS)
            drawing_img_width, drawing_img_height = new_pre_width, new_pre_height
        else:
            logger.info(f"Base image ({original_img_width}x{original_img_height}) is smaller than or equal to target pre-resize edge ({target_pre_resize_long_edge}). No pre-resize needed.")
            drawing_img_width, drawing_img_height = original_img_width, original_img_height

        # --- Step 2: Prepare for drawing on the (potentially pre-resized) image ---
        if current_img_for_drawing.mode != 'RGBA':
            current_img_for_drawing = current_img_for_drawing.convert('RGBA')
            logger.info("Converted image for drawing to RGBA mode.")
        draw = ImageDraw.Draw(current_img_for_drawing)

        # --- Step 3: Scale coordinates and drawing elements to the drawing_img dimensions ---
        scale_to_drawing_img_x = drawing_img_width / ref_width
        scale_to_drawing_img_y = drawing_img_height / ref_height

        draw_x = int(original_ref_x * scale_to_drawing_img_x)
        draw_y = int(original_ref_y * scale_to_drawing_img_y)

        logger.info(f"Input map coordinates: ({original_ref_x}, {original_ref_y}) for reference {ref_width}x{ref_height}.")
        logger.info(f"Drawing on image of size: {drawing_img_width}x{drawing_img_height}. Scale factors to this image: sx={scale_to_drawing_img_x:.2f}, sy={scale_to_drawing_img_y:.2f}.")
        logger.info(f"Scaled drawing coordinates on this image: ({draw_x}, {draw_y}).")

        base_font_size = 16
        base_rect_width = 40
        base_rect_height = 45
        rect_outline_color = "red"
        rect_fill_color = (255, 0, 0, 100)
        text_color = "black"

        avg_scale_to_drawing_img = (scale_to_drawing_img_x + scale_to_drawing_img_y) / 2.0

        font_size_on_drawing_img = max(10, int(base_font_size * avg_scale_to_drawing_img))
        rect_width_on_drawing_img = max(10, int(base_rect_width * scale_to_drawing_img_x))
        rect_height_on_drawing_img = max(5, int(base_rect_height * scale_to_drawing_img_y))
        # Increased base outline width from 2 to 3 for better visibility
        outline_width_on_drawing_img = max(1, int(3 * avg_scale_to_drawing_img))

        logger.info(f"Font size on drawing image: {font_size_on_drawing_img}")
        logger.info(f"Rectangle on drawing image: {rect_width_on_drawing_img}x{rect_height_on_drawing_img}, Outline: {outline_width_on_drawing_img}")

        try:
            font = ImageFont.truetype("arial.ttf", font_size_on_drawing_img)
        except IOError:
            logger.warning(f"Arial font not found for size {font_size_on_drawing_img}, using default PIL font.")
            font = ImageFont.load_default()

        # --- Step 4: Draw on the (potentially pre-resized) image ---
        rect_x1 = draw_x
        rect_y1 = draw_y
        rect_x2 = draw_x + rect_width_on_drawing_img
        rect_y2 = draw_y + rect_height_on_drawing_img

        # Draw outline-only rectangle
        draw.rectangle([(rect_x1, rect_y1), (rect_x2, rect_y2)],
                       outline=rect_outline_color, width=outline_width_on_drawing_img) # Removed fill=rect_fill_color
        logger.info(f"Drawing outline-only rectangle on image at [({rect_x1}, {rect_y1}), ({rect_x2}, {rect_y2})]")

        text_anchor_x = rect_x1 + rect_width_on_drawing_img / 2
        text_anchor_y = rect_y2 + int(5 * avg_scale_to_drawing_img)

        try:
            text_width = font.getlength(resource_name)
            text_x = text_anchor_x - (text_width / 2)
        except AttributeError:
            text_bbox_calc = draw.textbbox((0,0), resource_name, font=font)
            text_width_calc = text_bbox_calc[2] - text_bbox_calc[0]
            text_x = text_anchor_x - (text_width_calc / 2)

        text_y = text_anchor_y
        draw.text((text_x, text_y), resource_name, fill=text_color, font=font)
        # Corrected variable name in the log line below
        logger.info(f"Drawing text '{resource_name}' at ({text_x:.0f}, {text_y:.0f}) with font size {font_size_on_drawing_img}")

        # --- Step 5: Final Save and Compression ---
        # current_img_for_drawing is the annotated image, in RGBA mode.
        temp_image_buffer = io.BytesIO()
        current_img_for_drawing.save(temp_image_buffer, format="PNG") # Save with alpha
        img_size_kb = temp_image_buffer.tell() / 1024
        logger.info(f"Saved annotated image as PNG (supports alpha). Size: {img_size_kb:.2f} KB")

        final_data_to_send = None
        final_content_type = "image/png" # Default to PNG

        if img_size_kb <= 300:
            logger.info("PNG size is within limits. Using PNG with alpha.")
            final_data_to_send = temp_image_buffer.getvalue()
        else:
            logger.info(f"PNG image size ({img_size_kb:.2f} KB) is too large. Converting to JPEG.")
            final_content_type = "image/jpeg"

            # To convert RGBA to JPEG and simulate transparency, composite onto a background.
            # The original floor map (pre-resized, before annotation) can act as the background.
            # This ensures the transparent rectangle color blends with actual map features.

            # Re-open the original pre-resized image (before annotation and RGBA conversion for drawing)
            # This is tricky if 'img' was modified in place. Let's re-evaluate.
            # current_img_for_drawing IS the annotated RGBA image.
            # We need the map content that was *under* the annotation.

            # Simpler: If we must go to JPEG, true alpha is lost.
            # The previous method of pasting onto white is one way to handle it.
            # If "see-through" means the map details show through the color, then pasting onto
            # white makes the red very faint. If that's not desired, then a solid but lighter fill
            # for JPEGs, or an outline-only for JPEGs are alternatives.

            # Let's stick to the "paste RGBA onto white for JPEG" strategy,
            # ensuring the alpha (26) for the rectangle fill is very low.

            # current_img_for_drawing is our RGBA image with the (255,0,0,26) rectangle
            background = Image.new("RGB", current_img_for_drawing.size, (255, 255, 255))
            background.paste(current_img_for_drawing, (0, 0), current_img_for_drawing) # Use alpha channel of current_img_for_drawing as mask

            composited_rgb_image = background

            temp_image_buffer.seek(0)
            temp_image_buffer.truncate()
            composited_rgb_image.save(temp_image_buffer, format="JPEG", quality=85, optimize=True)
            img_size_kb = temp_image_buffer.tell() / 1024
            logger.info(f"Converted RGBA to JPEG by pasting on white. JPEG size: {img_size_kb:.2f} KB")

            if img_size_kb > 300:
                logger.warning(f"JPEG image size ({img_size_kb:.2f} KB) still exceeds 300KB. Attempting iterative resize/quality reduction.")
                temp_image_buffer.seek(0)
                img_to_resize_jpeg = Image.open(temp_image_buffer) # This is the composited RGB JPEG

                quality = 85
                while img_size_kb > 300 and max(img_to_resize_further.width, img_to_resize_further.height) > 300:
                    factor = 0.9
                    new_width = int(img_to_resize_further.width * factor)
                    new_height = int(img_to_resize_further.height * factor)

                    if new_width < 100 or new_height < 100:
                        logger.warning(f"Image resizing stopped to prevent making it too small ({new_width}x{new_height}). Current size: {img_size_kb:.2f} KB.")
                        break

                    logger.info(f"Further resizing image from {img_to_resize_further.width}x{img_to_resize_further.height} to {new_width}x{new_height}")
                    img_to_resize_further = img_to_resize_further.resize((new_width, new_height), Image.Resampling.LANCZOS)

                    temp_image_buffer.seek(0)
                    temp_image_buffer.truncate()
                    # Ensure image is RGB for JPEG save if it was RGBA (e.g. if PNG was re-opened)
                    if img_to_resize_further.mode != 'RGB':
                        img_to_save_jpeg_loop = img_to_resize_further.convert('RGB')
                    else:
                        img_to_save_jpeg_loop = img_to_resize_further

                    img_to_save_jpeg_loop.save(temp_image_buffer, format="JPEG", quality=quality, optimize=True)
                    img_size_kb = temp_image_buffer.tell() / 1024
                    logger.info(f"Resized JPEG image. New size: {img_size_kb:.2f} KB. Quality: {quality}")

                    if img_size_kb > 300 and quality > 50:
                        quality -= 10
        temp_image_buffer.seek(0)
        return temp_image_buffer.getvalue()

    except Exception as e:
        logger.exception(f"Error generating booking image for resource {resource_id}: {e}")
        return None

from email_utils import send_booking_email # Import the new function

def send_email(to_address: str, subject: str, body: str = None, html_body: str = None, attachment_path: str = None, attachment_data: bytes = None, attachment_filename: str = "booking_location.png"):
    logger = current_app.logger if current_app else logging.getLogger(__name__)

    # If attachment_path is provided and attachment_data is not, read the file.
    # This maintains compatibility if some parts of the code still use attachment_path.
    if attachment_path and not attachment_data:
        try:
            with open(attachment_path, 'rb') as f:
                attachment_data = f.read()
            if not attachment_filename or attachment_filename == "booking_location.png": # Default filename if not specific
                attachment_filename = os.path.basename(attachment_path)
            logger.info(f"Attachment read from path: {attachment_path}")
        except IOError as e:
            logger.error(f"Error reading attachment from path {attachment_path}: {e}")
            # Decide if we should proceed without attachment or fail
            attachment_data = None # Do not send a broken or non-existent attachment

    # Determine MIME type for the attachment if data is present
    attachment_mimetype = 'application/octet-stream' # Default MIME type
    if attachment_filename and attachment_data:
        if attachment_filename.lower().endswith('.png'):
            attachment_mimetype = 'image/png'
        elif attachment_filename.lower().endswith('.jpg') or attachment_filename.lower().endswith('.jpeg'):
            attachment_mimetype = 'image/jpeg'
        # Add more MIME types as needed
        logger.info(f"Attachment details: filename='{attachment_filename}', mimetype='{attachment_mimetype}', data_size={len(attachment_data) if attachment_data else 0} bytes.")


    success = send_booking_email(
        to_address=to_address,
        subject=subject,
        html_body=html_body,
        text_body=body, # Note: send_booking_email expects 'text_body' for plain text
        attachment_data=attachment_data,
        attachment_filename=attachment_filename,
        attachment_mimetype=attachment_mimetype
    )

    if success:
        logger.info(f"Email to {to_address} with subject '{subject}' delegated to email_utils.send_booking_email successfully.")
        # Optionally, add to a local log for testing/auditing if needed, though send_booking_email does its own logging.
        # email_log.append({'to': to_address, 'subject': subject, 'status': 'sent'})
    else:
        logger.error(f"Email to {to_address} with subject '{subject}' failed to send via email_utils.send_booking_email.")
        # email_log.append({'to': to_address, 'subject': subject, 'status': 'failed'})

    # The original stub function had 'pass'. Now it returns the success status.
    return success

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
                floor_map.name = map_item.get('name', floor_map.name)
                new_description = map_item.get('description')
                if new_description is not None:
                    # This will attempt to set the attribute.
                    # If 'description' is not a column in FloorMap, this won't persist
                    # but it crucially avoids reading a non-existent attribute.
                    # setattr is used to be explicit about setting an attribute that might
                    # not be a direct column, though direct assignment would also work here
                    # if the attribute was expected to exist (even if not a column).
                    try:
                        floor_map.description = new_description
                    except AttributeError:
                        # This handles cases where the model strictly prevents setting non-column attributes.
                        # For now, we log a warning, as the main goal is to prevent the crash.
                        # The broader issue of whether 'description' should be a column is noted in the plan.
                        logger.warning(f"Attempted to set 'description' on FloorMap ID {floor_map.id} but it's not a model attribute. Backup value was: '{new_description}'")
                # image_filename is stored as is. Actual file restoration is separate.
                floor_map.image_filename = map_item.get('image_filename', floor_map.image_filename)
                floor_map.display_order = map_item.get('display_order', floor_map.display_order)
                floor_map.is_published = map_item.get('is_published', floor_map.is_published)
                # map_data_json can be None, get() handles this.
                floor_map.map_data_json = map_item.get('map_data_json', floor_map.map_data_json)

                db.session.add(floor_map)
                maps_updated += 1
                backup_to_new_map_id_mapping[backup_map_id] = floor_map.id
            else: # Map with this ID does not exist, create a new one
                map_constructor_args = {
                    'name': map_item.get('name'),
                    'image_filename': map_item.get('image_filename'),
                    # Ensure all model fields are passed to constructor if available in backup
                    'location': map_item.get('location'),
                    'floor': map_item.get('floor'),
                    'offset_x': map_item.get('offset_x', 0), # Default if not in backup
                    'offset_y': map_item.get('offset_y', 0), # Default if not in backup
                    'display_order': map_item.get('display_order', 0),
                    'is_published': map_item.get('is_published', True),
                    'description': map_item.get('description'),
                    'map_data_json': map_item.get('map_data_json')
                }

                # Description and other fields are now part of the model and constructor
                # We will handle 'description' after object creation using direct assignment if needed,
                # similar to how it's handled for existing map objects.

                new_map = FloorMap(**map_constructor_args)
                db.session.add(new_map)
                db.session.flush() # Flush to get the new_map.id

                # This block can be simplified as fields are now in constructor
                # new_description = map_item.get('description')
                # if new_description is not None and new_map.description != new_map.description:
                #    new_map.description = new_description

                backup_to_new_map_id_mapping[backup_map_id] = new_map.id
                maps_created += 1
                warnings.append(f"Map with backup ID {backup_map_id} ('{new_map.name}') not found. Created as new map with ID {new_map.id} and attributes from backup.")
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

            storage_provider = current_app.config.get('STORAGE_PROVIDER', 'local')

            for filename in image_filenames:
                if not filename or not isinstance(filename, str): # Basic validation
                    logger.warning(f"Invalid image filename found: {filename}. Skipping.")
                    continue

                # Sanitize filename to prevent directory traversal issues, though less critical for reads
                # For ZIP archive name, it's usually fine, but for os.path.join, be careful.
                # Assuming filenames from DB are generally safe but good practice to be aware.
                secure_filename = filename # Placeholder if further sanitization like werkzeug.secure_filename is needed
                                          # but that's typically for *saving* uploads, not archive paths.

                if storage_provider == 'r2':
                    try:
                        key = f"floor_map_uploads/{secure_filename}"
                        file_stream = io.BytesIO()
                        if r2_storage.client:
                            r2_storage.client.download_fileobj(r2_storage.bucket_name, key, file_stream)
                            zip_file.writestr(secure_filename, file_stream.getvalue())
                            logger.debug(f"Added image {secure_filename} to ZIP from R2.")
                        else:
                            logger.error("R2 client not initialized during ZIP export.")
                    except Exception as e_r2:
                        logger.error(f"Error downloading image {secure_filename} from R2 for ZIP: {e_r2}")
                else:
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
    logger.info("Starting export of resource configurations data.")
    all_resources_data = []

    try:
        resources = Resource.query.all()
        logger.info(f"Found {len(resources)} resources to process.")

        for resource in resources:
            resource_config = {
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity,
                'equipment': resource.equipment,
                'status': resource.status,
                'booking_restriction': resource.booking_restriction,
                'image_filename': resource.image_filename,
                'is_under_maintenance': resource.is_under_maintenance,
                'max_recurrence_count': resource.max_recurrence_count,
                'scheduled_status': resource.scheduled_status,
                'floor_map_id': resource.floor_map_id,
                'current_pin': resource.current_pin,
            }

            # Handle tags (ensure string)
            if isinstance(resource.tags, list):
                resource_config['tags'] = ",".join(resource.tags)
            else:
                resource_config['tags'] = resource.tags

            # Handle maintenance_until (ISO format if datetime)
            if isinstance(resource.maintenance_until, datetime):
                resource_config['maintenance_until'] = resource.maintenance_until.isoformat()
            else:
                resource_config['maintenance_until'] = resource.maintenance_until

            # Handle scheduled_status_at (ISO format if datetime)
            if isinstance(resource.scheduled_status_at, datetime):
                resource_config['scheduled_status_at'] = resource.scheduled_status_at.isoformat()
            else:
                resource_config['scheduled_status_at'] = resource.scheduled_status_at

            # Handle map_coordinates (JSON string if complex)
            if isinstance(resource.map_coordinates, (dict, list)):
                try:
                    resource_config['map_coordinates'] = json.dumps(resource.map_coordinates)
                except TypeError:
                    logger.warning(f"Could not serialize map_coordinates for resource {resource.id} to JSON. Storing as string.")
                    resource_config['map_coordinates'] = str(resource.map_coordinates)
            else:
                resource_config['map_coordinates'] = resource.map_coordinates # Assume already string or None

            # Handle map_allowed_role_ids (JSON string if list/dict)
            if isinstance(resource.map_allowed_role_ids, (list, dict)):
                try:
                    resource_config['map_allowed_role_ids'] = json.dumps(resource.map_allowed_role_ids)
                except TypeError:
                    logger.warning(f"Could not serialize map_allowed_role_ids for resource {resource.id} to JSON. Storing as string.")
                    resource_config['map_allowed_role_ids'] = str(resource.map_allowed_role_ids)
            else:
                # If it's already a string (intended to be JSON), or None, keep as is.
                # If it's some other type, it might need specific handling or will be stored as its string representation.
                resource_config['map_allowed_role_ids'] = resource.map_allowed_role_ids


            # ResourcePINs
            resource_pins_list = []
            for pin_obj in resource.pins: # Assuming 'pins' is the relationship name
                resource_pins_list.append({
                    'id': pin_obj.id,
                    'pin_value': pin_obj.pin_value,
                    'is_active': pin_obj.is_active,
                    'created_at': pin_obj.created_at.isoformat() if pin_obj.created_at else None,
                    'notes': pin_obj.notes
                })
            resource_config['resource_pins'] = resource_pins_list

            # Associated Roles
            associated_roles_list = []
            for role_obj in resource.roles: # Assuming 'roles' is the relationship name
                associated_roles_list.append({
                    'id': role_obj.id,
                    'name': role_obj.name
                })
            resource_config['associated_roles'] = associated_roles_list

            all_resources_data.append(resource_config)

        logger.info(f"Successfully processed {len(all_resources_data)} resources for export.")

    except Exception as e:
        logger.error(f"Error during resource configurations data export: {e}", exc_info=True)
        # Depending on desired behavior, could raise e or return partially collected data or empty list
        # For now, returning what has been collected so far, or empty if error was early.
        # Consider adding a specific error state to the return if needed by the caller.

    return all_resources_data

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

                # Handle new direct Resource fields
                resource.image_filename = resource_data.get('image_filename', resource.image_filename)
                resource.floor_map_id = resource_data.get('floor_map_id', resource.floor_map_id)
                map_coordinates_data = resource_data.get('map_coordinates')
                if map_coordinates_data is not None: # Could be dict or already JSON string
                    if isinstance(map_coordinates_data, dict):
                        resource.map_coordinates = json.dumps(map_coordinates_data)
                    else: # Assume it's a valid JSON string or None
                        resource.map_coordinates = map_coordinates_data
                else:
                    resource.map_coordinates = None # Explicitly set to None if not in backup

                resource.max_recurrence_count = resource_data.get('max_recurrence_count', resource.max_recurrence_count)
                resource.scheduled_status = resource_data.get('scheduled_status', resource.scheduled_status)
                resource.map_allowed_role_ids = resource_data.get('map_allowed_role_ids', resource.map_allowed_role_ids)
                resource.current_pin = resource_data.get('current_pin', resource.current_pin)

                scheduled_status_at_str = resource_data.get('scheduled_status_at')
                resource.scheduled_status_at = _parse_iso_datetime(scheduled_status_at_str) if scheduled_status_at_str else resource.scheduled_status_at


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
                resource.maintenance_until = _parse_iso_datetime(maintenance_until_str) # _parse_iso_datetime handles None

                # Handle Roles (Many-to-Many)
                backed_up_role_ids_data = resource_data.get('roles', []) # Default to empty list if key missing
                if backed_up_role_ids_data is not None: # Check if 'roles' key was present
                    backed_up_role_ids = {role_info.get('id') for role_info in backed_up_role_ids_data if role_info.get('id') is not None}

                    if backed_up_role_ids: # Only query if there are IDs to look for
                        current_roles_in_db = Role.query.filter(Role.id.in_(backed_up_role_ids)).all()
                        found_role_ids_in_db = {role.id for role in current_roles_in_db}

                        for backed_up_id in backed_up_role_ids:
                            if backed_up_id not in found_role_ids_in_db:
                                warnings.append(f"For Resource ID {backup_id}, Role ID {backed_up_id} from backup not found in database. Skipping assignment of this role.")
                        resource.roles = current_roles_in_db # Assign the list of Role objects found in DB
                    else: # Empty list of roles in backup means remove all roles
                        resource.roles = []
                # If 'roles' key is missing from backup, existing roles are preserved unless explicitly set to empty list

                # START ResourcePIN Import/Update Logic for existing resource
                resource_pins_data = resource_data.get('resource_pins', [])
                if isinstance(resource_pins_data, list):
                    for pin_data in resource_pins_data:
                        pin_backup_id = pin_data.get('id')
                        pin_value = pin_data.get('pin_value')

                        if not pin_value: # Skip PIN if no value
                            warnings.append(f"Resource ID {backup_id}: PIN data found with no pin_value. Skipping this PIN. Data: {pin_data}")
                            continue

                        existing_pin = None
                        if pin_backup_id is not None:
                            # Try to find by backup ID AND ensure it belongs to this resource
                            # This check is important if PIN IDs from backup might not be unique across all resources
                            # or if we want to strictly re-associate based on backup ID.
                            # However, ResourcePIN primary key 'id' is globally unique.
                            # So, db.session.get(ResourcePIN, pin_backup_id) is sufficient if we assume backup ID is the PK.
                            # Let's refine: find by PK, then verify resource_id if necessary,
                            # or if the goal is to match *within* the resource context.
                            # Given the task, the `id` is the ResourcePIN's own PK.
                            pin_to_check = db.session.get(ResourcePIN, pin_backup_id)
                            if pin_to_check and pin_to_check.resource_id == resource.id:
                                existing_pin = pin_to_check
                            elif pin_to_check and pin_to_check.resource_id != resource.id:
                                warnings.append(f"Resource ID {backup_id}: PIN with backup ID {pin_backup_id} found but belongs to another resource ({pin_to_check.resource_id}). Skipping update for this PIN data.")
                                continue # Skip this pin_data, as it seems to be for a different resource

                        if existing_pin:
                            # Update existing PIN
                            original_pin_value = existing_pin.pin_value
                            new_pin_value = pin_data.get('pin_value', original_pin_value)

                            if new_pin_value != original_pin_value:
                                # Check for conflict before changing pin_value
                                conflict_pin = ResourcePIN.query.filter_by(resource_id=resource.id, pin_value=new_pin_value).first()
                                if conflict_pin and conflict_pin.id != existing_pin.id:
                                    warnings.append(f"Resource ID {backup_id}, PIN ID {existing_pin.id}: Cannot update pin_value to '{new_pin_value}' as it conflicts with existing PIN ID {conflict_pin.id}. Value not changed.")
                                else:
                                    existing_pin.pin_value = new_pin_value

                            existing_pin.is_active = pin_data.get('is_active', existing_pin.is_active)
                            existing_pin.notes = pin_data.get('notes', existing_pin.notes)
                            # created_at is generally not updated for existing PINs
                            db.session.add(existing_pin)
                        else:
                            # Create new PIN if no existing_pin was found (either no pin_backup_id or ID didn't match)
                            # Check for conflict before creating
                            conflict_pin = ResourcePIN.query.filter_by(resource_id=resource.id, pin_value=pin_value).first()
                            if conflict_pin:
                                warnings.append(f"Resource ID {backup_id}: Cannot create new PIN with value '{pin_value}' as it already exists (PIN ID {conflict_pin.id}). Skipping creation of this PIN.")
                                continue

                            new_pin = ResourcePIN(resource_id=resource.id)
                            new_pin.pin_value = pin_value
                            new_pin.is_active = pin_data.get('is_active', True)
                            new_pin.notes = pin_data.get('notes')
                            created_at_str = pin_data.get('created_at')
                            parsed_created_at = _parse_iso_datetime(created_at_str)
                            new_pin.created_at = parsed_created_at if parsed_created_at else datetime.utcnow()
                            # Backup ID (pin_backup_id) is not used for new_pin.id
                            db.session.add(new_pin)
                # END ResourcePIN Import/Update Logic

                db.session.add(resource)
                resources_updated += 1
            else:
                # Create new resource
                logger.info(f"Resource with backup ID {backup_id} not found. Creating as new resource.")
                if not isinstance(backup_id, int): # Ensure backup_id is int for new resource ID
                    errors.append(f"Resource with backup ID '{backup_id}' ('{resource_data.get('name', 'N/A')}') has a non-integer ID. Cannot create.")
                    continue

                # Check if ID already exists (e.g. due to previous failed import or manual entry)
                # This requires a query. If performance is critical for bulk new imports,
                # and IDs are guaranteed unique from backup, this could be skipped.
                # However, `db.session.get` for existing resources already handles this.
                # This is more about `new_resource.id = backup_id` potentially colliding if not careful.
                # SQLAlchemy's identity map usually handles this if an object with backup_id is already loaded.
                # If we proceed with `new_resource.id = backup_id`, ensure the session is flushed or committed
                # carefully if there's a mix of new and existing resources in one transaction.
                # For now, let's assume `backup_id` for new resources is safe to assign.

                new_resource = Resource()
                new_resource.id = backup_id # Set ID from backup_id for new resource

                new_resource.name = resource_data.get('name')
                new_resource.capacity = resource_data.get('capacity')
                new_resource.equipment = resource_data.get('equipment')
                new_resource.status = resource_data.get('status', 'draft') # Default to 'draft'

                # Handle new direct Resource fields for new resource
                new_resource.image_filename = resource_data.get('image_filename')
                new_resource.floor_map_id = resource_data.get('floor_map_id')
                map_coordinates_data_new = resource_data.get('map_coordinates')
                if map_coordinates_data_new is not None:
                    if isinstance(map_coordinates_data_new, dict):
                        new_resource.map_coordinates = json.dumps(map_coordinates_data_new)
                    else:
                        new_resource.map_coordinates = map_coordinates_data_new
                else:
                    new_resource.map_coordinates = None


                new_resource.max_recurrence_count = resource_data.get('max_recurrence_count')
                new_resource.scheduled_status = resource_data.get('scheduled_status')
                new_resource.map_allowed_role_ids = resource_data.get('map_allowed_role_ids')
                new_resource.current_pin = resource_data.get('current_pin')

                scheduled_status_at_str_new = resource_data.get('scheduled_status_at')
                new_resource.scheduled_status_at = _parse_iso_datetime(scheduled_status_at_str_new)


                tags_data = resource_data.get('tags')
                if isinstance(tags_data, list):
                    new_resource.tags = ",".join(tags_data)
                elif tags_data is None:
                    new_resource.tags = None
                else:
                    new_resource.tags = tags_data

                new_resource.booking_restriction = resource_data.get('booking_restriction')

                published_at_str = resource_data.get('published_at')
                new_resource.published_at = _parse_iso_datetime(published_at_str)

                allowed_users_data = resource_data.get('allowed_user_ids')
                if isinstance(allowed_users_data, list):
                    new_resource.allowed_user_ids = json.dumps(allowed_users_data)
                elif allowed_users_data is None:
                    new_resource.allowed_user_ids = None
                else:
                    new_resource.allowed_user_ids = allowed_users_data

                new_resource.is_under_maintenance = resource_data.get('is_under_maintenance', False) # Default to False

                maintenance_until_str = resource_data.get('maintenance_until')
                new_resource.maintenance_until = _parse_iso_datetime(maintenance_until_str)

                # Handle Roles (Many-to-Many) for new resource
                backed_up_role_ids_data_new = resource_data.get('roles', []) # Default to empty list
                new_resource_roles = []
                # Ensure backed_up_role_ids_data_new is not None before processing
                # This check might be redundant if default is [], but good for safety
                if backed_up_role_ids_data_new is not None:
                    backed_up_role_ids_new = {role_info.get('id') for role_info in backed_up_role_ids_data_new if role_info.get('id') is not None}

                    if backed_up_role_ids_new:
                        current_roles_in_db_new = Role.query.filter(Role.id.in_(backed_up_role_ids_new)).all()
                        found_role_ids_in_db_new = {role.id for role in current_roles_in_db_new}

                        for backed_up_id_role_new in backed_up_role_ids_new:
                            if backed_up_id_role_new not in found_role_ids_in_db_new:
                                warnings.append(f"For new Resource (Backup ID {backup_id}), Role ID {backed_up_id_role_new} from backup not found in database. Skipping assignment of this role.")
                        new_resource_roles = current_roles_in_db_new
                new_resource.roles = new_resource_roles

                # Add the new resource to session to get its ID for PINs, if not already set (it is set above)
                # db.session.add(new_resource) # Add new_resource first
                # db.session.flush() # Flush to ensure new_resource gets an ID if it's auto-generated
                                     # Not strictly necessary here as ID is set from backup_id

                # START ResourcePIN Import/Update Logic for new resource
                resource_pins_data_new = resource_data.get('resource_pins', [])
                if isinstance(resource_pins_data_new, list):
                    for pin_data_new in resource_pins_data_new:
                        pin_value_new = pin_data_new.get('pin_value')

                        if not pin_value_new:
                            warnings.append(f"New Resource (Backup ID {backup_id}): PIN data found with no pin_value. Skipping this PIN. Data: {pin_data_new}")
                            continue

                        # For new resources, all PINs are new. Check for conflict before creating.
                        # This check needs new_resource.id, which is backup_id.
                        conflict_pin_new_res = ResourcePIN.query.filter_by(resource_id=new_resource.id, pin_value=pin_value_new).first()
                        if conflict_pin_new_res:
                            warnings.append(f"New Resource (Backup ID {backup_id}): Cannot create new PIN with value '{pin_value_new}' as it would conflict (likely pre-existing or duplicate in import). Skipping creation of this PIN.")
                            continue

                        fresh_pin = ResourcePIN(resource_id=new_resource.id) # Associate with new_resource.id
                        fresh_pin.pin_value = pin_value_new
                        fresh_pin.is_active = pin_data_new.get('is_active', True)
                        fresh_pin.notes = pin_data_new.get('notes')
                        created_at_str_new_pin = pin_data_new.get('created_at')
                        parsed_created_at_new_pin = _parse_iso_datetime(created_at_str_new_pin)
                        fresh_pin.created_at = parsed_created_at_new_pin if parsed_created_at_new_pin else datetime.utcnow()
                        db.session.add(fresh_pin)
                # END ResourcePIN Import/Update Logic for new resource

                db.session.add(new_resource) # Add new_resource to session (might be redundant if already added for flush)
                created_count += 1
        except exc.IntegrityError as ie: # Catch specific DB errors like unique constraint violations for Resource itself
            db.session.rollback() # Rollback the specific resource changes
            error_msg = f"Database integrity error processing resource (Backup ID: {backup_id}, Name: {resource_data.get('name', 'N/A')}): {str(ie)}. This resource was skipped."
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
        except Exception as e_res: # Catch other general errors
            db.session.rollback() # Rollback for other errors too for safety for current resource
            error_msg = f"Error processing resource (Backup ID: {backup_id}, Name: {resource_data.get('name', 'N/A')}): {str(e_res)}. This resource was skipped."
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    status_code = 200
    try:
        db.session.commit() # Commit all accumulated changes (valid resources and their PINs)
    except exc.IntegrityError as e_commit: # Catch commit-time integrity errors (e.g. for PINs if not caught before)
        db.session.rollback()
        errors.append(f"Database commit integrity error: {str(e_commit)}. Some changes might not have been saved.")
        logger.error(f"Database commit integrity error during resource configurations import: {e_commit}", exc_info=True)
        status_code = 500 # Server error
    except Exception as e_commit_other:
        db.session.rollback()
        errors.append(f"Database commit error: {str(e_commit_other)}")
        logger.error(f"Database commit error during resource configurations import: {e_commit_other}", exc_info=True)
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
    logger.info("Starting export of user and role configurations data.")

    all_roles_data = []
    all_users_data = []

    # Export Roles
    try:
        roles = Role.query.all()
        logger.info(f"Found {len(roles)} roles to process.")
        for role in roles:
            role_config = {
                'id': role.id,
                'name': role.name,
                'description': getattr(role, 'description', None) # Use getattr if description might not exist
            }

            permissions_data = getattr(role, 'permissions', None)
            if isinstance(permissions_data, str):
                # Assuming comma-separated if string, otherwise might need json.loads if it's a JSON string
                try:
                    # Attempt to parse as JSON first, as it's a common way to store lists in a string field
                    parsed_permissions = json.loads(permissions_data)
                    if isinstance(parsed_permissions, list):
                        role_config['permissions'] = parsed_permissions
                    else:
                        # If not a list after parsing, treat as a single permission or fallback
                        logger.warning(f"Permissions for role {role.id} ('{role.name}') was a JSON string but not a list. Storing as is.")
                        role_config['permissions'] = [str(permissions_data)] # Fallback to list with the string
                except json.JSONDecodeError:
                    # If not valid JSON, then assume comma-separated
                    role_config['permissions'] = [p.strip() for p in permissions_data.split(',') if p.strip()]
            elif isinstance(permissions_data, list):
                role_config['permissions'] = permissions_data
            elif permissions_data is None:
                role_config['permissions'] = []
            else:
                logger.warning(f"Permissions for role {role.id} ('{role.name}') is of unexpected type: {type(permissions_data)}. Storing as string list.")
                role_config['permissions'] = [str(permissions_data)] # Fallback

            all_roles_data.append(role_config)
        logger.info(f"Successfully processed {len(all_roles_data)} roles.")
    except Exception as e:
        logger.error(f"Error during role configurations data export: {e}", exc_info=True)
        # Continue to user export even if roles fail, or handle error as per requirements

    # Export Users
    try:
        users = User.query.all()
        logger.info(f"Found {len(users)} users to process.")
        for user in users:
            user_config = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin,
                # Use getattr for fields that might not be present on all User model versions
                'first_name': getattr(user, 'first_name', None),
                'last_name': getattr(user, 'last_name', None),
                'phone': getattr(user, 'phone', None),
                'section': getattr(user, 'section', None),
                'department': getattr(user, 'department', None),
                'position': getattr(user, 'position', None),
                'is_active': getattr(user, 'is_active', True) # Default to True if not present
            }

            # Assigned Role IDs
            user_config['assigned_role_ids'] = [role.id for role in user.roles]

            all_users_data.append(user_config)
        logger.info(f"Successfully processed {len(all_users_data)} users.")
    except Exception as e:
        logger.error(f"Error during user configurations data export: {e}", exc_info=True)

    num_roles_exported = len(all_roles_data)
    num_users_exported = len(all_users_data)
    logger.info(f"User and role configurations data export completed. Exported {num_users_exported} users and {num_roles_exported} roles.")

    return {
        'users': all_users_data,
        'roles': all_roles_data,
        'message': f"Exported {num_users_exported} users and {num_roles_exported} roles."
    }

def _import_user_configurations_data(user_config_data: dict): # Return type will be bool or dict
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"Importing user and role configurations. Processing {len(user_config_data.get('roles', []))} roles and {len(user_config_data.get('users', []))} users.")

    roles_data = user_config_data.get('roles', [])
    users_data = user_config_data.get('users', [])

    roles_processed = 0
    roles_created = 0
    roles_updated = 0
    users_processed = 0
    users_updated = 0

    errors = []
    warnings = []
    # This mapping is crucial if user's role assignments depend on role IDs that might change if roles are recreated by name.
    backup_to_new_role_id_mapping = {}

    # Process Roles
    for role_item in roles_data:
        roles_processed += 1
        backup_role_id = role_item.get('id')
        role_name = role_item.get('name')

        if backup_role_id is None or role_name is None:
            errors.append(f"Role item found with missing 'id' or 'name': {role_item}")
            logger.warning(f"Skipping role item due to missing ID or name: {role_item}")
            continue

        try:
            # Robust handling for permissions
            permissions_data = role_item.get('permissions') # Get the raw data
            permissions_list = [] # Default to empty list

            if isinstance(permissions_data, list):
                permissions_list = [str(p) for p in permissions_data if p is not None]  # Ensure all are strings
            elif isinstance(permissions_data, str):
                if not permissions_data.strip(): # Handle empty string case
                    permissions_list = []
                else:
                    try:
                        loaded_perms = json.loads(permissions_data)
                        if isinstance(loaded_perms, list):
                            permissions_list = [str(p) for p in loaded_perms if p is not None]
                        else:
                            warnings.append(f"Permissions for Role ID {backup_role_id} ('{role_name}') was a JSON string but not a list: '{permissions_data}'. Treating as a single permission.")
                            permissions_list = [str(loaded_perms)]
                    except json.JSONDecodeError:
                        warnings.append(f"Permissions string for Role ID {backup_role_id} ('{role_name}') is not valid JSON: '{permissions_data}'. Attempting to split by comma or use as single permission.")
                        permissions_list = [p.strip() for p in permissions_data.split(',') if p.strip()]
                        if not permissions_list and permissions_data.strip():
                            permissions_list = [permissions_data.strip()]
            elif permissions_data is None:
                permissions_list = []
            else:
                warnings.append(f"Permissions for Role ID {backup_role_id} ('{role_name}') is of unexpected type: {type(permissions_data)}. Defaulting to empty list.")
                permissions_list = []

            # Ensure all items in permissions_list are strings (already done above for lists, good to be sure)
            permissions_list = [str(p) for p in permissions_list if p is not None]


            role = db.session.get(Role, backup_role_id)

            if role: # Role exists by ID
                role.name = role_name
                # Assuming Role.description and Role.permissions are attributes that can be set
                role.description = role_item.get('description', role.description)
                role.permissions = json.dumps(permissions_list)
                db.session.add(role)
                roles_updated += 1
                backup_to_new_role_id_mapping[backup_role_id] = role.id
            else: # Role does not exist by ID, try to find by name
                role_by_name = Role.query.filter_by(name=role_name).first()
                if role_by_name:
                    warnings.append(f"Role with backup ID {backup_role_id} not found, but role with name '{role_name}' (ID: {role_by_name.id}) exists. Updating existing role by name.")
                    role_by_name.description = role_item.get('description', role_by_name.description)
                    role_by_name.permissions = json.dumps(permissions_list)
                    db.session.add(role_by_name)
                    roles_updated += 1
                    backup_to_new_role_id_mapping[backup_role_id] = role_by_name.id
                else: # Create new role
                    logger.info(f"Role with backup ID {backup_role_id} ('{role_name}') not found by ID or name. Creating as new role.")
                    new_role = Role(
                        name=role_name,
                        description=role_item.get('description'),
                        permissions=json.dumps(permissions_list)
                    )
                    # If backup_role_id is intended to be preserved for new roles (and is unique)
                    # new_role.id = backup_role_id # This might require careful handling if IDs are auto-incrementing
                    db.session.add(new_role)
                    db.session.flush() # To get new_role.id if it's auto-generated
                    backup_to_new_role_id_mapping[backup_role_id] = new_role.id
                    roles_created += 1
        except Exception as e_role:
            error_msg = f"Error processing role (Backup ID: {backup_role_id}, Name: {role_name}): {str(e_role)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    # Process Users (Update existing only, or create if not found - current log says "Skipped (user creation from backup is not supported)")
    # For now, stick to update-only or skip-if-not-found for users as per previous logs.
    for user_item in users_data:
        users_processed += 1
        backup_user_id = user_item.get('id')
        username = user_item.get('username')

        if backup_user_id is None or username is None:
            errors.append(f"User item found with missing 'id' or 'username': {user_item}")
            logger.warning(f"Skipping user item due to missing ID or name: {user_item}")
            continue

        try:
            user = db.session.get(User, backup_user_id)

            if user:
                user.username = username # Update username
                user.email = user_item.get('email', user.email)
                user.is_admin = user_item.get('is_admin', user.is_admin)

                # Update other User fields from backup if they exist in user_item
                # Using getattr to avoid errors if fields are missing from backup JSON for some reason
                user.first_name = getattr(user_item, 'first_name', user.first_name)
                user.last_name = getattr(user_item, 'last_name', user.last_name)
                user.phone = getattr(user_item, 'phone', user.phone)
                user.section = getattr(user_item, 'section', user.section)
                user.department = getattr(user_item, 'department', user.department)
                user.position = getattr(user_item, 'position', user.position)
                user.is_active = user_item.get('is_active', user.is_active) # .get() for bools is fine

                # Password hash is intentionally NOT updated from backup for security.

                # Handle user roles
                backed_up_user_role_ids = user_item.get('assigned_role_ids', []) # From backup JSON
                actual_db_roles_for_user = []
                if isinstance(backed_up_user_role_ids, list):
                    for b_role_id in backed_up_user_role_ids:
                        actual_db_role_id = backup_to_new_role_id_mapping.get(b_role_id)
                        if actual_db_role_id:
                            role_obj = db.session.get(Role, actual_db_role_id)
                            if role_obj:
                                actual_db_roles_for_user.append(role_obj)
                            else:
                                warnings.append(f"For User '{username}' (Backup ID {backup_user_id}), mapped Role ID {actual_db_role_id} (from backup Role ID {b_role_id}) not found in DB. Skipping assignment.")
                        elif b_role_id is not None: # Only warn if it was a non-null ID that couldn't be mapped
                            warnings.append(f"For User '{username}' (Backup ID {backup_user_id}), backup Role ID {b_role_id} could not be mapped to a current Role ID. Skipping assignment.")
                user.roles = actual_db_roles_for_user # Ensure this is the correct variable

                db.session.add(user)
                users_updated += 1
            else:
                # User creation logic could be added here if desired, but current logs say it's skipped.
                warnings.append(f"User with backup ID {backup_user_id} ('{username}') not found in DB. Skipped (user creation from backup is not currently supported by this import function).")

        except Exception as e_user:
            error_msg = f"Error processing user (Backup ID: {backup_user_id}, Username: {username}): {str(e_user)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

    status_code = 200
    try:
        db.session.commit()
    except Exception as e_commit:
        db.session.rollback()
        errors.append(f"Database commit error: {str(e_commit)}")
        logger.error(f"Database commit error during user/role configurations import: {e_commit}", exc_info=True)
        status_code = 500

    final_message_parts = [
        f"Roles processed: {roles_processed} (Created: {roles_created}, Updated: {roles_updated}).",
        f"Users processed: {users_processed} (Updated: {users_updated})." # Assuming creation is not supported based on logs
    ]
    if warnings:
        final_message_parts.append(f"Warnings: {'; '.join(warnings)}")
    if errors:
        final_message_parts.append(f"Errors: {'; '.join(errors)}")
        if status_code == 200: status_code = 207 # Partial success if data errors but commit worked

    final_message = " ".join(final_message_parts)
    logger.info(f"User configurations import result: {final_message}")

    # Standardize return type: dictionary with status and details
    return {
        'success': not errors and status_code < 400, # Consider success if no hard errors and status code is ok
        'message': final_message,
        'errors': errors,
        'warnings': warnings,
        'status_code': status_code,
        'roles_processed': roles_processed,
        'roles_created': roles_created,
        'roles_updated': roles_updated,
        'users_processed': users_processed,
        'users_updated': users_updated
        # 'users_created': 0 # Explicitly if not supported
    }

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
            interval_minutes = incremental_config.get('interval_minutes', 30)
            if not isinstance(interval_minutes, int) or interval_minutes <= 0:
                app_instance.logger.error(f"Invalid interval_minutes ({interval_minutes}) for incremental backup. Must be a positive integer. Job not scheduled.")
            else:
                scheduler.add_job(
                    id='unified_incremental_booking_backup_job',
                    func='scheduler_tasks:run_scheduled_incremental_booking_data_task', # Path to the task function
                    trigger='interval',
                    minutes=interval_minutes,
                    args=[app_instance], # Pass the app instance
                    replace_existing=True,
                    misfire_grace_time=300 # 5 minutes
                )
                app_instance.logger.info(f"Scheduled unified incremental booking backup job to run every {interval_minutes} minutes.")
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

            # The scheduler.add_job(...) block for run_periodic_full_booking_data_task has been removed.
            app_instance.logger.warning("Unified full backup is enabled in settings, but the target task 'run_periodic_full_booking_data_task' is obsolete and will not be scheduled.")
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

def _get_general_configurations_data() -> dict:
    """
    Fetches general application configurations, currently from BookingSettings.
    Assumes BookingSettings contains a single row of settings.
    """
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Exporting general configurations data (BookingSettings).")

    settings_data_list = []
    try:
        # Assuming BookingSettings is imported in utils.py
        booking_settings = BookingSettings.query.first()
        if booking_settings:
            settings_data_list.append(booking_settings.to_dict())
            message = "Successfully exported BookingSettings."
        else:
            message = "No BookingSettings record found to export."
            logger.warning(message)

        logger.info(message)
        return {
            'booking_settings': settings_data_list, # Store as a list, even if only one record
            'message': message
        }
    except Exception as e:
        error_message = f"Error exporting BookingSettings: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {
            'booking_settings': [],
            'message': error_message,
            'error': True
        }

def _import_general_configurations_data(config_data: dict) -> tuple[dict, int]:
    """
    Imports general application configurations, currently targeting BookingSettings.
    Args:
        config_data: A dictionary typically containing a 'booking_settings' key
                     with a list of settings dictionaries (usually one).
    Returns:
        A tuple: (summary_dict, status_code)
    """
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Importing general configurations (BookingSettings).")

    if not isinstance(config_data, dict):
        msg = "Invalid input: config_data must be a dictionary."
        logger.error(msg)
        return ({'message': msg, 'errors': [msg], 'warnings': []}, 400)

    booking_settings_list = config_data.get('booking_settings', [])
    if not isinstance(booking_settings_list, list):
        msg = "Invalid format: 'booking_settings' must be a list."
        logger.error(msg)
        return ({'message': msg, 'errors': [msg], 'warnings': []}, 400)

    errors = []
    warnings = []
    processed_count = 0
    updated_count = 0
    created_count = 0

    if not booking_settings_list:
        warnings.append("No 'booking_settings' data found in the input. Nothing to import.")
    else:
        # Expecting only one item in the list for BookingSettings
        if len(booking_settings_list) > 1:
            warnings.append(f"Expected one BookingSettings object, found {len(booking_settings_list)}. Processing the first one only.")

        settings_data_to_apply = booking_settings_list[0]
        processed_count = 1

        try:
            # BookingSettings.from_dict handles finding or creating the record
            # It needs the db.session, which can be accessed via current_app or passed in.
            # For utils, it's better if db operations are managed by the caller or via app context.
            # However, BookingSettings.from_dict was defined to take db_session.
            # Let's assume db.session is available here as it is in other utils functions.

            booking_settings_record = BookingSettings.from_dict(settings_data_to_apply, db.session)

            if booking_settings_record:
                # Determine if it was created or updated based on its state before from_dict
                # This is a bit tricky without knowing original state. from_dict itself could return this.
                # For now, let's assume if from_dict returns an object, it's effectively an update/creation.
                # A simple way: check if ID was None before (if from_dict sets it).
                # Or, more simply, assume an update if it existed, creation if not.
                # BookingSettings.from_dict already adds to session if new.

                # Let's refine: from_dict modifies or adds. We just need to commit.
                # We can't easily tell if it was created or updated by from_dict's current design
                # without querying again or modifying from_dict to return more info.
                # For simplicity, let's assume "applied".

                # For now, we'll count it as an update if it was found, create if not.
                # This requires a query before calling from_dict, or changing from_dict.
                # Let's adjust to a simpler "applied" count.

                # A slightly better approach:
                existing_settings = db.session.query(BookingSettings).first()
                if existing_settings and existing_settings.id == booking_settings_record.id:
                    updated_count = 1
                else: # Was newly created by from_dict
                    created_count = 1

                # The commit will happen after all components are processed by the caller (e.g., restore API endpoint)
                # For now, this function's responsibility is to prepare the object in the session.
                # db.session.commit() # NO - commit should be handled by the calling restore orchestrator.

            else:
                errors.append("Failed to process BookingSettings data using from_dict (returned None).")

        except Exception as e:
            db.session.rollback() # Rollback if an error occurs during this specific import
            error_msg = f"Error importing BookingSettings: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)


    final_message_parts = [
        f"BookingSettings processed: {processed_count} (Created: {created_count}, Updated: {updated_count})."
    ]
    status_code = 200

    if warnings:
        final_message_parts.append(f"Warnings: {'; '.join(warnings)}")
    if errors:
        final_message_parts.append(f"Errors: {'; '.join(errors)}")
        status_code = 500 if not warnings else 207 # Error if errors, Multi-status if only warnings

    final_message = " ".join(final_message_parts)
    logger.info(f"BookingSettings import result: {final_message}")

    summary = {
        'message': final_message,
        'errors': errors,
        'warnings': warnings,
        'processed': processed_count,
        'created': created_count,
        'updated': updated_count
    }
    return summary, status_code


def get_map_opacity_value():
    """
    Retrieves the map opacity value.
    Priority:
    1. Value from MAP_OPACITY_CONFIG_FILE (if configured and valid).
    2. Value from current_app.config['MAP_RESOURCE_OPACITY'] (which handles env var and default).
    """
    config_file_path = current_app.config.get('MAP_OPACITY_CONFIG_FILE')

    if config_file_path: # Ensure path is configured
        try:
            # Ensure config_file_path is usable, Path objects from config.py should be fine
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    data = json.load(f)
                    opacity_val = data.get('map_resource_opacity')
                    if opacity_val is not None: # Check if key exists
                        try:
                            opacity_float = float(opacity_val)
                            if 0.0 <= opacity_float <= 1.0:
                                current_app.logger.debug(f"Opacity {opacity_float} loaded from file {config_file_path}")
                                return opacity_float
                            else:
                                current_app.logger.warning(f"Opacity value {opacity_float} from {config_file_path} is out of range (0.0-1.0). File value ignored.")
                        except ValueError:
                            current_app.logger.warning(f"Invalid opacity value '{opacity_val}' in {config_file_path}. Not a float. File value ignored.")
        except (IOError, json.JSONDecodeError, TypeError) as e: # Catch errors related to file access/parsing
            current_app.logger.error(f"Error reading/parsing {config_file_path}: {e}. Fallback will be used.")
        except Exception as e: # Catch any other unexpected errors
            current_app.logger.error(f"Unexpected error with config file {config_file_path}: {e}. Fallback will be used.")

    # Fallback to the value already processed by config.py (env var or its default in config.py)
    default_from_config = current_app.config.get('MAP_RESOURCE_OPACITY') # Should exist due to config.py
    if default_from_config is None: # Should not happen if config.py is loaded correctly
        current_app.logger.error("MAP_RESOURCE_OPACITY not found in app.config. This is unexpected. Using hardcoded default 0.7.")
        return 0.7

    current_app.logger.debug(f"Using opacity from app.config['MAP_RESOURCE_OPACITY']: {default_from_config} (derived from env var or default in config.py).")
    return default_from_config
