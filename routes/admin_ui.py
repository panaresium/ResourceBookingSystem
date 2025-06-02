from flask import Blueprint, render_template, current_app, jsonify # Added jsonify
from flask_login import login_required, current_user
from sqlalchemy import func # For analytics_bookings_data if merged here, or general use

# Assuming Booking, Resource, User models are in models.py
from models import Booking, Resource, User
# Assuming db is in extensions.py
from extensions import db
# Assuming permission_required is in auth.py
from auth import permission_required # Corrected: auth.py is at root
from datetime import datetime, timedelta # Add datetime imports

admin_ui_bp = Blueprint('admin_ui', __name__, url_prefix='/admin', template_folder='../templates')

@admin_ui_bp.route('/users_manage')
@login_required
@permission_required('manage_users')
def serve_user_management_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed User Management page.")
    return render_template("user_management.html")

@admin_ui_bp.route('/logs')
@login_required
@permission_required('view_audit_logs')
def serve_audit_log_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed Audit Log page.")
    return render_template("log_view.html")

@admin_ui_bp.route('/maps')
@login_required
@permission_required('manage_floor_maps')
def serve_admin_maps():
    return render_template("admin_maps.html")

@admin_ui_bp.route('/resources_manage')
@login_required
@permission_required('manage_resources')
def serve_resource_management_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed Resource Management page.")
    return render_template("resource_management.html")

@admin_ui_bp.route('/bookings')
@login_required
@permission_required('manage_bookings')
def serve_admin_bookings_page():
    logger = current_app.logger
    logger.info(f"User {current_user.username} accessed Admin Bookings page.")
    try:
        bookings_query = db.session.query(
            Booking.id,
            Booking.title,
            Booking.start_time,
            Booking.end_time,
            Booking.status,
            User.username.label('user_username'),
            Resource.name.label('resource_name')
        ).join(Resource, Booking.resource_id == Resource.id)\
         .join(User, Booking.user_name == User.username) # Ensure User model is imported

        all_bookings = bookings_query.order_by(Booking.start_time.desc()).all()

        bookings_list = []
        for booking_row in all_bookings:
            bookings_list.append({
                'id': booking_row.id,
                'title': booking_row.title,
                'start_time': booking_row.start_time,
                'end_time': booking_row.end_time,
                'status': booking_row.status,
                'user_username': booking_row.user_username,
                'resource_name': booking_row.resource_name
            })
        return render_template("admin_bookings.html", bookings=bookings_list)
    except Exception as e:
        logger.error(f"Error fetching bookings for admin page: {e}", exc_info=True)
        return render_template("admin_bookings.html", bookings=[], error="Could not load bookings.")

@admin_ui_bp.route('/backup_restore')
@login_required
@permission_required('manage_system')
def serve_backup_restore_page():
    current_app.logger.info(f"User {current_user.username} accessed Backup/Restore admin page.")
    return render_template('admin_backup_restore.html')

@admin_ui_bp.route('/analytics/') # Merged from analytics_bp
@login_required
@permission_required('view_analytics')
def analytics_dashboard():
    current_app.logger.info(f"User {current_user.username} accessed analytics dashboard.")
    return render_template('analytics.html')

@admin_ui_bp.route('/analytics/data') # New route for analytics data
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    try:
        current_app.logger.info(f"User {current_user.username} requested analytics bookings data.")

        # Calculate the date 30 days ago
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)

        # Query to get booking counts per resource per day for the last 30 days
        # We need to join Booking with Resource to get the resource name
        # We also need to group by resource name and the date part of start_time
        query_results = db.session.query(
            Resource.name,
            func.date(Booking.start_time).label('booking_date'),
            func.count(Booking.id).label('booking_count')
        ).join(Resource, Booking.resource_id == Resource.id) \
        .filter(func.date(Booking.start_time) >= thirty_days_ago) \
        .group_by(Resource.name, func.date(Booking.start_time)) \
        .order_by(Resource.name, func.date(Booking.start_time)) \
        .all()

        analytics_data = {}
        for resource_name, booking_date_obj, booking_count in query_results:
            booking_date_str = booking_date_obj.strftime('%Y-%m-%d')
            if resource_name not in analytics_data:
                analytics_data[resource_name] = []
            analytics_data[resource_name].append({
                "date": booking_date_str,
                "count": booking_count
            })

        current_app.logger.info(f"Successfully processed analytics data. Resources found: {len(analytics_data)}")
        return jsonify(analytics_data)

    except Exception as e:
        current_app.logger.error(f"Error generating analytics bookings data: {e}", exc_info=True)
        return jsonify({"error": "Could not process analytics data"}), 500

# Function to register this blueprint in the app factory
def init_admin_ui_routes(app):
    app.register_blueprint(admin_ui_bp)
