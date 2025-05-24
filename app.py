from flask import Flask, jsonify, render_template, request, url_for, redirect # Added redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func # Add this
from datetime import datetime, date, timedelta, time # Ensure all are here
import os
import json # For serializing coordinates
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # For User model and init_db
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

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

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(DATA_DIR, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # silence the warning

db = SQLAlchemy(app)

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

# Function to initialize the database
def init_db():
    with app.app_context(): # Create an application context
        print("Initializing the database...")
        
        # Delete existing data in reverse order of creation (bookings depend on resources)
        # or more simply, respecting foreign key constraints
        print("Deleting existing bookings...")
        num_bookings_deleted = db.session.query(Booking).delete()
        print(f"Deleted {num_bookings_deleted} bookings.")

        print("Deleting existing resources...")
        num_resources_deleted = db.session.query(Resource).delete()
        print(f"Deleted {num_resources_deleted} resources.")
        
        print("Deleting existing users...") # New
        num_users_deleted = db.session.query(User).delete()     # New
        print(f"Deleted {num_users_deleted} users.")
            
        print("Deleting existing floor maps...") # Moved FloorMap deletion after Resource
        num_floormaps_deleted = db.session.query(FloorMap).delete()
        print(f"Deleted {num_floormaps_deleted} floor maps.")
        
        db.session.commit() # Commit deletions
        print("Existing data deleted.")

        print("Creating database tables...")
        db.create_all() # Ensure tables are created (safe to call multiple times)
        print("Database tables created/verified.")
        
        # Add sample FloorMaps (if you decide to have defaults, otherwise admin uploads)
        # ... (no sample FloorMaps for now) ...

        # Add sample Users
        print("Adding default users...")
        try:
            default_users = [
                User(username='admin', email='admin@example.com', 
                     password_hash=generate_password_hash('adminpass', method='pbkdf2:sha256'), 
                     is_admin=True),
                User(username='user', email='user@example.com', 
                     password_hash=generate_password_hash('userpass', method='pbkdf2:sha256'), 
                     is_admin=False)
            ]
            db.session.bulk_save_objects(default_users)
            db.session.commit()
            print(f"{len(default_users)} default users added (admin/adminpass, user/userpass).")
        except Exception as e:
            db.session.rollback()
            print(f"Error adding default users: {e}")


        # Add sample resources (after users/floormaps if they had FKs to them)
        
        # Fetch default user IDs for more robust sample data
        admin_user_for_perms = User.query.filter_by(username='admin').first()
        standard_user_for_perms = User.query.filter_by(username='user').first()
        
        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1" # Fallback to "1"
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2" # Fallback to "2"

        print("Adding sample resources with granular permissions...") # Updated log message
        try: 
            sample_resources = [
                Resource(name="Conference Room Alpha", capacity=10, equipment="Projector,Whiteboard,Teleconference", 
                         booking_restriction=None, status='published', published_at=datetime.utcnow(),
                         allowed_user_ids=None, allowed_roles=None), # No specific granular restriction
                Resource(name="Meeting Room Beta", capacity=6, equipment="Teleconference,Whiteboard", 
                         booking_restriction='all_users', status='published', published_at=datetime.utcnow(),
                         allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}", allowed_roles=None), # Restricted to specific users
                Resource(name="Focus Room Gamma", capacity=2, equipment="Whiteboard", 
                         booking_restriction='admin_only', status='draft', published_at=None,
                         allowed_user_ids=None, allowed_roles='admin'), # Redundant with admin_only but shows field usage
                Resource(name="Quiet Pod Delta", capacity=1, equipment=None, 
                         booking_restriction=None, status='draft', published_at=None,
                         allowed_user_ids=None, allowed_roles='standard_user,admin'), # All roles can book this draft
                Resource(name="Archived Room Omega", capacity=5, equipment="Old Projector",
                         booking_restriction=None, status='archived', published_at=datetime.utcnow() - timedelta(days=30),
                         allowed_user_ids=None, allowed_roles=None)
            ]
            db.session.bulk_save_objects(sample_resources)
            db.session.commit()
            print(f"{len(sample_resources)} sample resources added with granular permissions.")
        except Exception as e:
            db.session.rollback()
            print(f"Error adding sample resources with granular permissions: {e}")

        # Add sample bookings (after resources)
        print("Adding sample bookings...")
        resource_alpha = Resource.query.filter_by(name="Conference Room Alpha").first()
        resource_beta = Resource.query.filter_by(name="Meeting Room Beta").first()

        if resource_alpha and resource_beta:
            today = date.today()
            sample_bookings = [
                Booking(resource_id=resource_alpha.id, user_name="user1", title="Team Sync Alpha", 
                        start_time=datetime.combine(today, time(9, 0)), 
                        end_time=datetime.combine(today, time(10, 0))),
                Booking(resource_id=resource_alpha.id, user_name="user2", title="Client Meeting", 
                        start_time=datetime.combine(today, time(11, 0)), 
                        end_time=datetime.combine(today, time(12, 30))),
                Booking(resource_id=resource_alpha.id, user_name="user1", title="Project Update Alpha", 
                        start_time=datetime.combine(today + timedelta(days=1), time(14, 0)), 
                        end_time=datetime.combine(today + timedelta(days=1), time(15, 0))),
                Booking(resource_id=resource_beta.id, user_name="user3", title="Quick Chat Beta", 
                        start_time=datetime.combine(today, time(10, 0)), 
                        end_time=datetime.combine(today, time(10, 30))),
                Booking(resource_id=resource_beta.id, user_name="user1", title="Planning Session Beta", 
                        start_time=datetime.combine(today, time(14, 0)), 
                        end_time=datetime.combine(today, time(16, 0))),
            ]
            db.session.bulk_save_objects(sample_bookings)
            db.session.commit()
            print(f"{len(sample_bookings)} sample bookings added.")
        else:
            print("Could not find sample resources to create bookings for after attempting to add them. Skipping sample booking addition.")
        # else:
        #    print("Bookings table was not empty after deletions, this is unexpected. Skipping sample booking addition.")
        
        print("Database initialization script completed successfully.")

@app.route("/api/resources", methods=['GET'])
def get_resources():
    try:
        # Filter resources by status
        resources_query = Resource.query.filter_by(status='published').all() # MODIFIED HERE
            
        resources_list = []
        for resource in resources_query: # Use the filtered query
            resources_list.append({
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity,
            'equipment': resource.equipment,
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': resource.map_coordinates,
            'booking_restriction': resource.booking_restriction,
            'status': resource.status, 
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'allowed_user_ids': resource.allowed_user_ids, # Added
            'allowed_roles': resource.allowed_roles       # Added
            # 'floor_map_name': resource.floor_map.name if resource.floor_map else None # Example if joining
            })
        return jsonify(resources_list), 200
    except Exception as e:
        # Log the error e for debugging
        print(f"Error fetching resources: {e}") # simple print for now
        return jsonify({'error': 'Failed to fetch resources'}), 500

@app.route('/api/resources/<int:resource_id>/availability', methods=['GET'])
def get_resource_availability(resource_id):
    # Get the date from query parameters, default to today if not provided
    date_str = request.args.get('date')
    
    target_date_obj = None
    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        # First, check if the resource exists
        resource = Resource.query.get(resource_id)
        if not resource:
            return jsonify({'error': 'Resource not found'}), 404

        # Query for bookings for the given resource_id and date
        # We need to compare the date part of Booking.start_time with target_date_obj
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
        # Log the error e for debugging
        print(f"Error fetching availability for resource {resource_id} on {target_date_obj}: {e}") # simple print
        return jsonify({'error': 'Failed to fetch resource availability'}), 500

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/admin/maps', methods=['POST'])
@login_required
def upload_floor_map():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required.'}), 403 # Forbidden

    if 'map_image' not in request.files:
        return jsonify({'error': 'No map_image file part in the request'}), 400
    
    file = request.files['map_image']
    map_name = request.form.get('map_name')

    if not map_name:
        return jsonify({'error': 'map_name is required'}), 400
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        if FloorMap.query.filter_by(image_filename=filename).first() or \
           FloorMap.query.filter_by(name=map_name).first():
            return jsonify({'error': 'A map with this name or image filename already exists.'}), 409

        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            new_map = FloorMap(name=map_name, image_filename=filename)
            db.session.add(new_map)
            db.session.commit()

            return jsonify({
                'id': new_map.id,
                'name': new_map.name,
                'image_filename': new_map.image_filename,
                'image_url': url_for('static', filename=f'floor_map_uploads/{new_map.image_filename}')
            }), 201
        except Exception as e:
            db.session.rollback()
            # if os.path.exists(file_path): os.remove(file_path) # Potentially delete saved file
            print(f"Error uploading floor map: {e}")
            return jsonify({'error': f'Failed to upload map: {str(e)}'}), 500 # Return string of e
    else:
        return jsonify({'error': 'File type not allowed.'}), 400

@app.route('/api/admin/maps', methods=['GET'])
@login_required
def get_floor_maps():
    if not current_user.is_admin:
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
        return jsonify(maps_list), 200
    except Exception as e:
        print(f"Error fetching floor maps: {e}")
        return jsonify({'error': 'Failed to fetch maps'}), 500

@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['PUT'])
@login_required 
def update_resource_map_info(resource_id):
    if not current_user.is_admin: 
        return jsonify({'error': 'Admin access required.'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404

    # Process booking_restriction
    if 'booking_restriction' in data:
        booking_restriction_data = data.get('booking_restriction')
        allowed_restrictions = ['admin_only', 'all_users', None, ""] # "" will be treated as None
        if booking_restriction_data not in allowed_restrictions: 
            return jsonify({'error': f'Invalid booking_restriction value. Allowed: {allowed_restrictions}. Received: {booking_restriction_data}'}), 400
        resource.booking_restriction = booking_restriction_data if booking_restriction_data != "" else None

    # Process allowed_user_ids
    if 'allowed_user_ids' in data:
        user_ids_list = data.get('allowed_user_ids')
        if user_ids_list is None:
            resource.allowed_user_ids = None
        elif isinstance(user_ids_list, list) and all(isinstance(uid, int) for uid in user_ids_list):
            resource.allowed_user_ids = ",".join(map(str, sorted(list(set(user_ids_list))))) if user_ids_list else None
        else:
            return jsonify({'error': 'Invalid allowed_user_ids format. Expected a list of integers or null.'}), 400

    # Process allowed_roles
    if 'allowed_roles' in data:
        roles_list = data.get('allowed_roles')
        if roles_list is None:
            resource.allowed_roles = None
        elif isinstance(roles_list, list) and all(isinstance(role, str) for role in roles_list):
            valid_roles = [role.strip().lower() for role in roles_list if role.strip()]
            resource.allowed_roles = ",".join(sorted(list(set(valid_roles)))) if valid_roles else None
        else:
            return jsonify({'error': 'Invalid allowed_roles format. Expected a list of strings or null.'}), 400

    # Logic for map and coordinates
    if 'floor_map_id' in data: 
        floor_map_id_data = data.get('floor_map_id')
        coordinates_data = data.get('coordinates')

        if floor_map_id_data is not None: 
            floor_map = FloorMap.query.get(floor_map_id_data)
            if not floor_map:
                return jsonify({'error': 'Floor map not found.'}), 404
            resource.floor_map_id = floor_map_id_data

            if not coordinates_data or not isinstance(coordinates_data, dict):
                return jsonify({'error': 'Missing or invalid coordinates data when floor_map_id is provided.'}), 400
            
            if coordinates_data.get('type') == 'rect':
                required_coords = ['x', 'y', 'width', 'height']
                for k in required_coords:
                    if k not in coordinates_data or not isinstance(coordinates_data[k], (int, float)):
                        return jsonify({'error': f'Missing or invalid coordinate: {k}'}), 400
                resource.map_coordinates = json.dumps(coordinates_data)
            else:
                return jsonify({'error': "Invalid coordinates type. Only 'rect' is supported."}), 400
        else: 
            resource.floor_map_id = None
            resource.map_coordinates = None
    
    try:
        db.session.commit()

        updated_resource_data = {
            'id': resource.id,
            'name': resource.name,
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
            'booking_restriction': resource.booking_restriction,
            'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'allowed_user_ids': resource.allowed_user_ids, # Added
            'allowed_roles': resource.allowed_roles,       # Added
            'capacity': resource.capacity, 
            'equipment': resource.equipment
        }
        return jsonify(updated_resource_data), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating resource map/permission info: {e}")
        return jsonify({'error': 'Failed to update resource due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/publish', methods=['POST'])
@login_required
def publish_resource(resource_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.status == 'published':
        return jsonify({'message': 'Resource is already published.', 
                        'resource': { # Return current state
                            'id': resource.id, 'name': resource.name, 
                            'status': resource.status, 
                            'published_at': resource.published_at.isoformat() if resource.published_at else None
                        }}), 200 # OK, but no change needed
    
    if resource.status != 'draft':
        return jsonify({'error': f'Resource cannot be published directly from status: {resource.status}. Must be a draft.'}), 400

    try:
        resource.status = 'published'
        resource.published_at = datetime.utcnow()
        db.session.commit()

        # Prepare response data for the updated resource
        updated_resource_data = {
            'id': resource.id,
            'name': resource.name,
            'status': resource.status,
            'published_at': resource.published_at.isoformat() if resource.published_at else None,
            'booking_restriction': resource.booking_restriction, # Include other key fields
            'capacity': resource.capacity,
            'equipment': resource.equipment,
            'floor_map_id': resource.floor_map_id,
            'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None
        }
        return jsonify({'message': 'Resource published successfully.', 'resource': updated_resource_data}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error publishing resource {resource_id}: {e}") # Server-side log
        return jsonify({'error': 'Failed to publish resource due to a server error.'}), 500

@app.route('/api/admin/users', methods=['GET'])
@login_required
def get_all_users():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required.'}), 403

    try:
        users = User.query.all()
        users_list = []
        for user in users:
            users_list.append({
                'id': user.id,
                'username': user.username,
                'email': user.email, 
                'is_admin': user.is_admin
            })
        return jsonify(users_list), 200
    except Exception as e:
        print(f"Error fetching all users: {e}") # Server-side log
        return jsonify({'error': 'Failed to fetch users due to a server error.'}), 500

@app.route('/api/admin/resources/<int:resource_id>/map_info', methods=['DELETE'])
@login_required
def delete_resource_map_info(resource_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required.'}), 403

    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404

    if resource.floor_map_id is None and resource.map_coordinates is None:
        return jsonify({'message': 'Resource is not currently mapped.'}), 200 

    try:
        resource.floor_map_id = None
        resource.map_coordinates = None
        db.session.commit()
        return jsonify({'message': f'Map information for resource ID {resource_id} has been deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting map info for resource {resource_id}: {e}") # Server-side log
        return jsonify({'error': 'Failed to delete map information due to a server error.'}), 500

@app.route('/api/map_details/<int:map_id>', methods=['GET'])
def get_map_details(map_id):
    date_str = request.args.get('date')
    target_date_obj = None

    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        floor_map = FloorMap.query.get(map_id)
        if not floor_map:
            return jsonify({'error': 'Floor map not found.'}), 404

        map_details_response = {
            'id': floor_map.id,
            'name': floor_map.name,
            'image_url': url_for('static', filename=f'floor_map_uploads/{floor_map.image_filename}')
        }

        # Fetch resources associated with this map that have coordinates AND are published
        mapped_resources_query = Resource.query.filter(
            Resource.floor_map_id == map_id,
            Resource.map_coordinates.isnot(None),
            Resource.status == 'published' # MODIFIED HERE
        ).all()

        mapped_resources_list = []
        for resource in mapped_resources_query:
            # Fetch bookings for this resource on the target date
            bookings_on_date = Booking.query.filter(
                Booking.resource_id == resource.id,
                func.date(Booking.start_time) == target_date_obj
            ).all()

            bookings_info = []
            for booking in bookings_on_date:
                bookings_info.append({
                    'title': booking.title,
                    'user_name': booking.user_name,
                    'start_time': booking.start_time.strftime('%H:%M:%S'),
                    'end_time': booking.end_time.strftime('%H:%M:%S')
                })
            
            resource_info = {
                'id': resource.id,
                'name': resource.name,
                'capacity': resource.capacity, # Optional: include other details
                'equipment': resource.equipment, # Optional
                'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None, # Deserialize
            'booking_restriction': resource.booking_restriction, 
            'status': resource.status, 
            'published_at': resource.published_at.isoformat() if resource.published_at else None, 
            'allowed_user_ids': resource.allowed_user_ids, # Added
            'allowed_roles': resource.allowed_roles,       # Added
                'bookings_on_date': bookings_info
            }
            mapped_resources_list.append(resource_info)
        
        return jsonify({
            'map_details': map_details_response,
            'mapped_resources': mapped_resources_list
        }), 200

    except Exception as e:
        print(f"Error fetching map details for map_id {map_id}: {e}") # Log for server admin
        return jsonify({'error': 'Failed to fetch map details due to a server error.'}), 500

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        # Log the user in using Flask-Login's login_user function
        login_user(user) # Flask-Login handles setting the session cookie
        
        # Prepare user data for the response (do not send password_hash)
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_admin': user.is_admin
        }
        return jsonify({'success': True, 'message': 'Login successful.', 'user': user_data}), 200
    else:
        # Invalid credentials
        return jsonify({'error': 'Invalid username or password.'}), 401 # Unauthorized

@app.route('/api/auth/logout', methods=['POST'])
@login_required # Ensures only logged-in users can access this endpoint
def api_logout():
    try:
        logout_user() # Flask-Login handles clearing the session
        return jsonify({'success': True, 'message': 'Logout successful.'}), 200
    except Exception as e:
        # This is a general catch, logout_user() itself rarely fails if session handling is ok
        print(f"Error during logout: {e}")
        return jsonify({'error': 'Logout failed due to a server error.'}), 500

@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    if current_user.is_authenticated:
        # User is logged in, provide user details
        user_data = {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'is_admin': current_user.is_admin
        }
        return jsonify({'logged_in': True, 'user': user_data}), 200
    else:
        # User is not logged in
        return jsonify({'logged_in': False}), 200

@app.route('/api/bookings', methods=['POST'])
@login_required # Ensures user is logged in before attempting to book anything
def create_booking():
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    # Extract data from request
    resource_id = data.get('resource_id')
    date_str = data.get('date_str')            # Expected 'YYYY-MM-DD'
    start_time_str = data.get('start_time_str')  # Expected 'HH:MM'
    end_time_str = data.get('end_time_str')    # Expected 'HH:MM'
    title = data.get('title')
    # user_name from payload is used for the booking record's user_name field.
    # For permission checking, current_user (from Flask-Login) is used.
    user_name_for_record = data.get('user_name') 

    # Basic validation for presence of required fields
    required_fields = {'resource_id': resource_id, 'date_str': date_str, 
                       'start_time_str': start_time_str, 'end_time_str': end_time_str}
    for field, value in required_fields.items():
        if value is None: 
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # Note: The user_name_for_record can be different from current_user.username
    # For this mock, we allow it, but in a real app, you might want to enforce
    # that user_name_for_record is current_user.username or handle it based on roles.
    if not user_name_for_record: # Still require some user identifier for the booking record
        return jsonify({'error': 'user_name for the booking record is required.'}), 400


    # Check if resource exists
    resource = Resource.query.get(resource_id)
    if not resource:
        return jsonify({'error': 'Resource not found.'}), 404

    # Permission Enforcement Logic
    can_book = False
    if resource.booking_restriction == 'admin_only':
        if current_user.is_admin:
            can_book = True
        else:
            return jsonify({'error': 'Admin access required to book this resource.'}), 403
    else:
        # Not 'admin_only', so check granular permissions if they exist.
        # If no granular permissions, any authenticated user can book (due to @login_required).
        
        current_user_role = 'admin' if current_user.is_admin else 'standard_user'

        has_user_id_restriction = resource.allowed_user_ids and resource.allowed_user_ids.strip()
        has_role_restriction = resource.allowed_roles and resource.allowed_roles.strip()

        if not has_user_id_restriction and not has_role_restriction:
            # No specific user or role restrictions, and not admin_only, so any authenticated user can book.
            can_book = True
        else:
            # Granular restrictions exist. User must satisfy AT LEAST ONE.
            if has_user_id_restriction:
                allowed_ids = {int(uid.strip()) for uid in resource.allowed_user_ids.split(',') if uid.strip()}
                if current_user.id in allowed_ids:
                    can_book = True
            
            if not can_book and has_role_restriction: # Only check roles if not already permitted by user ID
                allowed_roles_list = {role.strip().lower() for role in resource.allowed_roles.split(',') if role.strip()}
                if current_user_role in allowed_roles_list:
                    can_book = True
            
            if not can_book: # If after checking specific users and roles, still no permission
                return jsonify({'error': 'You are not authorized to book this specific resource based on user/role restrictions.'}), 403

    if not can_book: # Should have been caught by returns above, but as a final check.
            return jsonify({'error': 'Booking permission denied.'}), 403

    # Convert date and time strings to datetime objects
    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_h, start_m = map(int, start_time_str.split(':'))
        end_h, end_m = map(int, end_time_str.split(':'))

        new_booking_start_time = datetime.combine(booking_date, time(start_h, start_m))
        new_booking_end_time = datetime.combine(booking_date, time(end_h, end_m))

        if new_booking_end_time <= new_booking_start_time:
            return jsonify({'error': 'End time must be after start time.'}), 400

    except ValueError:
        return jsonify({'error': 'Invalid date or time format.'}), 400
    
    # Conflict Check: Ensure the slot is still available
    # An existing booking overlaps if:
    # (existing.start_time < new_booking.end_time) AND (existing.end_time > new_booking.start_time)
    conflicting_booking = Booking.query.filter(
        Booking.resource_id == resource_id,
        Booking.start_time < new_booking_end_time,
        Booking.end_time > new_booking_start_time
    ).first()

    if conflicting_booking:
        return jsonify({'error': 'This time slot is no longer available.'}), 409 # Conflict

    # If all checks pass, create and save the new booking
    try:
        new_booking = Booking(
            resource_id=resource_id,
            start_time=new_booking_start_time,
            end_time=new_booking_end_time,
            title=title,
            user_name=user_name_for_record # Using the extracted user_name from payload for the record
        )
        db.session.add(new_booking)
        db.session.commit()

        # Prepare response data for the created booking
        created_booking_data = {
            'id': new_booking.id,
            'resource_id': new_booking.resource_id,
            'title': new_booking.title,
            'user_name': new_booking.user_name,
            'start_time': new_booking.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': new_booking.end_time.strftime('%Y-%m-%d %H:%M:%S')
        }
        return jsonify(created_booking_data), 201 # Created
        
    except Exception as e:
        db.session.rollback() # Rollback in case of error during commit
        print(f"Error creating booking: {e}") # Log for server admin
        return jsonify({'error': 'Failed to create booking due to a server error.'}), 500

if __name__ == "__main__":
    # To initialize the DB, you can uncomment the next line and run 'python app.py' once.
    # Then comment it out again to prevent re-initialization on every run.
    # init_db() # Call this directly only for the very first setup
    
    app.run(debug=True)
