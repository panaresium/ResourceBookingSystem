import os
from flask import Blueprint, request, session, redirect, url_for, current_app, flash, render_template
from flask_login import login_required, current_user # Added current_user
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.exceptions import OAuthError

# Assuming User model might be needed for permission checks, or permission_required decorator
from auth import permission_required

gmail_auth_bp = Blueprint('gmail_auth', __name__, url_prefix='/admin/gmail_auth')

def get_gmail_oauth_flow():
    # Dynamically generate the redirect URI to ensure it matches the current environment (e.g., localhost or production)
    # This avoids configuration errors where the env var doesn't match the actual running host.
    redirect_uri = url_for('gmail_auth.authorize_gmail_callback', _external=True)

    # Scopes for sending email
    scopes = ['https://www.googleapis.com/auth/gmail.send']

    # Client config details are loaded from current_app.config
    # These should be the GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for the web application
    client_config = {
        "web": {
            "client_id": current_app.config.get('GOOGLE_CLIENT_ID'),
            "client_secret": current_app.config.get('GOOGLE_CLIENT_SECRET'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
            # "javascript_origins": [...] # Optional, if needed
        }
    }
    # For development/testing with http, allow insecure transport
    # In production, ensure HTTPS is used.
    if current_app.debug:
         os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=scopes,
        redirect_uri=redirect_uri
    )
    return flow

@gmail_auth_bp.route('/authorize_sending')
@login_required
@permission_required('manage_system') # Ensure only admins can initiate this
def authorize_gmail_sending():
    # For development/testing with http, allow insecure transport
    if current_app.debug: # Check if app is in debug mode
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    try:
        flow = get_gmail_oauth_flow()
        # Generate authorization URL & store state for CSRF protection
        authorization_url, state = flow.authorization_url(
            access_type='offline', # Request offline access to get a refresh token
            prompt='consent'       # Force consent screen to ensure refresh token is issued
        )
        session['oauth_gmail_state'] = state
        current_app.logger.info(f"Admin {current_user.username} initiating Gmail sending authorization. Redirecting to Google.")
        return redirect(authorization_url)
    except ValueError as ve:
        current_app.logger.error(f"Configuration error during Gmail auth initiation: {str(ve)}")
        flash(f"Configuration error: {str(ve)}. Please check server logs and config.", "danger")
        return redirect(url_for('admin_ui.serve_backup_settings_page'))
    except Exception as e:
        current_app.logger.exception(f"Error initiating Gmail sending authorization: {e}")
        flash("An unexpected error occurred while initiating Gmail authorization. Please try again.", "danger")
        return redirect(url_for('admin_ui.serve_backup_settings_page'))


@gmail_auth_bp.route('/authorize_callback')
# This route should match the GMAIL_OAUTH_REDIRECT_URI
@login_required # Ensure an admin is still logged in, though state also protects
@permission_required('manage_system')
def authorize_gmail_callback():
    # For development/testing with http, allow insecure transport
    if current_app.debug: # Check if app is in debug mode
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    state = session.pop('oauth_gmail_state', None)
    # Verify state parameter to prevent CSRF
    if not state or state != request.args.get('state'):
        current_app.logger.error("OAuth state mismatch in Gmail authorization callback. Potential CSRF.")
        flash("Authorization failed due to a state mismatch. Please try again.", "error")
        # Redirect to the new target page: /admin/backup/settings
        return redirect(url_for('admin_ui.serve_backup_settings_page'))

    try:
        flow = get_gmail_oauth_flow()
        # Exchange authorization code for tokens
        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials
        refresh_token = credentials.refresh_token
        access_token = credentials.token # Current access token

        # Log and display the refresh token to the admin
        # IMPORTANT: This is sensitive. In a real app, consider more secure handling or direct storage.
        log_message = (
            f"Gmail sending authorization successful for admin {current_user.username}. "
            f"Obtained refresh token (first 10 chars): {refresh_token[:10] if refresh_token else 'NONE'}... "
            f"Access token (first 10 chars): {access_token[:10] if access_token else 'NONE'}..."
        )
        current_app.logger.info(log_message)

        if refresh_token:
            flash_message = (
                "Gmail sending authorization successful! Your Refresh Token is: "
                f"<strong>{refresh_token}</strong><br>"
                "Please copy this token NOW and set it as the "
                "`GMAIL_REFRESH_TOKEN` environment variable for your application. "
                "Store this token securely. You will only see it once."
            )
            flash(flash_message, "success")
            # Redirect to the new target page: /admin/backup/settings
            return redirect(url_for('admin_ui.serve_backup_settings_page'))
        else:
            flash_message = (
                "Gmail authorization was successful, but a **Refresh Token was NOT provided by Google**. "
                "This might happen if consent was previously granted without 'offline' access, or if the "
                "'prompt=consent' parameter was not effective. Please ensure your Google OAuth client is "
                "configured correctly and try removing the app's access from the Google account settings "
                "and re-authorizing with 'prompt=consent'."
            )
            flash(flash_message, "warning")
            current_app.logger.warning(f"Gmail authorization for {current_user.username} did not yield a refresh token. Access token: {access_token}")
            # Redirect to the new target page: /admin/backup/settings
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

    except OAuthError as oe:
        current_app.logger.error(f"OAuthError during Gmail token exchange: {str(oe)}", exc_info=True)
        # Construct the expected redirect URI to help the user debug
        expected_redirect_uri = url_for('gmail_auth.authorize_gmail_callback', _external=True)
        flash(f"OAuth error during token exchange: {str(oe)}. <br>Ensure that <strong>{expected_redirect_uri}</strong> is added to 'Authorized redirect URIs' in your Google Cloud Console.", "danger")
        # Redirect to the new target page: /admin/backup/settings
        return redirect(url_for('admin_ui.serve_backup_settings_page'))
    except Exception as e:
        current_app.logger.exception(f"Error in Gmail authorization callback: {e}")
        flash("An unexpected error occurred during the Gmail authorization callback.", "danger")
        # Redirect to the new target page: /admin/backup/settings
        return redirect(url_for('admin_ui.serve_backup_settings_page'))

def init_gmail_auth_routes(app):
    app.register_blueprint(gmail_auth_bp)
