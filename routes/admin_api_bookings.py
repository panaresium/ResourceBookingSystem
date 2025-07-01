from flask import Blueprint, jsonify, request, current_app, render_template, url_for
from flask_login import login_required, current_user
from datetime import timezone, timedelta # Added timezone and timedelta

# Assuming extensions.py contains db # socketio and mail removed
from extensions import db # socketio and mail removed
# Assuming models.py contains these model definitions
from models import Booking, User, Resource, BookingSettings # Added Resource and BookingSettings
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

    booking_settings = BookingSettings.query.first()
    current_offset_hours = 0
    if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
        current_offset_hours = booking_settings.global_time_offset_hours
    else:
        current_app.logger.warning("BookingSettings not found or global_time_offset_hours not set for list_pending_bookings, using 0 offset for UTC conversion.")

    pending = Booking.query.filter_by(status='pending').all()
    result = []
    for b in pending:
        result.append({
            'id': b.id,
            'resource_id': b.resource_id,
            'resource_name': b.resource_booked.name if b.resource_booked else None,
            'user_name': b.user_name,
            'start_time': (b.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
            'end_time': (b.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).isoformat(),
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


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/send_confirmation_email', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def send_booking_confirmation_email(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    user = User.query.filter_by(username=booking.user_name).first()

    if not user:
        current_app.logger.error(f"User {booking.user_name} not found for booking {booking.id} when trying to send confirmation email.")
        return jsonify({'error': 'User not found for this booking.'}), 404

    if not user.email:
        current_app.logger.error(f"User {user.username} (ID: {user.id}) has no email address for booking {booking.id}.")
        return jsonify({'error': 'User email not found.'}), 400

    resource_name = booking.resource_booked.name if booking.resource_booked else "N/A"

    # Format start and end times
    # Assuming start_time and end_time are stored in UTC and need to be displayed in a user-friendly format.
    # For simplicity, using ISO format. Adjust formatting as needed.
    # Also, consider applying the global time offset if applicable, similar to list_pending_bookings
    booking_settings = BookingSettings.query.first()
    current_offset_hours = 0
    if booking_settings and hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None:
        current_offset_hours = booking_settings.global_time_offset_hours

    start_time_str = (booking.start_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M %Z')
    end_time_str = (booking.end_time - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M %Z')

    email_context = {
        'user_name': user.username,
        'resource_name': resource_name,
        'start_time': start_time_str,
        'end_time': end_time_str,
        'booking_title': booking.title or "No Title",
        'booking_id': booking.id
    }

    email_subject = "Booking Confirmation"
    email_template = "email/booking_confirmation.html" # Path relative to templates directory

    try:
        send_email(
            recipient_email=user.email,
            subject=email_subject,
            html_template=email_template,
            context=email_context
        )
        add_audit_log(
            action="SEND_BOOKING_CONFIRMATION_EMAIL",
            details=f"Admin {current_user.username} sent confirmation email for booking ID {booking.id} to {user.email}."
        )
        current_app.logger.info(f"Booking confirmation email sent for booking {booking.id} to {user.email} by admin {current_user.username}.")
        return jsonify({'success': True, 'message': 'Confirmation email sent.'}), 200
    except Exception as e:
        current_app.logger.error(f"Failed to send confirmation email for booking {booking.id} to {user.email}: {str(e)}")
        return jsonify({'error': 'Failed to send email', 'details': str(e)}), 500


@admin_api_bookings_bp.route('/bookings/<int:booking_id>/update_status', methods=['POST'])
@login_required
@permission_required('manage_bookings')
def update_booking_status(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    data = request.get_json()

    if not data or 'new_status' not in data:
        return jsonify({'error': 'Missing new_status in request body.'}), 400

    new_status = data['new_status']
    current_status = booking.status

    ALLOWED_STATUSES = [
        'pending',
        'approved',
        'rejected',
        'cancelled',
        'checked_in',
        'completed',
        'cancelled_by_user', # Retaining this as it's a common scenario, even if not explicitly set elsewhere in *these* files
        'cancelled_by_admin',
        'cancelled_admin_acknowledged', # Follow-up to cancelled_by_admin
        'system_cancelled_no_checkin', # Set by scheduler, admin might need to view/filter
        'confirmed', # Used in conflict/quota logic
        'no_show', # Common manual admin status
        'on_hold', # Useful manual admin status
        'under_review' # Useful manual admin status
    ]

    if new_status not in ALLOWED_STATUSES:
        return jsonify({'error': 'Invalid new_status provided.'}), 400

    # Define invalid transitions (current_status -> new_status)
    # This is a basic example; more complex logic might be needed.
    invalid_transitions = {
        'completed': ['pending', 'approved', 'checked_in', 'rejected', 'cancelled_by_user', 'cancelled_by_admin'],
        'cancelled': ['pending', 'approved', 'checked_in', 'completed', 'rejected'], # Or make it completely unchangeable
        'cancelled_by_user': ['pending', 'approved', 'checked_in', 'completed', 'rejected'],
        'cancelled_by_admin': ['pending', 'approved', 'checked_in', 'completed', 'rejected'],
        'rejected': ['approved', 'checked_in', 'completed']
        # Add more as needed, e.g. 'checked_in' cannot go to 'pending'
    }

    if current_status in invalid_transitions and new_status in invalid_transitions[current_status]:
        message = f"Cannot change status from '{current_status}' to '{new_status}'."
        current_app.logger.warning(f"Invalid status transition attempt for booking {booking_id}: {message}")
        return jsonify({'error': 'Invalid status transition', 'message': message}), 409 # 409 Conflict is suitable

    booking.status = new_status
    try:
        db.session.commit()

        # Send email notification about status change
        try:
            user = User.query.filter_by(username=booking.user_name).first()
            resource = Resource.query.get(booking.resource_id)

            if user and user.email and resource:
                # booking_settings = BookingSettings.query.first() # Not strictly needed if displaying stored time directly
                # offset_hours = booking_settings.global_time_offset_hours if booking_settings and booking_settings.global_time_offset_hours is not None else 0

                # Display times as stored (venue local time)
                start_time_display = booking.start_time.strftime('%Y-%m-%d %H:%M')
                end_time_display = booking.end_time.strftime('%Y-%m-%d %H:%M')

                email_context = {
                    'user_name': user.username,
                    'resource_name': resource.name,
                    'booking_title': booking.title or 'N/A', # Handle if title is None
                    'start_time': start_time_display,
                    'end_time': end_time_display,
                    'old_status': current_status,
                    'new_status': booking.status, # This is new_status
                    'admin_reason': None, # No specific reason field in this function currently
                    'my_bookings_url': url_for('ui.my_bookings_page', _external=True)
                }

                html_body = render_template('email/admin_booking_status_change.html', **email_context)
                text_body = render_template('email/admin_booking_status_change_text.html', **email_context)

                email_subject = f"Booking Status Updated: {resource.name} - {booking.title or 'Booking'}"

                send_email(
                    to_address=user.email,
                    subject=email_subject,
                    body=text_body,
                    html_body=html_body
                )
                current_app.logger.info(f"Admin status change notification email sent to {user.email} for booking ID {booking.id}.")
            elif not user:
                current_app.logger.warning(f"User {booking.user_name} not found. Cannot send status change email for booking ID {booking.id}.")
            elif not user.email:
                current_app.logger.warning(f"User {booking.user_name} (ID: {user.id if user else 'N/A'}) has no email. Cannot send status change email for booking ID {booking.id}.")
            elif not resource:
                current_app.logger.warning(f"Resource ID {booking.resource_id} not found for booking ID {booking.id}. Cannot send status change email.")

        except Exception as e_email:
            current_app.logger.error(f"Failed to send admin status change email for booking ID {booking.id}: {str(e_email)}", exc_info=True)

        add_audit_log(
            action="UPDATE_BOOKING_STATUS",
            details=f"Admin {current_user.username} updated booking ID {booking.id} status from '{current_status}' to '{new_status}'."
        )
        # socketio.emit('booking_updated', { # Removed
        #     'action': 'status_updated', # Removed
        #     'booking_id': booking.id, # Removed
        #     'new_status': new_status, # Removed
        #     'resource_id': booking.resource_id, # Removed
        #     'user_name': booking.user_name # Good to include for client-side updates # Removed
        # }) # Removed
        current_app.logger.info(f"Booking {booking.id} status updated from '{current_status}' to '{new_status}' by admin {current_user.username}.")
        return jsonify({'success': True, 'message': 'Booking status updated.', 'new_status': booking.status}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to update status for booking {booking.id}: {str(e)}")
        return jsonify({'error': 'Failed to update booking status', 'details': str(e)}), 500

# Initialization function for this blueprint
def init_admin_api_bookings_routes(app):
    app.register_blueprint(admin_api_bookings_bp)
