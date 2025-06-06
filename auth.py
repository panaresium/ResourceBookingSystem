import logging
import os
from functools import wraps
from flask import (
    Blueprint, request, session, redirect, url_for, jsonify, current_app, abort, flash
)
from flask_login import current_user, login_user, logout_user, login_required

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Assuming User model is in models.py
from models import User
# Assuming db, login_manager, oauth, csrf are in extensions.py
from extensions import db, login_manager, oauth, csrf
# Assuming add_audit_log is in utils.py
from utils import add_audit_log

# This will be imported from config.py in the app factory context
# For now, define it here or ensure it's available when get_google_flow is called.
# If SCOPES is in config.py, get_google_flow will access it via current_app.config['SCOPES']
# For this module, it's better to rely on current_app.config.
# SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']


auth_bp = Blueprint('auth', __name__)

# --- Flask-Login Setup ---
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized_callback():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized'}), 401
    # Assuming 'ui.serve_login' will be the route for the login page in the ui blueprint
    return redirect(url_for('ui.serve_login', next=request.url))


# --- Google OAuth Logic ---
def get_google_flow():
    # Scopes should be loaded from config
    scopes = current_app.config.get('SCOPES', ['openid', 'email', 'profile'])
    redirect_uri_dynamic = url_for('auth.login_google_callback', _external=True)
    return Flow.from_client_config(
        client_config={'web': {
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri_dynamic],
            'javascript_origins': [current_app.config.get('GOOGLE_JAVASCRIPT_ORIGIN', 'http://127.0.0.1:5000')]
        }},
        scopes=scopes,
        redirect_uri=redirect_uri_dynamic
    )

@auth_bp.route('/login/google')
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for('ui.serve_index')) # Assuming 'ui.serve_index' for the main page

    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['oauth_state'] = state
    return redirect(authorization_url)

@auth_bp.route('/login/google/callback')
def login_google_callback():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    state = session.pop('oauth_state', None)
    if state is None or state != request.args.get('state'):
        logger.error("Invalid OAuth state parameter during Google callback. Potential CSRF.")
        return redirect(url_for('ui.serve_login')) # Assuming 'ui.serve_login'

    flow = get_google_flow()
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        logger.error(f"Error fetching OAuth token from Google: {e}", exc_info=True)
        return redirect(url_for('ui.serve_login'))

    if not flow.credentials:
        logger.error("Failed to retrieve credentials from Google after token fetch.")
        return redirect(url_for('ui.serve_login'))

    id_token_jwt = flow.credentials.id_token
    try:
        id_info = id_token.verify_oauth2_token(
            id_token_jwt, google_requests.Request(), current_app.config['GOOGLE_CLIENT_ID']
        )
        google_user_id = id_info.get('sub')
        google_user_email = id_info.get('email')

        if not google_user_id or not google_user_email:
            logger.error(f"Google ID token missing 'sub' or 'email'. Email: {google_user_email}, Sub: {google_user_id}")
            return redirect(url_for('ui.serve_login'))

        user = User.query.filter_by(google_id=google_user_id).first()
        if user:
            if user.is_admin: # Application specific logic
                login_user(user)
                logger.info(f"Admin user {user.username} (Google ID: {google_user_id}) logged in via Google.")
                return redirect(url_for('ui.serve_index'))
            else:
                logger.warning(f"Non-admin user {user.username} (Google ID: {google_user_id}) attempted Google login. Denied.")
                return redirect(url_for('ui.serve_login'))

        admin_with_email = User.query.filter_by(email=google_user_email, is_admin=True).first()
        if admin_with_email:
            existing_google_id_user = User.query.filter_by(google_id=google_user_id).first()
            if existing_google_id_user and existing_google_id_user.id != admin_with_email.id:
                logger.error(f"Google ID {google_user_id} already linked to another user.")
                return redirect(url_for('ui.serve_login'))

            admin_with_email.google_id = google_user_id
            admin_with_email.google_email = google_user_email
            try:
                db.session.commit()
                login_user(admin_with_email)
                logger.info(f"Admin user {admin_with_email.username} linked Google account (ID: {google_user_id}).")
                return redirect(url_for('ui.serve_index'))
            except Exception as e:
                db.session.rollback()
                logger.exception(f"DB error linking Google ID {google_user_id} to user {admin_with_email.username}:")
                return redirect(url_for('ui.serve_login'))
        else:
            logger.warning(f"Google account (Email: {google_user_email}) not associated with any admin user. Login denied.")
            return redirect(url_for('ui.serve_login'))

    except ValueError as e:
        logger.error(f"Invalid Google ID token: {e}", exc_info=True)
        return redirect(url_for('ui.serve_login'))
    except Exception:
        logger.exception("Unexpected error during Google login callback:")
        return redirect(url_for('ui.serve_login'))

# --- Google Account Linking/Unlinking ---

def get_google_link_flow():
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    scopes = current_app.config.get('SCOPES', ['openid', 'email', 'profile'])
    # IMPORTANT: This redirect_uri MUST match exactly what's configured in Google Cloud Console
    # for the OAuth client, under "Authorized redirect URIs".
    redirect_uri_dynamic = url_for('auth.link_google_callback', _external=True)
    current_app.logger.info(f"Generated Google Link Flow redirect URI: {redirect_uri_dynamic}")
    return Flow.from_client_config(
        client_config={'web': {
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri_dynamic], # Must be a list
            'javascript_origins': [current_app.config.get('GOOGLE_JAVASCRIPT_ORIGIN', 'http://127.0.0.1:5000')]
        }},
        scopes=scopes,
        redirect_uri=redirect_uri_dynamic
    )

@auth_bp.route('/profile/link/google')
@login_required
def link_google_auth():
    if current_user.google_id:
        flash('Your account is already linked with Google.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    flow = get_google_link_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        # prompt='consent' # Optional: to ensure refresh token, or if user previously denied scopes
    )
    session['oauth_link_state'] = state
    session['oauth_link_user_id'] = current_user.id # Store user ID to link in callback
    current_app.logger.info(f"User {current_user.username} initiating Google account linking. State: {state}")
    return redirect(authorization_url)

@auth_bp.route('/profile/link/google/callback')
@login_required
def link_google_callback():
    logger = current_app.logger
    state = session.pop('oauth_link_state', None)
    link_user_id = session.pop('oauth_link_user_id', None)

    if state is None or state != request.args.get('state') or link_user_id is None:
        logger.error("Invalid OAuth state or missing user ID during Google link callback. Potential CSRF or session issue.")
        flash('Google linking failed due to an invalid state. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    user_to_link = db.session.get(User, link_user_id)
    if not user_to_link or user_to_link.id != current_user.id:
        logger.error(f"User ID mismatch in Google link callback. Session user ID: {link_user_id}, Current user ID: {current_user.id}")
        flash('Google linking failed due to a user mismatch. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    flow = get_google_link_flow()
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        logger.error(f"Error fetching OAuth token from Google during link: {e}", exc_info=True)
        flash('Failed to fetch authentication token from Google. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    if not flow.credentials:
        logger.error("Failed to retrieve credentials from Google after token fetch during link.")
        flash('Failed to retrieve credentials from Google. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    id_token_jwt = flow.credentials.id_token
    try:
        id_info = id_token.verify_oauth2_token(
            id_token_jwt, google_requests.Request(), current_app.config['GOOGLE_CLIENT_ID']
        )
        google_user_id = id_info.get('sub')
        google_user_email = id_info.get('email')

        if not google_user_id or not google_user_email:
            logger.error(f"Google ID token missing 'sub' or 'email' during link. Email: {google_user_email}, Sub: {google_user_id}")
            flash('Google authentication was successful but necessary ID or email was not provided.', 'error')
            return redirect(url_for('ui.serve_profile_page'))

        # Check if this Google account is already linked to ANOTHER user
        existing_user_with_google_id = User.query.filter(User.google_id == google_user_id, User.id != user_to_link.id).first()
        if existing_user_with_google_id:
            logger.warning(f"User {user_to_link.username} attempted to link Google ID {google_user_id} which is already linked to user {existing_user_with_google_id.username}.")
            flash(f"This Google account ({google_user_email}) is already linked to another user ({existing_user_with_google_id.username}).", 'error')
            return redirect(url_for('ui.serve_profile_page'))

        user_to_link.google_id = google_user_id
        user_to_link.google_email = google_user_email
        db.session.commit()

        logger.info(f"User {user_to_link.username} successfully linked Google account (ID: {google_user_id}, Email: {google_user_email}).")
        add_audit_log(action="LINK_GOOGLE_SUCCESS", details=f"User {user_to_link.username} linked Google account (Email: {google_user_email}).", user_id=user_to_link.id)
        flash(f'Successfully linked your Google account ({google_user_email}).', 'success')
        return redirect(url_for('ui.serve_profile_page'))

    except ValueError as e: # Specific error for token verification
        logger.error(f"Invalid Google ID token during link: {e}", exc_info=True)
        flash('Invalid Google authentication token received. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Unexpected error during Google link callback for user {user_to_link.username}:")
        flash('An unexpected error occurred while linking your Google account. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

@auth_bp.route('/profile/unlink/google', methods=['POST'])
@login_required
# @csrf.protect # Add this if you have CSRFProtect initialized and are using Flask-WTF forms for the button
def unlink_google_account():
    logger = current_app.logger
    if not current_user.google_id:
        flash('Your account is not currently linked with Google.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    unlinked_google_email = current_user.google_email
    current_user.google_id = None
    current_user.google_email = None
    try:
        db.session.commit()
        logger.info(f"User {current_user.username} unlinked Google account (was {unlinked_google_email}).")
        add_audit_log(action="UNLINK_GOOGLE_SUCCESS", details=f"User {current_user.username} unlinked Google account (was {unlinked_google_email}).", user_id=current_user.id)
        flash('Successfully unlinked your Google account.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error unlinking Google account for user {current_user.username}:")
        flash('An error occurred while unlinking your Google account. Please try again.', 'error')
    return redirect(url_for('ui.serve_profile_page'))

# --- Facebook Account Linking/Unlinking ---

@auth_bp.route('/profile/link/facebook')
@login_required
def link_facebook_auth():
    if current_user.facebook_id:
        flash('Your account is already linked with Facebook.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    redirect_uri = url_for('auth.link_facebook_callback', _external=True)
    session['oauth_link_facebook_user_id'] = current_user.id # Store user ID to link in callback
    current_app.logger.info(f"User {current_user.username} initiating Facebook account linking.")
    # Assuming oauth.facebook is registered and configured
    if not hasattr(oauth, 'facebook'):
        current_app.logger.error("Facebook OAuth client 'oauth.facebook' not registered.")
        flash('Facebook integration is not configured. Please contact support.', 'error')
        return redirect(url_for('ui.serve_profile_page'))
    return oauth.facebook.authorize_redirect(redirect_uri)

@auth_bp.route('/profile/link/facebook/callback')
@login_required
def link_facebook_callback():
    logger = current_app.logger
    link_user_id = session.pop('oauth_link_facebook_user_id', None)

    if link_user_id is None:
        logger.error("Missing user ID during Facebook link callback. Session issue.")
        flash('Facebook linking failed due to a session issue. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    user_to_link = db.session.get(User, link_user_id)
    if not user_to_link or user_to_link.id != current_user.id:
        logger.error(f"User ID mismatch in Facebook link callback. Session user ID: {link_user_id}, Current user ID: {current_user.id}")
        flash('Facebook linking failed due to a user mismatch. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    if not hasattr(oauth, 'facebook'):
        current_app.logger.error("Facebook OAuth client 'oauth.facebook' not registered for callback.")
        flash('Facebook integration is not configured. Please contact support.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    try:
        token = oauth.facebook.authorize_access_token()
    except Exception as e: # Authlib specific errors can be caught if known, e.g., OAuthError
        logger.error(f"Error authorizing Facebook access token: {e}", exc_info=True)
        flash('Failed to authorize with Facebook. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    if not token or 'access_token' not in token:
        logger.error("Failed to retrieve access token from Facebook during link.")
        flash('Failed to retrieve access token from Facebook. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    try:
        # Assuming userinfo_endpoint was 'https://graph.facebook.com/me?fields=id,email'
        resp = oauth.facebook.get('me?fields=id') # Only ID is strictly needed for linking
        profile_data = resp.json()
        facebook_user_id = profile_data.get('id')

        if not facebook_user_id:
            logger.error("Facebook profile data missing 'id'.")
            flash('Facebook authentication was successful but necessary ID was not provided.', 'error')
            return redirect(url_for('ui.serve_profile_page'))

        existing_user_with_facebook_id = User.query.filter(User.facebook_id == facebook_user_id, User.id != user_to_link.id).first()
        if existing_user_with_facebook_id:
            logger.warning(f"User {user_to_link.username} attempted to link Facebook ID {facebook_user_id} which is already linked to user {existing_user_with_facebook_id.username}.")
            flash(f"This Facebook account is already linked to another user ({existing_user_with_facebook_id.username}).", 'error')
            return redirect(url_for('ui.serve_profile_page'))

        user_to_link.facebook_id = facebook_user_id
        db.session.commit()

        logger.info(f"User {user_to_link.username} successfully linked Facebook account (ID: {facebook_user_id}).")
        add_audit_log(action="LINK_FACEBOOK_SUCCESS", details=f"User {user_to_link.username} linked Facebook account.", user_id=user_to_link.id)
        flash('Successfully linked your Facebook account.', 'success')
        return redirect(url_for('ui.serve_profile_page'))

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Unexpected error during Facebook link callback for user {user_to_link.username}: {e}")
        flash('An unexpected error occurred while linking your Facebook account. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

@auth_bp.route('/profile/unlink/facebook', methods=['POST'])
@login_required
# @csrf.protect # Add this if CSRFProtect is globally enabled
def unlink_facebook_account():
    logger = current_app.logger
    if not current_user.facebook_id:
        flash('Your account is not currently linked with Facebook.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    current_user.facebook_id = None
    try:
        db.session.commit()
        logger.info(f"User {current_user.username} unlinked Facebook account.")
        add_audit_log(action="UNLINK_FACEBOOK_SUCCESS", details=f"User {current_user.username} unlinked Facebook account.", user_id=current_user.id)
        flash('Successfully unlinked your Facebook account.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error unlinking Facebook account for user {current_user.username}:")
        flash('An error occurred while unlinking your Facebook account. Please try again.', 'error')
    return redirect(url_for('ui.serve_profile_page'))

# --- Instagram Account Linking/Unlinking ---

@auth_bp.route('/profile/link/instagram')
@login_required
def link_instagram_auth():
    if current_user.instagram_id:
        flash('Your account is already linked with Instagram.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    redirect_uri = url_for('auth.link_instagram_callback', _external=True)
    session['oauth_link_instagram_user_id'] = current_user.id
    current_app.logger.info(f"User {current_user.username} initiating Instagram account linking.")

    if not hasattr(oauth, 'instagram'):
        current_app.logger.error("Instagram OAuth client 'oauth.instagram' not registered.")
        flash('Instagram integration is not configured. Please contact support.', 'error')
        return redirect(url_for('ui.serve_profile_page'))
    return oauth.instagram.authorize_redirect(redirect_uri)

@auth_bp.route('/profile/link/instagram/callback')
@login_required
def link_instagram_callback():
    logger = current_app.logger
    link_user_id = session.pop('oauth_link_instagram_user_id', None)

    if link_user_id is None:
        logger.error("Missing user ID during Instagram link callback. Session issue.")
        flash('Instagram linking failed due to a session issue. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    user_to_link = db.session.get(User, link_user_id)
    if not user_to_link or user_to_link.id != current_user.id:
        logger.error(f"User ID mismatch in Instagram link callback. Session user ID: {link_user_id}, Current user ID: {current_user.id}")
        flash('Instagram linking failed due to a user mismatch. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    if not hasattr(oauth, 'instagram'):
        current_app.logger.error("Instagram OAuth client 'oauth.instagram' not registered for callback.")
        flash('Instagram integration is not configured. Please contact support.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    try:
        token = oauth.instagram.authorize_access_token()
    except Exception as e:
        logger.error(f"Error authorizing Instagram access token: {e}", exc_info=True)
        flash('Failed to authorize with Instagram. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    if not token or 'access_token' not in token: # Instagram might also return 'user_id' directly with short-lived token
        logger.error(f"Failed to retrieve access token from Instagram during link. Token: {token}")
        flash('Failed to retrieve access token from Instagram. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

    try:
        # For Instagram Basic Display API, user ID is often part of the access token response,
        # or fetched via /me endpoint. The userinfo_endpoint should be https://graph.instagram.com/me?fields=id
        # If the token is a short-lived token, it must be exchanged for a long-lived one ideally.
        # This example assumes a simple get for user ID.
        resp = oauth.instagram.get('me?fields=id') # User ID and username are common fields.
        profile_data = resp.json()
        instagram_user_id = profile_data.get('id')
        # instagram_username = profile_data.get('username') # Optional, if needed

        if not instagram_user_id:
            logger.error(f"Instagram profile data missing 'id'. Data: {profile_data}")
            flash('Instagram authentication was successful but necessary ID was not provided.', 'error')
            return redirect(url_for('ui.serve_profile_page'))

        existing_user_with_instagram_id = User.query.filter(User.instagram_id == instagram_user_id, User.id != user_to_link.id).first()
        if existing_user_with_instagram_id:
            logger.warning(f"User {user_to_link.username} attempted to link Instagram ID {instagram_user_id} which is already linked to user {existing_user_with_instagram_id.username}.")
            flash(f"This Instagram account is already linked to another user ({existing_user_with_instagram_id.username}).", 'error')
            return redirect(url_for('ui.serve_profile_page'))

        user_to_link.instagram_id = instagram_user_id
        db.session.commit()

        logger.info(f"User {user_to_link.username} successfully linked Instagram account (ID: {instagram_user_id}).")
        add_audit_log(action="LINK_INSTAGRAM_SUCCESS", details=f"User {user_to_link.username} linked Instagram account.", user_id=user_to_link.id)
        flash('Successfully linked your Instagram account.', 'success')
        return redirect(url_for('ui.serve_profile_page'))

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Unexpected error during Instagram link callback for user {user_to_link.username}: {e}")
        flash('An unexpected error occurred while linking your Instagram account. Please try again.', 'error')
        return redirect(url_for('ui.serve_profile_page'))

@auth_bp.route('/profile/unlink/instagram', methods=['POST'])
@login_required
# @csrf.protect
def unlink_instagram_account():
    logger = current_app.logger
    if not current_user.instagram_id:
        flash('Your account is not currently linked with Instagram.', 'info')
        return redirect(url_for('ui.serve_profile_page'))

    current_user.instagram_id = None
    try:
        db.session.commit()
        logger.info(f"User {current_user.username} unlinked Instagram account.")
        add_audit_log(action="UNLINK_INSTAGRAM_SUCCESS", details=f"User {current_user.username} unlinked Instagram account.", user_id=current_user.id)
        flash('Successfully unlinked your Instagram account.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error unlinking Instagram account for user {current_user.username}:")
        flash('An error occurred while unlinking your Instagram account. Please try again.', 'error')
    return redirect(url_for('ui.serve_profile_page'))

# --- Permission Decorator ---
def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_permission(permission):
                current_app.logger.warning(f"User {current_user.username} lacks permission '{permission}' for {f.__name__}")
                abort(403) # Forbidden
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- API Authentication Routes ---
@auth_bp.route('/api/auth/login', methods=['POST'])
@csrf.exempt
def api_login():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    data = request.get_json()
    if not data:
        logger.warning("Login attempt with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        logger.warning("Login attempt with missing username or password.")
        return jsonify({'error': 'Username and password are required.'}), 400

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        login_user(user)
        user_data = {'id': user.id, 'username': user.username, 'email': user.email, 'is_admin': user.is_admin}
        logger.info(f"User '{username}' logged in successfully.")
        add_audit_log(action="LOGIN_SUCCESS", details=f"User '{username}' logged in successfully.", user_id=user.id, username=user.username)
        return jsonify({'success': True, 'message': 'Login successful.', 'user': user_data}), 200
    else:
        logger.warning(f"Invalid login attempt for username: {username}")
        add_audit_log(action="LOGIN_FAILED", details=f"Failed login attempt for username: '{username}'.")
        return jsonify({'error': 'Invalid username or password.'}), 401

@auth_bp.route('/api/auth/logout', methods=['POST'])
@csrf.exempt
def api_logout():
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    user_identifier = current_user.username if current_user.is_authenticated else "Anonymous"
    user_id_for_log = current_user.id if current_user.is_authenticated else None

    try:
        logout_user()
        logger.info(f"User '{user_identifier}' logged out successfully.")
        add_audit_log(action="LOGOUT_SUCCESS", details=f"User '{user_identifier}' logged out.", user_id=user_id_for_log, username=user_identifier)
        return jsonify({'success': True, 'message': 'Logout successful.'}), 200
    except Exception as e:
        logger.exception(f"Error during logout for user {user_identifier}:")
        add_audit_log(action="LOGOUT_FAILED", details=f"Logout attempt failed for user '{user_identifier}'. Error: {str(e)}", user_id=user_id_for_log, username=user_identifier)
        return jsonify({'error': 'Logout failed due to a server error.'}), 500

@auth_bp.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    if current_user.is_authenticated:
        user_data = {
            'id': current_user.id, 'username': current_user.username,
            'email': current_user.email, 'is_admin': current_user.is_admin
        }
        return jsonify({'logged_in': True, 'user': user_data}), 200
    else:
        return jsonify({'logged_in': False}), 200

# --- Initialization Function ---
def init_auth(app, login_manager_instance, oauth_instance, csrf_instance):
    login_manager_instance.init_app(app)
    # login_manager is already initialized in extensions.py, just configure it
    login_manager_instance.login_view = 'ui.serve_login' # Assuming serve_login will be in 'ui' blueprint
    login_manager_instance.login_message = 'Please log in to access this page.'
    login_manager_instance.login_message_category = 'info'

    # The user_loader and unauthorized_handler are already set on login_manager instance from extensions.py

    # OAuth client registration (moved from app.py)
    # This uses the oauth_instance passed from extensions
    oauth_instance.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url=app.config['GOOGLE_DISCOVERY_URL'],
        client_kwargs={
            'scope': ' '.join(app.config.get('SCOPES', ['openid', 'email', 'profile']))
        }
    )

    app.register_blueprint(auth_bp)
