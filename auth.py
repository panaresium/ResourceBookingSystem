import logging
from functools import wraps
from flask import (
    Blueprint, request, session, redirect, url_for, jsonify, current_app, abort
)
from flask_login import current_user, login_user, logout_user

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
