import click
from flask.cli import with_appcontext
from flask import current_app, render_template
from email_utils import send_booking_email # Using the core sender
from models import User # To validate admin user

@click.command('send-admin-email', help="Send a custom email from an admin account.")
@click.option('--sender-username', required=True, help="Username of the admin sending the email.")
@click.option('--to-email', required=True, help="Recipient's email address.")
@click.option('--subject', required=True, help="Subject of the email.")
@click.option('--body-html', help="HTML body of the email. Use file:@path/to/file.html to load from file.")
@click.option('--body-text', help="Plain text body of the email. Use file:@path/to/file.txt to load from file.")
@with_appcontext
def send_admin_email_command(sender_username, to_email, subject, body_html, body_text):
    """
    Allows an admin to send a custom email.
    """
    logger = current_app.logger

    admin_user = User.query.filter_by(username=sender_username, is_admin=True).first()
    if not admin_user:
        click.echo(f"Error: Admin user '{sender_username}' not found or is not an admin.")
        logger.error(f"send-admin-email: Admin user '{sender_username}' not found or not an admin.")
        return

    if not body_html and not body_text:
        click.echo("Error: At least one of --body-html or --body-text must be provided.")
        logger.error("send-admin-email: No email body provided.")
        return

    final_html_body = None
    if body_html:
        if body_html.startswith('file:@'):
            try:
                filepath = body_html[6:]
                with open(filepath, 'r', encoding='utf-8') as f:
                    final_html_body = f.read()
                click.echo(f"Loaded HTML body from {filepath}")
            except Exception as e:
                click.echo(f"Error loading HTML body from file {filepath}: {e}")
                logger.error(f"send-admin-email: Error loading HTML body from {filepath}: {e}")
                return
        else:
            final_html_body = body_html

    final_text_body = None
    if body_text:
        if body_text.startswith('file:@'):
            try:
                filepath = body_text[6:]
                with open(filepath, 'r', encoding='utf-8') as f:
                    final_text_body = f.read()
                click.echo(f"Loaded text body from {filepath}")
            except Exception as e:
                click.echo(f"Error loading text body from file {filepath}: {e}")
                logger.error(f"send-admin-email: Error loading text body from {filepath}: {e}")
                return
        else:
            final_text_body = body_text

    click.echo(f"Attempting to send email to '{to_email}' with subject '{subject}' from admin '{sender_username}'...")

    success = send_booking_email(
        to_address=to_email,
        subject=subject,
        html_body=final_html_body,
        text_body=final_text_body
        # No attachments for this generic admin email command for now
    )

    if success:
        click.echo(click.style(f"Email successfully sent to {to_email}.", fg='green'))
        logger.info(f"send-admin-email: Email to {to_email} from {sender_username} sent successfully.")
    else:
        click.echo(click.style(f"Failed to send email to {to_email}.", fg='red'))
        logger.error(f"send-admin-email: Failed to send email to {to_email} from {sender_username}.")

def register_cli_admin_email_commands(app):
    app.cli.add_command(send_admin_email_command)

# Example usage:
# flask send-admin-email --sender-username admin --to-email user@example.com --subject "Important Update" --body-text "Hello, this is an important update."
# flask send-admin-email --sender-username admin --to-email user@example.com --subject "Newsletter" --body-html file:@./templates/email/generic_newsletter.html
