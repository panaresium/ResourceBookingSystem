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

# Configuration constants that will be imported from config.py later
# For now, define them here if they are used by functions being moved.
# Example: ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
# SCHEDULE_CONFIG_FILE = "data/backup_schedule.json"
# DEFAULT_SCHEDULE_DATA = { ... }
# UPLOAD_FOLDER = "static/floor_map_uploads"

# This will be imported from config.py in the app factory context
# For now, if a util needs it directly and utils.py is at root:
basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')
# SCHEDULE_CONFIG_FILE = os.path.join(DATA_DIR, 'backup_schedule.json') # Related to old backup schedule
# DEFAULT_SCHEDULE_DATA = {
# "is_enabled": False,
# "schedule_type": "daily",
# "day_of_week": None,
# "time_of_day": "02:00"
# }

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
    "booking_backup_type": "full_export", # New field: 'full_export' or 'incremental'
    "range": "all" # e.g. "all", "1day", "7days" - Relevant for full_export
}

DEFAULT_SCHEDULER_SETTINGS = {
    "full_backup": DEFAULT_FULL_BACKUP_SCHEDULE.copy(),
    "booking_csv_backup": DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy(),
    "auto_restore_booking_records_on_startup": False # New setting
}

def load_scheduler_settings() -> dict:
    """Loads scheduler settings from a JSON file, merging with defaults."""
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    if not os.path.exists(SCHEDULER_SETTINGS_FILE_PATH):
        logger.info(f"Scheduler settings file not found at '{SCHEDULER_SETTINGS_FILE_PATH}'. Creating with default settings.")
        try:
            # Ensure DATA_DIR exists
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

        # Merge loaded settings with defaults to ensure all keys are present
        # and new default sub-schedules are added if missing from file.
        # The file's values take precedence for existing keys within each sub-schedule.
        final_settings = DEFAULT_SCHEDULER_SETTINGS.copy() # Start with a fresh copy of defaults

        for schedule_key, default_item_value in DEFAULT_SCHEDULER_SETTINGS.items():
            if schedule_key in loaded_settings:
                if isinstance(default_item_value, dict) and isinstance(loaded_settings[schedule_key], dict):
                    # Both default and loaded are dicts, so merge
                    merged_schedule = default_item_value.copy()
                    merged_schedule.update(loaded_settings[schedule_key])
                    final_settings[schedule_key] = merged_schedule
                else:
                    # Default is not a dict OR loaded value is not a dict.
                    # In this case, the loaded value (if it exists and is of a compatible type, or even if not, json.load would have produced it)
                    # takes precedence directly, without merging.
                    # This handles the boolean case for "auto_restore_booking_records_on_startup"
                    # and also cases where a structure might change from dict to non-dict or vice-versa.
                    final_settings[schedule_key] = loaded_settings[schedule_key]
            # If schedule_key is not in loaded_settings, the value from final_settings (which is a copy of DEFAULT_SCHEDULER_SETTINGS) remains.

        # Ensure no extraneous top-level keys from the file are carried over
        # (though current logic effectively does this by starting with DEFAULT_SCHEDULER_SETTINGS)
        # final_settings = {key: final_settings[key] for key in DEFAULT_SCHEDULER_SETTINGS if key in final_settings}


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
    """Saves the provided scheduler settings dictionary to a JSON file."""
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        # Ensure DATA_DIR exists
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SCHEDULER_SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=2)
        logger.info(f"Successfully saved scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}'.")
    except IOError as e:
        logger.error(f"Error saving scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error saving scheduler settings to '{SCHEDULER_SETTINGS_FILE_PATH}': {e}", exc_info=True)


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
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    try:
        # Assuming url_for is available in the context this function is called
        image_url = url_for('static', filename=f'resource_uploads/{resource.image_filename}') if resource.image_filename else None
    except RuntimeError:
        image_url = None # Fallback if outside of application context

    published_at_iso = None
    if resource.published_at is not None:
        # Assuming resource.published_at is a datetime.datetime object
        published_at_iso = resource.published_at.replace(tzinfo=timezone.utc).isoformat()

    maintenance_until_iso = None
    if resource.maintenance_until is not None:
        # Assuming resource.maintenance_until is a datetime.datetime object
        maintenance_until_iso = resource.maintenance_until.replace(tzinfo=timezone.utc).isoformat()

    scheduled_status_at_iso = None
    if resource.scheduled_status_at is not None:
        # Assuming resource.scheduled_status_at is a datetime.datetime object
        scheduled_status_at_iso = resource.scheduled_status_at.replace(tzinfo=timezone.utc).isoformat()

    resource_dict = {
        'id': resource.id,
        'name': resource.name,
        'capacity': resource.capacity,
        'equipment': resource.equipment,
        'status': resource.status,
        'tags': resource.tags,
        'booking_restriction': resource.booking_restriction,
        'image_url': image_url, # Use the variable defined above
        'published_at': published_at_iso,
        'allowed_user_ids': resource.allowed_user_ids,
        'roles': [{'id': r.id, 'name': r.name} for r in resource.roles],
        'floor_map_id': resource.floor_map_id,
        # map_coordinates specific handling will be adjusted in the next plan step
        'is_under_maintenance': resource.is_under_maintenance,
        'maintenance_until': maintenance_until_iso,
        'max_recurrence_count': resource.max_recurrence_count,
        'scheduled_status': resource.scheduled_status,
        'scheduled_status_at': scheduled_status_at_iso,
        'current_pin': resource.current_pin
    }

    # Handle map_coordinates and map_allowed_role_ids
    parsed_coords = None # Initialize to None
    if resource.map_coordinates:
        try:
            parsed_coords = json.loads(resource.map_coordinates)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in map_coordinates for resource {resource.id}: {resource.map_coordinates}")
            pass # parsed_coords remains None if JSON is invalid

    parsed_map_roles = []

    if resource.map_allowed_role_ids:
        try:
            loaded_roles = json.loads(resource.map_allowed_role_ids)
            if isinstance(loaded_roles, list): # Make sure it's a list
                # Further validation could be added here to ensure it's a list of integers if necessary
                parsed_map_roles = loaded_roles
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in map_allowed_role_ids for resource {resource.id}: {resource.map_allowed_role_ids}")
            pass # Defaults to empty list if JSON is invalid or field is empty

    if parsed_coords is not None and isinstance(parsed_coords, dict): # Ensure parsed_coords is a dict before adding keys
        parsed_coords['allowed_role_ids'] = parsed_map_roles
    elif parsed_coords is not None:
        logger.warning(f"Resource {resource.id} map_coordinates was not a dict after parsing: {type(parsed_coords)}")
        pass

    resource_dict['map_coordinates'] = parsed_coords

    return resource_dict

def generate_booking_image(resource_id: int, map_coordinates_str: str, resource_name: str) -> str | None:
    logger = current_app.logger if current_app else logging.getLogger(__name__)

    resource = Resource.query.get(resource_id)
    if not resource:
        logger.error(f"generate_booking_image: Resource with ID {resource_id} not found.")
        return None

    if not resource.floor_map_id:
        logger.error(f"generate_booking_image: Resource ID {resource_id} ('{resource.name}') has no associated floor_map_id.")
        return None

    floor_map = FloorMap.query.get(resource.floor_map_id)
    if not floor_map:
        logger.error(f"generate_booking_image: FloorMap with ID {resource.floor_map_id} not found for Resource ID {resource_id}.")
        return None

    if not floor_map.image_filename:
        logger.error(f"generate_booking_image: FloorMap ID {floor_map.id} ('{floor_map.name}') has no image_filename set.")
        return None

    base_image_filename = floor_map.image_filename
    upload_folder = current_app.config.get('FLOOR_MAP_UPLOAD_FOLDER')

    if not upload_folder:
        logger.error("generate_booking_image: FLOOR_MAP_UPLOAD_FOLDER not configured.")
        return None

    base_image_path = os.path.join(upload_folder, base_image_filename)

    if not os.path.exists(base_image_path):
        logger.error(f"generate_booking_image: Base image not found at {base_image_path} (derived from FloorMap ID {floor_map.id}).")
        return None

    try:
        img = Image.open(base_image_path)

        # Initial Resize
        original_width, original_height = img.size
        if original_width == 0:
            logger.error(f"generate_booking_image: Original image width is 0 for {base_image_path} (Resource ID {resource_id}). Cannot resize.")
            return None
        aspect_ratio = original_height / original_width
        target_width = 800
        target_height = int(target_width * aspect_ratio)
        if target_height == 0: target_height = 1 # Ensure height is at least 1 pixel

        logger.info(f"generate_booking_image: Resizing base image for Resource ID {resource_id} from {original_width}x{original_height} to {target_width}x{target_height} for drawing.")
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        img = img.convert("RGBA") # Ensure RGBA for drawing with alpha
        draw = ImageDraw.Draw(img) # Pillow handles RGBA context for Draw

        if map_coordinates_str:
            try:
                coords = json.loads(map_coordinates_str)
                x = coords.get('x', coords.get('left'))
                y = coords.get('y', coords.get('top'))
                width = coords.get('width')
                height = coords.get('height')

                if x is not None and y is not None and width is not None and height is not None:
                    try:
                        x0, y0 = float(x), float(y)
                        x1, y1 = float(x) + float(width), float(y) + float(height)

                        outline_color = (255, 0, 0, 255)  # Opaque red for outline
                        fill_color = (255, 0, 0, 77)  # Red with ~0.3 opacity (77/255)
                        stroke_width_pil = 3

                        draw.rectangle([(x0, y0), (x1, y1)], outline=outline_color, fill=fill_color, width=stroke_width_pil)
                        logger.info(f"Drew semi-transparent rectangle on image at ({x0},{y0})-({x1},{y1}) for resource ID {resource_id} (working size {img.width}x{img.height})")

                        # Add resource name text
                        try:
                            # Attempt to load a bold font, fallback to default
                            font_size = 20  # Adjust as needed
                            try:
                                # Common bold font names. Actual file names might vary.
                                # Ensure the font file is accessible in your environment.
                                font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
                            except IOError:
                                try:
                                    font = ImageFont.truetype("arialbd.ttf", font_size)
                                except IOError:
                                    logger.warning("Bold font (DejaVuSans-Bold.ttf or arialbd.ttf) not found. Using default font for resource name. Text may not be bold.")
                                    font = ImageFont.load_default() # Default font, likely not bold.

                            text_color = (0, 0, 0, 255)  # Black, opaque

                            # Calculate text size and position
                            # Use textbbox for more accurate bounding box in Pillow 8.0.0+
                            if hasattr(draw, 'textbbox'):
                                text_bbox = draw.textbbox((0,0), resource_name, font=font)
                                text_width = text_bbox[2] - text_bbox[0]
                                text_height = text_bbox[3] - text_bbox[1]
                            else: # Fallback for older Pillow versions
                                text_size_legacy = draw.textsize(resource_name, font=font)
                                text_width = text_size_legacy[0]
                                text_height = text_size_legacy[1]


                            # Position text above the rectangle, centered horizontally
                            text_x = x0 + (width - text_width) / 2
                            text_y = y0 - text_height - 5  # 5 pixels padding above rectangle

                            # Ensure text is not drawn off the top of the image
                            if text_y < 0:
                                text_y = 0
                            # Ensure text is not drawn off the left of the image
                            if text_x < 0:
                                text_x = 0
                            # Ensure text is not drawn off the right of the image (optional, might clip)
                            if text_x + text_width > img.width:
                                text_x = img.width - text_width
                                if text_x < 0: text_x = 0 # If text is wider than image

                            draw.text((text_x, text_y), resource_name, font=font, fill=text_color)
                            logger.info(f"Drew resource name '{resource_name}' at ({text_x},{text_y}) for resource ID {resource_id}")

                        except Exception as e_text:
                            logger.error(f"Error drawing resource name for resource ID {resource_id}: {e_text}", exc_info=True)

                    except (ValueError, TypeError) as e_coords:
                        logger.warning(f"Invalid coordinate values for drawing on floor map {base_image_filename} for resource ID {resource_id}: {e_coords}. Coords string: {map_coordinates_str}")
                else:
                    logger.warning(f"Incomplete coordinates for drawing on {base_image_filename} for resource ID {resource_id}. Coords string: {map_coordinates_str}")
            except json.JSONDecodeError as e_json:
                logger.warning(f"Could not decode map_coordinates JSON for {base_image_filename} for resource ID {resource_id}: {e_json}. Coords string: {map_coordinates_str}")
            except Exception as e_draw_block:
                 logger.error(f"Error in drawing block for resource ID {resource_id}: {e_draw_block}", exc_info=True)

        # Convert to RGB for JPG
        if img.mode == 'RGBA' or (img.mode == 'P' and 'transparency' in img.info):
            logger.debug(f"Image mode is {img.mode}, converting to RGB with white background for resource ID {resource_id}.")
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            alpha_channel = img.split()[-1]
            background.paste(img, (0,0), mask=alpha_channel)
            img = background
        elif img.mode != 'RGB':
            logger.debug(f"Image mode is {img.mode}, converting to RGB for resource ID {resource_id}.")
            img = img.convert('RGB')

        # Final Thumbnail if still too large
        MAX_DIMENSION_FINAL = 1200
        if img.width > MAX_DIMENSION_FINAL or img.height > MAX_DIMENSION_FINAL:
            logger.info(f"Image for resource ID {resource_id} ('{resource_name}') still large ({img.width}x{img.height}) after drawing, thumbnailing to fit {MAX_DIMENSION_FINAL}px.")
            img.thumbnail((MAX_DIMENSION_FINAL, MAX_DIMENSION_FINAL))
            logger.info(f"Image for resource ID {resource_id} ('{resource_name}') final size {img.width}x{img.height}.")

        sanitized_name_base = re.sub(r'[^\w.-]', '', resource_name.replace(' ', '_'))
        sanitized_name_base = sanitized_name_base[:100]
        if not sanitized_name_base:
            sanitized_name_base = f"resource_{resource_id}"

        output_filename = f"{sanitized_name_base}.jpg"
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, output_filename)

        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug(f"Removed existing temporary file at {output_path} before saving new one.")
            except OSError as e_remove:
                logger.warning(f"Could not remove existing temp file {output_path} before saving: {e_remove}")

        img.save(output_path, "JPEG", quality=75, optimize=True)

        logger.info(f"Saved modified image for resource ID {resource_id} ('{resource_name}') to temporary JPG file at {output_path}")
        return output_path

    except Exception as e_outer:
        logger.error(f"Error in generate_booking_image for resource ID {resource_id}: {e_outer}", exc_info=True)
        return None

def send_email(to_address: str, subject: str, body: str = None, html_body: str = None, attachment_path: str = None):
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"send_email function called. To: {to_address}, Subject: '{subject}'. Attachment present: {bool(attachment_path)}")

    if not body and not html_body:
        logger.error(f"Email to {to_address} has no body or html_body. Not sending.")
        if attachment_path and tempfile.gettempdir() in os.path.normpath(os.path.abspath(attachment_path)):
            try:
                os.remove(attachment_path)
                logger.info(f"Cleaned up temporary attachment due to no body/html_body: {attachment_path}")
            except Exception as e_clean_no_body:
                logger.error(f"Error cleaning up temporary attachment {attachment_path} (no body/html_body): {e_clean_no_body}", exc_info=True)
        return

    logger.info(f"Checking email configurations for sending to {to_address}:")
    mail_suppress_send = current_app.config.get('MAIL_SUPPRESS_SEND', False) # Default to False if not set
    logger.info(f"  MAIL_SUPPRESS_SEND: {mail_suppress_send}")

    gmail_sender_address = current_app.config.get('GMAIL_SENDER_ADDRESS')
    logger.info(f"  GMAIL_SENDER_ADDRESS: {'Present' if gmail_sender_address else 'MISSING!'}")

    google_client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    logger.info(f"  GOOGLE_CLIENT_ID: {'Present' if google_client_id and google_client_id != 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER_config.py' else 'MISSING or Placeholder!'}")

    google_client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
    logger.info(f"  GOOGLE_CLIENT_SECRET: {'Present' if google_client_secret and google_client_secret != 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER_config.py' else 'MISSING or Placeholder!'}")

    gmail_refresh_token = current_app.config.get('GMAIL_REFRESH_TOKEN')
    logger.info(f"  GMAIL_REFRESH_TOKEN: {'Present' if gmail_refresh_token else 'MISSING!'}")

    if mail_suppress_send:
        logger.warning(f"Email sending is SUPPRESSED (MAIL_SUPPRESS_SEND is True). Email to {to_address} with subject '{subject}' will not be sent.")
        if attachment_path and tempfile.gettempdir() in os.path.normpath(os.path.abspath(attachment_path)):
            try:
                os.remove(attachment_path)
                logger.info(f"Cleaned up temporary attachment due to MAIL_SUPPRESS_SEND: {attachment_path}")
            except Exception as e_clean_suppress:
                logger.error(f"Error cleaning up temporary attachment {attachment_path} (suppressed): {e_clean_suppress}", exc_info=True)
        return

    if not all([gmail_sender_address, google_client_id, google_client_secret, gmail_refresh_token]) or \
       google_client_id == 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER_config.py' or \
       google_client_secret == 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER_config.py':
        logger.error(f"CRITICAL: Email configuration is INCOMPLETE. Cannot send email to {to_address} with subject '{subject}'. Please check GMAIL_SENDER_ADDRESS, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REFRESH_TOKEN.")
        if attachment_path and tempfile.gettempdir() in os.path.normpath(os.path.abspath(attachment_path)):
            try:
                os.remove(attachment_path)
                logger.info(f"Cleaned up temporary attachment due to missing configuration: {attachment_path}")
            except Exception as e_clean_cfg:
                logger.error(f"Error cleaning up temporary attachment {attachment_path} (config issue): {e_clean_cfg}", exc_info=True)
        return # Exit the function if critical configs are missing

    email_log_entry = {
        'to': to_address, 'subject': subject, 'body_present': bool(body),
        'html_body_present': bool(html_body), 'attachment_path': attachment_path,
        'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'pending_api_retries'
    }
    email_log.append(email_log_entry) # Log initial attempt marker

    max_retries = 5
    retry_delay = 15  # seconds

    try: # Wrap the loop and potentially error-prone operations in a try
        for attempt in range(max_retries):
            logger.info(f"Attempt {attempt + 1}/{max_retries} to send email via Gmail API to {to_address}: {subject} {'with attachment' if attachment_path else ''}")
            try:
                client_id = current_app.config.get('GOOGLE_CLIENT_ID')
                client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
                refresh_token = current_app.config.get('GMAIL_REFRESH_TOKEN')
                from_email = current_app.config.get('GMAIL_SENDER_ADDRESS')

                if not all([client_id, client_secret, refresh_token, from_email]):
                    logger.error("Gmail API OAuth 2.0 Client ID credentials not fully configured.")
                    email_log_entry['status'] = 'failed_oauth_config_missing'
                    # Do not return immediately, allow cleanup logic to run
                    break # Break from retry loop as this is a config error

                try: # This is the try block around line 490 (now ~494)
                    creds = UserCredentials( # This was line 491 in a previous version
                        None, refresh_token=refresh_token, token_uri='https://oauth2.googleapis.com/token',
                        client_id=client_id, client_secret=client_secret,
                        scopes=['https://www.googleapis.com/auth/gmail.send']
                    )
                except Exception as e_creds:
                    logger.error(f"Failed to create/refresh Google OAuth credentials on attempt {attempt + 1}: {str(e_creds)}", exc_info=True)
                    email_log_entry['status'] = 'failed_oauth_credential_creation'
                    email_log_entry['error_detail'] = str(e_creds)
                    # Do not return immediately, allow cleanup logic to run
                    break # Break from retry loop as this is likely a persistent auth issue

                service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
                message = MIMEMultipart('mixed')
                if html_body and attachment_path:
                     message = MIMEMultipart('mixed')
                elif html_body or attachment_path:
                    message = MIMEMultipart('mixed')
                else:
                    message = MIMEText(body, 'plain', 'utf-8')

                message['to'] = to_address
                message['from'] = from_email
                message['subject'] = subject

                if isinstance(message, MIMEMultipart):
                    alt_part = MIMEMultipart('alternative')
                    if body:
                        alt_part.attach(MIMEText(body, 'plain', 'utf-8'))
                    if html_body:
                        alt_part.attach(MIMEText(html_body, 'html', 'utf-8'))
                    message.attach(alt_part)

                if attachment_path:
                    file_ext = os.path.splitext(attachment_path)[1].lower()
                    maintype, subtype = 'application', 'octet-stream'
                    if file_ext == '.png': maintype, subtype = 'image', 'png'
                    elif file_ext in ['.jpg', '.jpeg']: maintype, subtype = 'image', 'jpeg'
                    elif file_ext == '.pdf': maintype, subtype = 'application', 'pdf'
                    elif file_ext == '.txt': maintype, subtype = 'text', 'plain'

                    with open(attachment_path, 'rb') as fp:
                        if maintype == 'image': msg_attach = MIMEImage(fp.read(), _subtype=subtype, name=os.path.basename(attachment_path))
                        elif maintype == 'text': msg_attach = MIMEText(fp.read().decode('utf-8'), _subtype=subtype, _charset='utf-8')
                        else: msg_attach = MIMEApplication(fp.read(), _subtype=subtype, name=os.path.basename(attachment_path))

                    msg_attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_path))
                    message.attach(msg_attach)
                    logger.info(f"Attachment {attachment_path} prepared for Gmail API on attempt {attempt + 1}.")

                raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
                create_message_body = {'raw': raw_message}
                sent_message = service.users().messages().send(userId='me', body=create_message_body).execute()
                logger.info(f"Email sent successfully via Gmail API to {to_address} on attempt {attempt + 1}. Message ID: {sent_message.get('id')}")
                email_log_entry['status'] = 'sent_api_success'
                email_log_entry['message_id'] = sent_message.get('id')
                email_log_entry['attempts'] = attempt + 1
                break  # Exit loop on success

            except (socket.gaierror, httplib2.error.ServerNotFoundError, HttpError) as e_retryable:
                logger.warning(f"Retryable error on attempt {attempt + 1}/{max_retries} sending email to {to_address}: {type(e_retryable).__name__} - {str(e_retryable)}", exc_info=True)
                email_log_entry['status'] = f'failed_api_retryable_error_attempt_{attempt + 1}'
                email_log_entry['error_detail'] = str(e_retryable)
                email_log_entry['error_type'] = type(e_retryable).__name__
                if attempt < max_retries - 1:
                    logger.info(f"Waiting {retry_delay} seconds before next attempt...")
                    time_module.sleep(retry_delay)
                else:
                    logger.error(f"Max retries ({max_retries}) reached for email to {to_address}. Final error: {type(e_retryable).__name__}", exc_info=True)
                    email_log_entry['status'] = f'failed_api_max_retries_reached' # More specific final status
            except Exception as e_non_retryable:
                logger.error(f"A non-retryable error occurred sending email to {to_address} on attempt {attempt + 1}: {e_non_retryable}", exc_info=True)
                email_log_entry['status'] = 'failed_api_non_retryable_error'
                email_log_entry['error_detail'] = str(e_non_retryable)
                email_log_entry['error_type'] = type(e_non_retryable).__name__
                break # Exit loop for non-retryable errors (e.g., bad request, auth, unexpected)
                # No 'finally' block inside the loop's try needed for attachment cleanup, handled by outer finally.
    finally:
        # This finally block is now correctly associated with the outer try,
        # ensuring cleanup happens after all attempts or if an unexpected error occurs before/during the loop.
        if attachment_path and tempfile.gettempdir() in os.path.normpath(os.path.abspath(attachment_path)):
            try:
                os.remove(attachment_path)
                logger.info(f"Cleaned up temporary attachment: {attachment_path}")
            except Exception as e_clean:
                logger.error(f"Error cleaning up temporary attachment {attachment_path}: {e_clean}", exc_info=True)

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

            # Handle floor_map_id and map_coordinates
            new_floor_map_id = res_data.get('floor_map_id') # Use .get() to fetch, could be None

            if new_floor_map_id is not None:
                # Attempt to convert to integer if it's a string representation
                try:
                    processed_floor_map_id = int(new_floor_map_id)
                except (ValueError, TypeError):
                    # If conversion fails (e.g., it's an empty string or non-numeric)
                    # Treat as if no valid floor_map_id was provided for lookup,
                    # but log an error if it wasn't an intentional empty string.
                    # If it was an empty string, it means "remove existing map link".
                    if new_floor_map_id == '': # Explicitly clear
                        resource.floor_map_id = None
                        logger.info(f"Resource '{original_resource_name_for_log}' (ID: {res_data.get('id', resource.id)}): floor_map_id explicitly cleared.")
                    elif new_floor_map_id is not None : # It was some other invalid value
                        errors.append({
                            'resource_name': original_resource_name_for_log,
                            'id': res_data.get('id', resource.id),
                            'error': f"Invalid non-integer floor_map_id value '{new_floor_map_id}' provided. floor_map_id was not updated."
                        })
                        # resource.floor_map_id remains unchanged in this specific error case.
                    # If new_floor_map_id was None initially, this block is skipped.
                    processed_floor_map_id = None # Ensure it's None if conversion failed or was empty string

                if processed_floor_map_id is not None: # Only proceed if we have a valid integer ID
                    floor_map_exists = db.session.query(FloorMap.id).filter_by(id=processed_floor_map_id).first()
                    if floor_map_exists:
                        resource.floor_map_id = processed_floor_map_id
                    else:
                        error_msg = f"Resource '{original_resource_name_for_log}' (ID: {res_data.get('id', resource.id)}) references FloorMap ID {processed_floor_map_id}, which does not exist. Map coordinates were imported, but will not function correctly until the corresponding FloorMap data is present/imported."
                        errors.append({
                            'resource_name': original_resource_name_for_log,
                            'id': res_data.get('id', resource.id),
                            'floor_map_id': processed_floor_map_id,
                            'error': error_msg
                        })
                        resource.floor_map_id = None # Set to None as per requirement
            elif 'floor_map_id' in res_data and res_data['floor_map_id'] is None:
                # If 'floor_map_id' is explicitly provided as null/None in res_data
                resource.floor_map_id = None
            # If 'floor_map_id' key is not in res_data at all, resource.floor_map_id remains unchanged (existing value)

            # Handle map_coordinates assignment
            if 'map_coordinates' in res_data:
                coords_val = res_data['map_coordinates']
                if isinstance(coords_val, dict):
                    resource.map_coordinates = json.dumps(coords_val)
                elif isinstance(coords_val, str):
                    resource.map_coordinates = coords_val
                elif coords_val is None:
                    resource.map_coordinates = None
                else:
                    # If it's some other type that's not dict, str, or None (e.g. int, list directly)
                    # This case should ideally not happen for map_coordinates.
                    # Log a warning and attempt to stringify, or set to None, or raise error.
                    # For now, let's log and set to None as a safeguard.
                    logger.warning(
                        f"Resource '{original_resource_name_for_log}' (ID: {res_data.get('id')}) "
                        f"has map_coordinates of unexpected type: {type(coords_val)}. Setting to None."
                    )
                    resource.map_coordinates = None
            # If 'map_coordinates' is not in res_data, resource.map_coordinates remains unchanged.

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
                upload_folder_path = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'static', 'floor_map_uploads'))
                if fm.image_filename and not os.path.exists(os.path.join(upload_folder_path, fm.image_filename)):
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
                    error_message = f"Resource not found during map import: Name='{res_map_data.get('name', 'N/A')}', ID='{res_map_data.get('id', 'N/A')}'. Skipping mapping for this resource."
                    logger.warning(error_message) # Explicitly log as warning
                    resource_errors.append({'error': error_message, 'data': res_map_data})
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

# LEGACY - Local CSV Export - Kept for reference / To be removed if no other part of app uses it.
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

def _emit_import_progress(socketio_instance, task_id, message, detail='', level='INFO', context_prefix=""):
    """ Helper to emit progress for import operations, prepending a context prefix. """
    if socketio_instance and task_id:
        full_message = f"{context_prefix}{message}"
        # Assuming _emit_progress is a global helper or part of a class if this is a method
        # For standalone utils.py, it might need to be passed or defined here.
        # For now, let's assume a global _emit_progress exists or this is adapted.
        # If azure_backup._emit_progress is intended, it needs to be imported or passed.
        # For simplicity, assuming a local or passed _emit_progress similar to azure_backup's.
        try:
            from azure_backup import _emit_progress as azure_emit_progress # Try to use the one from azure_backup
            azure_emit_progress(socketio_instance, task_id, 'import_progress', full_message, detail, level)
        except ImportError: # Fallback if azure_backup._emit_progress is not available
             current_app.logger.debug(f"SocketIO Emit (Import): {full_message} - {detail} ({level})")


def import_bookings_from_csv_file(csv_file_path, app, clear_existing: bool = False, socketio_instance=None, task_id=None, import_context_message_prefix: str = ""):
    """
    Imports bookings from a CSV file.

    Args:
        csv_file_path (str): The path to the CSV file.
        app: The Flask application object for app context.
        clear_existing (bool): If True, deletes all existing bookings before import.
        socketio_instance: Optional SocketIO instance for progress.
        task_id: Optional task ID for SocketIO.
        import_context_message_prefix (str): Prefix for SocketIO messages to give context.

    Returns:
        dict: A summary of the import process.
    """
    logger = app.logger
    event_name = 'import_progress' # Generic event for this util, context prefix helps distinguish

    _emit_import_progress(socketio_instance, task_id, "Import process started.", detail=f"File: {os.path.basename(csv_file_path)}", level='INFO', context_prefix=import_context_message_prefix)

    bookings_processed = 0
    bookings_created = 0
    bookings_updated = 0 # For future use if upsert logic is added
    bookings_skipped_duplicate = 0
    bookings_skipped_fk_violation = 0
    bookings_skipped_other_errors = 0
    errors = []
    current_offset_hours = 0 # Initialize

    try:
        with app.app_context():
            try:
                booking_settings = BookingSettings.query.first()
                if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
                    current_offset_hours = booking_settings.global_time_offset_hours
                else:
                    logger.warning(f"{import_context_message_prefix}BookingSettings not found or global_time_offset_hours not set for CSV import, using 0 offset. Imported times will be treated as UTC if they have offset, or as naive local if they don't.")
            except Exception as e_settings:
                logger.error(f"{import_context_message_prefix}Error fetching BookingSettings for CSV import: {e_settings}. Using 0 offset for time conversions.")


            if clear_existing:
                try:
                    num_deleted = db.session.query(Booking).delete()
                    logger.info(f"{import_context_message_prefix}Cleared {num_deleted} existing bookings before import.")
                    _emit_import_progress(socketio_instance, task_id, f"Cleared {num_deleted} existing bookings.", level='INFO', context_prefix=import_context_message_prefix)
                except Exception as e_clear:
                    db.session.rollback()
                    error_msg = f"Error clearing existing bookings: {str(e_clear)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)
                    _emit_import_progress(socketio_instance, task_id, "Error clearing existing bookings.", detail=str(e_clear), level='ERROR', context_prefix=import_context_message_prefix)
                    return {
                        'processed': 0, 'created': 0, 'updated': 0, 'skipped_duplicates': 0,
                        'skipped_fk_violation': 0, 'skipped_other_errors': 0, 'errors': errors,
                        'status': 'failed_clear_existing'
                    }

            # Pre-fetch existing user and resource IDs for faster FK checks if memory allows and tables are large
            # For smaller tables, direct DB checks per row might be acceptable.
            # For this example, direct checks will be performed.

            with open(csv_file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)

                row_count_for_progress_update = 0
                for row in reader:
                    bookings_processed += 1
                    row_count_for_progress_update +=1
                    line_num = reader.line_num

                    if row_count_for_progress_update % 50 == 0: # Emit progress every 50 rows
                        _emit_import_progress(socketio_instance, task_id, f"Processing row {line_num}...", detail=f"{bookings_created} created, {bookings_skipped_fk_violation} FK skips, {bookings_skipped_other_errors} other skips.", level='INFO', context_prefix=import_context_message_prefix)

                    try:
                        resource_id_str = row.get('resource_id')
                        if not resource_id_str:
                            errors.append(f"Row {line_num}: Missing resource_id.")
                            bookings_skipped_other_errors += 1
                            continue
                        try:
                            resource_id = int(resource_id_str)
                        except ValueError:
                            errors.append(f"Row {line_num}: Invalid resource_id '{resource_id_str}'. Must be an integer.")
                            bookings_skipped_other_errors += 1
                            continue

                        user_name = row.get('user_name', '').strip()
                        if not user_name:
                            errors.append(f"Row {line_num}: Missing user_name.")
                            bookings_skipped_other_errors += 1
                            continue

                        title = row.get('title', '').strip()
                        if not title:
                            errors.append(f"Row {line_num}: Missing title.")
                            bookings_skipped_other_errors += 1
                            continue

                        # _parse_iso_datetime returns an aware datetime object (typically UTC)
                        start_time_aware = _parse_iso_datetime(row.get('start_time'))
                        end_time_aware = _parse_iso_datetime(row.get('end_time'))
                        checked_in_at_aware = _parse_iso_datetime(row.get('checked_in_at'))
                        checked_out_at_aware = _parse_iso_datetime(row.get('checked_out_at'))

                        if not start_time_aware or not end_time_aware:
                            errors.append(f"Row {line_num}: Invalid or missing start_time or end_time format.")
                            bookings_skipped_other_errors += 1
                            continue
                        if start_time_aware >= end_time_aware:
                            errors.append(f"Row {line_num}: Start time must be before end time.")
                            bookings_skipped_other_errors += 1
                            continue

                        # Convert aware times (assumed UTC from _parse_iso_datetime) to naive venue local
                        start_time_local_naive = (start_time_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if start_time_aware else None
                        end_time_local_naive = (end_time_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if end_time_aware else None
                        checked_in_at_local_naive = (checked_in_at_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if checked_in_at_aware else None
                        checked_out_at_local_naive = (checked_out_at_aware.astimezone(timezone.utc) + timedelta(hours=current_offset_hours)).replace(tzinfo=None) if checked_out_at_aware else None


                        # FK Checks
                        resource = db.session.get(Resource, resource_id)
                        if not resource:
                            err_msg_fk_res = f"Row {line_num}: Resource ID {resource_id} not found. Booking for '{title}' skipped."
                            errors.append(err_msg_fk_res)
                            logger.warning(err_msg_fk_res)
                            bookings_skipped_fk_violation += 1
                            continue

                        user = User.query.filter_by(username=user_name).first()
                        if not user:
                            err_msg_fk_user = f"Row {line_num}: User '{user_name}' not found. Booking for '{title}' skipped."
                            errors.append(err_msg_fk_user)
                            logger.warning(err_msg_fk_user)
                            bookings_skipped_fk_violation += 1
                            continue

                        status = row.get('status', 'approved').strip().lower()
                        if status not in ['pending', 'approved', 'cancelled', 'rejected', 'completed', 'checked_in']: # Added checked_in
                             logger.warning(f"Row {line_num}: Invalid status value '{row.get('status')}' for booking '{title}'. Defaulting to 'approved'.")
                             errors.append(f"Row {line_num}: Invalid status '{row.get('status')}' for '{title}', defaulted to 'approved'.")
                             status = 'approved'

                        recurrence_rule = row.get('recurrence_rule')
                        if recurrence_rule == '': recurrence_rule = None

                        checked_in_at = _parse_iso_datetime(row.get('checked_in_at'))
                        checked_out_at = _parse_iso_datetime(row.get('checked_out_at'))

                        # ID from CSV is only used if clear_existing was true and we want to preserve original IDs
                        # Otherwise, for adding to existing data, ID should be auto-generated.
                        # For now, assuming new bookings get new IDs. If preserving IDs from CSV is needed,
                        # this logic needs adjustment and a check for existing booking by ID.
                        # The current duplicate check is semantic (user, resource, time).

                        # If not clearing existing, check for duplicates using naive local times
                        if not clear_existing:
                            existing_booking = Booking.query.filter_by(
                                resource_id=resource_id, user_name=user_name,
                                start_time=start_time_local_naive, end_time=end_time_local_naive
                            ).first()
                            if existing_booking:
                                bookings_skipped_duplicate += 1
                                logger.info(f"Row {line_num}: Skipping duplicate booking for resource {resource_id}, user '{user_name}' at {start_time_local_naive}.")
                                continue

                        new_booking = Booking(
                            resource_id=resource_id, user_name=user_name,
                            start_time=start_time_local_naive, end_time=end_time_local_naive, title=title,
                            status=status, recurrence_rule=recurrence_rule,
                            checked_in_at=checked_in_at_local_naive, checked_out_at=checked_out_at_local_naive
                        )
                        # If clear_existing was true, and CSV contains 'id', and we want to preserve it:
                        # if clear_existing and 'id' in row and row['id']:
                        #    try:
                        #        new_booking.id = int(row['id'])
                        #    except ValueError:
                        #        errors.append(f"Row {line_num}: Invalid booking ID '{row['id']}' in CSV. Auto-generating ID.")
                        #        logger.warning(f"Row {line_num}: Invalid booking ID '{row['id']}' in CSV for '{title}'. Auto-generating ID.")

                        db.session.add(new_booking)
                        bookings_created += 1

                    except Exception as e_row:
                        errors.append(f"Row {line_num}: Unexpected error: {str(e_row)}")
                        logger.error(f"Row {line_num}: Error processing row: {row} - {str(e_row)}", exc_info=True)
                        bookings_skipped_other_errors += 1
                        db.session.rollback() # Rollback this specific row's transaction part
                        continue

            # Final commit for all processed rows in the file (if not committed per row)
            try:
                db.session.commit()
                logger.info(f"{import_context_message_prefix}Successfully committed {bookings_created} new/updated bookings from CSV.")
                _emit_import_progress(socketio_instance, task_id, "Batch commit successful.", detail=f"{bookings_created} bookings.", level='INFO', context_prefix=import_context_message_prefix)
            except Exception as e_commit:
                db.session.rollback()
                errors.append(f"Final database commit failed: {str(e_commit)}")
                logger.error(f"{import_context_message_prefix}Database commit failed after processing CSV: {str(e_commit)}", exc_info=True)
                _emit_import_progress(socketio_instance, task_id, "Final commit failed.", detail=str(e_commit), level='ERROR', context_prefix=import_context_message_prefix)
                # Adjust counts if the commit failure means nothing was saved
                bookings_created = 0
                bookings_updated = 0


    except FileNotFoundError:
        error_msg = f"CSV file not found: {csv_file_path}"
        errors.append(error_msg)
        logger.error(error_msg)
        _emit_import_progress(socketio_instance, task_id, "Import file not found.", detail=csv_file_path, level='ERROR', context_prefix=import_context_message_prefix)
    except Exception as e_file:
        error_msg = f"Error reading CSV {csv_file_path}: {str(e_file)}"
        errors.append(error_msg)
        logger.error(error_msg, exc_info=True)
        _emit_import_progress(socketio_instance, task_id, "Error reading CSV file.", detail=str(e_file), level='ERROR', context_prefix=import_context_message_prefix)
        if 'app' in locals() and app:
             with app.app_context(): db.session.rollback()

    final_status = 'completed_successfully'
    if errors:
        final_status = 'completed_with_errors'
        _emit_import_progress(socketio_instance, task_id, "Import completed with errors.", detail=f"{len(errors)} errors.", level='WARNING', context_prefix=import_context_message_prefix)
    else:
        _emit_import_progress(socketio_instance, task_id, "Import completed successfully.", detail=f"{bookings_created} created.", level='SUCCESS', context_prefix=import_context_message_prefix)


    summary = {
        'processed': bookings_processed,
        'created': bookings_created,
        'updated': bookings_updated, # Currently not implementing updates for existing via CSV, but placeholder is here
        'skipped_duplicates': bookings_skipped_duplicate,
        'skipped_fk_violation': bookings_skipped_fk_violation,
        'skipped_other_errors': bookings_skipped_other_errors,
        'errors': errors,
        'status': final_status
    }
    logger.info(f"{import_context_message_prefix}Booking CSV import summary: {summary}")
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




def check_booking_permission(user: User, resource: Resource, logger_instance) -> tuple[bool, str | None]:
    """
    Checks if a user has permission to book a given resource.

    Args:
        user: The User object attempting the booking.
        resource: The Resource object being booked.
        logger_instance: The logger instance (e.g., current_app.logger) for logging.

    Returns:
        A tuple (can_book_bool, error_message_str).
        can_book_bool is True if permission is granted, False otherwise.
        error_message_str contains a user-friendly error message if permission is denied,
        or None if granted.
    """
    can_book_overall = False
    error_message = "You are not authorized to book this resource."  # Default error

    logger_instance.debug(f"Checking booking permissions for user '{user.username}' (ID: {user.id}, IsAdmin: {user.is_admin}) on resource ID {resource.id} ('{resource.name}').")
    logger_instance.debug(f"Resource details: booking_restriction='{resource.booking_restriction}', allowed_user_ids='{resource.allowed_user_ids}', resource_roles={[role.name for role in resource.roles]}, map_coordinates='{resource.map_coordinates}'")

    if user.is_admin:
        can_book_overall = True
        logger_instance.debug(f"Permission granted for resource {resource.id}: User '{user.username}' is admin.")
    elif resource.booking_restriction == 'admin_only':
        error_message = "This resource can only be booked by administrators."
        logger_instance.warning(f"Booking denied for resource {resource.id}: Non-admin user '{user.username}' attempted to book admin-only resource.")
        # can_book_overall remains False
    else:
        # Check for area-specific roles defined in map_coordinates
        area_roles_defined = False
        area_allowed_role_ids = []
        parsed_resource_allowed_ids = set()
        if resource.allowed_user_ids and resource.allowed_user_ids.strip():
            parsed_resource_allowed_ids = {int(uid.strip()) for uid in resource.allowed_user_ids.split(',') if uid.strip()}

        if resource.map_coordinates:
            try:
                map_coords_data = json.loads(resource.map_coordinates)
                if isinstance(map_coords_data.get('allowed_role_ids'), list) and map_coords_data['allowed_role_ids']:
                    area_allowed_role_ids = [int(r_id) for r_id in map_coords_data['allowed_role_ids'] if isinstance(r_id, int)] # Ensure list of ints
                    if area_allowed_role_ids: # Only set defined to true if list is not empty after validation
                        area_roles_defined = True
                        logger_instance.debug(f"Resource {resource.id} has area-specific roles defined in map_coordinates: {area_allowed_role_ids}")
            except json.JSONDecodeError:
                logger_instance.warning(f"Could not parse map_coordinates JSON for resource {resource.id}: '{resource.map_coordinates}'. Skipping area role check.")
            except (TypeError, ValueError):
                logger_instance.warning(f"Invalid data type for role IDs in map_coordinates for resource {resource.id}. Expected list of integers. Skipping area role check.")

        if area_roles_defined:
            logger_instance.debug(f"Evaluating permissions against area roles for resource {resource.id}.")
            user_is_specifically_allowed_on_resource = user.id in parsed_resource_allowed_ids

            if user_is_specifically_allowed_on_resource:
                can_book_overall = True
                logger_instance.debug(f"Permission granted for resource {resource.id}: User '{user.username}' (ID: {user.id}) is in resource.allowed_user_ids, bypassing area role check.")
            else:
                user_role_ids = {role.id for role in user.roles}
                if not user_role_ids.isdisjoint(set(area_allowed_role_ids)):
                    can_book_overall = True
                    logger_instance.debug(f"Permission granted for resource {resource.id}: User '{user.username}' has a matching role for area-specific roles. User roles: {user_role_ids}, Area roles: {area_allowed_role_ids}.")
                else:
                    error_message = f"You do not have the required role to book this resource via its map area (Resource: {resource.name})."
                    logger_instance.warning(f"Booking denied for resource {resource.id}: User '{user.username}' lacks required area-specific role. User roles: {user_role_ids}, Area roles: {area_allowed_role_ids}.")
                    # can_book_overall remains False
        else:
            # No area-specific roles defined, or they were empty/invalid. Fall back to general resource permissions.
            logger_instance.debug(f"No valid area-specific roles for resource {resource.id}. Evaluating general resource permissions.")
            if user.id in parsed_resource_allowed_ids:
                can_book_overall = True
                logger_instance.debug(f"Permission granted for resource {resource.id}: User '{user.username}' (ID: {user.id}) is in resource.allowed_user_ids.")

            if not can_book_overall and resource.roles:
                user_role_ids = {role.id for role in user.roles}
                resource_allowed_role_ids = {role.id for role in resource.roles}
                if not user_role_ids.isdisjoint(resource_allowed_role_ids):
                    can_book_overall = True
                    logger_instance.debug(f"Permission granted for resource {resource.id}: User '{user.username}' has a matching general role for the resource. User roles: {user_role_ids}, Resource roles: {resource_allowed_role_ids}.")

            if not can_book_overall and not parsed_resource_allowed_ids and not resource.roles:
                # This means the resource itself has no specific user ID restrictions and no role restrictions.
                # booking_restriction != 'admin_only' is already handled.
                can_book_overall = True
                logger_instance.debug(f"Permission granted for resource {resource.id}: Resource is open to all authenticated users (no specific user/role restrictions).")

    # Final authorization log
    # Note: Some local variables from the original context (like 'parsed_resource_allowed_ids' specific to non-admin path)
    # might not be defined if the admin path was taken. Using .get() or checking existence for robust logging.
    log_details_permission_check = (
        f"Booking permission check for user '{user.username}' on resource ID {resource.id} ('{resource.name}'): "
        f"UserIsAdmin: {user.is_admin}, "
        f"ResourceAdminOnly: {resource.booking_restriction == 'admin_only'}, "
        f"AreaRolesDefined: {locals().get('area_roles_defined', 'N/A (admin path)')}, "
        f"AreaAllowedRoleIDs: {locals().get('area_allowed_role_ids', 'N/A (admin path)') if locals().get('area_roles_defined', False) else 'N/A (area roles not defined or admin path)'}, "
        f"UserInParsedResourceAllowedIDs: {(user.id in locals().get('parsed_resource_allowed_ids', set())) if 'parsed_resource_allowed_ids' in locals() else 'N/A (admin path)'}, "
        f"UserRoleIDs: {[role.id for role in user.roles]}, "
        f"GeneralResourceRoleIDs: {[role.id for role in resource.roles] if resource.roles else 'N/A'}, "
        f"CanBookOverall: {can_book_overall}"
    )
    logger_instance.debug(log_details_permission_check)

    if not can_book_overall:
        logger_instance.warning(f"Final booking permission check DENIED for user '{user.username}' on resource {resource.id} ('{resource.name}'). Reason: {error_message}")
        return False, error_message

    return True, None


def check_resources_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> bool:
    """
    Checks if any resource in the given list has at least one bookable slot
    for the specified user on the target_date within the primary_slots.

    Args:
        resources_list: A list of Resource model instances to check.
        target_date: A date object for the day to check availability.
        user: The User object (current_user) for whom to check availability.
        primary_slots: A list of (start_time_obj, end_time_obj) tuples defining slots.
        logger_instance: The logger instance for logging.

    Returns:
        True if at least one resource has a bookable slot for the user, False otherwise.
    """
    if not resources_list:
        return False

    current_offset_hours = 0
    try:
        settings = BookingSettings.query.first()
        if settings and hasattr(settings, 'global_time_offset_hours') and settings.global_time_offset_hours is not None:
            current_offset_hours = settings.global_time_offset_hours
    except Exception as e_settings:
        logger_instance.error(f"Error fetching BookingSettings for availability check: {e_settings}. Using 0 offset.")

    # Get current user's other bookings for the target_date once for efficiency
    try:
        user_other_bookings = Booking.query.filter(
            Booking.user_name == user.username,
            func.date(Booking.start_time) == target_date # Booking.start_time is naive local
        ).all()
    except Exception as e:
        logger_instance.error(f"Error fetching user's other bookings for {user.username} on {target_date}: {e}", exc_info=True)
        return False # Cannot reliably check availability if this query fails

    for resource in resources_list:
        if resource.status != 'published':
            continue

        # Maintenance check: Convert maintenance_until (naive UTC) to naive local for comparison
        maintenance_until_local_naive = None
        if resource.maintenance_until:
            maint_utc = resource.maintenance_until.replace(tzinfo=timezone.utc)
            maint_local_aware = maint_utc + timedelta(hours=current_offset_hours)
            maintenance_until_local_naive = maint_local_aware.replace(tzinfo=None)

        if resource.is_under_maintenance and maintenance_until_local_naive and maintenance_until_local_naive.date() >= target_date:
            if maintenance_until_local_naive.date() > target_date or maintenance_until_local_naive.time() == time.max:
                logger_instance.debug(f"Resource {resource.id} under maintenance for the whole of {target_date} (local).")
                continue

        user_other_bookings_for_this_resource_check = [
            b for b in user_other_bookings if b.resource_id != resource.id
        ]

        for slot_start_time_obj, slot_end_time_obj in primary_slots:
            slot_start_dt = datetime.combine(target_date, slot_start_time_obj)
            slot_end_dt = datetime.combine(target_date, slot_end_time_obj)

            # Ensure datetimes are offset-aware (UTC) for comparisons if necessary,
            # though SQLAlchemy usually handles this if DB stores them correctly.
            # For this function, we assume inputs and DB times are compatible (e.g., naive UTC).
            # If not, make them UTC aware:
            # slot_start_dt = slot_start_dt.replace(tzinfo=timezone.utc)
            # slot_end_dt = slot_end_dt.replace(tzinfo=timezone.utc)


            # a. Check general bookings for the slot on this resource
            general_bookings_overlap = Booking.query.filter(
                Booking.resource_id == resource.id,
                Booking.start_time < slot_end_dt,
                Booking.end_time > slot_start_dt,
                Booking.status.notin_(['cancelled', 'rejected', 'system_cancelled_no_checkin', 'cancelled_by_system'])
            ).all()

            is_generally_booked = bool(general_bookings_overlap)
            is_booked_by_current_user_here = any(
                b.user_name == user.username for b in general_bookings_overlap
            )

            if is_booked_by_current_user_here:
                logger_instance.debug(f"User {user.username} has already booked resource {resource.id} in slot {slot_start_dt}-{slot_end_dt}. Considering available for user.")
                return True # User already has this specific slot booked

            # b. Check slot-specific maintenance (using converted local naive maintenance time)
            slot_is_under_maintenance = False
            if resource.is_under_maintenance and maintenance_until_local_naive:
                if slot_start_dt < maintenance_until_local_naive:
                    slot_is_under_maintenance = True
                    logger_instance.debug(f"Resource {resource.id} slot {slot_start_dt}-{slot_end_dt} (local) is under maintenance (maintenance active until {maintenance_until_local_naive} local).")

            # c. Check for conflicts with user's other bookings (on *other* resources)
            is_conflicting_with_user_other_bookings = False
            if not is_booked_by_current_user_here: # No need to check if user already booked this slot
                for other_booking in user_other_bookings_for_this_resource_check:
                    # Ensure other_booking times are comparable (e.g. naive UTC)
                    other_booking_start = other_booking.start_time
                    other_booking_end = other_booking.end_time

                    if max(slot_start_dt, other_booking_start) < min(slot_end_dt, other_booking_end):
                        is_conflicting_with_user_other_bookings = True
                        logger_instance.debug(f"Slot {slot_start_dt}-{slot_end_dt} for resource {resource.id} conflicts with user {user.username}'s other booking {other_booking.id} on resource {other_booking.resource_id}.")
                        break

            # Slot is bookable if not generally booked, not under maintenance, and no conflict with user's other bookings
            if not is_generally_booked and not slot_is_under_maintenance and not is_conflicting_with_user_other_bookings:
                logger_instance.info(f"Found available slot for user {user.username} on resource {resource.id}: {slot_start_dt}-{slot_end_dt}.")
                return True # Found a bookable slot for this resource

    return False # No resource in the list has any bookable slot for the user


def get_detailed_map_availability_for_user(resources_list: list[Resource], target_date: date, user: User, primary_slots: list[tuple[time, time]], logger_instance) -> dict:
    """
    Calculates detailed availability for a list of resources for a specific user,
    considering primary time slots and the user's other bookings.

    Args:
        resources_list: A list of Resource model instances to check.
        target_date: A date object for the day to check availability.
        user: The User object for whom to check availability.
        primary_slots: A list of (start_time_obj, end_time_obj) tuples defining primary slots.
        logger_instance: The logger instance for logging.

    Returns:
        A dictionary with 'total_primary_slots' and 'available_primary_slots_for_user'.
    """
    total_primary_slots = 0
    available_primary_slots_for_user = 0

    if not resources_list:
        return {'total_primary_slots': 0, 'available_primary_slots_for_user': 0}

    current_offset_hours = 0
    allow_multiple_resources_same_time_setting = False  # Default value
    try:
        settings = BookingSettings.query.first()
        if settings:
            if hasattr(settings, 'global_time_offset_hours') and settings.global_time_offset_hours is not None:
                current_offset_hours = settings.global_time_offset_hours
            if hasattr(settings, 'allow_multiple_resources_same_time'): # Check if the attribute exists
                allow_multiple_resources_same_time_setting = settings.allow_multiple_resources_same_time
                logger_instance.info(f"BookingSetting 'allow_multiple_resources_same_time' is {allow_multiple_resources_same_time_setting}.")
            else:
                logger_instance.warning("BookingSetting 'allow_multiple_resources_same_time' attribute not found. Defaulting to False.")
        else:
            logger_instance.warning("BookingSettings not found. Using default for 'allow_multiple_resources_same_time' (False) and 'global_time_offset_hours' (0).")

    except Exception as e_settings:
        logger_instance.error(f"Error fetching BookingSettings for detailed availability: {e_settings}. Using default for 'allow_multiple_resources_same_time' (False) and 'global_time_offset_hours' (0).")
        # current_offset_hours remains 0
        # allow_multiple_resources_same_time_setting remains False

    # Fetch all bookings for the user on the target_date across all resources
    try:
        user_all_bookings_on_date = Booking.query.filter(
            Booking.user_name == user.username,
            func.date(Booking.start_time) == target_date, # Booking.start_time is naive local
            sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_conflict)
        ).all()
    except Exception as e:
        logger_instance.error(f"Error fetching user's bookings for {user.username} on {target_date}: {e}", exc_info=True)
        return {'total_primary_slots': 0, 'available_primary_slots_for_user': 0}


    for resource in resources_list:
        if resource.status != 'published':
            logger_instance.debug(f"Resource {resource.id} ('{resource.name}') is not published. Skipping.")
            continue

        # --- Permission Check START ---
        user_has_permission = False
        if user.is_admin:
            user_has_permission = True
            logger_instance.debug(f"User {user.id} ('{user.username}') has permission for resource {resource.id} ('{resource.name}') because user is admin.")
        elif not resource.map_allowed_role_ids: # Assuming map_allowed_role_ids is a string field from the model
            user_has_permission = True
            logger_instance.debug(f"User {user.id} ('{user.username}') has permission for resource {resource.id} ('{resource.name}') because resource.map_allowed_role_ids is empty (public).")
        else:
            try:
                allowed_role_ids = json.loads(resource.map_allowed_role_ids)
                if not isinstance(allowed_role_ids, list): # Ensure it's a list
                    logger_instance.warning(f"Resource {resource.id} map_allowed_role_ids was not a list after JSON parsing: {allowed_role_ids}. Denying access for safety.")
                    user_has_permission = False # Or handle as error / grant if empty list means public
                else:
                    user_role_ids = {role.id for role in user.roles}
                    # Check for intersection
                    if any(role_id in user_role_ids for role_id in allowed_role_ids):
                        user_has_permission = True
                        logger_instance.debug(f"User {user.id} ('{user.username}') has permission for resource {resource.id} ('{resource.name}') due to matching role ID. User roles: {user_role_ids}, Resource allowed roles: {allowed_role_ids}.")
                    else:
                        logger_instance.debug(f"User {user.id} ('{user.username}') DENIED permission for resource {resource.id} ('{resource.name}'). No matching role ID. User roles: {user_role_ids}, Resource allowed roles: {allowed_role_ids}.")
            except json.JSONDecodeError:
                logger_instance.error(f"Failed to parse map_allowed_role_ids JSON for resource {resource.id}: '{resource.map_allowed_role_ids}'. Denying access.")
                user_has_permission = False # Deny access if JSON is invalid

        if not user_has_permission:
            logger_instance.info(f"User {user.id} ('{user.username}') does not have permission to access resource {resource.id} ('{resource.name}'). Skipping this resource for availability calculation.")
            # Do not add its len(primary_slots) to total_primary_slots
            # It contributes 0 to available_primary_slots_for_user
            continue # Skip to the next resource
        # --- Permission Check END ---

        # If permission granted, proceed with existing logic
        total_primary_slots += len(primary_slots)

        maintenance_until_local_naive = None
        if resource.maintenance_until: # naive UTC
            maint_utc = resource.maintenance_until.replace(tzinfo=timezone.utc)
            maint_local_aware = maint_utc + timedelta(hours=current_offset_hours)
            maintenance_until_local_naive = maint_local_aware.replace(tzinfo=None)

        if resource.is_under_maintenance and maintenance_until_local_naive:
            if maintenance_until_local_naive.date() > target_date or \
               (maintenance_until_local_naive.date() == target_date and maintenance_until_local_naive.time() == time.max):
                logger_instance.debug(f"Resource {resource.id} ('{resource.name}') is under maintenance for the whole of {target_date} (local). Skipping its primary slots.")
                continue

        user_other_bookings_for_this_resource_check = [
            b for b in user_all_bookings_on_date if b.resource_id != resource.id
        ]

        for slot_start_time_obj, slot_end_time_obj in primary_slots:
            slot_start_dt = datetime.combine(target_date, slot_start_time_obj)
            slot_end_dt = datetime.combine(target_date, slot_end_time_obj)

            # Ensure datetimes are offset-aware (UTC) if necessary for comparisons
            # Assuming naive UTC for now, consistent with other parts of the codebase.
            # If timezone issues arise, they would need to be handled here and in booking data.
            # slot_start_dt = slot_start_dt.replace(tzinfo=timezone.utc)
            # slot_end_dt = slot_end_dt.replace(tzinfo=timezone.utc)

            # i. Check for general bookings on *this* resource for *this* slot (excluding cancelled/rejected)
            general_bookings_on_slot = Booking.query.filter(
                Booking.resource_id == resource.id,
                Booking.start_time < slot_end_dt,
                Booking.end_time > slot_start_dt,
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_conflict)
            ).all()

            is_generally_booked_by_anyone = bool(general_bookings_on_slot)

            # ii. Check if the current user has a booking on *this* resource for *this* slot
            # This is implicitly covered: if is_booked_by_current_user_here, then is_generally_booked_by_anyone is true.
            # Such slots will NOT be counted as *newly* available.
            # If a user *already* has it, it's "theirs", but not "available" for a *new* booking by them.

            # iii. Check for slot-specific maintenance for *this* resource and *slot*
            slot_is_under_maintenance = False
            if resource.is_under_maintenance and maintenance_until_local_naive:
                if slot_start_dt < maintenance_until_local_naive: # Compare naive local with naive local
                    slot_is_under_maintenance = True
                    logger_instance.debug(f"Resource {resource.id} slot {slot_start_dt}-{slot_end_dt} (local) is effectively under maintenance (maintenance active until {maintenance_until_local_naive} local).")

            # iv. Check if *this* slot on *this* resource conflicts with user_other_bookings_for_this_resource_check
            slot_conflicts_with_user_other_bookings = False
            for other_booking in user_other_bookings_for_this_resource_check:
                # Ensure other_booking times are comparable (e.g. naive UTC)
                other_booking_start = other_booking.start_time # Assuming naive UTC from DB
                other_booking_end = other_booking.end_time   # Assuming naive UTC from DB

                # Check for overlap: max(start1, start2) < min(end1, end2)
                if max(slot_start_dt, other_booking_start) < min(slot_end_dt, other_booking_end):
                    slot_conflicts_with_user_other_bookings = True
                    logger_instance.debug(f"Slot {slot_start_dt}-{slot_end_dt} for resource {resource.id} conflicts with user {user.username}'s other booking {other_booking.id} on resource {other_booking.resource_id} ({other_booking_start}-{other_booking_end}).")
                    break

            # A slot is counted towards available_primary_slots_for_user if:
            # - It is NOT generally booked by anyone (which also covers not booked by current user here).
            # - It is NOT under slot-specific maintenance.
            # - It does NOT conflict with the user's other bookings (unless allow_multiple_resources_same_time_setting is True).

            can_book_based_on_user_schedule = True # Assume true by default
            if not allow_multiple_resources_same_time_setting: # Check the new setting
                if slot_conflicts_with_user_other_bookings:
                    can_book_based_on_user_schedule = False
                    logger_instance.debug(f"Slot {slot_start_dt}-{slot_end_dt} for resource {resource.id} cannot be booked due to conflict with user's other bookings (allow_multiple_resources_same_time is False).")

            if not is_generally_booked_by_anyone and \
               not slot_is_under_maintenance and \
               can_book_based_on_user_schedule:
                available_primary_slots_for_user += 1
                logger_instance.debug(f"Slot {slot_start_dt}-{slot_end_dt} on resource {resource.id} counted as available for user {user.username}.")
            else:
                logger_instance.debug(f"Slot {slot_start_dt}-{slot_end_dt} on resource {resource.id} NOT available for user {user.username}. Reasons: generally_booked={is_generally_booked_by_anyone}, maintenance={slot_is_under_maintenance}, can_book_user_schedule={can_book_based_on_user_schedule} (conflict_other={slot_conflicts_with_user_other_bookings}, allow_multiple={allow_multiple_resources_same_time_setting}).")

    logger_instance.info(f"Detailed availability for user {user.username} on {target_date}: Total Primary Slots={total_primary_slots}, Available for User={available_primary_slots_for_user} across {len(resources_list)} resources. allow_multiple_resources_same_time={allow_multiple_resources_same_time_setting}")
    return {'total_primary_slots': total_primary_slots, 'available_primary_slots_for_user': available_primary_slots_for_user}


def get_current_effective_time():
    """
    Calculates the effective current time by applying the global time offset
    from BookingSettings to the current UTC time.
    """
    offset_hours = 0
    try:
        # This query needs an active app context.
        settings = BookingSettings.query.first()
        if settings and settings.global_time_offset_hours is not None:
            offset_hours = settings.global_time_offset_hours
        # Optional: log if settings are missing or offset is None, defaults to 0 anyway.
        # else:
        #     if current_app:
        #         current_app.logger.debug("BookingSettings not found or global_time_offset_hours not set, using offset 0.")
    except Exception as e:
        # In case of DB error or other issues accessing settings
        if current_app:
            current_app.logger.error(f"Error fetching time offset from BookingSettings: {e}. Defaulting offset to 0.")
        else:
            # Fallback logger if no app context (e.g., called from a script)
            # Consider a basic logger setup if this utility is often used outside app context.
            print(f"Error fetching time offset (no app context or logger not configured): {e}. Defaulting offset to 0.")
        offset_hours = 0 # Safeguard if settings fetch fails

    utc_now = datetime.now(timezone.utc)
    effective_time = utc_now + timedelta(hours=offset_hours)
    return effective_time

[end of utils.py]
