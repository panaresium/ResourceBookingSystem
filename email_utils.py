import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest # Import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import current_app, render_template

def send_booking_email(to_address, subject, html_body=None, text_body=None, attachment_data=None, attachment_filename=None, attachment_mimetype='image/png'):
    """
    Sends an email using Gmail API.

    Args:
        to_address (str): Recipient's email address.
        subject (str): Email subject.
        html_body (str, optional): HTML content of the email.
        text_body (str, optional): Plain text content of the email.
        attachment_data (bytes, optional): Binary data for the attachment.
        attachment_filename (str, optional): Filename for the attachment.
        attachment_mimetype (str, optional): MIME type of the attachment.

    Returns:
        bool: True if email was sent successfully, False otherwise.
    """
    logger = current_app.logger
    # Use GMAIL_SENDER_ADDRESS as defined in config.py
    gmail_user = current_app.config.get('GMAIL_SENDER_ADDRESS')
    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
    refresh_token = current_app.config.get('GMAIL_REFRESH_TOKEN')

    if not all([gmail_user, client_id, client_secret, refresh_token]):
        logger.error("Email sending aborted: Missing Gmail API credentials in app config.")
        return False

    creds = Credentials(
        None,  # No access token initially
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token', # Default token URI
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/gmail.send']
    )

    try:
        # Prepare the request object for refreshing credentials
        auth_request = GoogleAuthRequest()

        if not creds.valid or creds.expired:
            logger.info("Gmail credentials need refresh.")
            creds.refresh(auth_request) # Pass the GoogleAuthRequest instance
            logger.info("Gmail credentials refreshed.")
            # Note: In a long-running app, you might want to save the new creds.token (access_token)
            # For example, by updating a stored configuration or session.
            # For simplicity here, we assume the refreshed creds object is used for the current send.
            # However, for single email sends, refreshing each time if needed is okay.

        service = build('gmail', 'v1', credentials=creds)

        message = MIMEMultipart('alternative')
        message['to'] = to_address
        message['from'] = gmail_user
        message['subject'] = subject

        if text_body:
            part_text = MIMEText(text_body, 'plain')
            message.attach(part_text)

        if html_body:
            part_html = MIMEText(html_body, 'html')
            message.attach(part_html)

        if attachment_data and attachment_filename:
            if attachment_mimetype.startswith('image/'):
                mime_attachment = MIMEImage(attachment_data, _subtype=attachment_mimetype.split('/')[-1], name=attachment_filename)
            else:
                mime_attachment = MIMEApplication(attachment_data, _subtype=attachment_mimetype.split('/')[-1], name=attachment_filename)

            mime_attachment.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
            # Re-attach the main content after adding the attachment, if the main content was text/html.
            # This ensures the structure is multipart/mixed -> multipart/alternative -> text/plain, text/html
            # And the attachment is at the same level as multipart/alternative.

            # Correct approach: Create a new MIMEMultipart('mixed') if there's an attachment.
            # The 'alternative' part goes inside 'mixed'.
            if text_body or html_body:
                outer_message = MIMEMultipart('mixed')
                outer_message['to'] = to_address
                outer_message['from'] = gmail_user
                outer_message['subject'] = subject

                # Re-attach the text/html parts to the original 'alternative' message
                # This seems redundant if 'message' already has them.
                # The issue is 'message' is alternative. It should be added to 'mixed'.
                outer_message.attach(message) # message is the MIMEMultipart('alternative')
                outer_message.attach(mime_attachment)
                encoded_message = base64.urlsafe_b64encode(outer_message.as_bytes()).decode()
            else: # Email with only attachment
                message = MIMEMultipart('mixed') # Override original 'alternative' message
                message['to'] = to_address
                message['from'] = gmail_user
                message['subject'] = subject
                message.attach(mime_attachment)
                encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        else: # No attachment
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message_request = {'raw': encoded_message}
        send_request = service.users().messages().send(userId=gmail_user, body=create_message_request)
        sent_message = send_request.execute()

        logger.info(f"Email sent successfully to {to_address}. Message ID: {sent_message['id']}")
        return True

    except HttpError as error:
        logger.error(f"An HTTP error occurred while sending email to {to_address}: {error.resp.status} - {error._get_reason()}")
        logger.error(f"Error details: {error.content}")
        # Specific check for token errors
        if error.resp.status == 401 or error.resp.status == 403:
            logger.error("This might be due to an invalid, expired, or revoked refresh token, or incorrect client credentials.")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred while sending email to {to_address}: {e}")
        return False

def render_email_template(template_name_or_list, **context):
    """Renders a Jinja2 template for email."""
    # This is a helper if you want to keep template rendering logic separate
    # but Flask's render_template usually works fine directly.
    return render_template(template_name_or_list, **context)
