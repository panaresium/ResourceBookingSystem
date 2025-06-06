import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime
import tempfile # Added for temporary file
import re # Added for regex parsing of CSV filenames
import time
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError, ServiceRequestError # Added HttpResponseError

# Assuming models.py is in the same directory or accessible via PYTHONPATH
# This import is tricky as azure_backup.py might be run in different contexts.
# If this script is run by a scheduler that doesn't initialize Flask app context fully,
# direct model imports might fail or behave unexpectedly.
# For now, proceeding with the import as requested by the subtask.
from models import Booking
from utils import export_bookings_to_csv_string, import_bookings_from_csv_file

try:
    from azure.storage.fileshare import ShareServiceClient, ShareClient, ShareDirectoryClient, ShareFileClient
    # ResourceNotFoundError and HttpResponseError are already imported above if SDK is present
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    ShareClient = None # Add placeholders if SDK not present
    ShareDirectoryClient = None # Add placeholders
    ShareFileClient = None # Add placeholders
    # Define ResourceNotFoundError and HttpResponseError as base Exception if SDK not present,
    # so try-except blocks later don't cause NameError.
    if 'ResourceNotFoundError' not in globals(): # Ensure it's not already defined
        ResourceNotFoundError = Exception
    if 'HttpResponseError' not in globals(): # Ensure it's not already defined
        HttpResponseError = Exception


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_DB = os.path.join(DATA_DIR, 'backup_hashes.db')

# Module-level logger used for backup operations
logger = logging.getLogger(__name__)


# Constants for backup directories and prefixes
DB_BACKUPS_DIR = 'db_backups'
CONFIG_BACKUPS_DIR = 'config_backups'
BOOKING_CSV_BACKUPS_DIR = 'booking_csv_backups' # New constant for booking CSVs
MEDIA_BACKUPS_DIR_BASE = 'media_backups'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'
DB_FILENAME_PREFIX = 'site_'
BOOKING_CSV_FILENAME_PREFIX = 'bookings_' # New prefix for booking CSVs


def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if ShareServiceClient is None:
        raise RuntimeError('azure-storage-file-share package is not installed')
    return ShareServiceClient.from_connection_string(connection_string)


def _client_exists(client):
    """
    Return True if the given Share/File/Directory client exists.
    Uses the appropriate get_properties method and catches ResourceNotFoundError
    for ShareClient, ShareDirectoryClient, and ShareFileClient from azure-storage-file-share.
    """
    try:
        if isinstance(client, ShareClient):
            client.get_share_properties()
        elif isinstance(client, ShareDirectoryClient):
            client.get_directory_properties()
        elif isinstance(client, ShareFileClient):
            client.get_file_properties()
        else:
            # Fallback or error for unknown client types, though the code typically passes specific clients.
            # Depending on strictness, could raise an error or log a warning.
            # For now, assume it's one of the known types based on usage elsewhere.
            # If client type is unknown and has no 'exists' or 'get_properties', this will likely error out.
            # However, the original code also assumed client.exists() would be present.
            logger.warning(f"Unknown client type passed to _client_exists: {type(client)}. Attempting generic check if possible or expecting error.")
            # As a very basic fallback, if we absolutely had to try something generic:
            # return hasattr(client, 'get_properties') # This is too generic and not reliable.
            # Better to rely on the specific types above.
            # If it's not one of the above, and doesn't have a method that would indicate existence,
            # it's safer to assume it doesn't exist or let an error propagate if type is truly unexpected.
            # Given the function's use, it's always one of the three Azure clients.
            return False # Or raise TypeError if strictness is required.
        return True
    except ResourceNotFoundError:
        return False
    except Exception as e:
        # Log unexpected errors during the exists() check for diagnostics
        logger.warning(f"Unexpected error when checking client existence for '{getattr(client, 'name', 'Unknown Client')}' (type: {type(client).__name__}): {e}", exc_info=True)
        return False # Safely assume not exists on unexpected error

def _get_hash_conn():
    os.makedirs(os.path.dirname(HASH_DB), exist_ok=True)
    conn = sqlite3.connect(HASH_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS backup_hashes (filename TEXT PRIMARY KEY, filehash TEXT)"
    )
    return conn


def _load_hashes():
    conn = _get_hash_conn()
    cur = conn.execute("SELECT filename, filehash FROM backup_hashes")
    hashes = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return hashes


def _save_hashes(hashes):
    conn = _get_hash_conn()
    conn.execute("DELETE FROM backup_hashes")
    conn.executemany(
        "INSERT OR REPLACE INTO backup_hashes(filename, filehash) VALUES (?, ?)",
        list(hashes.items()),
    )
    conn.commit()
    conn.close()


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _emit_progress(socketio_instance, task_id, event_name, message, detail='', level='INFO'):
    """
    Emits a progress event via SocketIO if an instance and task_id are provided.

    Args:
        socketio_instance: The SocketIO instance.
        task_id (str): The ID of the task for which progress is being reported.
        event_name (str): The name of the SocketIO event to emit.
        message (str): The main progress message.
        detail (str, optional): Additional details for the progress. Defaults to ''.
        level (str, optional): The severity level of the progress message (e.g., 'INFO',
                               'WARNING', 'ERROR', 'SUCCESS'). Defaults to 'INFO'.
    """
    if socketio_instance and task_id:
        try:
            payload = {
                'task_id': task_id,
                'status': message,
                'detail': detail,
                'level': level.upper()  # Ensure level is uppercase for consistency
            }
            socketio_instance.emit(event_name, payload)
            # logger.debug(f"Emitted {event_name} for {task_id}: {message} - {detail} - Level: {level}")
        except Exception as e:
            logger.error(f"Failed to emit SocketIO event {event_name} for task {task_id} (Level: {level}): {e}")

def _ensure_directory_exists(share_client, directory_path):
    """Ensure the specified directory exists on the share, creating it if necessary."""
    if not directory_path: # Cannot ensure empty or root path with this logic
        return
    dir_client = share_client.get_directory_client(directory_path)
    if not _client_exists(dir_client):
        try:
            dir_client.create_directory()
            logger.info(f"Created directory '{directory_path}' on share '{share_client.share_name}'.")
        except Exception as e:
            logger.error(f"Failed to create directory '{directory_path}' on share '{share_client.share_name}': {e}")
            raise


# Helper function to create a share with retry logic
def _create_share_with_retry(share_client, share_name, retries=3, delay_seconds=5, backoff_factor=2):
    """
    Attempts to create a share with retries on failure.

    Args:
        share_client: The Azure ShareClient.
        share_name (str): Name of the share (for logging).
        retries (int): Maximum number of retry attempts.
        delay_seconds (int): Initial delay between retries.
        backoff_factor (int): Factor by which the delay increases after each retry.

    Returns:
        bool: True if the share was created or already exists, False if all retries failed.
              (Note: Will re-raise ServiceRequestError on final attempt failure)
    """
    current_delay = delay_seconds
    for attempt_num in range(retries):
        try:
            share_client.create_share()
            logger.info(f"Share '{share_name}' created successfully or already existed.")
            return True
        except ServiceRequestError as e:
            logger.error(
                f"Attempt {attempt_num + 1} of {retries}: Failed to create share '{share_name}'. "
                f"Error: {e}. Retrying in {current_delay} seconds..."
            )
            if attempt_num == retries - 1:
                logger.error(f"All {retries} retries failed for share '{share_name}'. Error: {e}")
                raise  # Re-raise the exception on the last attempt
            time.sleep(current_delay)
            current_delay *= backoff_factor
        except Exception as e: # Catch other unexpected exceptions
            logger.error(
                f"An unexpected error occurred while trying to create share '{share_name}' on attempt {attempt_num + 1}: {e}"
            )
            # For unexpected errors, re-raise immediately without retry.
            # If retrying these is desired, this block needs to be more like the ServiceRequestError block.
            raise


def upload_file(share_client, source_path, file_path):
    directory_path = os.path.dirname(file_path)
    if directory_path:
        directory_client = share_client.get_directory_client(directory_path)
        if not _client_exists(directory_client):
            try:
                logger.info(f"Attempting to create directory '{directory_path}' in share '{share_client.share_name}' from within upload_file.")
                directory_client.create_directory()
                logger.info(f"Successfully created directory '{directory_path}' in share '{share_client.share_name}'.")
            except Exception as e:
                logger.error(f"Failed to create directory '{directory_path}' in share '{share_client.share_name}' from within upload_file: {e}")
                raise RuntimeError(f"Failed to create parent directory '{directory_path}' for file '{file_path}'. Original error: {e}")
    file_client = share_client.get_file_client(file_path)
    with open(source_path, 'rb') as f:
        data = f.read()
    # ShareFileClient.upload_file does not support an 'overwrite' parameter.
    # Passing it causes a TypeError when the request is sent. Simply uploading
    # the data will overwrite the file if it already exists.
    file_client.upload_file(data)


def download_file(share_client, file_path, dest_path):
    file_client = share_client.get_file_client(file_path)
    if not _client_exists(file_client):
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        downloader = file_client.download_file()

        # Check for 0-byte file
        if downloader.properties.size == 0:
            with open(dest_path, 'wb') as f:
                pass # Create empty file
            logger.info(f"Successfully created empty file for 0-byte remote file '{file_path}' at '{dest_path}'.")
            return True

        # For non-empty files, proceed to read content
        content = downloader.readall()

        with open(dest_path, 'wb') as f:
            f.write(content)

        logger.info(f"Successfully downloaded '{file_path}' (size: {downloader.properties.size}) to '{dest_path}'.")
        return True

    except HttpResponseError as hre:
        # This will catch HTTP errors like 404 (ResourceNotFound, though _client_exists should catch this first),
        # 403 (Forbidden), 416 (InvalidRange), etc., that occur during download_file() or readall().
        logger.error(f"Failed to download file '{file_path}' from share '{share_client.share_name}'. "
                     f"Azure HTTP Error: {type(hre).__name__}, Status: {hre.status_code if hasattr(hre, 'status_code') else 'N/A'}, Details: {str(hre)}",
                     exc_info=True) # Log with full traceback
        return False
    except Exception as e:
        # Catch any other unexpected errors during download or file writing.
        logger.error(f"An unexpected error occurred downloading file '{file_path}' from share '{share_client.share_name}'. "
                     f"Exception: {type(e).__name__}, Details: {str(e)}",
                     exc_info=True) # Log with full traceback
        return False


def backup_database():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        _create_share_with_retry(share_client, share_name) # MODIFIED
    db_path = os.path.join(DATA_DIR, 'site.db')
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    file_name = f'site_{timestamp}.db'
    upload_file(share_client, db_path, file_name)
    return file_name


def save_floor_map_to_share(local_path, dest_filename=None):
    """Upload a single floor map file to the configured Azure File Share."""
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        _create_share_with_retry(share_client, share_name) # MODIFIED
    if dest_filename is None:
        dest_filename = os.path.basename(local_path)
    file_path = f'floor_map_uploads/{dest_filename}'
    upload_file(share_client, local_path, file_path)


def backup_media():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        _create_share_with_retry(share_client, share_name) # MODIFIED
    # Upload floor map images
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                file_path = f'{os.path.basename(folder)}/{fname}'
                upload_file(share_client, fpath, file_path)


def backup_if_changed():
    """Backup the SQLite database and media files only when their hashes change.

    The database file lives in ``data/site.db`` and is not committed to the
    repository. This function uploads that file along with any images under
    ``static/floor_map_uploads`` and ``static/resource_uploads`` to the
    configured Azure File Shares.
    """
    hashes = _load_hashes()
    service_client = _get_service_client()

    # Database backup
    db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_client = service_client.get_share_client(db_share)
    if not _client_exists(db_client):
        _create_share_with_retry(db_client, db_share) # MODIFIED
    db_local = os.path.join(DATA_DIR, 'site.db')
    db_rel = 'site.db'
    db_hash = _hash_file(db_local) if os.path.exists(db_local) else None
    if db_hash is None:
        logger.warning(f"Database file not found: {db_local}")
    elif hashes.get(db_rel) != db_hash:
        upload_file(db_client, db_local, db_rel)
        hashes[db_rel] = db_hash
        logger.info(f"Uploaded database '{db_rel}' to share '{db_share}'.")
    else:
        logger.info("Database unchanged; skipping upload")

    # Media backup
    media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_client = service_client.get_share_client(media_share)
    if not _client_exists(media_client):
        _create_share_with_retry(media_client, media_share) # MODIFIED
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue
            rel = f"{os.path.basename(folder)}/{fname}"
            f_hash = _hash_file(fpath)
            if hashes.get(rel) != f_hash:
                upload_file(media_client, fpath, rel)
                hashes[rel] = f_hash
                logger.info(f"Uploaded media file '{rel}' to share '{media_share}'.")


    _save_hashes(hashes)


# def restore_from_share():
#     """
#     DEPRECATED: Replaced by restore_latest_backup_set_on_startup for use in app_factory.py.
#     Download DB and media files from Azure File Share if available.
#     """
#     service_client = _get_service_client()

#     db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
#     db_client = service_client.get_share_client(db_share)
#     if _client_exists(db_client):
#         download_file(db_client, 'site.db', os.path.join(DATA_DIR, 'site.db'))

#     media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
#     media_client = service_client.get_share_client(media_share)
#     if _client_exists(media_client):
#         for prefix in ('floor_map_uploads', 'resource_uploads'):
#             directory_client = media_client.get_directory_client(prefix)
#             if not _client_exists(directory_client):
#                 continue
#             for item in directory_client.list_directories_and_files():
#                 file_path = f"{prefix}/{item['name']}"
#                 dest = os.path.join(STATIC_DIR, prefix, item['name'])
#                 download_file(media_client, file_path, dest)


def main():
    """Run an incremental backup when executed as a script."""
    backup_if_changed()
    print('Backup completed.')


def backup_bookings_csv(app, socketio_instance=None, task_id=None, start_date_dt=None, end_date_dt=None, range_label=None):
    """
    Creates a CSV backup of bookings, optionally filtered by date range, and uploads it to Azure File Share.

    Args:
        app: The Flask application object (for app context).
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.
        start_date_dt (datetime.datetime, optional): Start date for filtering bookings.
        end_date_dt (datetime.datetime, optional): End date for filtering bookings.
        range_label (str, optional): A label for the date range (e.g., "1day", "all").
    Returns:
        bool: True if backup was successful, False otherwise.
    """
    if range_label and range_label.strip():
        effective_range_label = range_label.strip()
    else:
        effective_range_label = "all"

    log_msg_detail = f"range: {effective_range_label}"
    if start_date_dt:
        log_msg_detail += f", from: {start_date_dt.strftime('%Y-%m-%d %H:%M:%S') if start_date_dt else 'any'}"
    if end_date_dt:
        log_msg_detail += f", to: {end_date_dt.strftime('%Y-%m-%d %H:%M:%S') if end_date_dt else 'any'}"

    logger.info(f"Starting booking CSV backup process ({log_msg_detail}). Task ID: {task_id}")
    _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', f'Starting booking CSV backup ({effective_range_label})...', detail=log_msg_detail, level='INFO')

    try:
        timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        remote_filename = f"{BOOKING_CSV_FILENAME_PREFIX}{effective_range_label}_{timestamp_str}.csv"

        csv_data_string = ""
        # The export_bookings_to_csv_string function now handles app_context and querying
        logger.info(f"Exporting bookings ({log_msg_detail}) to CSV format for backup file {remote_filename}.")
        _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', f'Exporting bookings ({effective_range_label})...', detail=log_msg_detail, level='INFO')
        csv_data_string = export_bookings_to_csv_string(app, start_date=start_date_dt, end_date=end_date_dt)

        # Check if csv_data_string is empty or only contains the header
        # (A simple check for number of newlines; header + 1 data row means at least 2 newlines)
        if not csv_data_string or csv_data_string.count('\n') < 2 :
            logger.info("CSV data is empty or contains only headers. Skipping upload of empty booking CSV backup.")
            _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', 'No data to backup after CSV export.', detail='CSV data empty or headers only.', level='INFO')
            return True

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv', encoding='utf-8') as tmp_file:
            tmp_file.write(csv_data_string)
            temp_file_path = tmp_file.name

        logger.info(f"CSV data written to temporary file: {temp_file_path}")

        service_client = _get_service_client()
        # Using AZURE_CONFIG_SHARE for booking CSVs as per subtask notes
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            logger.info(f"Creating share '{share_name}' for booking CSV backups.")
            _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', f"Creating share '{share_name}'...", level='INFO')
            _create_share_with_retry(share_client, share_name) # MODIFIED

        _ensure_directory_exists(share_client, BOOKING_CSV_BACKUPS_DIR)

        remote_path_on_azure = f"{BOOKING_CSV_BACKUPS_DIR}/{remote_filename}"

        logger.info(f"Attempting to upload booking CSV backup: {temp_file_path} to {share_name}/{remote_path_on_azure}")
        _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', f'Uploading {remote_filename} to {share_name}...', level='INFO')

        upload_file(share_client, temp_file_path, remote_path_on_azure)

        logger.info(f"Successfully backed up bookings CSV to '{share_name}/{remote_path_on_azure}'.")
        _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', 'Booking CSV backup complete.', detail=f'{share_name}/{remote_path_on_azure}', level='SUCCESS')
        return True

    except Exception as e:
        logger.error(f"Failed to backup bookings CSV: {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, 'booking_csv_backup_progress', 'Booking CSV backup failed.', detail=str(e), level='ERROR')
        return False
    finally:
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"Temporary file {temp_file_path} deleted.")
            except Exception as e_remove:
                logger.error(f"Error deleting temporary file {temp_file_path}: {e_remove}", exc_info=True)


def list_available_booking_csv_backups():
    """
    Lists available booking CSV backup timestamps from Azure File Share.

    Returns:
        list: A sorted list of dictionaries, each representing a backup file.
              Each dictionary contains 'timestamp', 'range_label', 'filename', 'display_name'.
              Returns an empty list if no backups are found or if there's an error.
    """
    logger.info("Attempting to list available booking CSV backups with range labels.")
    backup_items = []
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            logger.warning(f"Booking CSV backup share '{share_name}' does not exist. No backups to list.")
            return []

        backup_dir_client = share_client.get_directory_client(BOOKING_CSV_BACKUPS_DIR)
        if not _client_exists(backup_dir_client):
            logger.warning(f"Booking CSV backup directory '{BOOKING_CSV_BACKUPS_DIR}' does not exist on share '{share_name}'. No backups to list.")
            return []

        # Regex to capture range_label (optional) and timestamp
        # Assumes BOOKING_CSV_FILENAME_PREFIX is 'bookings_'
        # Example: bookings_3days_20230101_100000.csv -> range_label '3days', timestamp '20230101_100000'
        # Example: bookings_all_20230101_100000.csv -> range_label 'all', timestamp '20230101_100000'
        # Example: bookings_20230101_100000.csv -> range_label 'all' (implicit), timestamp '20230101_100000'
        pattern = re.compile(
            rf"^{re.escape(BOOKING_CSV_FILENAME_PREFIX)}(?P<range_label_part>[a-zA-Z0-9]+_)?(?P<timestamp>\d{{8}}_\d{{6}})\.csv$"
        )
        # A more robust pattern that assumes if range_label_part is not present, then it's an older format without explicit "all"
        # This regex matches:
        #   bookings_all_20230101_100000.csv -> range_label_part='all_', timestamp='20230101_100000'
        #   bookings_3days_20230101_100000.csv -> range_label_part='3days_', timestamp='20230101_100000'
        #   bookings_20230101_100000.csv -> range_label_part=None, timestamp='20230101_100000'

        # Corrected regex to handle files that might not have range_label part
        # e.g. bookings_YYYYMMDD_HHMMSS.csv or bookings_somelabel_YYYYMMDD_HHMMSS.csv
        # The key is that range_label part must end with an underscore if present.
        # If BOOKING_CSV_FILENAME_PREFIX is "bookings_", then:
        # filename_part = filename[len(BOOKING_CSV_FILENAME_PREFIX):-len('.csv')]
        # Example filename_part:
        #   "all_20230101_100000"
        #   "3days_20230101_100000"
        #   "20230101_100000" (older format, implicitly "all")

        for item in backup_dir_client.list_directories_and_files():
            if item['is_directory']:
                continue

            filename = item['name']

            # Simplified parsing based on structure: {PREFIX}{label}_{TIMESTAMP}.csv
            # Or for older/implicit 'all': {PREFIX}{TIMESTAMP}.csv
            if not filename.startswith(BOOKING_CSV_FILENAME_PREFIX) or not filename.endswith('.csv'):
                logger.warning(f"Skipping file with incorrect prefix/suffix: {filename}")
                continue

            name_part = filename[len(BOOKING_CSV_FILENAME_PREFIX):-len('.csv')] # Strip prefix and suffix

            # Parsing logic:
            # The timestamp is always the last two parts if split by '_',
            # e.g., YYYYMMDD_HHMMSS.
            # Any parts before that constitute the range_label.
            # If there are no parts before the timestamp, it's an older format
            # or an implicit "all" range.
            parts = name_part.split('_')
            timestamp_str = ""
            range_label = "all" # Default to "all"

            # Check if the last two parts could form a valid timestamp based on length and digits
            if len(parts) >= 2 and \
               len(parts[-2]) == 8 and re.match(r'^\d{8}$', parts[-2]) and \
               len(parts[-1]) == 6 and re.match(r'^\d{6}$', parts[-1]):
                try:
                    # Potential timestamp found, construct and validate its format
                    timestamp_str = f"{parts[-2]}_{parts[-1]}"
                    datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S') # Validate actual date/time format

                    # The remaining parts (if any) form the range_label
                    label_parts = parts[:-2]
                    if label_parts:
                        range_label = "_".join(label_parts)
                    # If label_parts is empty, it means the filename was like "bookings_YYYYMMDD_HHMMSS.csv",
                    # so range_label correctly remains "all" (the default).
                except ValueError:
                    # Timestamp format was incorrect (e.g., invalid date like 20231301)
                    logger.warning(f"Skipping CSV backup with invalid timestamp in name: {filename} (parsed timestamp as {timestamp_str})")
                    continue
            else:
                # Filename does not match the expected pattern for timestamp (e.g., not enough parts, incorrect length/format)
                logger.warning(f"Skipping CSV backup with unexpected filename format after prefix: {name_part} (from full filename: {filename})")
                continue

            # Create a user-friendly display name for UI
            display_range = range_label.replace("_", " ").replace("day", " Day").replace("days", " Days").title()
            if display_range == "All":
                display_range = "All Bookings"

            try:
                ts_datetime = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                display_timestamp = ts_datetime.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError: # Should not happen due to earlier validation, but as safety
                display_timestamp = timestamp_str.replace("_", " ") # Basic fallback display

            backup_item = {
                'timestamp': timestamp_str,
                'range_label': range_label,
                'filename': filename,
                'display_name': f"Bookings ({display_range}) - {display_timestamp} UTC"
            }
            backup_items.append(backup_item)

        # Sort by timestamp, newest first
        backup_items.sort(key=lambda x: x['timestamp'], reverse=True)

        logger.info(f"Found {len(backup_items)} available booking CSV backup items.")
        return backup_items

    except Exception as e:
        logger.error(f"Error listing available booking CSV backups: {e}", exc_info=True)
        return []


def restore_bookings_from_csv_backup(app, timestamp_str, socketio_instance=None, task_id=None):
    """
    Restores bookings from a specific CSV backup file from Azure File Share.

    Args:
        app: The Flask application object (for app context).
        timestamp_str (str): The timestamp of the booking CSV backup to restore.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        dict: A summary of the restore operation.
    """
    event_name = 'booking_csv_restore_progress'
    actions_summary = {
        'status': 'started',
        'message': f'Starting restore of booking CSV for timestamp {timestamp_str}.',
        'processed': 0,
        'created': 0,
        'skipped_duplicates': 0,
        'errors': []
    }
    logger.info(actions_summary['message'])
    _emit_progress(socketio_instance, task_id, event_name, actions_summary['message'], level='INFO')

    temp_csv_path = None  # Initialize to ensure it's available in finally block

    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            actions_summary['status'] = 'failed'
            actions_summary['message'] = f"Azure share '{share_name}' not found."
            actions_summary['errors'].append(actions_summary['message'])
            logger.error(actions_summary['message'])
            _emit_progress(socketio_instance, task_id, event_name, actions_summary['message'], detail=f"Share '{share_name}' not found.", level='ERROR')
            return actions_summary

        # Filename might now include a range label.
        # To restore, we need the exact filename. The timestamp_str alone is not enough.
        # This function will need to find the filename that matches the timestamp_str.
        # For now, assume timestamp_str IS the unique identifier and older files (without range_label in name)
        # are implicitly 'all'. This means the filename construction needs to be smarter or
        # this function needs the full filename or the parsed range_label.
        # Let's assume for now the route passes the full filename or enough info.
        # The current subtask is about LISTING. This function's modification is not the primary focus here,
        # but its call signature implies it might need adjustment later if timestamp_str is not unique.
        # For now, the existing logic for finding the file is based on timestamp_str only.
        # If all new files have {PREFIX}{label}_{TIMESTAMP}.csv, then the old logic
        # of {PREFIX}{TIMESTAMP}.csv will fail for new files.
        # The simplest fix here is to iterate and find the matching file if timestamp_str is just the time part.
        # However, the calling route `restore_booking_csv_route` uses `timestamp_str` from the URL,
        # which will be the pure timestamp. So, we need to find the actual filename.
        # This part needs careful thought for compatibility.
        # For now, let's assume the filename is uniquely identified by the timestamp_str (which is how it was before ranges)
        # OR that the calling route will be updated to pass the full filename.
        # The prompt for THIS task is about LISTING, so I will focus on that.
        # The `restore_booking_csv_route` will pass the `backup_item.timestamp` which is `YYYYMMDD_HHMMSS`.
        # So, this function needs to find the correct file.
        # This is a significant change from just `f"{BOOKING_CSV_FILENAME_PREFIX}{timestamp_str}.csv"`

        # Get all backup items to find the one matching the timestamp_str
        all_backup_files_details = list_available_booking_csv_backups() # This now returns list of dicts
        target_backup_item = None
        for item_detail in all_backup_files_details:
            if item_detail['timestamp'] == timestamp_str:
                target_backup_item = item_detail
                break

        if not target_backup_item:
            actions_summary['status'] = 'failed'
            actions_summary['message'] = f"Booking CSV backup for timestamp '{timestamp_str}' not found in available list."
            actions_summary['errors'].append(actions_summary['message'])
            logger.error(actions_summary['message'])
            _emit_progress(socketio_instance, task_id, event_name, actions_summary['message'], detail=f"Timestamp '{timestamp_str}' not in list.", level='ERROR')
            return actions_summary

        remote_csv_filename = target_backup_item['filename'] # Use the actual filename
        remote_azure_path = f"{BOOKING_CSV_BACKUPS_DIR}/{remote_csv_filename}"

        file_client = share_client.get_file_client(remote_azure_path)
        if not _client_exists(file_client):
            actions_summary['status'] = 'failed'
            actions_summary['message'] = f"Booking CSV backup file '{remote_azure_path}' not found on share '{share_name}'."
            actions_summary['errors'].append(actions_summary['message'])
            logger.error(actions_summary['message'])
            _emit_progress(socketio_instance, task_id, event_name, actions_summary['message'], detail=f"File '{remote_azure_path}' not on share.", level='ERROR')
            return actions_summary

        _emit_progress(socketio_instance, task_id, event_name, f"Downloading booking CSV: {remote_azure_path}", level='INFO')

        # Create a temporary file to download the CSV into
        # delete=False is important because we need to pass the path to another function
        # and ensure the file is still there. We'll manually delete it.
        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w+b') as tmp_file_obj:
            temp_csv_path = tmp_file_obj.name
        # The file is created empty and closed. download_file will open it in 'wb' mode.

        logger.info(f"Downloading '{remote_azure_path}' to temporary file '{temp_csv_path}'.")
        download_success = download_file(share_client, remote_azure_path, temp_csv_path)

        if not download_success:
            actions_summary['status'] = 'failed'
            actions_summary['message'] = f"Failed to download booking CSV '{remote_azure_path}'."
            actions_summary['errors'].append(actions_summary['message'])
            logger.error(actions_summary['message'])
            _emit_progress(socketio_instance, task_id, event_name, actions_summary['message'], detail=f"Download failed for '{remote_azure_path}'.", level='ERROR')
            # temp_csv_path might still exist if download_file created it but failed writing, handled in finally
            return actions_summary

        logger.info(f"Successfully downloaded booking CSV to '{temp_csv_path}'. Starting import.")
        _emit_progress(socketio_instance, task_id, event_name, "Download complete. Starting import from CSV.", level='INFO')

        import_summary = import_bookings_from_csv_file(temp_csv_path, app)

        actions_summary.update(import_summary) # This will overwrite 'errors' if any, and add others
        actions_summary['message'] = "Booking CSV restore process completed."

        if import_summary.get('errors'):
            actions_summary['status'] = 'completed_with_errors'
            logger.warning(f"Booking CSV import for {timestamp_str} completed with errors. Summary: {import_summary}")
            _emit_progress(socketio_instance, task_id, event_name, "Import completed with errors.", detail=f"Errors: {len(import_summary['errors'])}", level='WARNING')
        else:
            actions_summary['status'] = 'completed_successfully'
            logger.info(f"Booking CSV import for {timestamp_str} completed successfully. Summary: {import_summary}")
            _emit_progress(socketio_instance, task_id, event_name, "Import completed successfully.", detail="All records imported.", level='SUCCESS')

    except Exception as e:
        error_message = f"An unexpected error occurred during booking CSV restore: {str(e)}"
        logger.error(error_message, exc_info=True)
        actions_summary['status'] = 'failed'
        actions_summary['message'] = error_message
        if str(e) not in actions_summary['errors']: # Avoid duplicate generic error
            actions_summary['errors'].append(str(e))
        _emit_progress(socketio_instance, task_id, event_name, error_message, detail=str(e), level='CRITICAL_ERROR')
    finally:
        if temp_csv_path and os.path.exists(temp_csv_path):
            try:
                os.remove(temp_csv_path)
                logger.info(f"Temporary CSV file '{temp_csv_path}' deleted.")
            except Exception as e_remove:
                logger.error(f"Failed to delete temporary CSV file '{temp_csv_path}': {e_remove}", exc_info=True)
                # Optionally add this error to actions_summary['errors'] if critical for audit
                # actions_summary['errors'].append(f"Cleanup error: Failed to delete temp file {temp_csv_path}: {e_remove}")

    return actions_summary


def verify_booking_csv_backup(timestamp_str, socketio_instance=None, task_id=None):
    """
    Verifies the existence of a specific Booking CSV backup file in Azure File Share.

    Args:
        timestamp_str (str): The timestamp of the booking CSV backup to verify.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        dict: A result dictionary with 'status', 'message', and 'file_path'.
    """
    event_name = 'booking_csv_verify_progress'
    result = {
        'status': 'unknown', # Possible: unknown, success, not_found, error
        'message': '',
        'file_path': ''
    }

    logger.info(f"Starting verification for booking CSV backup: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, event_name, 'Starting booking CSV verification...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            result['status'] = 'error'
            result['message'] = f"Azure share '{share_name}' not found."
            logger.error(result['message'])
            _emit_progress(socketio_instance, task_id, event_name, result['message'], detail=f"Share '{share_name}' not found.", level='ERROR')
            return result

        # Similar logic adjustment needed for verify_booking_csv_backup as in restore
        all_backup_files_details_verify = list_available_booking_csv_backups()
        target_backup_item_verify = None
        for item_detail_v in all_backup_files_details_verify:
            if item_detail_v['timestamp'] == timestamp_str:
                target_backup_item_verify = item_detail_v
                break

        if not target_backup_item_verify:
            result['status'] = 'error' # Changed from not_found to error, as it implies an issue if called for a non-listed ts
            result['message'] = f"Booking CSV backup for timestamp '{timestamp_str}' not found in available list for verification."
            logger.error(result['message'])
            _emit_progress(socketio_instance, task_id, event_name, result['message'], detail=f"Timestamp '{timestamp_str}' not in list.", level='ERROR')
            return result

        remote_csv_filename = target_backup_item_verify['filename']
        remote_azure_path = f"{BOOKING_CSV_BACKUPS_DIR}/{remote_csv_filename}"
        result['file_path'] = remote_azure_path

        file_client = share_client.get_file_client(remote_azure_path)

        if file_client.exists(): # This check remains valid
            result['status'] = 'success'
            result['message'] = f"Booking CSV backup file '{remote_csv_filename}' verified successfully (found) on share '{share_name}' at path '{remote_azure_path}'."
            logger.info(result['message'])
            _emit_progress(socketio_instance, task_id, event_name, 'Verification successful: File found.', detail=remote_azure_path, level='SUCCESS')
        else:
            result['status'] = 'not_found'
            result['message'] = f"Booking CSV backup file '{remote_csv_filename}' NOT found on Azure share '{share_name}' at path '{remote_azure_path}'."
            logger.warning(result['message'])
            _emit_progress(socketio_instance, task_id, event_name, 'Verification failed: File not found.', detail=remote_azure_path, level='WARNING')

    except RuntimeError as rte: # Specifically catch RuntimeError from _get_service_client
        result['status'] = 'error'
        result['message'] = str(rte)
        logger.error(f"Error during booking CSV verification for {timestamp_str}: {result['message']}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, result['message'], detail=str(rte), level='ERROR')
    except Exception as e:
        result['status'] = 'error'
        result['message'] = f"An unexpected error occurred during verification: {str(e)}"
        logger.error(f"Unexpected error during booking CSV verification for {timestamp_str}: {result['message']}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, result['message'], detail=str(e), level='CRITICAL_ERROR')

    return result


def delete_booking_csv_backup(timestamp_str, socketio_instance=None, task_id=None):
    """
    Deletes a specific Booking CSV backup file from Azure File Share.

    Args:
        timestamp_str (str): The timestamp of the booking CSV backup to delete.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        bool: True if deletion was successful or file was not found, False if an error occurred.
    """
    event_name = 'booking_csv_delete_progress' # Could be a more generic event if preferred
    logger.info(f"Attempting to delete booking CSV backup for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, event_name, f"Starting deletion of booking CSV backup: {timestamp_str}", level='INFO')

    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups') # Same share as backup
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            logger.error(f"Azure share '{share_name}' not found. Cannot delete booking CSV backup.")
            _emit_progress(socketio_instance, task_id, event_name, f"Share '{share_name}' not found.", detail=f"Share name: {share_name}", level='ERROR')
            return False

        # Similar logic adjustment needed for delete_booking_csv_backup as in restore and verify
        all_backup_files_details_delete = list_available_booking_csv_backups()
        target_backup_item_delete = None
        for item_detail_d in all_backup_files_details_delete:
            if item_detail_d['timestamp'] == timestamp_str:
                target_backup_item_delete = item_detail_d
                break

        if not target_backup_item_delete:
            # If we are asked to delete a timestamp that's not listed, it might mean it's already gone
            # or the list is stale. For deletion, this is usually fine.
            logger.info(f"Booking CSV backup for timestamp '{timestamp_str}' not found in available list. Assuming already deleted.")
            _emit_progress(socketio_instance, task_id, event_name, f"Backup for '{timestamp_str}' not found. Assuming already deleted.", detail=f"Timestamp {timestamp_str} not in list.", level='INFO')
            return True # Effectively deleted

        remote_csv_filename = target_backup_item_delete['filename']
        remote_azure_path = f"{BOOKING_CSV_BACKUPS_DIR}/{remote_csv_filename}"

        file_client = share_client.get_file_client(remote_azure_path)

        if _client_exists(file_client):
            logger.info(f"Booking CSV backup '{remote_azure_path}' found on share '{share_name}'. Attempting deletion.")
            _emit_progress(socketio_instance, task_id, event_name, f"File '{remote_csv_filename}' found. Deleting...", detail=remote_azure_path, level='INFO')
            try:
                file_client.delete_file()
                logger.info(f"Successfully deleted booking CSV backup '{remote_azure_path}'.")
                _emit_progress(socketio_instance, task_id, event_name, f"File '{remote_csv_filename}' deleted successfully.", detail=remote_azure_path, level='SUCCESS')
                return True
            except Exception as e_delete:
                logger.error(f"Failed to delete booking CSV backup '{remote_azure_path}': {e_delete}", exc_info=True)
                _emit_progress(socketio_instance, task_id, event_name, f"Error deleting file '{remote_csv_filename}'.", detail=str(e_delete), level='ERROR')
                return False
        else:
            # This case should ideally be covered by the check against all_backup_files_details_delete
            # But if it occurs due to a race condition or inconsistency:
            logger.info(f"Booking CSV backup '{remote_azure_path}' confirmed not found on share '{share_name}' by _client_exists. No action needed.")
            _emit_progress(socketio_instance, task_id, event_name, f"File '{remote_csv_filename}' not found by _client_exists. Already deleted or never existed.", detail=remote_azure_path, level='INFO')
            return True

    except Exception as e:
        logger.error(f"An unexpected error occurred during deletion of booking CSV backup for {timestamp_str}: {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, f"Unexpected error deleting CSV backup for {timestamp_str}.", detail=str(e), level='CRITICAL_ERROR')
        return False


# --- Backup Component Functions ---

def backup_database_component(timestamp_str, db_share_client, local_db_path, socketio_instance=None, task_id=None):
    """
    Backs up the database file, including WAL checkpoint.

    Args:
        timestamp_str (str): The timestamp for the backup.
        db_share_client: The Azure ShareClient for database backups.
        local_db_path (str): Path to the local database file.
        socketio_instance: Optional SocketIO instance.
        task_id: Optional task ID for SocketIO.

    Returns:
        tuple: (bool success, str remote_db_path_or_error_msg)
    """
    remote_db_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
    remote_db_path = f"{DB_BACKUPS_DIR}/{remote_db_filename}"
    event_name = 'backup_progress' # Assuming 'backup_progress' is the common event

    _emit_progress(socketio_instance, task_id, event_name, 'Backing up database...', detail=f'{local_db_path} to {db_share_client.share_name}/{remote_db_path}', level='INFO')

    if not os.path.exists(local_db_path):
        logger.warning(f"Local database file not found at '{local_db_path}'. Skipping database backup.")
        _emit_progress(socketio_instance, task_id, event_name, 'Database backup skipped (local file not found).', detail=local_db_path, level='WARNING')
        return False, f"Local database file not found: {local_db_path}"

    try:
        # Perform WAL checkpoint before backup
        logger.info(f"Attempting to perform WAL checkpoint on {local_db_path} before backup.")
        _emit_progress(socketio_instance, task_id, event_name, 'Performing database WAL checkpoint...', detail=local_db_path, level='INFO')
        try:
            conn = sqlite3.connect(local_db_path)
            conn.execute("PRAGMA busy_timeout = 5000;") # 5 seconds
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
            logger.info(f"Successfully performed WAL checkpoint on {local_db_path}.")
            _emit_progress(socketio_instance, task_id, event_name, 'Database WAL checkpoint successful.', level='INFO')
        except sqlite3.Error as e_sqlite:
            logger.error(f"Error during WAL checkpoint on {local_db_path}: {e_sqlite}. Proceeding with backup attempt.", exc_info=True)
            _emit_progress(socketio_instance, task_id, event_name, f'Database WAL checkpoint failed: {e_sqlite}. Continuing backup.', detail=str(e_sqlite), level='WARNING')
        except Exception as e_generic_checkpoint:
            logger.error(f"A non-SQLite error occurred during WAL checkpoint on {local_db_path}: {e_generic_checkpoint}. Proceeding with backup attempt.", exc_info=True)
            _emit_progress(socketio_instance, task_id, event_name, f'Database WAL checkpoint failed with a non-SQLite error: {e_generic_checkpoint}. Continuing backup.', detail=str(e_generic_checkpoint), level='WARNING')

        logger.info(f"Attempting database backup: Share='{db_share_client.share_name}', Path='{remote_db_path}', LocalSource='{local_db_path}'")
        _ensure_directory_exists(db_share_client, DB_BACKUPS_DIR) # Ensure parent directory exists
        upload_file(db_share_client, local_db_path, remote_db_path)
        logger.info(f"Successfully backed up database to '{db_share_client.share_name}/{remote_db_path}'.")
        _emit_progress(socketio_instance, task_id, event_name, 'Database backup complete.', detail=f'{db_share_client.share_name}/{remote_db_path}', level='SUCCESS')
        _emit_progress(socketio_instance, task_id, event_name, 'Database backup includes all tables (e.g., users, bookings, resources).', detail='Informational note.', level='INFO')
        return True, remote_db_path
    except Exception as e:
        logger.error(f"Failed to backup database to '{db_share_client.share_name}/{remote_db_path}': {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, 'Database backup failed.', detail=str(e), level='ERROR')
        return False, str(e)


def backup_json_config_component(config_name, timestamp_str, config_data, config_share_client, remote_dir, remote_filename_prefix, socketio_instance=None, task_id=None):
    """
    Backs up a JSON configuration file.

    Args:
        config_name (str): User-friendly name of the configuration (e.g., "Map Configuration").
        timestamp_str (str): The timestamp for the backup.
        config_data (dict or list): The configuration data to back up.
        config_share_client: The Azure ShareClient for config backups.
        remote_dir (str): The remote directory on the share (e.g., CONFIG_BACKUPS_DIR).
        remote_filename_prefix (str): Prefix for the remote filename (e.g., MAP_CONFIG_FILENAME_PREFIX).
        socketio_instance: Optional SocketIO instance.
        task_id: Optional task ID for SocketIO.

    Returns:
        tuple: (bool success, str remote_config_path_or_error_msg)
    """
    event_name = 'backup_progress'
    remote_filename = f"{remote_filename_prefix}{timestamp_str}.json"
    remote_config_path = f"{remote_dir}/{remote_filename}"

    _emit_progress(socketio_instance, task_id, event_name, f'Backing up {config_name}...', detail=f'To {config_share_client.share_name}/{remote_config_path}', level='INFO')

    if not config_data:
        logger.warning(f"No {config_name} data provided for timestamp {timestamp_str}. Skipping {config_name} backup.")
        _emit_progress(socketio_instance, task_id, event_name, f'{config_name} backup skipped (no data provided).', level='INFO')
        return True, f"No data provided for {config_name}" # Not a failure of backup itself, but no data to backup

    try:
        _ensure_directory_exists(config_share_client, remote_dir) # Ensure parent directory exists
        file_client = config_share_client.get_file_client(remote_config_path)
        config_json_bytes = json.dumps(config_data, indent=2).encode('utf-8')

        logger.info(f"Attempting {config_name} backup: Share='{config_share_client.share_name}', Path='{remote_config_path}'")
        file_client.upload_file(data=config_json_bytes) # Default is overwrite=True if file exists

        logger.info(f"Successfully backed up {config_name} to '{config_share_client.share_name}/{remote_config_path}'.")
        _emit_progress(socketio_instance, task_id, event_name, f'{config_name} backup complete.', detail=f'{config_share_client.share_name}/{remote_config_path}', level='SUCCESS')
        return True, remote_config_path
    except Exception as e:
        logger.error(f"Failed to backup {config_name} to '{config_share_client.share_name}/{remote_config_path}': {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, f'{config_name} backup failed.', detail=str(e), level='ERROR')
        return False, str(e)


def backup_media_component(media_type_name, timestamp_str, local_media_dir_path, remote_media_dir_base_name, media_share_client, socketio_instance=None, task_id=None):
    """
    Backs up a directory of media files.

    Args:
        media_type_name (str): User-friendly name (e.g., "Floor Maps").
        timestamp_str (str): Timestamp for the backup.
        local_media_dir_path (str): Path to the local directory of media files.
        remote_media_dir_base_name (str): Base name for the remote subdirectory (e.g., "floor_map_uploads").
        media_share_client: Azure ShareClient for media backups.
        socketio_instance: Optional SocketIO instance.
        task_id: Optional task ID for SocketIO.

    Returns:
        tuple: (bool success, str status_message)
    """
    event_name = 'backup_progress'
    remote_media_timestamped_dir = f"{MEDIA_BACKUPS_DIR_BASE}/{remote_media_dir_base_name}_{timestamp_str}"

    _emit_progress(socketio_instance, task_id, event_name, f'Backing up {media_type_name}...', detail=f'Local: {local_media_dir_path} to Remote: {media_share_client.share_name}/{remote_media_timestamped_dir}', level='INFO')

    if not os.path.isdir(local_media_dir_path):
        warn_msg = f"Local directory for {media_type_name} not found at '{local_media_dir_path}'. Skipping {media_type_name} backup."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, event_name, f'{media_type_name} backup skipped (directory not found).', detail=local_media_dir_path, level='WARNING')
        return True, warn_msg # Not a failure of backup itself, but no data

    try:
        # Ensure the base directory for all media backups exists first (e.g., 'media_backups')
        _ensure_directory_exists(media_share_client, MEDIA_BACKUPS_DIR_BASE)
        # Ensure the specific timestamped subdirectory for this media type exists (e.g., 'media_backups/floor_map_uploads_20230101_120000')
        _ensure_directory_exists(media_share_client, remote_media_timestamped_dir)

        files_backed_up = 0
        files_failed = 0
        for filename in os.listdir(local_media_dir_path):
            local_file_path = os.path.join(local_media_dir_path, filename)
            if os.path.isfile(local_file_path):
                remote_file_path = f"{remote_media_timestamped_dir}/{filename}"
                _emit_progress(socketio_instance, task_id, event_name, f'Backing up {media_type_name} file: {filename}', detail=local_file_path, level='INFO')
                try:
                    logger.info(f"Attempting {media_type_name} file backup: Share='{media_share_client.share_name}', Path='{remote_file_path}', LocalSource='{local_file_path}'")
                    upload_file(media_share_client, local_file_path, remote_file_path)
                    logger.info(f"Successfully backed up {media_type_name} file '{filename}' to '{media_share_client.share_name}/{remote_file_path}'.")
                    files_backed_up += 1
                except Exception as e_file:
                    files_failed += 1
                    logger.error(f"Failed to backup {media_type_name} file '{local_file_path}' to '{media_share_client.share_name}/{remote_file_path}': {e_file}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, event_name, f'Failed to backup {media_type_name} file: {filename}', detail=str(e_file), level='ERROR')

        status_msg = f"{media_type_name} backup phase complete. Backed up: {files_backed_up}, Failed: {files_failed}."
        _emit_progress(socketio_instance, task_id, event_name, status_msg, level='INFO' if files_failed == 0 else 'WARNING')
        logger.info(status_msg)
        return files_failed == 0, status_msg

    except Exception as e:
        err_msg = f"Critical error during {media_type_name} backup to '{media_share_client.share_name}/{remote_media_timestamped_dir}': {e}"
        logger.error(err_msg, exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, f'{media_type_name} backup failed critically.', detail=str(e), level='ERROR')
        return False, err_msg


def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, socketio_instance=None, task_id=None):
    """
    Creates a full backup of the database, map configuration, and media files.

    Args:
        timestamp_str (str): The timestamp string in "YYYYMMDD_HHMMSS" format.
        map_config_data (dict, optional): Actual map configuration data to back up.
        resource_configs_data (list, optional): Resource configurations data.
        user_configs_data (dict, optional): User and Role configurations data.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.
    """
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Starting full backup processing...', detail=f'Timestamp: {timestamp_str}', level='INFO')
    logger.info(f"Starting full backup for timestamp: {timestamp_str}")
    service_client = _get_service_client()
    overall_success = True

    # Database Backup
    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_share_client = service_client.get_share_client(db_share_name)
    remote_db_path = None # Initialize for manifest
    if not _client_exists(db_share_client):
        logger.info(f"Creating share '{db_share_name}' for database backups.")
        _create_share_with_retry(db_share_client, db_share_name)

    local_db_path = os.path.join(DATA_DIR, 'site.db')
    db_backup_success, db_path_or_msg = backup_database_component(
        timestamp_str, db_share_client, local_db_path, socketio_instance, task_id
    )
    if db_backup_success:
        remote_db_path = db_path_or_msg # Store path for manifest
    else:
        overall_success = False
        # db_path_or_msg contains error message, already logged by component

    # JSON Configurations Backup
    config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    config_share_client = service_client.get_share_client(config_share_name)
    remote_config_path = None # Initialize for manifest (map_config)
    remote_resource_configs_path = None # Initialize for manifest
    remote_user_configs_path = None # Initialize for manifest

    if not _client_exists(config_share_client):
        logger.info(f"Creating share '{config_share_name}' for config backups.")
        _create_share_with_retry(config_share_client, config_share_name)

    # Map Configuration
    map_config_backup_success, map_path_or_msg = backup_json_config_component(
        "Map Configuration", timestamp_str, map_config_data, config_share_client,
        CONFIG_BACKUPS_DIR, MAP_CONFIG_FILENAME_PREFIX, socketio_instance, task_id
    )
    if map_config_backup_success:
        if map_config_data: # Only store path if data was actually backed up
             remote_config_path = map_path_or_msg
    elif map_config_data : # If data was present but backup failed
        overall_success = False

    # Resource Configurations
    resource_configs_backup_success, rc_path_or_msg = backup_json_config_component(
        "Resource Configurations", timestamp_str, resource_configs_data, config_share_client,
        CONFIG_BACKUPS_DIR, "resource_configs_", socketio_instance, task_id
    )
    if resource_configs_backup_success:
        if resource_configs_data:
            remote_resource_configs_path = rc_path_or_msg
    elif resource_configs_data:
        overall_success = False

    # User and Role Configurations
    user_configs_backup_success, uc_path_or_msg = backup_json_config_component(
        "User/Role Configurations", timestamp_str, user_configs_data, config_share_client,
        CONFIG_BACKUPS_DIR, "user_configs_", socketio_instance, task_id
    )
    if user_configs_backup_success:
        if user_configs_data:
            remote_user_configs_path = uc_path_or_msg
    elif user_configs_data:
        overall_success = False

    # Media Backup
    media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_share_client = service_client.get_share_client(media_share_name)
    remote_floor_map_dir = None # Initialize for manifest
    remote_resource_uploads_dir = None # Initialize for manifest

    if not _client_exists(media_share_client):
        logger.info(f"Creating share '{media_share_name}' for media backups.")
        _create_share_with_retry(media_share_client, media_share_name)

    # Check/Create base media backup directory (can be done once if backup_media_component doesn't)
    # Note: backup_media_component now handles this.

    # Floor Maps
    fm_backup_success, fm_status_msg = backup_media_component(
        "Floor Maps", timestamp_str, FLOOR_MAP_UPLOADS, "floor_map_uploads",
        media_share_client, socketio_instance, task_id
    )
    if fm_backup_success: # Store path for manifest if successful
        remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
    elif os.path.isdir(FLOOR_MAP_UPLOADS) : # If directory existed but backup failed
        overall_success = False # Consider it a failure if local dir exists but backup fails

    # Resource Uploads
    ru_backup_success, ru_status_msg = backup_media_component(
        "Resource Uploads", timestamp_str, RESOURCE_UPLOADS, "resource_uploads",
        media_share_client, socketio_instance, task_id
    )
    if ru_backup_success: # Store path for manifest
        remote_resource_uploads_dir = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
    elif os.path.isdir(RESOURCE_UPLOADS):
        overall_success = False

    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Main backup process completed. Overall success so far: {overall_success}', level='INFO')

    if overall_success:
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Checking retention policy...', level='INFO')
        try:
            retention_days_str = os.environ.get('BACKUP_RETENTION_DAYS')
            if not retention_days_str:
                logger.info("BACKUP_RETENTION_DAYS not set. Skipping retention policy.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy skipped (not configured).', level='INFO')
                return overall_success

            try:
                retention_days = int(retention_days_str)
            except ValueError:
                logger.error(f"Invalid BACKUP_RETENTION_DAYS value: '{retention_days_str}'. Must be an integer.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Retention policy error (invalid config value: {retention_days_str}).', detail=f"Value: {retention_days_str}", level='WARNING')
                return overall_success # Still return true as backup itself was successful

            if retention_days <= 0:
                logger.info(f"Backup retention is disabled (BACKUP_RETENTION_DAYS={retention_days}). Skipping.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy skipped (disabled).', level='INFO')
                return overall_success

            logger.info(f"Applying backup retention policy: Keep last {retention_days} days/sets.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', f'Applying retention: keep last {retention_days} backups.', level='INFO')
            available_backups = list_available_backups() # Sorted newest first

            if len(available_backups) > retention_days:
                backups_to_delete_count = len(available_backups) - retention_days
                logger.info(f"Found {len(available_backups)} backups. Need to delete {backups_to_delete_count} oldest backup(s).")
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Found {len(available_backups)} backups, deleting {backups_to_delete_count} oldest ones.', level='INFO')

                timestamps_to_delete = available_backups[retention_days:]

                for ts_to_delete in timestamps_to_delete:
                    logger.info(f"Retention policy: Deleting backup set for timestamp {ts_to_delete}.")
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Retention: Deleting backup set {ts_to_delete}', level='INFO')
                    delete_success = delete_backup_set(ts_to_delete) # delete_backup_set has its own logging for success/failure of individual components
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Deletion of {ts_to_delete} {"completed" if delete_success else "had issues"}.', level='SUCCESS' if delete_success else 'WARNING')
            else:
                logger.info(f"Number of available backups ({len(available_backups)}) is within retention limit ({retention_days}). No old backups to delete.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'No old backups to delete due to retention policy.', level='INFO')
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy check complete.', level='INFO')
        except Exception as e:
            logger.error(f"Error during backup retention policy execution: {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error during retention policy execution.', detail=str(e), level='ERROR')
            # Do not change overall_success here, as the backup itself was successful.
            # Retention is a secondary operation.

    # --- Manifest Creation ---
    # The manifest file provides a record of all components included in this backup set.
    # It helps in verifying the integrity and completeness of the backup during restoration.
    # It includes:
    #   - timestamp: The unique identifier for this backup set.
    #   - files: A list of individual files backed up (DB, JSON configs), their remote paths,
    #            types, SHA256 hashes (of local files/data before upload), and target Azure shares.
    #   - media_directories_expected: A list of media directories, their remote paths, types,
    #                                 expected file counts (based on local source at backup time),
    #                                 and target Azure shares.
    if overall_success: # Only create manifest if all primary backup operations were successful
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Creating backup manifest...', level='INFO')
        logger.info(f"Creating backup manifest for timestamp: {timestamp_str}")
        manifest_data = {'timestamp': timestamp_str, 'files': [], 'media_directories_expected': []}

        # Database entry in manifest
        if os.path.exists(local_db_path): # Check if DB was actually backed up
            try:
                db_hash = _hash_file(local_db_path)
                manifest_data['files'].append({
                    'path': remote_db_path, # remote_db_path defined earlier in the function
                    'type': 'database', # Type identifier for the backup component
                    'sha256': db_hash, # Hash of the local DB file at the time of backup
                    'share': db_share_name # Azure share where this file is stored
                })
            except Exception as e:
                logger.error(f"Failed to hash local database for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing database for manifest.', detail=str(e), level='ERROR')
                # Potentially mark manifest as incomplete or skip it

        # Map Configuration entry in manifest
        if map_config_data: # Check if map_config_data was provided and presumably uploaded
            try:
                config_json_bytes = json.dumps(map_config_data, indent=2).encode('utf-8')
                config_hash = hashlib.sha256(config_json_bytes).hexdigest()
                manifest_data['files'].append({
                    'path': remote_config_path, # remote_config_path defined earlier
                    'type': 'map_config',
                    'sha256': config_hash, # Hash of the config data at the time of backup
                    'share': config_share_name
                })
            except Exception as e:
                logger.error(f"Failed to hash map configuration for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing map_config for manifest.', detail=str(e), level='ERROR')

        # Resource Configurations entry in manifest
        if resource_configs_data: # Check if data was provided and presumably uploaded
            try:
                # Re-serialize to get bytes for hash, or use stored bytes if available
                rc_bytes_for_hash = json.dumps(resource_configs_data, indent=2).encode('utf-8')
                rc_hash = hashlib.sha256(rc_bytes_for_hash).hexdigest()
                manifest_data['files'].append({
                    'path': remote_resource_configs_path, # Defined earlier in the function
                    'type': 'resource_configs',
                    'sha256': rc_hash, # Hash of the resource configs data
                    'share': config_share_name # Defined earlier
                })
            except Exception as e:
                logger.error(f"Failed to hash resource_configs for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing resource_configs for manifest.', detail=str(e), level='ERROR')

        # User Configurations entry in manifest
        if user_configs_data: # Check if data was provided and presumably uploaded
            try:
                uc_bytes_for_hash = json.dumps(user_configs_data, indent=2).encode('utf-8')
                uc_hash = hashlib.sha256(uc_bytes_for_hash).hexdigest()
                manifest_data['files'].append({
                    'path': remote_user_configs_path, # Defined earlier
                    'type': 'user_configs',
                    'sha256': uc_hash, # Hash of the user configs data
                    'share': config_share_name # Defined earlier
                })
            except Exception as e:
                logger.error(f"Failed to hash user_configs for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing user_configs for manifest.', detail=str(e), level='ERROR')

        # Media Directories entries in manifest
        # For media, we record the directory path and the expected number of files.
        # Individual file hashes are not stored in the manifest for media to keep it concise,
        # but verification can check if the expected number of files exists.
        if os.path.isdir(FLOOR_MAP_UPLOADS):
            num_floor_maps = len([name for name in os.listdir(FLOOR_MAP_UPLOADS) if os.path.isfile(os.path.join(FLOOR_MAP_UPLOADS, name))])
            manifest_data['media_directories_expected'].append({
                'path': remote_floor_map_dir, # remote_floor_map_dir defined earlier
                'type': 'floor_maps',
                'expected_file_count': num_floor_maps, # Number of files in local source dir
                'share': media_share_name
            })

        if os.path.isdir(RESOURCE_UPLOADS):
            num_resource_uploads = len([name for name in os.listdir(RESOURCE_UPLOADS) if os.path.isfile(os.path.join(RESOURCE_UPLOADS, name))])
            manifest_data['media_directories_expected'].append({
                'path': remote_resource_uploads_dir, # remote_resource_uploads_dir defined earlier
                'type': 'resource_uploads',
                'expected_file_count': num_resource_uploads, # Number of files in local source dir
                'share': media_share_name
            })

        # Upload Manifest File (to DB share for simplicity, as it's central to a backup set)
        manifest_filename = f"backup_manifest_{timestamp_str}.json"
        remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
        try:
            manifest_json_bytes = json.dumps(manifest_data, indent=2).encode('utf-8')
            # db_share_client is already defined and initialized
            manifest_file_client = db_share_client.get_file_client(remote_manifest_path)
            logger.info(f"Attempting to upload manifest data of size: {len(manifest_json_bytes)} bytes to {remote_manifest_path} on share '{db_share_client.share_name}'")
            manifest_file_client.upload_file(data=manifest_json_bytes, overwrite=True)
            logger.info(f"Successfully uploaded backup manifest to '{db_share_name}/{remote_manifest_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backup manifest uploaded successfully.', level='SUCCESS')
            # (This is after existing successful upload logs and emits)
            try:
                props = manifest_file_client.get_file_properties()
                logger.info(f"POST-UPLOAD CHECK: Manifest '{remote_manifest_path}' on share '{db_share_client.share_name}' found. Size: {props.size}, ETag: {props.etag}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Post-upload check: Manifest {timestamp_str} found.', detail=f"Size: {props.size}", level='INFO')
            except ResourceNotFoundError:
                logger.error(f"POST-UPLOAD CHECK FAILED: Manifest '{remote_manifest_path}' on share '{db_share_client.share_name}' NOT FOUND immediately after upload. This will likely cause verification issues.", exc_info=True)
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Post-upload check: Manifest {timestamp_str} NOT found after upload.', level='ERROR')
                overall_success = False # Ensure this failure is critical
            except Exception as verify_e:
                logger.error(f"POST-UPLOAD CHECK FAILED: Error getting properties for manifest '{remote_manifest_path}' on share '{db_share_client.share_name}' after upload: {verify_e}", exc_info=True)
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Post-upload check: Error verifying manifest {timestamp_str} after upload.', detail=str(verify_e), level='ERROR')
                overall_success = False # Ensure this failure is critical
        except Exception as e:
            logger.error(f"CRITICAL: Manifest creation/upload FAILED for '{db_share_name}/{remote_manifest_path}'. Setting overall_success to False due to this manifest operation failure. Error: {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backup manifest creation/upload FAILED.', detail=str(e), level='ERROR')
            overall_success = False # Crucial change

    if overall_success:
        _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backup completed with overall success: True', detail="All components backed up successfully.", level='SUCCESS')
    else:
        _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backup completed with overall success: False. Check server logs for details.', detail="One or more components failed to backup.", level='ERROR')
    return overall_success


def restore_latest_backup_set_on_startup(app_logger=None):
    """
    Restores the latest available backup set on application startup.
    This includes database, configurations, and media files.
    Designed to be called from app_factory.py.
    """
    log = app_logger if app_logger else logger
    log.info("Attempting to restore latest backup set on startup...")

    try:
        service_client = _get_service_client() # Handles RuntimeError if not configured
        
        available_backups = list_available_backups() # Handles its own errors, returns [] if issues
        if not available_backups:
            log.info("No available backups found in Azure. Startup restore will not proceed.")
            return None

        latest_timestamp = available_backups[0] # list_available_backups sorts newest first
        log.info(f"Latest backup timestamp found: {latest_timestamp}. Proceeding with restore of this set.")

        downloaded_config_paths = {}

        # Get share clients
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)

        # --- Database Restore ---
        if not _client_exists(db_share_client):
            log.error(f"Database share '{db_share_name}' not found. Cannot restore database. Aborting startup restore.")
            return None
        
        db_success, db_msg, _, db_path = restore_database_component(
            latest_timestamp, db_share_client, dry_run=False, socketio_instance=None, task_id=None
        )
        if not db_success:
            log.error(f"Critical: Failed to restore database for latest backup {latest_timestamp} on startup: {db_msg}. Aborting startup restore.")
            return None
        log.info(f"Database for {latest_timestamp} successfully restored to {db_path} on startup.")

        # --- Resource Configurations Download (before Map Config) ---
        if _client_exists(config_share_client):
            rc_success, rc_msg, _, rc_path = download_resource_configs_component(
                latest_timestamp, config_share_client, dry_run=False, socketio_instance=None, task_id=None
            )
            if rc_success and rc_path:
                downloaded_config_paths['resource_configs_path'] = rc_path
                log.info(f"Resource configurations for {latest_timestamp} downloaded to {rc_path} on startup.")
            else:
                log.warning(f"Could not download resource configurations for {latest_timestamp} on startup: {rc_msg}")
        else:
            log.warning(f"Config share '{config_share_name}' not found. Skipping resource configurations download on startup.")

        # --- Map Configuration Download ---
        if _client_exists(config_share_client):
            map_success, map_msg, _, map_path = download_map_config_component(
                latest_timestamp, config_share_client, dry_run=False, socketio_instance=None, task_id=None
            )
            if map_success and map_path:
                downloaded_config_paths['map_config_path'] = map_path
                log.info(f"Map configuration for {latest_timestamp} downloaded to {map_path} on startup.")
            else:
                log.warning(f"Could not download map configuration for {latest_timestamp} on startup: {map_msg}")
        else:
            # This log might be redundant if already logged for resource_configs, but good for clarity
            log.warning(f"Config share '{config_share_name}' not found. Skipping map configuration download on startup.")

        # --- User Configurations Download ---
        if _client_exists(config_share_client):
            uc_success, uc_msg, _, uc_path = download_user_configs_component(
                latest_timestamp, config_share_client, dry_run=False, socketio_instance=None, task_id=None
            )
            if uc_success and uc_path:
                downloaded_config_paths['user_configs_path'] = uc_path
                log.info(f"User configurations for {latest_timestamp} downloaded to {uc_path} on startup.")
            else:
                log.warning(f"Could not download user configurations for {latest_timestamp} on startup: {uc_msg}")
        else:
            log.warning(f"Config share '{config_share_name}' not found. Skipping user configurations download on startup.")
            
        # --- Media Restore (Floor Maps & Resource Uploads) ---
        if _client_exists(media_share_client):
            fm_success, fm_msg, _ = restore_media_component(
                latest_timestamp, "FloorMaps", FLOOR_MAP_UPLOADS, "floor_map_uploads",
                media_share_client, dry_run=False, socketio_instance=None, task_id=None
            )
            log.info(f"Floor maps restore for {latest_timestamp} on startup: {fm_msg} (Success: {fm_success})")

            ru_success, ru_msg, _ = restore_media_component(
                latest_timestamp, "ResourceUploads", RESOURCE_UPLOADS, "resource_uploads",
                media_share_client, dry_run=False, socketio_instance=None, task_id=None
            )
            log.info(f"Resource uploads restore for {latest_timestamp} on startup: {ru_msg} (Success: {ru_success})")
        else:
            log.warning(f"Media share '{media_share_name}' not found. Skipping media restore on startup.")

        log.info(f"Startup restore process for {latest_timestamp} completed.")
        return downloaded_config_paths

    except RuntimeError as rte: # Catch specific RuntimeError from _get_service_client
        log.error(f"Azure Storage not configured for startup restore: {rte}. Startup restore aborted.")
        return None
    except Exception as e:
        log.exception(f"Critical error during startup restore process: {e}. Startup restore aborted.")
        return None


def verify_backup_set(timestamp_str, socketio_instance=None, task_id=None):
    """
    Verifies a backup set against its manifest.

    Args:
        timestamp_str (str): The timestamp of the backup set to verify.
        socketio_instance: Optional SocketIO instance for progress.
        task_id: Optional task ID for SocketIO.

    Returns:
        dict: A dictionary containing verification results.
    """
    verification_results = {
        'timestamp': timestamp_str,
        'status': 'pending', # Possible statuses: pending, manifest_missing, manifest_corrupt, failed_verification, verified_present
        'checks': [], # List of dicts detailing each check
        'errors': []  # List of error messages
    }
    component_name = f"BackupSetVerify-{timestamp_str}"

    def _emit_verify_progress(status_msg, detail='', level="INFO"):
        logger.info(f"[{component_name}] {status_msg} {detail}")
        if socketio_instance and task_id:
            _emit_progress(socketio_instance, task_id, 'backup_verification_progress', status_msg, detail)

    _emit_verify_progress(f"Starting verification for backup set: {timestamp_str}")

    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(db_share_client):
            msg = f"Database share '{db_share_name}' not found."
            verification_results['errors'].append(msg)
            verification_results['status'] = 'failed_verification'
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        # 1. Download and Parse Manifest
        manifest_filename = f"backup_manifest_{timestamp_str}.json"
        remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
        manifest_file_client = db_share_client.get_file_client(remote_manifest_path)

        logger.info(f"VERIFY_BACKUP_SET: Attempting to check existence of manifest via _client_exists for: '{db_share_name}/{remote_manifest_path}'")
        if not _client_exists(manifest_file_client):
            msg = f"Manifest file '{remote_manifest_path}' not found on share '{db_share_name}'."
            verification_results['errors'].append(msg)
            verification_results['status'] = 'manifest_missing'
            # Corrected log:
            logger.warning(f"VERIFY_BACKUP_SET: _client_exists returned False for manifest: '{db_share_name}/{remote_manifest_path}'. Detailed message: {msg}")
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        manifest_data = None
        try:
            downloader = manifest_file_client.download_file()
            manifest_bytes = downloader.readall()
            manifest_data = json.loads(manifest_bytes.decode('utf-8'))
            _emit_verify_progress("Manifest downloaded and parsed successfully.")
            verification_results['checks'].append({'item': 'manifest', 'status': 'found_and_parsed', 'path': remote_manifest_path})
        except Exception as e:
            msg = f"Error downloading or parsing manifest '{remote_manifest_path}': {e}"
            verification_results['errors'].append(msg)
            verification_results['status'] = 'manifest_corrupt'
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        # 2. Verify Files from Manifest (manifest_data['files'])
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups') # Used if map_config is in manifest
        config_share_client = service_client.get_share_client(config_share_name) # Initialize once

        for file_entry in manifest_data.get('files', []):
            entry_path = file_entry.get('path')
            entry_type = file_entry.get('type')
            entry_share_name = file_entry.get('share')
            # entry_hash = file_entry.get('sha256') # For future checksum verification

            check_item = {'item': entry_path, 'type': entry_type, 'status': 'unknown'}
            _emit_verify_progress(f"Verifying file: {entry_path} (type: {entry_type})")

            target_share_client = None
            if entry_share_name == db_share_name:
                target_share_client = db_share_client
            elif entry_share_name == config_share_name:
                target_share_client = config_share_client
            else:
                msg = f"Unknown share '{entry_share_name}' for file '{entry_path}' in manifest."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_unknown_share'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            if not _client_exists(target_share_client):
                msg = f"Share '{entry_share_name}' for file '{entry_path}' does not exist."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_missing'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            file_client_to_check = target_share_client.get_file_client(entry_path)
            if _client_exists(file_client_to_check):
                check_item['status'] = 'found'
                # Optional: Add checksum verification here if feasible in future
                # For now, presence is the main check.
            else:
                msg = f"Missing file: {entry_path} on share {entry_share_name}"
                verification_results['errors'].append(msg)
                check_item['status'] = 'missing'
            verification_results['checks'].append(check_item)
            _emit_verify_progress(f"File {entry_path}: {check_item['status']}")

        # 3. Verify Media Directories from Manifest (manifest_data['media_directories_expected'])
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media') # Used for media
        media_share_client = service_client.get_share_client(media_share_name)

        for dir_entry in manifest_data.get('media_directories_expected', []):
            dir_path = dir_entry.get('path')
            dir_type = dir_entry.get('type')
            expected_count = dir_entry.get('expected_file_count')
            entry_share_name = dir_entry.get('share')

            check_item = {'item': dir_path, 'type': dir_type, 'status': 'unknown', 'expected_count': expected_count, 'actual_count': 0}
            _emit_verify_progress(f"Verifying media directory: {dir_path} (type: {dir_type})")

            if entry_share_name != media_share_name:
                msg = f"Manifest inconsistency: Media directory '{dir_path}' expected on share '{media_share_name}' but manifest says '{entry_share_name}'."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_mismatch'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            if not _client_exists(media_share_client):
                msg = f"Media share '{media_share_name}' for directory '{dir_path}' does not exist."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_missing'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            dir_client_to_check = media_share_client.get_directory_client(dir_path)
            if _client_exists(dir_client_to_check):
                try:
                    remote_files = list(dir_client_to_check.list_directories_and_files())
                    actual_count = len([f for f in remote_files if not f['is_directory']])
                    check_item['actual_count'] = actual_count
                    if actual_count == expected_count:
                        check_item['status'] = 'found_count_match'
                    else:
                        msg = f"File count mismatch for {dir_path}: Expected {expected_count}, Found {actual_count}."
                        verification_results['errors'].append(msg) # Considered an error for verification
                        check_item['status'] = 'found_count_mismatch'
                        _emit_verify_progress(msg, level="WARNING")
                except Exception as e:
                    msg = f"Error listing files in remote directory '{dir_path}': {e}"
                    verification_results['errors'].append(msg)
                    check_item['status'] = 'error_listing_files'
                    _emit_verify_progress(msg, level="ERROR")
            else:
                msg = f"Missing media directory: {dir_path} on share {media_share_name}"
                verification_results['errors'].append(msg)
                check_item['status'] = 'missing'
            verification_results['checks'].append(check_item)
            _emit_verify_progress(f"Directory {dir_path}: {check_item['status']}")

        # 4. Determine Overall Status
        if verification_results['errors']:
            verification_results['status'] = 'failed_verification'
        else:
            verification_results['status'] = 'verified_present'

        _emit_verify_progress(f"Verification finished for {timestamp_str}. Status: {verification_results['status']}", level="INFO" if verification_results['status'] == 'verified_present' else "ERROR")

    except Exception as e:
        msg = f"Critical error during backup verification for {timestamp_str}: {e}"
        logger.error(msg, exc_info=True)
        verification_results['errors'].append(msg)
        verification_results['status'] = 'critical_error'
        _emit_verify_progress(msg, level="CRITICAL")

    return verification_results


def restore_database_component(timestamp_str, db_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores the database from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, restored_db_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Database"
    restored_db_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} restore component...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    remote_db_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
    azure_db_path = f"{DB_BACKUPS_DIR}/{remote_db_filename}"
    local_db_target_path = os.path.join(DATA_DIR, 'site.db')

    db_file_client = db_share_client.get_file_client(azure_db_path)

    if not _client_exists(db_file_client):
        err_msg = f"{dry_run_prefix}{component_name} backup file '{azure_db_path}' not found on share '{db_share_client.share_name}'."
        logger.error(err_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, detail=azure_db_path, level='ERROR')
        if dry_run: actions.append(err_msg)
        return False, err_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{db_share_client.share_name}/{azure_db_path}' to '{local_db_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg, level='INFO')
        logger.info(action_msg)
        restored_db_path = "DRY_RUN_DB_PATH_PLACEHOLDER"
        success_msg = f"DRY RUN: {component_name} component finished."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg, level='INFO')
        logger.info(success_msg)
        return True, success_msg, actions, restored_db_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring {component_name}...', detail=f'{azure_db_path} to {local_db_target_path}', level='INFO')
        logger.info(f"Restoring {component_name} from '{db_share_client.share_name}/{azure_db_path}' to '{local_db_target_path}'.")
        if download_file(db_share_client, azure_db_path, local_db_target_path):
            success_msg = f"{component_name} restored successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.', detail=local_db_target_path, level='SUCCESS')
            restored_db_path = local_db_target_path
            return True, success_msg, actions, restored_db_path
        else:
            err_msg = f"{component_name} restoration failed during download."
            logger.error(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, detail=azure_db_path, level='ERROR')
            return False, err_msg, actions, None


def download_map_config_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the map configuration JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Map Configuration"
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    remote_config_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    # Note: DATA_DIR is a global constant
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename)

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
        if dry_run: actions.append(warn_msg)
        # This is not a critical failure for the overall restore, so return True.
        return True, warn_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg, level='INFO')
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_MAP_CONFIG_PATH_PLACEHOLDER"
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg, level='INFO')
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', detail=f'{azure_config_path} to {local_config_target_path}', level='INFO')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.', detail=local_config_target_path, level='SUCCESS')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            # Log as warning because map config might be optional for some restore scenarios.
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
            return True, warn_msg, actions, None # Non-critical failure, return True


def download_resource_configs_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the resource configurations JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Resource Configurations"
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    remote_config_filename = f"resource_configs_{timestamp_str}.json" # Changed filename
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename) # DATA_DIR is global

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions, None # Not critical failure

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg, level='INFO')
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_RESOURCE_CONFIGS_PATH_PLACEHOLDER" # Placeholder
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg, level='INFO')
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', detail=f'{azure_config_path} to {local_config_target_path}', level='INFO')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.', detail=local_config_target_path, level='SUCCESS')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'." # Non-critical
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
            return True, warn_msg, actions, None


def download_user_configs_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the user and role configurations JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "User/Role Configurations" # Changed component name
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    remote_config_filename = f"user_configs_{timestamp_str}.json" # Changed filename
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename)

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg, level='INFO')
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_USER_CONFIGS_PATH_PLACEHOLDER" # Placeholder
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg, level='INFO')
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', detail=f'{azure_config_path} to {local_config_target_path}', level='INFO')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.', detail=local_config_target_path, level='SUCCESS')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=azure_config_path, level='WARNING')
            return True, warn_msg, actions, None


def restore_media_component(timestamp_str, media_type_name, local_target_dir, remote_media_subdir_base, media_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores a specific type of media files (e.g., FloorMaps, ResourceUploads).

    Args:
        timestamp_str (str): The backup timestamp.
        media_type_name (str): User-friendly name of the media type (e.g., "Floor Maps").
        local_target_dir (str): The local directory to restore files to (e.g., FLOOR_MAP_UPLOADS).
        remote_media_subdir_base (str): The base name for the remote subdirectory
                                        (e.g., "floor_map_uploads" which becomes "floor_map_uploads_{timestamp_str}").
        media_share_client: The Azure ShareClient for media.
        dry_run (bool): If True, simulate operations.
        socketio_instance: Optional SocketIO instance.
        task_id: Optional task ID for SocketIO.

    Returns:
        tuple: (success_bool, message_str, actions_list)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {media_type_name} restore component...', detail=f'Timestamp: {timestamp_str}', level='INFO')

    remote_media_dir_path = f"{MEDIA_BACKUPS_DIR_BASE}/{remote_media_subdir_base}_{timestamp_str}"
    azure_media_dir_client = media_share_client.get_directory_client(remote_media_dir_path)

    if not _client_exists(azure_media_dir_client):
        warn_msg = f"{dry_run_prefix}{media_type_name} backup directory '{remote_media_dir_path}' not found on share '{media_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=remote_media_dir_path, level='WARNING')
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions # Not a critical failure

    if dry_run:
        action_msg = f"DRY RUN: Would clear local directory: {local_target_dir}"
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg, level='INFO')
        logger.info(action_msg)

        # Simulate listing and downloading files
        try:
            # To list files in dry run, we still need to query the remote directory
            item_count = 0
            for item in azure_media_dir_client.list_directories_and_files():
                if not item['is_directory']:
                    item_count +=1
                    filename = item['name']
                    azure_file_path = f"{remote_media_dir_path}/{filename}"
                    local_file_path = os.path.join(local_target_dir, filename)
                    action_msg_file = f"DRY RUN: Would download media file '{filename}' from '{azure_file_path}' to '{local_file_path}'."
                    actions.append(action_msg_file)
                    _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg_file, level='INFO')
                    logger.info(action_msg_file)
            if item_count == 0:
                 actions.append(f"DRY RUN: No files found in remote directory {remote_media_dir_path} to download.")

        except Exception as e:
            err_msg = f"DRY RUN: Error listing files in {remote_media_dir_path}: {e}"
            logger.error(err_msg)
            actions.append(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, detail=str(e), level='ERROR')
            # Continue, as this is a dry run, but report the issue.

        success_msg = f"DRY RUN: {media_type_name} component finished (simulated operations)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg, level='INFO')
        logger.info(success_msg)
        return True, success_msg, actions
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Clearing local directory: {local_target_dir}', level='INFO')
        if os.path.exists(local_target_dir):
            for filename in os.listdir(local_target_dir):
                file_to_delete = os.path.join(local_target_dir, filename)
                if os.path.isfile(file_to_delete):
                    try:
                        os.remove(file_to_delete)
                    except Exception as e:
                        logger.error(f"Failed to delete local file {file_to_delete}: {e}")
                        _emit_progress(socketio_instance, task_id, 'restore_progress', f"Error deleting local file {file_to_delete}", detail=str(e), level='ERROR')
                        # Decide if this is critical enough to stop this component
        else:
            os.makedirs(local_target_dir, exist_ok=True)

        files_downloaded = 0
        files_failed = 0
        for item in azure_media_dir_client.list_directories_and_files():
            if not item['is_directory']:
                filename = item['name']
                azure_file_path = f"{remote_media_dir_path}/{filename}"
                local_file_path = os.path.join(local_target_dir, filename)
                _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring {media_type_name} file: {filename}', detail=local_file_path, level='INFO')
                if download_file(media_share_client, azure_file_path, local_file_path):
                    logger.info(f"Restored {media_type_name} file '{filename}' successfully.")
                    files_downloaded +=1
                else:
                    logger.warning(f"Failed to restore {media_type_name} file '{filename}' from '{azure_file_path}'.")
                    _emit_progress(socketio_instance, task_id, 'restore_progress', f'Failed to restore {media_type_name} file: {filename}', detail=azure_file_path, level='WARNING')
                    files_failed +=1

        final_msg = f"{media_type_name.capitalize()} restoration: {files_downloaded} files downloaded, {files_failed} failed."
        logger.info(final_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', final_msg, level='SUCCESS' if files_failed == 0 else 'WARNING')
        return files_failed == 0, final_msg, actions # Success if no files failed


def list_available_backups():
    """
    Lists available backup timestamps based on the presence of database backup files.

    Returns:
        list: A sorted list of unique timestamp strings (YYYYMMDD_HHMMSS), most recent first.
              Returns an empty list if no backups are found or if there's an error.
    """
    logger.info("Attempting to list available backups.")
    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(share_client):
            logger.warning(f"Backup share '{db_share_name}' does not exist. No backups to list.")
            return []

        db_backup_dir_client = share_client.get_directory_client(DB_BACKUPS_DIR)

        if not _client_exists(db_backup_dir_client):
            logger.warning(f"Database backup directory '{DB_BACKUPS_DIR}' does not exist on share '{db_share_name}'. No backups to list.")
            return []

        timestamps = set()
        for item in db_backup_dir_client.list_directories_and_files():
            if item['is_directory']:
                continue
            filename = item['name']
            if filename.startswith(DB_FILENAME_PREFIX) and filename.endswith('.db'):
                try:
                    # Extract YYYYMMDD_HHMMSS part
                    timestamp_str = filename[len(DB_FILENAME_PREFIX):-len('.db')]
                    # Basic validation of timestamp format (15 chars, YYYYMMDD_HHMMSS)
                    if len(timestamp_str) == 15 and timestamp_str[8] == '_':
                        datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S') # Validate format
                        timestamps.add(timestamp_str)
                    else:
                        logger.warning(f"Skipping file with unexpected name format: {filename}")
                except ValueError:
                    logger.warning(f"Skipping file with invalid timestamp format: {filename}")

        sorted_timestamps = sorted(list(timestamps), reverse=True)
        logger.info(f"Found {len(sorted_timestamps)} available backup timestamps.")
        return sorted_timestamps
    except Exception as e:
        logger.error(f"Error listing available backups: {e}")
        return []


def restore_full_backup(timestamp_str, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores a full backup (database, map configuration, and media files) for a specific timestamp.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup to restore.
        dry_run (bool): If True, simulates restore operations without making changes.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        tuple: (path_to_restored_db_or_None, path_to_downloaded_map_config_or_None, path_to_downloaded_resource_configs_or_None, path_to_downloaded_user_configs_or_None, actions_list)
               Returns (None, None, None, None, actions_list) if critical (DB) restoration fails.
               actions_list contains strings describing operations if dry_run is True.
    """
    overall_actions_list = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    final_restored_db_path = None
    final_downloaded_map_config_path = None
    final_downloaded_resource_configs_path = None
    final_downloaded_user_configs_path = None

    logger.info(f"{dry_run_prefix}Starting full restore for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, 'restore_progress', f"{dry_run_prefix}Starting full restore processing...", detail=f'Timestamp: {timestamp_str}', level='INFO')

    try:
        service_client = _get_service_client()

        # --- Database Restore Component ---
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(db_share_client):
            err_msg = f"{dry_run_prefix}Database backup share '{db_share_name}' does not exist. Cannot proceed with any restore operations."
            logger.error(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, detail=f"Share {db_share_name} missing.", level='ERROR')
            if dry_run: overall_actions_list.append(err_msg)
            return None, None, None, None, overall_actions_list # Adjusted return to include all 4 paths

        db_success, db_message, db_actions, db_output_path = restore_database_component(
            timestamp_str, db_share_client, dry_run, socketio_instance, task_id
        )
        if dry_run: overall_actions_list.extend(db_actions)
        final_restored_db_path = db_output_path # This will be placeholder in dry_run, actual path otherwise

        if not db_success: # Critical failure if DB component fails
            logger.error(f"{dry_run_prefix}Database restore component failed: {db_message}. Aborting full restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"{dry_run_prefix}Database restore failed. Full restore aborted.", detail=db_message, level='ERROR')
            return None, None, None, None, overall_actions_list # Return None for paths, include actions gathered so far

        # --- Map Configuration Download Component ---
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)

        if _client_exists(config_share_client):
            map_success, map_message, map_actions, map_output_path = download_map_config_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(map_actions)
            final_downloaded_map_config_path = map_output_path
            if not map_success: # Log warning, but continue as it's not deemed critical
                 logger.warning(f"{dry_run_prefix}Map configuration download component reported issues: {map_message}")
        else:
            warn_msg = f"{dry_run_prefix}Config backup share '{config_share_name}' does not exist. Skipping map configuration download."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=f"Share {config_share_name} missing.", level='WARNING')
            if dry_run: overall_actions_list.append(warn_msg)

        # --- Resource Configurations Download Component ---
        if _client_exists(config_share_client): # Check if config share itself exists
            rc_success, rc_message, rc_actions, rc_output_path = download_resource_configs_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(rc_actions)
            final_downloaded_resource_configs_path = rc_output_path
            if not rc_success: logger.warning(f"{dry_run_prefix}Resource configs download component reported issues: {rc_message}")
        # No else here, as config_share_client existence is checked above for map_config already.

        # --- User Configurations Download Component ---
        if _client_exists(config_share_client):
            uc_success, uc_message, uc_actions, uc_output_path = download_user_configs_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(uc_actions)
            final_downloaded_user_configs_path = uc_output_path
            if not uc_success: logger.warning(f"{dry_run_prefix}User configs download component reported issues: {uc_message}")
        # No else here, as config_share_client existence is checked above for map_config already.

        # --- Media Restore Components ---
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)

        if _client_exists(media_share_client):
            # Restore Floor Maps
            fm_success, fm_message, fm_actions = restore_media_component(
                timestamp_str, "FloorMaps", FLOOR_MAP_UPLOADS, "floor_map_uploads",
                media_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(fm_actions)
            if not fm_success: logger.warning(f"{dry_run_prefix}FloorMaps restore component reported issues: {fm_message}")

            # Restore Resource Uploads
            ru_success, ru_message, ru_actions = restore_media_component(
                timestamp_str, "ResourceUploads", RESOURCE_UPLOADS, "resource_uploads",
                media_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(ru_actions)
            if not ru_success: logger.warning(f"{dry_run_prefix}ResourceUploads restore component reported issues: {ru_message}")
        else:
            warn_msg = f"{dry_run_prefix}Media backup share '{media_share_name}' does not exist. Skipping all media restore."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, detail=f"Share {media_share_name} missing.", level='WARNING')
            if dry_run: overall_actions_list.append(warn_msg)

        logger.info(f"{dry_run_prefix}Full restore process completed for timestamp: {timestamp_str}")
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Full restore operations finished.', level='INFO')
        return final_restored_db_path, final_downloaded_map_config_path, final_downloaded_resource_configs_path, final_downloaded_user_configs_path, overall_actions_list

    except Exception as e:
        err_msg_final = f"{dry_run_prefix}Critical error during full restore orchestration for timestamp {timestamp_str}: {e}"
        logger.error(err_msg_final, exc_info=True)
        _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg_final, detail=str(e), level='ERROR')
        if dry_run: overall_actions_list.append(err_msg_final)
        return None, None, None, None, overall_actions_list


def delete_backup_set(timestamp_str, socketio_instance=None, task_id=None):
    """
    Deletes a complete backup set for a given timestamp, including database,
    map configuration, manifest, and media files/directories.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup set to delete.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        bool: True if all critical components were attempted to be deleted (some may not exist),
              False if a critical error occurred during setup or essential component deletion.
    """
    event_name = 'backup_delete_progress'
    log_prefix = f"[Task {task_id if task_id else 'N/A'}] "
    logger.info(f"{log_prefix}Attempting to delete backup set for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, event_name, f"Starting deletion for backup set: {timestamp_str}", level='INFO')

    overall_success = True
    critical_component_processed = False # Tracks if critical components (DB, Manifest) were processed (deleted or confirmed not found)

    try:
        service_client = _get_service_client()

        # --- Helper: Delete File ---
        def _delete_file_if_exists(share_client, file_path, component_name, share_name_for_log, is_critical=False):
            nonlocal overall_success, critical_component_processed
            _emit_progress(socketio_instance, task_id, event_name, f"Checking for {component_name}...", detail=file_path, level='INFO')
            file_client = share_client.get_file_client(file_path)
            if _client_exists(file_client):
                try:
                    file_client.delete_file()
                    logger.info(f"{log_prefix}Successfully deleted {component_name} '{file_path}' from share '{share_name_for_log}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"{component_name} deleted.", detail=file_path, level='SUCCESS')
                    if is_critical: critical_component_processed = True
                    return True
                except Exception as e:
                    logger.error(f"{log_prefix}Failed to delete {component_name} '{file_path}' from share '{share_name_for_log}'. Exception: {type(e).__name__}, Details: {str(e)}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, event_name, f"Failed to delete {component_name} ({type(e).__name__})", detail=str(e), level='ERROR')
                    if is_critical: overall_success = False # Failure to delete an existing critical file is a failure
                    return False
            else:
                logger.info(f"{log_prefix}{component_name} file '{file_path}' not found on share '{share_name_for_log}'. Skipping deletion.")
                _emit_progress(socketio_instance, task_id, event_name, f"{component_name} not found, skipping.", detail=file_path, level='INFO')
                if is_critical: critical_component_processed = True
                return True # Not finding an optional or even critical file isn't a failure of the delete *operation*

        # --- Helper: Delete Directory ---
        def _delete_directory_if_exists(share_client, dir_path, component_name, share_name_for_log, is_critical=False):
            nonlocal overall_success # `critical_component_processed` not used here as directories are media, not critical for this flag
            _emit_progress(socketio_instance, task_id, event_name, f"Checking for {component_name} directory...", detail=dir_path, level='INFO')
            dir_client = share_client.get_directory_client(dir_path)
            dir_path_for_emit = dir_path # Used for emit messages, as dir_path might be modified by loop

            if _client_exists(dir_client):
                try:
                    # List and delete files within the directory first
                    items_in_dir = list(dir_client.list_directories_and_files())
                    logger.info(f"{log_prefix}Found {len(items_in_dir)} items in directory '{dir_path}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"Found {len(items_in_dir)} items in {component_name} directory '{dir_path_for_emit}'. Attempting to delete contents.", level='INFO')

                    for item in items_in_dir:
                        item_name_for_log = item['name']
                        if item['is_directory']:
                            # Note: Current backup structure does not create sub-directories within these media backup dirs.
                            # If it did, recursive deletion would be needed here.
                            # For now, log a warning if a sub-directory is unexpectedly found.
                            logger.warning(f"{log_prefix}Unexpected sub-directory '{item_name_for_log}' found in '{dir_path}'. This structure is not standard. Skipping this sub-directory.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Skipping unexpected sub-directory '{item_name_for_log}' in '{dir_path_for_emit}'.", detail="Sub-directory found.", level='WARNING')
                            continue # Skip to next item

                        # It's a file, attempt to delete it
                        file_in_dir_client = dir_client.get_file_client(item_name_for_log)
                        try:
                            logger.info(f"{log_prefix}Attempting to delete file '{item_name_for_log}' in directory '{dir_path}'.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Deleting file {item_name_for_log} in {dir_path_for_emit} for {component_name}", level='INFO')
                            file_in_dir_client.delete_file()
                            logger.info(f"{log_prefix}Successfully deleted file '{item_name_for_log}' in directory '{dir_path}'.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Deleted file {item_name_for_log} in {dir_path_for_emit}", detail=f"{dir_path_for_emit}/{item_name_for_log}", level='SUCCESS')
                        except Exception as e_file:
                            logger.error(f"{log_prefix}Failed to delete file '{item_name_for_log}' in directory '{dir_path}'. Exception: {type(e_file).__name__}, Details: {str(e_file)}", exc_info=True)
                            _emit_progress(socketio_instance, task_id, event_name, f"Error deleting file {item_name_for_log} in {dir_path_for_emit}", detail=str(e_file), level='ERROR')
                            overall_success = False # Failure to delete a file within directory means directory delete will fail
                            return False # Critical failure for this helper's operation

                    # All contents attempted to be deleted, now delete the main directory
                    logger.info(f"{log_prefix}Attempting to delete main directory '{dir_path}' for {component_name}.")
                    dir_client.delete_directory()
                    logger.info(f"{log_prefix}Successfully deleted {component_name} directory '{dir_path}' from share '{share_name_for_log}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"{component_name} directory and its contents deleted.", detail=dir_path_for_emit, level='SUCCESS')
                    return True
                except Exception as e: # Catch error during list_directories_and_files or final delete_directory
                    logger.error(f"{log_prefix}Failed to delete {component_name} directory '{dir_path}' or its contents from share '{share_name_for_log}'. Exception: {type(e).__name__}, Details: {str(e)}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, event_name, f"Failed to delete {component_name} directory ({type(e).__name__})", detail=str(e), level='ERROR')
                    overall_success = False
                    return False
            else:
                logger.info(f"{log_prefix}{component_name} directory '{dir_path}' not found on share '{share_name_for_log}'. Skipping deletion.")
                _emit_progress(socketio_instance, task_id, event_name, f"{component_name} directory not found, skipping.", detail=dir_path, level='INFO')
                return True # Not finding directory is not a failure of delete operation

        # --- Main Deletion Logic ---
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)
        if _client_exists(db_share_client):
            db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
            db_backup_path = f"{DB_BACKUPS_DIR}/{db_backup_filename}"
            if not _delete_file_if_exists(db_share_client, db_backup_path, "Database Backup", db_share_name, is_critical=True):
                overall_success = False

            manifest_filename = f"backup_manifest_{timestamp_str}.json"
            manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
            if not _delete_file_if_exists(db_share_client, manifest_path, "Backup Manifest", db_share_name, is_critical=True):
                overall_success = False
        else:
            logger.warning(f"{log_prefix}Database backup share '{db_share_name}' not found. Skipping DB and Manifest backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Database share '{db_share_name}' not found. Skipping DB & Manifest.", detail=f"Share: {db_share_name}", level='WARNING')
            overall_success = False # If DB share is missing, it's a significant issue
            critical_component_processed = False # Explicitly mark critical components as not processed

        # Delete Map Configuration JSON Backup
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)
        if _client_exists(config_share_client):
            config_backup_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
            config_backup_path = f"{CONFIG_BACKUPS_DIR}/{config_backup_filename}"
            if not _delete_file_if_exists(config_share_client, config_backup_path, "Map Configuration Backup", config_share_name):
                # Not critical enough to set overall_success = False, but good to note if needed
                pass
        else:
            logger.info(f"{log_prefix}Config backup share '{config_share_name}' not found. Skipping config backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Config share '{config_share_name}' not found. Skipping map config.", detail=f"Share: {config_share_name}", level='INFO')

        # Delete Media Backups
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)
        if _client_exists(media_share_client):
            remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
            if not _delete_directory_if_exists(media_share_client, remote_floor_map_dir, "Floor Map Backup", media_share_name):
                overall_success = False # If directory existed and failed to delete, consider it a failure for overall

            remote_resource_uploads_dir = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
            if not _delete_directory_if_exists(media_share_client, remote_resource_uploads_dir, "Resource Uploads Backup", media_share_name):
                overall_success = False # If directory existed and failed to delete, consider it a failure for overall
        else:
            logger.info(f"{log_prefix}Media backup share '{media_share_name}' not found. Skipping media backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Media share '{media_share_name}' not found. Skipping media.", detail=f"Share: {media_share_name}", level='INFO')

        # Final check on critical component processing
        if not critical_component_processed and not _client_exists(db_share_client):
            # This condition confirms if DB share was missing AND thus critical components were never attempted.
            # overall_success is already False from the DB share check, this is an additional log.
            logger.error(f"{log_prefix}Critical backup components (DB or Manifest on DB Share) could not be processed because the share '{db_share_name}' was missing.")
            _emit_progress(socketio_instance, task_id, event_name, "Critical components could not be processed due to missing DB share.", detail=f"Share {db_share_name} missing.", level='ERROR')
        elif not critical_component_processed and _client_exists(db_share_client):
            # This case implies DB share existed, but both DB and Manifest files were not found.
            # This is not necessarily an error for the delete operation itself.
            logger.info(f"{log_prefix}Critical components (DB and Manifest) were not found on share '{db_share_name}', but share exists. Assuming already deleted or not part of this backup.")


        final_status_level = "SUCCESS" if overall_success else "ERROR" # FAILURE if any part of deletion of existing items failed OR critical share missing
        logger.info(f"{log_prefix}Deletion process for backup set {timestamp_str} completed. Overall success: {overall_success}")
        _emit_progress(socketio_instance, task_id, event_name, "Backup set deletion process finished.", detail=f"Overall success: {overall_success}", level=final_status_level)
        return overall_success

    except Exception as e:
        logger.error(f"{log_prefix}Critical error during deletion of backup set for timestamp {timestamp_str}: {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, f"Critical error during backup set deletion: {timestamp_str}", detail=str(e), level='CRITICAL_ERROR')
        return False


if __name__ == '__main__':
    main()
