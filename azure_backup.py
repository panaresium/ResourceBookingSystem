"""Utility script to upload the local database and media to Azure Blob Storage.

This script reuses the helpers from :mod:`azure_storage` and simply calls the
backup routines when executed directly. It keeps backward compatibility with the
previous commit while allowing more advanced usage from ``azure_storage``.
"""

from azure_storage import upload_database, upload_media


def backup_database():
    """Upload ``site.db`` with a timestamped name."""
    return upload_database(versioned=True)


def backup_media():
    """Upload floor map and resource images."""
    upload_media()


def main():
    db_blob = backup_database()
    backup_media()
    print(f'Backup completed. Database blob: {db_blob}')


if __name__ == '__main__':
    main()
