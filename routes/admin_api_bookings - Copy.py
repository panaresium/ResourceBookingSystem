from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from datetime import timezone # Added timezone

# Assuming extensions.py contains db, mail # socketio removed
from extensions import db, mail # socketio removed
# Assuming models.py contains these model definitions
from models import Booking, User, Resource # Added Resource
# Assuming utils.py contains these helper functions
from utils import add_audit_log, send_email, send_slack_notification # Added other utils as needed
# Assuming auth.py contains permission_required decorator
from auth import permission_required

admin_api_bookings_bp = Blueprint('admin_api_bookings', __name__, url_prefix='/api/admin')

@admin_api_bookings_bp.route('/bookings/pending', methods=['GET'])
@login_required
@permission_required('manage_bookings')
def list_pending_bookings():
    # The @permission_required decorator handles auth and permission.
    pending = Booking.query.filter_by(status='pending').all()
    result = []
    for b in pending:
        result.append({
            'id': b.id,
            'resource_id': b.resource_id,
            'resource_name': b.resource_booked.name if b.resource_booked else None,
            'user_name': b.user_name,
            'start_time': b.start_time.replace(tzinfo=timezone.utc).isoformat(),
            'end_time': b.end_time.replace(tzinfo=timezone.utc).isoformat(),
            'title': b.title,
        })
    return jsonify(result), 200


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/approve', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def approve_booking_admin(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'approved'
    db.session.commit()
    user = User.query.filter_by(username=booking.user_name).first()
    if user and user.email:
        send_email(user.email, 'Booking Approved',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been approved.")
    send_slack_notification(f"Booking {booking.id} approved by {current_user.username}")
    current_app.logger.info(f"Booking {booking.id} approved by admin {current_user.username}.")
    add_audit_log(action="APPROVE_BOOKING_ADMIN", details=f"Admin {current_user.username} approved booking ID {booking.id}.")
    # socketio.emit('booking_updated', {'action': 'approved', 'booking_id': booking.id, 'status': 'approved', 'resource_id': booking.resource_id}) # Removed
    return jsonify({'success': True}), 200


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/reject', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def reject_booking_admin(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != 'pending':
        return jsonify({'error': 'Booking not pending'}), 400
    booking.status = 'rejected'
    db.session.commit()
    user = User.query.filter_by(username=booking.user_name).first()
    if user and user.email:
        send_email(user.email, 'Booking Rejected',
                   f"Your booking for {booking.resource_booked.name if booking.resource_booked else 'resource'} on {booking.start_time.strftime('%Y-%m-%d %H:%M')} has been rejected.")
    send_slack_notification(f"Booking {booking.id} rejected by {current_user.username}")
    current_app.logger.info(f"Booking {booking.id} rejected by admin {current_user.username}.")
    add_audit_log(action="REJECT_BOOKING_ADMIN", details=f"Admin {current_user.username} rejected booking ID {booking.id}.")
    # socketio.emit('booking_updated', {'action': 'rejected', 'booking_id': booking.id, 'status': 'rejected', 'resource_id': booking.resource_id}) # Removed
    return jsonify({'success': True}), 200


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/delete', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_delete_booking(booking_id):
    current_app.logger.info(f"Admin user {current_user.username} attempting to delete booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Admin delete attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        original_status = booking.status
        resource_name = booking.resource_booked.name if booking.resource_booked else "Unknown Resource"
        booking_title = booking.title or "N/A"
        user_name_of_booking = booking.user_name
        resource_id_of_booking = booking.resource_id

        db.session.delete(booking)
        db.session.commit()

        audit_details = (
            f"Admin '{current_user.username}' DELETED booking ID {booking_id}. "
            f"Original status was: '{original_status}'. "
            f"Booked by: '{user_name_of_booking}'. "
            f"Resource: '{resource_name}' (ID: {resource_id_of_booking}). "
            f"Title: '{booking_title}'."
        )
        add_audit_log(action="ADMIN_DELETE_BOOKING", details=audit_details)

        # socketio.emit('booking_updated', { # Removed
        #     'action': 'deleted_by_admin', # Removed
        #     'booking_id': booking_id, # Removed
        #     'resource_id': resource_id_of_booking # Removed
        # }) # Removed

        current_app.logger.info(f"Admin user {current_user.username} successfully DELETED booking ID: {booking_id}.")
        return jsonify({'message': 'Booking deleted successfully by admin.', 'booking_id': booking_id}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during admin deletion of booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_DELETE_BOOKING_FAILED",
            details=f"Admin '{current_user.username}' failed to DELETE booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to delete booking due to a server error.'}), 500


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/cancel_by_admin', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_cancel_booking(booking_id):
    current_app.logger.info(f"Admin user {current_user.username} attempting to cancel booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Admin cancel attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        # Check if the booking can be cancelled
        non_cancellable_statuses = ['completed', 'checked_out', 'rejected', 'cancelled_by_admin', 'cancelled_admin_acknowledged']
        if booking.status in non_cancellable_statuses:
            current_app.logger.warning(
                f"Admin cancel attempt for booking ID {booking_id}: Booking status '{booking.status}' is not cancellable."
            )
            return jsonify({'error': f"Booking is already in a state ('{booking.status}') that cannot be cancelled by admin."}), 400

        data = request.get_json() if request.data else {}
        provided_reason = data.get('reason')

        # Update booking status and admin message
        booking.status = 'cancelled_by_admin'
        if provided_reason and provided_reason.strip():
            booking.admin_deleted_message = provided_reason.strip()
        else:
            booking.admin_deleted_message = None # Ensure it's None if no reason or empty reason is given

        db.session.commit()

        # Audit log
        audit_log_reason = booking.admin_deleted_message if booking.admin_deleted_message else 'N/A'
        audit_details = (
            f"Admin '{current_user.username}' CANCELLED booking ID {booking.id}. "
            f"Reason: '{audit_log_reason}'. "
            f"Booked by: '{booking.user_name}'. "
            f"Resource: '{booking.resource_booked.name if booking.resource_booked else 'Unknown Resource'}' (ID: {booking.resource_id}). "
            f"Title: '{booking.title or 'N/A'}'."
        )
        add_audit_log(action="ADMIN_CANCEL_BOOKING", details=audit_details)

        # SocketIO event # Removed
        # socketio.emit('booking_updated', { # Removed
        #     'action': 'cancelled_by_admin', # Removed
        #     'booking_id': booking.id, # Removed
        #     'resource_id': booking.resource_id, # Removed
        #     'new_status': booking.status, # Removed
        #     'admin_message': booking.admin_deleted_message, # This will be None if no reason was provided # Removed
        #     'user_name': booking.user_name # Removed
        # }) # Removed

        # Notify user
        user = User.query.filter_by(username=booking.user_name).first()
        if user and user.email:
            try:
                email_reason_text = f"Reason: {booking.admin_deleted_message}" if booking.admin_deleted_message else "No specific reason was provided."
                send_email(
                    user.email,
                    'Booking Cancelled by Admin',
                    f"Your booking for '{booking.resource_booked.name if booking.resource_booked else 'resource'}' "
                    f"(ID: {booking.id}, Title: {booking.title or 'N/A'}) "
                    f"from {booking.start_time.strftime('%Y-%m-%d %H:%M')} to {booking.end_time.strftime('%Y-%m-%d %H:%M')} "
                    f"has been cancelled by an administrator. {email_reason_text}"
                )
                current_app.logger.info(f"Cancellation email sent to {user.email} for booking ID {booking.id}.")
            except Exception as e_mail:
                current_app.logger.error(f"Failed to send cancellation email for booking {booking.id} to {user.email}: {e_mail}")


        current_app.logger.info(f"Admin user {current_user.username} successfully CANCELLED booking ID: {booking.id}. Reason: {audit_log_reason}")
        return jsonify({
            'message': 'Booking cancelled successfully.',
            'new_status': booking.status,
            'admin_message': booking.admin_deleted_message # This will be None if no reason was provided
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during admin cancellation of booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_CANCEL_BOOKING_FAILED",
            details=f"Admin '{current_user.username}' failed to CANCEL booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to cancel booking due to a server error.'}), 500


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/clear_admin_message', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def admin_clear_booking_message(booking_id):
    current_app.logger.info(f"Admin user '{current_user.username}' attempting to clear admin message for booking ID: {booking_id}")
    try:
        booking = Booking.query.get(booking_id)

        if not booking:
            current_app.logger.warning(f"Admin clear message attempt: Booking ID {booking_id} not found.")
            return jsonify({'error': 'Booking not found.'}), 404

        if booking.status != 'cancelled_by_admin':
            current_app.logger.warning(
                f"Admin clear message attempt: Booking ID {booking_id} is not in 'cancelled_by_admin' state (current: '{booking.status}')."
            )
            return jsonify({'error': "Message can only be cleared for bookings cancelled by an admin."}), 400

        booking.admin_deleted_message = None
        booking.status = 'cancelled_admin_acknowledged'
        db.session.commit()

        add_audit_log(
            action="ADMIN_CLEAR_BOOKING_MESSAGE",
            details=(
                f"Admin '{current_user.username}' cleared cancellation message for booking ID {booking.id}. "
                f"Status changed to 'cancelled_admin_acknowledged'."
            )
        )
        current_app.logger.info(
            f"Admin '{current_user.username}' cleared message for booking ID {booking.id}. Status set to 'cancelled_admin_acknowledged'."
        )

        # socketio.emit('booking_updated', { # Removed
        #     'action': 'admin_message_cleared_by_admin', # Removed
        #     'booking_id': booking.id, # Removed
        #     'resource_id': booking.resource_id, # Removed
        #     'new_status': booking.status, # Removed
        #     'admin_deleted_message': None # Removed
        # }) # Removed

        return jsonify({
            'message': 'Admin message cleared and booking acknowledged.',
            'new_status': booking.status
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during admin clearing message for booking ID {booking_id}:")
        add_audit_log(
            action="ADMIN_CLEAR_BOOKING_MESSAGE_FAILED",
            details=f"Admin '{current_user.username}' failed to clear message for booking ID {booking_id}. Error: {str(e)}"
        )
        return jsonify({'error': 'Failed to clear admin message due to a server error.'}), 500

# Initialization function for this blueprint
def init_admin_api_bookings_routes(app):
    app.register_blueprint(admin_api_bookings_bp)
