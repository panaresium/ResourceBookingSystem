from flask import Flask, jsonify, render_template, request, url_for, redirect, session # Added redirect and session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func # Add this
from datetime import datetime, date, timedelta, time # Ensure all are here
import os
import json # For serializing coordinates
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # For User model and init_db
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth # Added for Google Sign-In

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import pathlib # For finding the client_secret.json file path
import logging # Added for logging

# Base directory of the app - project root
basedir = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(basedir, 'data')
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'floor_map_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure the data directory exists (it should be created by init_setup.py)
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'dev_secret_key_123!@#' # CHANGE THIS in production!

# Google OAuth Configuration - Recommended to use environment variables
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID_PLACEHOLDER')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET_PLACEHOLDER')
app.config['GOOGLE_DISCOVERY_URL'] = "https://accounts.google.com/.well-known/openid-configuration"

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(DATA_DIR, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # silence the warning

# Basic Logging Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
# For Flask's built-in logger, you might configure it further if needed,
# but basicConfig provides a good default if running app.py directly.
# app.logger.setLevel(logging.INFO) # Example if using Flask's logger predominantly

# Google OAuth Configuration - Placeholders
app.config['GOOGLE_CLIENT_ID'] = '365817360521-ilj3v7uqhd0f7cu5lfr6mva9fmaepe15.apps.googleusercontent.com'
app.config['GOOGLE_CLIENT_SECRET'] = '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'

# OAuth 2.0 setup
# Note: client_secret.json is not used directly by google-auth-oauthlib Flow if client_id and client_secret are set in config.
# However, if you were to use it, this is how you might define its path:
# CLIENT_SECRET_FILE = os.path.join(pathlib.Path(__file__).parent, 'client_secret.json') 

# Ensure this URL is exactly as registered in your Google Cloud Console Authorized redirect URIs
REDIRECT_URI = 'http://127.0.0.1:5000/login/google/callback' # Or https if using https

# OAuth Scopes, request email and profile
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']

def get_google_flow():
    return Flow.from_client_config(
        client_config={'web': {
            'client_id': app.config['GOOGLE_CLIENT_ID'],
            'client_secret': app.config['GOOGLE_CLIENT_SECRET'],
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [REDIRECT_URI], # Must match exactly what's in Google Cloud Console
            'javascript_origins': ['http://127.0.0.1:5000'] # Or your app's origin
        }},
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

db = SQLAlchemy(app)

# Authlib OAuth 2.0 Client Setup
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url=app.config['GOOGLE_DISCOVERY_URL'],
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'serve_login' 
login_manager.login_message_category = 'info' 
login_manager.login_message = 'Please log in to access this page.' 

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin): 
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False) # Optional for now, but good practice
    password_hash = db.Column(db.String(256), nullable=False) # Increased length for potentially longer hashes
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    google_id = db.Column(db.String(200), nullable=True, unique=True)
    google_email = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f'<User {self.username} (Admin: {self.is_admin})>'

    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

class FloorMap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False, unique=True) # Store unique filename

    def __repr__(self):
        return f"<FloorMap {self.name} ({self.image_filename})>"

class Resource(db.Model): # UserMixin is correctly on User model, not Resource
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=True) # Optional capacity
    equipment = db.Column(db.String(200), nullable=True) 
    booking_restriction = db.Column(db.String(50), nullable=True) # e.g., 'admin_only', 'all_users'
    status = db.Column(db.String(50), nullable=False, default='draft') # Values: 'draft', 'published', 'archived'
    published_at = db.Column(db.DateTime, nullable=True)
    allowed_user_ids = db.Column(db.Text, nullable=True)  # Comma-separated string of User IDs
    allowed_roles = db.Column(db.String(255), nullable=True) # Comma-separated string of role names (e.g., 'admin', 'standard_user')
    
    # New fields for floor map integration
    floor_map_id = db.Column(db.Integer, db.ForeignKey('floor_map.id'), nullable=True)
    map_coordinates = db.Column(db.Text, nullable=True) # To store JSON like {'type':'rect', 'x':10, 'y':20, 'w':50, 'h':30}
    
    # Relationships
    bookings = db.relationship('Booking', backref='resource_booked', lazy=True, cascade="all, delete-orphan")
    floor_map = db.relationship('FloorMap', backref=db.backref('resources', lazy='dynamic')) # Optional but useful

    def __repr__(self):
        return f"<Resource {self.name}>"

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=True)  # Placeholder for user
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    title = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<Booking {self.title or self.id} for Resource {self.resource_id} from {self.start_time.strftime('%Y-%m-%d %H:%M')} to {self.end_time.strftime('%Y-%m-%d %H:%M')}>"

@app.route("/")
def serve_index():
    return render_template("index.html")

@app.route("/new_booking")
def serve_new_booking():
    return render_template("new_booking.html")

@app.route("/resources")
def serve_resources():
    return render_template("resources.html")

@app.route("/login")
def serve_login():
    return render_template("login.html")

@app.route("/profile")
@login_required
def serve_profile_page():
    """Serves the user's profile page."""
    # current_user is available thanks to Flask-Login
    app.logger.info(f"User {current_user.username} accessed their profile page.")
    return render_template("profile.html", 
                           username=current_user.username, 
                           email=current_user.email)

@app.route('/admin/maps')
@login_required # Ensures user is logged in
def serve_admin_maps():
    if not current_user.is_admin:
        # flash("You do not have permission to access this page.", "danger") # If using flash messages
        return redirect(url_for('serve_index')) # Or some other non-admin page, or a 403 page
    return render_template("admin_maps.html")

@app.route('/map_view/<int:map_id>')
def serve_map_view(map_id):
    # You could fetch map name here to pass to template title, but JS will fetch full details
    return render_template("map_view.html", map_id_from_flask=map_id)

@app.route('/login/google')
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for('serve_index'))
    
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    # Store the state in the session to verify in the callback
    session['oauth_state'] = state 
    return redirect(authorization_url)

@app.route('/login/google/callback')
def login_google_callback():
    state = session.pop('oauth_state', None)
    # It's important to verify the state to prevent CSRF attacks.
    # For explicit state check:
    if state is None or state != request.args.get('state'):
        app.logger.error("Invalid OAuth state parameter during Google callback. Potential CSRF.")
        # Flash messages are not part of this app's error handling strategy
        return redirect(url_for('serve_login'))

    flow = get_google_flow()
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e: # Catches errors like MismatchingStateError (already covered by above state check) or others
        app.logger.error(f"Error fetching OAuth token from Google: {e}", exc_info=True)
        # flash(f"Authentication failed: Could not fetch token. Please try again.", "danger")
        return redirect(url_for('serve_login')) 

    if not flow.credentials:
        app.logger.error("Failed to retrieve credentials from Google after token fetch.")
        # flash("Failed to retrieve credentials from Google. Please try again.", "danger")
        return redirect(url_for('serve_login'))

    # Extract the ID token from credentials
    id_token_jwt = flow.credentials.id_token

    try:
        # Verify the ID token and extract user info
        # The audience ('aud') parameter must match your Google Client ID
        id_info = id_token.verify_oauth2_token(
            id_token_jwt, google_requests.Request(), app.config['GOOGLE_CLIENT_ID']
        )

        google_user_id = id_info.get('sub')
        google_user_email = id_info.get('email')

        if not google_user_id or not google_user_email:
            app.logger.error(f"Google ID token verification successful, but 'sub' or 'email' missing. Email: {google_user_email}, Sub: {google_user_id}")
            # flash("Could not retrieve Google ID or email. Please ensure your Google account has an email and permissions are granted.", "danger")
            return redirect(url_for('serve_login'))

        # Check if user exists by google_id
        user = User.query.filter_by(google_id=google_user_id).first()

        if user: # User found by google_id
            if user.is_admin: # Only allow admin users for this application
                login_user(user)
                app.logger.info(f"Admin user {user.username} (Google ID: {google_user_id}) logged in via Google.")
                # flash(f'Welcome back, {user.username}!', 'success')
                return redirect(url_for('serve_index')) 
            else:
                app.logger.warning(f"Non-admin user {user.username} (Google ID: {google_user_id}) attempted Google login. Denied.")
                # flash('Your Google account is linked, but it is not associated with an admin user for this application.', 'danger')
                return redirect(url_for('serve_login')) 

        # If no user by google_id, check if an existing admin user has this email
        # This is to link an existing admin account (username/password) to Google Sign-In
        admin_with_email = User.query.filter_by(email=google_user_email, is_admin=True).first()

        if admin_with_email:
            # Check if this Google ID is already linked to another account (should be rare if google_id is unique)
            existing_google_id_user = User.query.filter_by(google_id=google_user_id).first() # This should be the same as `user` if found
            if existing_google_id_user and existing_google_id_user.id != admin_with_email.id:
                app.logger.error(f"Google ID {google_user_id} (email: {google_user_email}) is already linked to user {existing_google_id_user.username}, but trying to link to {admin_with_email.username}.")
                # flash('This Google account is already linked to a different user. Please contact support.', 'danger')
                return redirect(url_for('serve_login'))

            admin_with_email.google_id = google_user_id
            admin_with_email.google_email = google_user_email 
            try:
                db.session.commit()
                login_user(admin_with_email)
                app.logger.info(f"Admin user {admin_with_email.username} successfully linked their Google account (ID: {google_user_id}).")
                return redirect(url_for('serve_index')) 
            except Exception as e:
                db.session.rollback()
                app.logger.exception(f"Database error linking Google ID {google_user_id} to user {admin_with_email.username}:")
                return redirect(url_for('serve_login'))
        else:
            app.logger.warning(f"Google account (Email: {google_user_email}, ID: {google_user_id}) not associated with any existing admin user. Login denied for this application.")
            return redirect(url_for('serve_login'))

    except ValueError as e: # Specifically for id_token.verify_oauth2_token
        app.logger.error(f"Invalid Google ID token during Google login: {e}", exc_info=True)
        return redirect(url_for('serve_login'))
    except Exception as e: # Catch any other unexpected errors
        app.logger.exception("An unexpected error occurred during Google login callback:")
        return redirect(url_for('serve_login')) 

# Function to initialize the database
def init_db():
    with app.app_context():
        app.logger.info("Starting database initialization...")

        app.logger.info("Creating database tables (if they don't exist)...")
        db.create_all()
        app.logger.info("Database tables creation/verification step completed.")
        
        app.logger.info("Attempting to delete existing data in corrected order...")
        # Corrected Deletion Order: Booking -> Resource -> FloorMap -> User
        app.logger.info("Deleting existing Bookings...")
        num_bookings_deleted = db.session.query(Booking).delete()
        app.logger.info(f"Deleted {num_bookings_deleted} Bookings.")

        app.logger.info("Deleting existing Resources...")
        num_resources_deleted = db.session.query(Resource).delete()
        app.logger.info(f"Deleted {num_resources_deleted} Resources.")
        
        app.logger.info("Deleting existing FloorMaps...") 
        num_floormaps_deleted = db.session.query(FloorMap).delete()
        app.logger.info(f"Deleted {num_floormaps_deleted} FloorMaps.")
            
        app.logger.info("Deleting existing Users...") 
        num_users_deleted = db.session.query(User).delete()     
        app.logger.info(f"Deleted {num_users_deleted} Users.")
        
        try:
            db.session.commit()
            app.logger.info("Successfully committed deletions of existing data.")
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error committing deletions during DB initialization:")

        app.logger.info("Adding default users (admin/admin, user/userpass)...")
        try:
            default_users = [
                User(username='admin', email='admin@example.com', 
                     password_hash=generate_password_hash('admin', method='pbkdf2:sha256'), 
                     is_admin=True),
                User(username='user', email='user@example.com', 
                     password_hash=generate_password_hash('userpass', method='pbkdf2:sha256'), 
                     is_admin=False)
            ]
            db.session.bulk_save_objects(default_users)
            db.session.commit()
            app.logger.info(f"Successfully added {len(default_users)} default users.")
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error adding default users during DB initialization:")

        admin_user_for_perms = User.query.filter_by(username='admin').first()
        standard_user_for_perms = User.query.filter_by(username='user').first()
        
        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1" 
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2"

        app.logger.info("Adding sample resources...")
        try: 
            sample_resources = [
                Resource(name="Conference Room Alpha", capacity=10, equipment="Projector,Whiteboard,Teleconference", 
                         booking_restriction=None, status='published', published_at=datetime.utcnow(),
                         allowed_user_ids=None, allowed_roles=None),
                Resource(name="Meeting Room Beta", capacity=6, equipment="Teleconference,Whiteboard", 
                         booking_restriction='all_users', status='published', published_at=datetime.utcnow(),
                         allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}", allowed_roles=None),
                Resource(name="Focus Room Gamma", capacity=2, equipment="Whiteboard", 
                         booking_restriction='admin_only', status='draft', published_at=None,
                         allowed_user_ids=None, allowed_roles='admin'),
                Resource(name="Quiet Pod Delta", capacity=1, equipment=None, 
                         booking_restriction=None, status='draft', published_at=None,
                         allowed_user_ids=None, allowed_roles='standard_user,admin'),
                Resource(name="Archived Room Omega", capacity=5, equipment="Old Projector",
                         booking_restriction=None, status='archived', published_at=datetime.utcnow() - timedelta(days=30),
                         allowed_user_ids=None, allowed_roles=None)
            ]
            db.session.bulk_save_objects(sample_resources)
            db.session.commit()
            app.logger.info(f"Successfully added {len(sample_resources)} sample resources.")
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error adding sample resources during DB initialization:")

        app.logger.info("Adding sample bookings...")
        resource_alpha = Resource.query.filter_by(name="Conference Room Alpha").first()
        resource_beta = Resource.query.filter_by(name="Meeting Room Beta").first()

        if resource_alpha and resource_beta:
            try:
                sample_bookings = [
                    Booking(resource_id=resource_alpha.id, user_name="user1", title="Team Sync Alpha", 
                            start_time=datetime.combine(date.today(), time(9, 0)), 
                            end_time=datetime.combine(date.today(), time(10, 0))),
                    Booking(resource_id=resource_alpha.id, user_name="user2", title="Client Meeting", 
                            start_time=datetime.combine(date.today(), time(11, 0)), 
                            end_time=datetime.combine(date.today(), time(12, 30))),
                    Booking(resource_id=resource_alpha.id, user_name="user1", title="Project Update Alpha", 
                            start_time=datetime.combine(date.today() + timedelta(days=1), time(14, 0)), 
                            end_time=datetime.combine(date.today() + timedelta(days=1), time(15, 0))),
                    Booking(resource_id=resource_beta.id, user_name="user3", title="Quick Chat Beta", 
                            start_time=datetime.combine(date.today(), time(10, 0)), 
                            end_time=datetime.combine(date.today(), time(10, 30))),
                    Booking(resource_id=resource_beta.id, user_name="user1", title="Planning Session Beta", 
                            start_time=datetime.combine(date.today(), time(14, 0)), 
                            end_time=datetime.combine(date.today(), time(16, 0))),
                ]
                db.session.bulk_save_objects(sample_bookings)
                db.session.commit()
                app.logger.info(f"Successfully added {len(sample_bookings)} sample bookings.")
            except Exception as e:
                db.session.rollback()
                app.logger.exception("Error adding sample bookings during DB initialization:")
        else:
            app.logger.warning("Could not find sample resources 'Conference Room Alpha' or 'Meeting Room Beta' to create bookings for. Skipping sample booking addition.")
        
        app.logger.info("Database initialization script completed.")

@app.route("/api/resources", methods=['GET'])
def get_resources():
    try:
        # Filter resources by status
        resources_query = Resource.query.filter_by(status='published').all() # MODIFIED HERE
            
        resources_list = []
        for resource in resources_query:
            resources_list.append({
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity,
                'equipment': resource.equipment,
                'floor_map_id': resource.floor_map_id,
                'map_coordinates': resource.map_coordinates, # This should be json.loads if stored as string
                'booking_restriction': resource.booking_restriction,
                'status': resource.status, 
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids,
                'allowed_roles': resource.allowed_roles
            })
        app.logger.info("Successfully fetched published resources.")
        return jsonify(resources_list), 200
    except Exception as e:
        app.logger.exception("Error fetching resources:")
        return jsonify({'error': 'Failed to fetch resources due to a server error.'}), 500

@app.route('/api/resources/<int:resource_id>/availability', methods=['GET'])
def get_resource_availability(resource_id):
    # Get the date from query parameters, default to today if not provided
    date_str = request.args.get('date')
    
    target_date_obj = None
    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.warning(f"Invalid date format provided: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        resource = Resource.query.get(resource_id)
        if not resource:
            app.logger.warning(f"Resource availability check for non-existent resource ID: {resource_id}")
            return jsonify({'error': 'Resource not found.'}), 404

        bookings_on_date = Booking.query.filter(
            Booking.resource_id == resource_id,
            func.date(Booking.start_time) == target_date_obj
        ).all()

        booked_slots = []
        for booking in bookings_on_date:
            booked_slots.append({
                'title': booking.title, # Optional: include title
                'user_name': booking.user_name, # Optional: include user
                'start_time': booking.start_time.strftime('%H:%M:%S'),
                'end_time': booking.end_time.strftime('%H:%M:%S')
            })
        
        return jsonify(booked_slots), 200

    except Exception as e:
        app.logger.exception(f"Error fetching availability for resource {resource_id} on {target_date_obj}:")
        return jsonify({'error': 'Failed to fetch resource availability due to a server error.'}), 500

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/admin/maps', methods=['POST'])
@login_required
def upload_floor_map():
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to upload map.")
        return jsonify({'error': 'Admin access required.'}), 403

    if 'map_image' not in request.files:
        app.logger.warning("Map image missing in upload request.")
        return jsonify({'error': 'No map_image file part in the request.'}), 400
    
    file = request.files['map_image']
    map_name = request.form.get('map_name')

    if not map_name:
        app.logger.warning("Map name missing in upload request.")
        return jsonify({'error': 'map_name is required.'}), 400
    
    if file.filename == '':
        app.logger.warning("No file selected for map upload.")
        return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        # Check for existing map with same name or filename to prevent duplicates
        existing_map_by_filename = FloorMap.query.filter_by(image_filename=filename).first()
        existing_map_by_name = FloorMap.query.filter_by(name=map_name).first()
        
        if existing_map_by_filename:
            app.logger.warning(f"Attempt to upload map with duplicate filename: {filename}")
            return jsonify({'error': 'A map with this image filename already exists.'}), 409 # Conflict
        if existing_map_by_name:
            app.logger.warning(f"Attempt to upload map with duplicate name: {map_name}")
            return jsonify({'error': 'A map with this name already exists.'}), 409 # Conflict

        file_path = None # Initialize file_path to ensure it's defined for potential cleanup
        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            new_map = FloorMap(name=map_name, image_filename=filename)
            db.session.add(new_map)
            db.session.commit()
            app.logger.info(f"Floor map '{map_name}' uploaded successfully by {current_user.username}.")
            return jsonify({
                'id': new_map.id,
                'name': new_map.name,
                'image_filename': new_map.image_filename,
                'image_url': url_for('static', filename=f'floor_map_uploads/{new_map.image_filename}')
            }), 201
        except Exception as e:
            db.session.rollback()
            if file_path and os.path.exists(file_path): # Attempt to clean up saved file on error
                 os.remove(file_path)
                 app.logger.info(f"Cleaned up partially uploaded file: {file_path}")
            app.logger.exception(f"Error uploading floor map '{map_name}':")
            return jsonify({'error': f'Failed to upload map due to a server error.'}), 500
    else:
        app.logger.warning(f"File type not allowed for map upload: {file.filename}")
        return jsonify({'error': 'File type not allowed. Allowed types are: png, jpg, jpeg.'}), 400

@app.route('/api/admin/maps', methods=['GET'])
@login_required
def get_floor_maps():
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to get floor maps.")
        return jsonify({'error': 'Admin access required.'}), 403
    try:
        maps = FloorMap.query.all()
        maps_list = []
        for m in maps:
            maps_list.append({
                'id': m.id,
                'name': m.name,
                'image_filename': m.image_filename,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}')
            })
        app.logger.info("Successfully fetched all floor maps for admin.")
        return jsonify(maps_list), 200
    except Exception as e:
        app.logger.exception("Error fetching floor maps:")
        return jsonify({'error': 'Failed to fetch maps due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['PUT'])
@login_required 
def update_resource_map_info(resource_id):
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to update map info for resource {resource_id}.")
        return jsonify({'error': 'Admin access required.'}), 403

    data = request.get_json()
    if not data:
        app.logger.warning(f"Invalid input for update_resource_map_info for resource {resource_id}: No JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to update map info for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    # Process booking_restriction
    if 'booking_restriction' in data:
        booking_restriction_data = data.get('booking_restriction')
        allowed_restrictions = ['admin_only', 'all_users', None, ""] 
        if booking_restriction_data not in allowed_restrictions:
            app.logger.warning(f"Invalid booking_restriction value '{booking_restriction_data}' for resource {resource_id}.")
            return jsonify({'error': f'Invalid booking_restriction value. Allowed: {allowed_restrictions}. Received: {booking_restriction_data}'}), 400
        resource.booking_restriction = booking_restriction_data if booking_restriction_data != "" else None

    # Process allowed_user_ids
    if 'allowed_user_ids' in data: # This key must be present to modify allowed_user_ids
        user_ids_str_list = data.get('allowed_user_ids') # Expecting a string of comma-separated IDs or null
        if user_ids_str_list is None or user_ids_str_list.strip() == "":
            resource.allowed_user_ids = None
        elif isinstance(user_ids_str_list, str):
            try: # Validate that all are integers
                processed_ids = sorted(list(set(int(uid.strip()) for uid in user_ids_str_list.split(',') if uid.strip())))
                resource.allowed_user_ids = ",".join(map(str, processed_ids)) if processed_ids else None
            except ValueError:
                app.logger.warning(f"Invalid user ID in allowed_user_ids for resource {resource_id}: {user_ids_str_list}")
                return jsonify({'error': 'Invalid allowed_user_ids format. Expected a comma-separated string of integers or null.'}), 400
        else: # Should be string or null
            app.logger.warning(f"Incorrect type for allowed_user_ids for resource {resource_id}: {type(user_ids_str_list)}")
            return jsonify({'error': 'allowed_user_ids must be a string or null.'}), 400


    # Process allowed_roles
    if 'allowed_roles' in data: # This key must be present to modify allowed_roles
        roles_str = data.get('allowed_roles') # Expecting a string of comma-separated roles or null
        if roles_str is None or roles_str.strip() == "":
            resource.allowed_roles = None
        elif isinstance(roles_str, str):
            valid_roles = [role.strip().lower() for role in roles_str.split(',') if role.strip()]
            # Optional: Validate against a predefined list of roles if you have one
            resource.allowed_roles = ",".join(sorted(list(set(valid_roles)))) if valid_roles else None
        else: # Should be string or null
            app.logger.warning(f"Incorrect type for allowed_roles for resource {resource_id}: {type(roles_str)}")
            return jsonify({'error': 'allowed_roles must be a string or null.'}), 400


    # Logic for map and coordinates
    # Only update map info if 'floor_map_id' is explicitly in the payload
    if 'floor_map_id' in data: 
        floor_map_id_data = data.get('floor_map_id')
        coordinates_data = data.get('coordinates') # This should be present if floor_map_id is not null

        if floor_map_id_data is not None: 
            floor_map = FloorMap.query.get(floor_map_id_data)
            if not floor_map:
                app.logger.warning(f"Floor map ID {floor_map_id_data} not found for resource {resource_id}.")
                return jsonify({'error': 'Floor map not found.'}), 404
            resource.floor_map_id = floor_map_id_data

            if not coordinates_data or not isinstance(coordinates_data, dict):
                app.logger.warning(f"Missing or invalid coordinates for resource {resource_id} when floor_map_id is {floor_map_id_data}.")
                return jsonify({'error': 'Missing or invalid coordinates data when floor_map_id is provided.'}), 400
            
            if coordinates_data.get('type') == 'rect':
                required_coords = ['x', 'y', 'width', 'height']
                if not all(k in coordinates_data and isinstance(coordinates_data[k], (int, float)) for k in required_coords):
                    app.logger.warning(f"Invalid rect coordinates for resource {resource_id}: {coordinates_data}")
                    return jsonify({'error': 'Rect coordinates require numeric x, y, width, height.'}), 400
                resource.map_coordinates = json.dumps(coordinates_data)
            else:
                app.logger.warning(f"Invalid coordinates type for resource {resource_id}: {coordinates_data.get('type')}")
                return jsonify({'error': "Invalid coordinates type. Only 'rect' is supported."}), 400
        else: # floor_map_id is explicitly set to null (or empty string handled by frontend)
            resource.floor_map_id = None
            resource.map_coordinates = None
    
    try:
        db.session.commit()
        app.logger.info(f"Successfully updated map/permission info for resource ID {resource.id} by user {current_user.username}.")
        updated_resource_data = {
            'id': resource.id, 'name': resource.name,
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
            'booking_restriction': resource.booking_restriction, 'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'allowed_user_ids': resource.allowed_user_ids, 'allowed_roles': resource.allowed_roles,
            'capacity': resource.capacity, 'equipment': resource.equipment
        }
        return jsonify(updated_resource_data), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error committing update_resource_map_info for resource {resource_id}:")
        return jsonify({'error': 'Failed to update resource due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/publish', methods=['POST'])
@login_required
def publish_resource(resource_id):
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to publish resource {resource_id}.")
        return jsonify({'error': 'Admin access required.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to publish non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.status == 'published':
        app.logger.info(f"Resource {resource_id} is already published. No action taken.")
        return jsonify({'message': 'Resource is already published.', 
                        'resource': {
                            'id': resource.id, 'name': resource.name, 'status': resource.status, 
                            'published_at': resource.published_at.isoformat() if resource.published_at else None
                        }}), 200
    
    if resource.status != 'draft':
        app.logger.warning(f"Attempt to publish resource {resource_id} from invalid status: {resource.status}")
        return jsonify({'error': f'Resource cannot be published from status: {resource.status}. Must be a draft.'}), 400

    try:
        resource.status = 'published'
        resource.published_at = datetime.utcnow()
        db.session.commit()
        app.logger.info(f"Resource {resource_id} ('{resource.name}') published successfully by {current_user.username}.")
        updated_resource_data = {
            'id': resource.id, 'name': resource.name, 'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'booking_restriction': resource.booking_restriction, 'capacity': resource.capacity,
            'equipment': resource.equipment, 'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None
        }
        return jsonify({'message': 'Resource published successfully.', 'resource': updated_resource_data}), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error publishing resource {resource_id}:")
        return jsonify({'error': 'Failed to publish resource due to a server error.'}), 500

@app.route('/api/admin/users', methods=['GET'])
@login_required
def get_all_users():
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to get all users.")
        return jsonify({'error': 'Admin access required.'}), 403

    try:
        users = User.query.all()
        users_list = [{'id': u.id, 'username': u.username, 'email': u.email, 'is_admin': u.is_admin} for u in users]
        app.logger.info(f"Admin user {current_user.username} fetched all users list.")
        return jsonify(users_list), 200
    except Exception as e:
        app.logger.exception("Error fetching all users:")
        return jsonify({'error': 'Failed to fetch users due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['DELETE'])
@login_required
def delete_resource_map_info(resource_id):
    if not current_user.is_admin:
        app.logger.warning(f"Non-admin user {current_user.username} attempted to delete map info for resource {resource_id}.")
        return jsonify({'error': 'Admin access required.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Attempt to delete map info for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.floor_map_id is None and resource.map_coordinates is None:
        app.logger.info(f"Resource {resource_id} is not mapped. No action taken for map info deletion.")
        return jsonify({'message': 'Resource is not currently mapped. No changes made.'}), 200 

    try:
        resource.floor_map_id = None
        resource.map_coordinates = None
        db.session.commit()
        app.logger.info(f"Map information for resource ID {resource_id} deleted by {current_user.username}.")
        return jsonify({'message': f'Map information for resource ID {resource_id} has been deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error deleting map info for resource {resource_id}:")
        return jsonify({'error': 'Failed to delete map information due to a server error.'}), 500

@app.route('/api/map_details/<int:map_id>', methods=['GET'])
def get_map_details(map_id):
    date_str = request.args.get('date')
    target_date_obj = None

    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.warning(f"Invalid date format for map details: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        floor_map = FloorMap.query.get(map_id)
        if not floor_map:
            app.logger.warning(f"Map details requested for non-existent map ID: {map_id}")
            return jsonify({'error': 'Floor map not found.'}), 404

        map_details_response = {
            'id': floor_map.id,
            'name': floor_map.name,
            'image_url': url_for('static', filename=f'floor_map_uploads/{floor_map.image_filename}')
        }
        
        # Ensure only published resources are shown on the public map view
        mapped_resources_query = Resource.query.filter(
            Resource.floor_map_id == map_id,
            Resource.map_coordinates.isnot(None),
            Resource.status == 'published' 
        ).all()

        mapped_resources_list = []
        for resource in mapped_resources_query:
            bookings_on_date = Booking.query.filter(
                Booking.resource_id == resource.id,
                func.date(Booking.start_time) == target_date_obj
            ).all()
            bookings_info = [{'title': b.title, 'user_name': b.user_name, 
                              'start_time': b.start_time.strftime('%H:%M:%S'), 
                              'end_time': b.end_time.strftime('%H:%M:%S')} for b in bookings_on_date]
            
            resource_info = {
                'id': resource.id, 'name': resource.name, 'capacity': resource.capacity,
                'equipment': resource.equipment,
                'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
                'booking_restriction': resource.booking_restriction, 'status': resource.status,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids, 'allowed_roles': resource.allowed_roles,
                'bookings_on_date': bookings_info
            }
            mapped_resources_list.append(resource_info)
        
        app.logger.info(f"Successfully fetched map details for map ID {map_id} for date {target_date_obj}.")
        return jsonify({
            'map_details': map_details_response,
            'mapped_resources': mapped_resources_list
        }), 200

    except Exception as e:
        app.logger.exception(f"Error fetching map details for map_id {map_id}:")
        return jsonify({'error': 'Failed to fetch map details due to a server error.'}), 500

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        app.logger.warning("Login attempt with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        app.logger.warning("Login attempt with missing username or password.")
        return jsonify({'error': 'Username and password are required.'}), 400

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        login_user(user)
        user_data = {'id': user.id, 'username': user.username, 'email': user.email, 'is_admin': user.is_admin}
        app.logger.info(f"User '{username}' logged in successfully.")
        return jsonify({'success': True, 'message': 'Login successful.', 'user': user_data}), 200
    else:
        app.logger.warning(f"Invalid login attempt for username: {username}")
        return jsonify({'error': 'Invalid username or password.'}), 401

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def api_logout():
    user_identifier = current_user.username if current_user else "Unknown user"
    try:
        logout_user()
        app.logger.info(f"User '{user_identifier}' logged out successfully.")
        return jsonify({'success': True, 'message': 'Logout successful.'}), 200
    except Exception as e:
        app.logger.exception(f"Error during logout for user {user_identifier}:")
        return jsonify({'error': 'Logout failed due to a server error.'}), 500

@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    if current_user.is_authenticated:
        user_data = {
            'id': current_user.id, 'username': current_user.username, 
            'email': current_user.email, 'is_admin': current_user.is_admin
        }
        # app.logger.debug(f"Auth status check: User '{current_user.username}' is logged in.") # Too verbose for INFO
        return jsonify({'logged_in': True, 'user': user_data}), 200
    else:
        # app.logger.debug("Auth status check: No user logged in.") # Too verbose for INFO
        return jsonify({'logged_in': False}), 200

@app.route('/api/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.get_json()

    if not data:
        app.logger.warning(f"Booking attempt by {current_user.username} with no JSON data.")
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource_id = data.get('resource_id')
    date_str = data.get('date_str')
    start_time_str = data.get('start_time_str')
    end_time_str = data.get('end_time_str')
    title = data.get('title')
    user_name_for_record = data.get('user_name') 

    required_fields = {'resource_id': resource_id, 'date_str': date_str, 
                       'start_time_str': start_time_str, 'end_time_str': end_time_str}
    missing_fields = [field for field, value in required_fields.items() if value is None]
    if missing_fields:
        app.logger.warning(f"Booking attempt by {current_user.username} missing fields: {', '.join(missing_fields)}")
        return jsonify({'error': f'Missing required field(s): {", ".join(missing_fields)}'}), 400
    
    if not user_name_for_record: # Though logged_in, ensure user_name for record is present
        app.logger.warning(f"Booking attempt by {current_user.username} missing user_name_for_record in payload.")
        return jsonify({'error': 'user_name for the booking record is required in payload.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        app.logger.warning(f"Booking attempt by {current_user.username} for non-existent resource ID: {resource_id}")
        return jsonify({'error': 'Resource not found.'}), 404

    # Permission Enforcement Logic
    can_book = False # Initialize to False
    app.logger.debug(f"Checking booking permissions for user '{current_user.username}' on resource ID {resource_id} ('{resource.name}'). Resource booking_restriction: '{resource.booking_restriction}'.")
    
    if resource.booking_restriction == 'admin_only':
        if current_user.is_admin:
            app.logger.debug(f"Booking permitted: Admin user '{current_user.username}' on admin-only resource {resource_id}.")
            can_book = True
        else:
            app.logger.warning(f"Booking denied: Non-admin user '{current_user.username}' attempted to book admin-only resource {resource_id}.")
            return jsonify({'error': 'Admin access required to book this resource.'}), 403
    else: # Not 'admin_only', or restriction is None/'all_users' (effectively)
        current_user_role = 'admin' if current_user.is_admin else 'standard_user'
        has_user_id_restriction = resource.allowed_user_ids and resource.allowed_user_ids.strip()
        has_role_restriction = resource.allowed_roles and resource.allowed_roles.strip()

        if not has_user_id_restriction and not has_role_restriction:
            # If booking_restriction is 'all_users' or None (meaning generally available to authenticated users)
            app.logger.debug(f"Booking permitted: Resource {resource_id} has no specific user/role list restrictions. User '{current_user.username}' can book.")
            can_book = True # Authenticated users can book if no other restrictions
        else:
            # Granular checks if lists are present
            if has_user_id_restriction:
                allowed_ids_list = {int(uid.strip()) for uid in resource.allowed_user_ids.split(',') if uid.strip()}
                if current_user.id in allowed_ids_list:
                    app.logger.debug(f"Booking permitted: User '{current_user.username}' (ID: {current_user.id}) is in allowed_user_ids for resource {resource_id}.")
                    can_book = True
            
            if not can_book and has_role_restriction: # Only check roles if not already permitted by user ID
                allowed_roles_list = {role.strip().lower() for role in resource.allowed_roles.split(',') if role.strip()}
                if current_user_role in allowed_roles_list:
                    app.logger.debug(f"Booking permitted: User '{current_user.username}' (Role: {current_user_role}) is in allowed_roles for resource {resource_id}.")
                    can_book = True
            
            if not can_book: 
                app.logger.warning(f"Booking denied: User '{current_user.username}' does not meet specific user/role restrictions for resource {resource_id}. Allowed User IDs: '{resource.allowed_user_ids}', Allowed Roles: '{resource.allowed_roles}'.")
                return jsonify({'error': 'You are not authorized to book this specific resource based on its user/role restrictions.'}), 403
    
    if not can_book: # This should ideally not be reached if logic above is exhaustive
         app.logger.error(f"Booking permission logic fallthrough: User '{current_user.username}', Resource ID {resource_id}. Denying booking as a safeguard.")
         return jsonify({'error': 'Booking permission denied due to an unexpected authorization state.'}), 403

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_h, start_m = map(int, start_time_str.split(':'))
        end_h, end_m = map(int, end_time_str.split(':'))
        new_booking_start_time = datetime.combine(booking_date, time(start_h, start_m))
        new_booking_end_time = datetime.combine(booking_date, time(end_h, end_m))
        if new_booking_end_time <= new_booking_start_time:
            app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid time range: {start_time_str} - {end_time_str}")
            return jsonify({'error': 'End time must be after start time.'}), 400
    except ValueError:
        app.logger.warning(f"Booking attempt by {current_user.username} for resource {resource_id} with invalid date/time format: {date_str} {start_time_str}-{end_time_str}")
        return jsonify({'error': 'Invalid date or time format.'}), 400
    
    conflicting_booking = Booking.query.filter(
        Booking.resource_id == resource_id,
        Booking.start_time < new_booking_end_time,
        Booking.end_time > new_booking_start_time
    ).first()

    if conflicting_booking:
        app.logger.info(f"Booking conflict for user {current_user.username}, resource {resource_id} at {new_booking_start_time}-{new_booking_end_time}.")
        return jsonify({'error': 'This time slot is no longer available. Please try another slot.'}), 409 # Conflict

    try:
        new_booking = Booking(resource_id=resource_id, start_time=new_booking_start_time,
                              end_time=new_booking_end_time, title=title, user_name=user_name_for_record)
        db.session.add(new_booking)
        db.session.commit()
        app.logger.info(f"Booking ID {new_booking.id} created for resource {resource_id} by user {current_user.username} (record user: {user_name_for_record}).")
        created_booking_data = {
            'id': new_booking.id, 'resource_id': new_booking.resource_id, 'title': new_booking.title,
            'user_name': new_booking.user_name, 
            'start_time': new_booking.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': new_booking.end_time.strftime('%Y-%m-%d %H:%M:%S')
        }
        return jsonify(created_booking_data), 201
        
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error creating booking for resource {resource_id} by {current_user.username}:")
        return jsonify({'error': 'Failed to create booking due to a server error.'}), 500

if __name__ == "__main__":
    # To initialize the DB, you can uncomment the next line and run 'python app.py' once.
    # Then comment it out again to prevent re-initialization on every run.
    # init_db() # Call this directly only for the very first setup
    app.logger.info("Flask app starting...")
    app.run(debug=True)
