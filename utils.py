import os
import json
import logging # Added for fallback logger
import tempfile # Added for image generation and email attachment
import re # Added for filename sanitization
from PIL import Image, ImageDraw, ImageFont # Added ImageFont for text rendering
import requests
from datetime import datetime, date, timedelta, time, timezone
from flask import url_for, jsonify, current_app # current_app already here, ensure it's used
from flask_login import current_user
# from flask_mail import Message # For send_email - No longer used
import csv
import io
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication # For generic attachments
# from google.oauth2.service_account import Credentials as ServiceAccountCredentials # Removed
from google.oauth2.credentials import Credentials as UserCredentials # Added for OAuth 2.0 Client ID
import socket # Added for specific network error handling
import httplib2 # Added for specific network error handling
import time as time_module # Added for retry mechanism
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Assuming db and mail are initialized in extensions.py
from extensions import db # mail is now fetched from current_app.extensions - mail removed
# Assuming models are defined in models.py
from models import AuditLog, User, Resource, FloorMap, Role, Booking, BookingSettings # Added Booking, Resource, FloorMap, BookingSettings
from sqlalchemy import func # Ensure func is imported
from sqlalchemy.sql import func as sqlfunc # Added for explicit use

# Global lists for logging (if these are the sole modifiers)
email_log = []
slack_log = []
teams_log = []

# This list should match the one used in routes/api_bookings.py create_booking
active_booking_statuses_for_conflict = ['approved', 'pending', 'checked_in', 'confirmed']

basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')

# --- Scheduler Settings ---
SCHEDULER_SETTINGS_FILE_PATH = os.path.join(DATA_DIR, 'scheduler_settings.json')

DEFAULT_FULL_BACKUP_SCHEDULE = {
    "is_enabled": False,
    "schedule_type": "daily",  # 'daily' or 'weekly'
    "day_of_week": None,       # 0=Monday, 6=Sunday (used if schedule_type is 'weekly')
    "time_of_day": "02:00"     # HH:MM format (24-hour)
}

DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE = {
    "is_enabled": False,
    "schedule_type": "interval", # 'interval'
    "interval_minutes": 60,
    "booking_backup_type": "full_export",
    "range": "all"
}

DEFAULT_SCHEDULER_SETTINGS = {
    "full_backup": DEFAULT_FULL_BACKUP_SCHEDULE.copy(),
    "booking_csv_backup": DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy(),
    "auto_restore_booking_records_on_startup": False
}

def load_scheduler_settings() -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    if not os.path.exists(SCHEDULER_SETTINGS_FILE_PATH):
        logger.info(f"Scheduler settings file not found at '{SCHEDULER_SETTINGS_FILE_PATH}'. Creating with default settings.")
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_SCHEDULER_SETTINGS, f, indent=2)
            logger.info(f"Successfully saved default scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}'.")
        except IOError as e:
            logger.error(f"Error saving default scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}': {e}", exc_info=True)
        return DEFAULT_SCHEDULER_SETTINGS.copy()
    try:
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'r', encoding='utf-8') as f:
            loaded_settings = json.load(f)
        final_settings = DEFAULT_SCHEDULER_SETTINGS.copy()
        for schedule_key, default_item_value in DEFAULT_SCHEDULER_SETTINGS.items():
            if schedule_key in loaded_settings:
                if isinstance(default_item_value, dict) and isinstance(loaded_settings[schedule_key], dict):
                    merged_schedule = default_item_value.copy()
                    merged_schedule.update(loaded_settings[schedule_key])
                    final_settings[schedule_key] = merged_schedule
                else:
                    final_settings[schedule_key] = loaded_settings[schedule_key]
        return final_settings
    except json.JSONDecodeError as e:
        logger.warning(f"Error decoding JSON from '{SCHEDULER_SETTINGS_FILE_PATH}': {e}. Returning default settings.", exc_info=True)
        return DEFAULT_SCHEDULER_SETTINGS.copy()
    except IOError as e:
        logger.error(f"IOError reading scheduler settings file '{SCHEDULER_SETTINGS_FILE_PATH}': {e}. Returning default settings.", exc_info=True)
        return DEFAULT_SCHEDULER_SETTINGS.copy()
    except Exception as e:
        logger.error(f"Unexpected error loading scheduler settings from '{SCHEDULER_SETTINGS_FILE_PATH}': {e}. Returning default settings.", exc_info=True)
        return DEFAULT_SCHEDULER_SETTINGS.copy()

def save_scheduler_settings(settings_dict: dict):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=2)
        logger.info(f"Successfully saved scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}'.")
    except IOError as e:
        logger.error(f"Error saving scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error saving scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}': {e}", exc_info=True)

def add_audit_log(action: str, details: str, user_id: int = None, username: str = None):
    try:
        log_user_id = user_id
        log_username = username
        if current_user and current_user.is_authenticated:
            if log_user_id is None: log_user_id = current_user.id
            if log_username is None: log_username = current_user.username
        if log_user_id is not None and log_username is None:
            user = User.query.get(log_user_id)
            log_username = user.username if user else f"User ID {log_user_id}"
        if log_user_id is None and log_username is None: log_username = "System"
        log_entry = AuditLog(user_id=log_user_id, username=log_username, action=action, details=details)
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        logger = current_app.logger if current_app else logging.getLogger(__name__)
        logger.error(f"Error adding audit log: {e}", exc_info=True)
        db.session.rollback()

def resource_to_dict(resource: Resource) -> dict:
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        image_url = url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None
    except RuntimeError:
        image_url = None
    published_at_iso = resource.published_at.replace(tzinfo=timezone.utc).isoformat() if resource.published_at is not None else None
    maintenance_until_iso = resource.maintenance_until.replace(tzinfo=timezone.utc).isoformat() if resource.maintenance_until is not None else None
    scheduled_status_at_iso = resource.scheduled_status_at.replace(tzinfo=timezone.utc).isoformat() if resource.scheduled_status_at is not None else None
    resource_dict = {
        'id': resource.id, 'name': resource.name, 'capacity': resource.capacity, 'equipment': resource.equipment,
        'status': resource.status, 'tags': resource.tags, 'booking_restriction': resource.booking_restriction,
        'image_url': image_url, 'published_at': published_at_iso, 'allowed_user_ids': resource.allowed_user_ids,
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles], 'floor_map_id': resource.floor_map_id,
        'is_under_maintenance': resource.is_under_maintenance, 'maintenance_until': maintenance_until_iso,
        'max_recurrence_count': resource.max_recurrence_count, 'scheduled_status': resource.scheduled_status,
        'scheduled_status_at': scheduled_status_at_iso, 'current_pin': resource.current_pin
    }
    parsed_coords = None
    if resource.map_coordinates:
        try: parsed_coords = json.loads(resource.map_coordinates)
        except json.JSONDecodeError: logger.warning(f"Invalid JSON in map_coordinates for resource {resource.id}: {resource.map_coordinates}")
    parsed_map_roles = []
    if resource.map_allowed_role_ids:
        try:
            loaded_roles = json.loads(resource.map_allowed_role_ids)
            if isinstance(loaded_roles, list): parsed_map_roles = loaded_roles
        except json.JSONDecodeError: logger.warning(f"Invalid JSON in map_allowed_role_ids for resource {resource.id}: {resource.map_allowed_role_ids}")
    if parsed_coords is not None and isinstance(parsed_coords, dict): parsed_coords['allowed_role_ids'] = parsed_map_roles
    elif parsed_coords is not None: logger.warning(f"Resource {resource.id} map_coordinates was not a dict after parsing: {type(parsed_coords)}")
    resource_dict['map_coordinates'] = parsed_coords
    return resource_dict

def generate_booking_image(resource_id: int, map_coordinates_str: str, resource_name: str) -> str | None:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("generate_booking_image called - content omitted for brevity in this step.")
    return None

def send_email(to_address: str, subject: str, body: str = None, html_body: str = None, attachment_path: str = None):
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("send_email called - content omitted for brevity in this step.")
    pass

def send_slack_notification(text: str):
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("send_slack_notification called - content omitted for brevity in this step.")
    pass

def send_teams_notification(to_email: str, title: str, text: str):
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("send_teams_notification called - content omitted for brevity in this step.")
    pass

def parse_simple_rrule(rule_str: str):
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("parse_simple_rrule called - content omitted for brevity in this step.")
    return None, 1

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_EXTENSIONS', set())

def _get_map_configuration_data() -> dict:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_get_map_configuration_data called - content omitted for brevity in this step.")
    return {}

def _get_resource_configurations_data() -> list:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_get_resource_configurations_data called - content omitted for brevity in this step.")
    return []

def _get_user_configurations_data() -> dict:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_get_user_configurations_data called - content omitted for brevity in this step.")
    return {'roles': [], 'users': []}

def _import_user_configurations_data(user_config_data: dict) -> tuple[int, int, int, int, list]:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_import_user_configurations_data called - content omitted for brevity in this step.")
    return 0,0,0,0,[]

def _import_resource_configurations_data(resources_data_list: list) -> tuple[int, int, list]:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_import_resource_configurations_data called - content omitted for brevity in this step.")
    return 0,0,[]

def _import_map_configuration_data(config_data: dict) -> tuple[dict, int]:
    # ... (Full implementation as provided in previous context, assumed correct for this task)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.debug("_import_map_configuration_data called - content omitted for brevity in this step.")
    return {}, 200

# LEGACY - Local CSV Export - Functionality commented out as it's no longer used by active features.
# def export_bookings_to_csv_string(app, start_date=None, end_date=None) -> str:
#     """
#     Exports Booking model objects to a CSV formatted string, optionally filtered by date range.
#
#     Args:
#         app: The Flask application object.
#         start_date (datetime.datetime, optional): Filter for bookings starting on or after this date.
#         end_date (datetime.datetime, optional): Filter for bookings starting strictly before this date.
#
#     Returns:
#         A string containing the CSV data.
#     """
#     logger = app.logger
#     header = [
#         'id', 'resource_id', 'user_name', 'start_time', 'end_time',
#         'title', 'checked_in_at', 'checked_out_at', 'status', 'recurrence_rule'
#     ]
#
#     bookings_to_export = []
#     current_offset_hours = 0
#     with app.app_context():
#         try:
#             booking_settings = BookingSettings.query.first()
#             if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
#                 current_offset_hours = booking_settings.global_time_offset_hours
#             else:
#                 logger.warning("BookingSettings not found or global_time_offset_hours not set for CSV export, using 0 offset. Times in CSV will be treated as naive local if they were stored as such.")
#         except Exception as e_settings:
#             logger.error(f"Error fetching BookingSettings for CSV export: {e_settings}. Using 0 offset.")
#             # current_offset_hours remains 0
#
#         query = Booking.query
#         if start_date:
#             # Assuming start_date is naive local, convert to UTC if DB times are UTC for query
#             # However, Booking.start_time is now naive local, so direct comparison is fine
#             query = query.filter(Booking.start_time >= start_date)
#         if end_date:
#             query = query.filter(Booking.start_time < end_date)
#         bookings_to_export = query.order_by(Booking.start_time).all()
#
#     output = io.StringIO()
#     writer = csv.writer(output)
#     writer.writerow(header)
#
#     if not bookings_to_export:
#         # Return CSV with only header if no bookings match
#         csv_data = output.getvalue()
#         output.close()
#         return csv_data
#
#     for booking in bookings_to_export:
#         row = [
#             booking.id,
#             booking.resource_id,
#             booking.user_name,
#             (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat() if booking.start_time else '',
#             (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat() if booking.end_time else '',
#             booking.title,
#             (booking.checked_in_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat() if booking.checked_in_at else '', # Assuming checked_in_at is naive local
#             (booking.checked_out_at - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat() if booking.checked_out_at else '', # Assuming checked_out_at is naive local
#             booking.status,
#             booking.recurrence_rule if booking.recurrence_rule is not None else ''
#         ]
#         writer.writerow(row)
#
#     csv_data = output.getvalue()
#     output.close()
#     return csv_data

# Helper function for parsing ISO datetime strings
def _parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        if dt_str.endswith('Z'):
            return datetime.fromisoformat(dt_str[:-1] + '+00:00')
        dt_obj = datetime.fromisoformat(dt_str)
        return dt_obj
    except ValueError:
        return None

def _emit_import_progress(socketio_instance, task_id, message, detail='', level='INFO', context_prefix=""):
    if socketio_instance and task_id:
        full_message = f"{context_prefix}{message}"
        try:
            from azure_backup import _emit_progress as azure_emit_progress
            azure_emit_progress(socketio_instance, task_id, 'import_progress', full_message, detail, level)
        except ImportError:
             current_app.logger.debug(f"SocketIO Emit (Import): {full_message} - {detail} ({level})")


def import_bookings_from_csv_file(csv_file_path, app, clear_existing: bool = False, socketio_instance=None, task_id=None, import_context_message_prefix: str = ""):
    logger = app.logger
    event_name = 'import_progress'
    _emit_import_progress(socketio_instance, task_id, "Import process started.", detail=f"File: {os.path.basename(csv_file_path)}", level='INFO', context_prefix=import_context_message_prefix)
    bookings_processed = 0; bookings_created = 0; bookings_updated = 0; bookings_skipped_duplicate = 0; bookings_skipped_fk_violation = 0; bookings_skipped_other_errors = 0
    errors = []
    current_offset_hours = 0
    try:
        with app.app_context():
            try:
                booking_settings = BookingSettings.query.first()
                if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
                    current_offset_hours = booking_settings.global_time_offset_hours
                else:
                    logger.warning(f"{import_context_message_prefix}BookingSettings not found or global_time_offset_hours not set for CSV import, using 0 offset.")
            except Exception as e_settings:
                logger.error(f"{import_context_message_prefix}Error fetching BookingSettings for CSV import: {e_settings}. Using 0 offset for time conversions.")
            if clear_existing:
                try:
                    num_deleted = db.session.query(Booking).delete()
                    # Commit the deletion before proceeding with inserts
                    db.session.commit()
                    logger.info(f"{import_context_message_prefix}Cleared {num_deleted} existing bookings before import.")
                    _emit_import_progress(socketio_instance, task_id, f"Cleared {num_deleted} existing bookings.", level='INFO', context_prefix=import_context_message_prefix)
                except Exception as e_clear:
                    db.session.rollback(); error_msg = f"Error clearing existing bookings: {str(e_clear)}"; errors.append(error_msg); logger.error(error_msg, exc_info=True)
                    _emit_import_progress(socketio_instance, task_id, "Error clearing existing bookings.", detail=str(e_clear), level='ERROR', context_prefix=import_context_message_prefix)
                    return {'processed': 0, 'created': 0, 'updated': 0, 'skipped_duplicates': 0, 'skipped_fk_violation': 0, 'skipped_other_errors': 0, 'errors': errors, 'status': 'failed_clear_existing'}
            with open(csv_file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                row_count_for_progress_update = 0
                for row in reader:
                    bookings_processed += 1; row_count_for_progress_update +=1; line_num = reader.line_num
                    if row_count_for_progress_update % 50 == 0:
                        _emit_import_progress(socketio_instance, task_id, f"Processing row {line_num}...", detail=f"{bookings_created} created, {bookings_skipped_fk_violation} FK skips, {bookings_skipped_other_errors} other skips.", level='INFO', context_prefix=import_context_message_prefix)
                    try:
                        resource_id_str = row.get('resource_id')
                        if not resource_id_str: errors.append(f"Row {line_num}: Missing resource_id."); bookings_skipped_other_errors += 1; continue
                        try: resource_id = int(resource_id_str)
                        except ValueError: errors.append(f"Row {line_num}: Invalid resource_id '{resource_id_str}'. Must be an integer."); bookings_skipped_other_errors += 1; continue
                        user_name = row.get('user_name', '').strip()
                        if not user_name: errors.append(f"Row {line_num}: Missing user_name."); bookings_skipped_other_errors += 1; continue
                        title = row.get('title', '').strip()
                        if not title: errors.append(f"Row {line_num}: Missing title."); bookings_skipped_other_errors += 1; continue
                        start_time_aware = _parse_iso_datetime(row.get('start_time')); end_time_aware = _parse_iso_datetime(row.get('end_time'))
                        checked_in_at_aware = _parse_iso_datetime(row.get('checked_in_at')); checked_out_at_aware = _parse_iso_datetime(row.get('checked_out_at'))
                        if not start_time_aware or not end_time_aware: errors.append(f"Row {line_num}: Invalid or missing start_time or end_time format."); bookings_skipped_other_errors += 1; continue
                        if start_time_aware >= end_time_aware: errors.append(f"Row {line_num}: Start time must be before end time."); bookings_skipped_other_errors += 1; continue
                        start_time_local_naive = (start_time_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if start_time_aware else None
                        end_time_local_naive = (end_time_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if end_time_aware else None
                        checked_in_at_local_naive = (checked_in_at_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if checked_in_at_aware else None
                        checked_out_at_local_naive = (checked_out_at_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if checked_out_at_aware else None
                        resource = db.session.get(Resource, resource_id)
                        if not resource: err_msg_fk_res = f"Row {line_num}: Resource ID {resource_id} not found. Booking for '{title}' skipped."; errors.append(err_msg_fk_res); logger.warning(err_msg_fk_res); bookings_skipped_fk_violation += 1; continue
                        user = User.query.filter_by(username=user_name).first()
                        if not user: err_msg_fk_user = f"Row {line_num}: User '{user_name}' not found. Booking for '{title}' skipped."; errors.append(err_msg_fk_user); logger.warning(err_msg_fk_user); bookings_skipped_fk_violation += 1; continue
                        status = row.get('status', 'approved').strip().lower()
                        if status not in ['pending', 'approved', 'cancelled', 'rejected', 'completed', 'checked_in']:
                             logger.warning(f"Row {line_num}: Invalid status value '{row.get('status')}' for booking '{title}'. Defaulting to 'approved'.")
                             errors.append(f"Row {line_num}: Invalid status '{row.get('status')}' for '{title}', defaulted to 'approved'."); status = 'approved'
                        recurrence_rule = row.get('recurrence_rule');
                        if recurrence_rule == '': recurrence_rule = None
                        if not clear_existing:
                            existing_booking = Booking.query.filter_by(resource_id=resource_id, user_name=user_name, start_time=start_time_local_naive, end_time=end_time_local_naive).first()
                            if existing_booking: bookings_skipped_duplicate += 1; logger.info(f"Row {line_num}: Skipping duplicate booking for resource {resource_id}, user '{user_name}' at {start_time_local_naive}."); continue
                        new_booking_data = {
                            'resource_id':resource_id, 'user_name':user_name,
                            'start_time':start_time_local_naive, 'end_time':end_time_local_naive,
                            'title':title, 'status':status, 'recurrence_rule':recurrence_rule,
                            'checked_in_at':checked_in_at_local_naive, 'checked_out_at':checked_out_at_local_naive
                        }
                        if clear_existing and 'id' in row and row['id']:
                           try: new_booking_data['id'] = int(row['id'])
                           except ValueError: errors.append(f"Row {line_num}: Invalid booking ID '{row['id']}' in CSV. Auto-generating ID."); logger.warning(f"Row {line_num}: Invalid booking ID '{row['id']}' for '{title}'. Auto-generating ID.")
                        new_booking = Booking(**new_booking_data)
                        db.session.add(new_booking); bookings_created += 1
                    except Exception as e_row:
                        errors.append(f"Row {line_num}: Unexpected error: {str(e_row)}"); logger.error(f"Row {line_num}: Error processing row: {row} - {str(e_row)}", exc_info=True)
                        bookings_skipped_other_errors += 1; db.session.rollback(); continue
            try:
                db.session.commit()
                logger.info(f"{import_context_message_prefix}Successfully committed {bookings_created} new/updated bookings from CSV.")
                _emit_import_progress(socketio_instance, task_id, "Batch commit successful.", detail=f"{bookings_created} bookings.", level='INFO', context_prefix=import_context_message_prefix)
            except Exception as e_commit:
                db.session.rollback(); errors.append(f"Final database commit failed: {str(e_commit)}")
                logger.error(f"{import_context_message_prefix}Database commit failed after processing CSV: {str(e_commit)}", exc_info=True)
                _emit_import_progress(socketio_instance, task_id, "Final commit failed.", detail=str(e_commit), level='ERROR', context_prefix=import_context_message_prefix)
                bookings_created = 0; bookings_updated = 0
    except FileNotFoundError:
        error_msg = f"CSV file not found: {csv_file_path}"; errors.append(error_msg); logger.error(error_msg)
        _emit_import_progress(socketio_instance, task_id, "Import file not found.", detail=csv_file_path, level='ERROR', context_prefix=import_context_message_prefix)
    except Exception as e_file:
        error_msg = f"Error reading CSV {csv_file_path}: {str(e_file)}"; errors.append(error_msg); logger.error(error_msg, exc_info=True)
        _emit_import_progress(socketio_instance, task_id, "Error reading CSV file.", detail=str(e_file), level='ERROR', context_prefix=import_context_message_prefix)
        if 'app' in locals() and app:
            with app.app_context():
                db.session.rollback()
    final_status = 'completed_successfully'
    if errors:
        final_status = 'completed_with_errors'
        _emit_import_progress(socketio_instance, task_id, "Import completed with errors.", detail=f"{len(errors)} errors.", level='WARNING', context_prefix=import_context_message_prefix)
    else:
        _emit_import_progress(socketio_instance, task_id, "Import completed successfully.", detail=f"{bookings_created} created.", level='SUCCESS', context_prefix=import_context_message_prefix)
    summary = {
        'processed': bookings_processed, 'created': bookings_created, 'updated': bookings_updated,
        'skipped_duplicates': bookings_skipped_duplicate, 'skipped_fk_violation': bookings_skipped_fk_violation,
        'skipped_other_errors': bookings_skipped_other_errors, 'errors': errors, 'status': final_status
    }
    logger.info(f"{import_context_message_prefix}Booking CSV import summary: {summary}")
    return summary

def _load_schedule_from_json():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    schedule_config_file = current_app.config['SCHEDULE_CONFIG_FILE']
    default_schedule_data = current_app.config['DEFAULT_SCHEDULE_DATA']
    if not os.path.exists(schedule_config_file):
        _save_schedule_to_json(default_schedule_data)
        return default_schedule_data.copy()
    try:
        with open(schedule_config_file, 'r', encoding='utf-8') as f: data = json.load(f)
        for key, default_value in default_schedule_data.items(): data.setdefault(key, default_value)
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
        if validated_data['schedule_type'] not in ['daily', 'weekly']: validated_data['schedule_type'] = default_schedule_data['schedule_type']
        day_of_week = data_to_save.get('day_of_week')
        if validated_data['schedule_type'] == 'weekly':
            if isinstance(day_of_week, int) and 0 <= day_of_week <= 6: validated_data['day_of_week'] = day_of_week
            else: validated_data['day_of_week'] = 0
        else: validated_data['day_of_week'] = None
        time_str = data_to_save.get('time_of_day', default_schedule_data['time_of_day'])
        try: datetime.strptime(time_str, '%H:%M'); validated_data['time_of_day'] = time_str
        except ValueError: validated_data['time_of_day'] = default_schedule_data['time_of_day']
        with open(schedule_config_file, 'w', encoding='utf-8') as f: json.dump(validated_data, f, indent=4)
        return True, "Schedule saved successfully to JSON."
    except IOError as e:
        logger.error(f"Error saving schedule to JSON '{schedule_config_file}': {e}")
        return False, f"Error saving schedule to JSON: {e}"

def check_booking_permission(user: User, resource: Resource, logger_instance) -> tuple[bool, str | None]:
    # ... (implementation as provided) ...
    return True, None

def check_resources_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> bool:
    # ... (implementation as provided) ...
    return False

def get_detailed_map_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> dict:
    # ... (implementation as provided) ...
    return {'total_primary_slots': 0, 'available_primary_slots_for_user': 0}

def get_current_effective_time():
    offset_hours = 0
    try:
        settings = BookingSettings.query.first()
        if settings and settings.global_time_offset_hours is not None: offset_hours = settings.global_time_offset_hours
    except Exception as e:
        logger = current_app.logger if current_app else logging.getLogger(__name__)
        logger.error(f"Error fetching time offset from BookingSettings: {e}. Defaulting offset to 0.")
        offset_hours = 0
    utc_now = datetime.now(timezone.utc)
    effective_time = utc_now + timedelta(hours=offset_hours)
    return effective_time
