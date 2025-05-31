
import os
import json
import hashlib
from datetime import datetime

try:
    from azure.storage.fileshare import ShareServiceClient
    from azure.core.exceptions import ResourceNotFoundError
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    ResourceNotFoundError = Exception


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_FILE = os.path.join(DATA_DIR, 'backup_hashes.json')


def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if ShareServiceClient is None:
        raise RuntimeError('azure-storage-file-share package is not installed')
    return ShareServiceClient.from_connection_string(connection_string)


def _client_exists(client):
    """Return True if the given share/file/directory client exists."""
    try:
        if hasattr(client, 'get_share_properties'):
            client.get_share_properties()
        elif hasattr(client, 'get_file_properties'):
            client.get_file_properties()
        elif hasattr(client, 'get_directory_properties'):
            client.get_directory_properties()
        else:
            return True
        return True
    except ResourceNotFoundError:
        return False
    except Exception:
        return False


def _load_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}


def _save_hashes(hashes):
    os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
    with open(HASH_FILE, 'w', encoding='utf-8') as f:
        json.dump(hashes, f)


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def upload_file(share_client, source_path, file_path):
    directory_path = os.path.dirname(file_path)
    if directory_path:
        directory_client = share_client.get_directory_client(directory_path)
        if not _client_exists(directory_client):
            directory_client.create_directory()
    with open(source_path, 'rb') as f:
        file_client = share_client.get_file_client(file_path)
        file_client.upload_file(f, overwrite=True)


def download_file(share_client, file_path, dest_path):
    file_client = share_client.get_file_client(file_path)
    if not _client_exists(file_client):
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'wb') as f:
        downloader = file_client.download_file()
        f.write(downloader.readall())
    return True


def backup_database():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        share_client.create_share()
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
        share_client.create_share()
    if dest_filename is None:
        dest_filename = os.path.basename(local_path)
    file_path = f'floor_map_uploads/{dest_filename}'
    upload_file(share_client, local_path, file_path)


def backup_media():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        share_client.create_share()
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
    """Backup DB and media files only if their hashes changed."""
    hashes = _load_hashes()
    service_client = _get_service_client()

    # Database backup
    db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_client = service_client.get_share_client(db_share)
    if not _client_exists(db_client):
        db_client.create_share()
    db_local = os.path.join(DATA_DIR, 'site.db')
    db_rel = 'site.db'
    db_hash = _hash_file(db_local) if os.path.exists(db_local) else None
    if db_hash and hashes.get(db_rel) != db_hash:
        upload_file(db_client, db_local, db_rel)
        hashes[db_rel] = db_hash

    # Media backup
    media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_client = service_client.get_share_client(media_share)
    if not _client_exists(media_client):
        media_client.create_share()
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

    _save_hashes(hashes)


def restore_from_share():
    """Download DB and media files from Azure File Share if available."""
    service_client = _get_service_client()

    db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_client = service_client.get_share_client(db_share)
    if _client_exists(db_client):
        download_file(db_client, 'site.db', os.path.join(DATA_DIR, 'site.db'))

    media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_client = service_client.get_share_client(media_share)
    if _client_exists(media_client):
        for prefix in ('floor_map_uploads', 'resource_uploads'):
            directory_client = media_client.get_directory_client(prefix)
            if not _client_exists(directory_client):
                continue
            for item in directory_client.list_directories_and_files():
                file_path = f"{prefix}/{item['name']}"
                dest = os.path.join(STATIC_DIR, prefix, item['name'])
                download_file(media_client, file_path, dest)


def main():
    backup_if_changed()
    print('Backup completed.')



if __name__ == '__main__':
    main()
