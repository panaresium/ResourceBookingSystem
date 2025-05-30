import os
from datetime import datetime

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:  # pragma: no cover - azure sdk optional
    BlobServiceClient = None


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')


def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if BlobServiceClient is None:
        raise RuntimeError('azure-storage-blob package is not installed')
    return BlobServiceClient.from_connection_string(connection_string)


def upload_file(container_client, source_path, blob_name):
    with open(source_path, 'rb') as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)


def backup_database():
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_DB_CONTAINER', 'db-backups')
    container_client = service_client.get_container_client(container_name)
    if not container_client.exists():
        container_client.create_container()
    db_path = os.path.join(DATA_DIR, 'site.db')
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    blob_name = f'site_{timestamp}.db'
    upload_file(container_client, db_path, blob_name)
    return blob_name


def backup_media():
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_MEDIA_CONTAINER', 'media')
    container_client = service_client.get_container_client(container_name)
    if not container_client.exists():
        container_client.create_container()
    # Upload floor map images
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                blob_name = f'{os.path.basename(folder)}/{fname}'
                upload_file(container_client, fpath, blob_name)


def main():
    db_blob = backup_database()
    backup_media()
    print(f'Backup completed. Database blob: {db_blob}')


if __name__ == '__main__':
    main()
