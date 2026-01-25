import boto3
from botocore.exceptions import ClientError
from flask import current_app
import os

class R2Storage:
    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.access_key = app.config.get('R2_ACCESS_KEY')
        self.secret_key = app.config.get('R2_SECRET_KEY')
        self.bucket_name = app.config.get('R2_BUCKET_NAME')
        self.endpoint_url = app.config.get('R2_ENDPOINT_URL')

        if not all([self.access_key, self.secret_key, self.bucket_name, self.endpoint_url]):
             app.logger.warning("R2 Storage configuration missing. R2 features will not work.")
             self.client = None
             return

        try:
            self.client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name='auto' # Cloudflare R2 uses 'auto'
            )
            app.logger.info("R2 Storage client initialized successfully.")
        except Exception as e:
            app.logger.error(f"Failed to initialize R2 Storage client: {e}")
            self.client = None

    def upload_file(self, file_obj, filename, folder=None):
        """
        Uploads a file to R2.
        :param file_obj: File object (like request.files['file'] or a stream)
        :param filename: The name of the file
        :param folder: Optional folder prefix (e.g. 'resource_uploads')
        :return: Boolean success
        """
        if not self.client:
            current_app.logger.error("R2 client not initialized. Cannot upload.")
            return False

        key = f"{folder}/{filename}" if folder else filename

        try:
            # Check if file_obj is a file path or file-like object
            if isinstance(file_obj, str) and os.path.exists(file_obj):
                self.client.upload_file(file_obj, self.bucket_name, key)
            else:
                 # Ensure we are at the start of the stream if it's a file-like object
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)
                self.client.upload_fileobj(file_obj, self.bucket_name, key)

            current_app.logger.info(f"Successfully uploaded {key} to R2.")
            return True
        except ClientError as e:
            current_app.logger.error(f"Failed to upload {key} to R2: {e}")
            return False
        except Exception as e:
             current_app.logger.error(f"Unexpected error uploading {key} to R2: {e}")
             return False

    def delete_file(self, filename, folder=None):
        """
        Deletes a file from R2.
        """
        if not self.client:
             return False

        key = f"{folder}/{filename}" if folder else filename
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            current_app.logger.info(f"Successfully deleted {key} from R2.")
            return True
        except ClientError as e:
            current_app.logger.error(f"Failed to delete {key} from R2: {e}")
            return False

    def generate_presigned_url(self, filename, folder=None, expiration=3600):
        """
        Generates a presigned URL for viewing the file.
        """
        if not self.client:
            return None

        key = f"{folder}/{filename}" if folder else filename
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            current_app.logger.error(f"Failed to generate presigned URL for {key}: {e}")
            return None

r2_storage = R2Storage()
