from flask import Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from datetime import timezone

# Assuming these paths are correct relative to how the app is structured.
from auth import permission_required
from extensions import db
from models import WaitlistEntry, User, Resource
from utils import add_audit_log

api_waitlist_bp = Blueprint('api_waitlist', __name__, url_prefix='/api/admin/waitlist')

@api_waitlist_bp.route('', methods=['GET'])
@login_required
@permission_required('manage_bookings') # Or a more specific 'manage_waitlist'
def get_waitlist_entries():
    """Fetches all waitlist entries with associated user and resource info."""
    try:
        entries = db.session.query(
            WaitlistEntry, User.username, Resource.name
        ).join(User, WaitlistEntry.user_id == User.id)\
         .join(Resource, WaitlistEntry.resource_id == Resource.id)\
         .order_by(WaitlistEntry.timestamp.asc()).all()

        waitlist_data = []
        for entry, username, resource_name in entries:
            waitlist_data.append({
                'id': entry.id,
                'resource_id': entry.resource_id,
                'resource_name': resource_name,
                'user_id': entry.user_id,
                'username': username,
                'timestamp': entry.timestamp.replace(tzinfo=timezone.utc).isoformat()
            })
        current_app.logger.info(f"User {current_user.username} fetched all waitlist entries.")
        return jsonify(waitlist_data), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching waitlist entries by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch waitlist entries due to a server error.'}), 500

@api_waitlist_bp.route('/<int:entry_id>', methods=['DELETE'])
@login_required
@permission_required('manage_bookings') # Or 'manage_waitlist'
def delete_waitlist_entry_admin(entry_id):
    """Admin deletes a waitlist entry."""
    entry = db.session.get(WaitlistEntry, entry_id)
    if not entry:
        current_app.logger.warning(f"Admin {current_user.username} failed to delete non-existent waitlist entry ID: {entry_id}")
        return jsonify({'error': 'Waitlist entry not found.'}), 404
    try:
        resource_name = entry.resource.name # For logging
        user_name = entry.user.username # For logging
        db.session.delete(entry)
        db.session.commit()
        # No specific audit log for this simple admin action in original, but could be added:
        add_audit_log(action="ADMIN_DELETE_WAITLIST_ENTRY", details=f"Admin {current_user.username} deleted waitlist entry ID {entry_id} (User: {user_name}, Resource: {resource_name}).", user_id=current_user.id)
        current_app.logger.info(f"Admin {current_user.username} deleted waitlist entry ID {entry_id} (User: {user_name}, Resource: {resource_name}).")
        return jsonify({'message': 'Waitlist entry deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting waitlist entry ID {entry_id} by admin {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete waitlist entry due to server error.'}), 500

def init_api_waitlist_routes(app):
    app.register_blueprint(api_waitlist_bp)
