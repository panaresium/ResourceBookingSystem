document.addEventListener('DOMContentLoaded', () => {
    const bookingsListDiv = document.getElementById('my-bookings-list');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status'); // For main page status messages
    const globalUserName = document.body.dataset.userName; // Assuming username is on body's data attribute

    // Helper to display status messages on the main page (remains)
    function showStatusMessage(element, message, type = 'info') {
        if (element) {
            element.textContent = message;
            element.className = `alert alert-${type}`;
            element.style.display = 'block';
        }
    }

    function hideStatusMessage(element) {
        if (element) {
            element.style.display = 'none';
        }
    }
    
    // showLoading, showError, showSuccess are assumed to be global or part of script.js
    // and will use statusDiv for messages on the main page.

    async function fetchAndDisplayBookings() {
        if (typeof showLoading === 'function') showLoading(statusDiv, 'Loading your bookings...');
        else console.log("showLoading function not found, cannot display loading message.");
        try {
            const bookings = await apiCall('/api/bookings/my_bookings');
            bookingsListDiv.innerHTML = '';

            if (bookings.length === 0) {
                showStatusMessage(statusDiv, 'You have no bookings.', 'info');
                return;
            }

            bookings.forEach(booking => {
                const bookingItemClone = bookingItemTemplate.content.cloneNode(true);
                const bookingItemDiv = bookingItemClone.querySelector('.booking-item');

                bookingItemDiv.dataset.bookingId = booking.id;
                bookingItemDiv.dataset.resourceId = booking.resource_id;
                bookingItemDiv.dataset.startTime = booking.start_time;
                bookingItemDiv.dataset.endTime = booking.end_time;

                bookingItemClone.querySelector('.resource-name').textContent = booking.resource_name;
                const titleSpan = bookingItemClone.querySelector('.booking-title');
                titleSpan.textContent = booking.title || 'N/A';
                titleSpan.dataset.originalTitle = booking.title || '';

                const startTimeSpan = bookingItemClone.querySelector('.start-time');
                startTimeSpan.textContent = new Date(booking.start_time).toUTCString();
                // startTimeSpan.dataset.originalStartTime = booking.start_time; // Not strictly needed with new modal

                const endTimeSpan = bookingItemClone.querySelector('.end-time');
                endTimeSpan.textContent = new Date(booking.end_time).toUTCString();
                // endTimeSpan.dataset.originalEndTime = booking.end_time; // Not strictly needed
                
                bookingItemClone.querySelector('.recurrence-rule').textContent = booking.recurrence_rule || '';
                
                // Ensure updateBtn exists before adding dataset property
                const updateBtn = bookingItemClone.querySelector('.update-booking-btn');
                if (updateBtn) updateBtn.dataset.bookingId = booking.id;

                const cancelBtn = bookingItemClone.querySelector('.cancel-booking-btn');
                if (cancelBtn) cancelBtn.dataset.bookingId = booking.id;

                const checkInBtn = bookingItemClone.querySelector('.check-in-btn');
                const checkOutBtn = bookingItemClone.querySelector('.check-out-btn');
                if (checkInBtn) checkInBtn.dataset.bookingId = booking.id;
                if (checkOutBtn) checkOutBtn.dataset.bookingId = booking.id;

                if (booking.can_check_in) {
                    if (checkInBtn) checkInBtn.style.display = 'inline-block';
                }
                if (booking.checked_in_at && !booking.checked_out_at) {
                    if (checkOutBtn) checkOutBtn.style.display = 'inline-block';
                }

                bookingsListDiv.appendChild(bookingItemClone);
            });
            hideStatusMessage(statusDiv);
        } catch (error) {
            console.error('Error fetching bookings:', error);
            if (error.message && error.message.includes('401')) {
                if (typeof showError === 'function') showError(statusDiv, 'Please log in to view your bookings.');
                else console.log("showError function not found.");
            } else {
                 if (typeof showError === 'function') showError(statusDiv, error.message || 'Failed to load bookings. Please try again.');
                 else console.log("showError function not found.");
            }
        }
    }

    // Event listener for dynamically created buttons
    bookingsListDiv.addEventListener('click', async (event) => {
        const target = event.target;

        if (target.classList.contains('cancel-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            if (confirm(`Are you sure you want to cancel booking ID ${bookingId}?`)) {
                if (typeof showLoading === 'function') showLoading(statusDiv, `Cancelling booking ${bookingId}...`);
                try {
                    await apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' });
                    if (typeof showSuccess === 'function') showSuccess(statusDiv, `Booking ${bookingId} cancelled successfully.`);
                    target.closest('.booking-item').remove();
                    if (bookingsListDiv.children.length === 0) {
                        showStatusMessage(statusDiv, 'You have no bookings remaining.', 'info');
                    }
                } catch (error) {
                    console.error('Error cancelling booking:', error);
                    if (typeof showError === 'function') showError(statusDiv, error.message || `Failed to cancel booking ${bookingId}.`);
                }
            }
        }

        if (target.classList.contains('update-booking-btn')) {
            const bookingItemDiv = target.closest('.booking-item');
            const bookingId = bookingItemDiv.dataset.bookingId;
            const resourceId = bookingItemDiv.dataset.resourceId;
            const resourceName = bookingItemDiv.querySelector('.resource-name').textContent;
            const currentTitle = bookingItemDiv.querySelector('.booking-title').dataset.originalTitle;
            const currentStartTimeISO = bookingItemDiv.dataset.startTime;
            const currentEndTimeISO = bookingItemDiv.dataset.endTime;

            if (typeof openBookingModal === 'function') {
                openBookingModal({
                    mode: 'update',
                    bookingId: bookingId,
                    resourceId: resourceId,
                    resourceName: resourceName,
                    currentTitle: currentTitle,
                    currentStartTimeISO: currentStartTimeISO,
                    currentEndTimeISO: currentEndTimeISO,
                    userNameForRecord: globalUserName, // Pass the global username
                    onSaveSuccess: (updatedBookingData) => {
                        console.log('Booking updated successfully on My Bookings page:', updatedBookingData);
                        if (typeof showSuccess === 'function') {
                           showSuccess(statusDiv, `Booking ${updatedBookingData.id || bookingId} updated successfully.`);
                        } else {
                           statusDiv.textContent = `Booking ${updatedBookingData.id || bookingId} updated successfully.`;
                           statusDiv.className = 'alert alert-success';
                           statusDiv.style.display = 'block';
                        }
                        fetchAndDisplayBookings(); // Re-fetch all bookings
                    }
                });
            } else {
                console.error("openBookingModal function not found. Ensure booking_modal_handler.js is loaded.");
                if (typeof showError === 'function') showError(statusDiv, "Error: Update functionality is currently unavailable.");
            }
        }

        if (target.classList.contains('check-in-btn')) {
            const bookingId = target.dataset.bookingId;
            if (typeof showLoading === 'function') showLoading(statusDiv, 'Checking in...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_in`, { method: 'POST' });
                target.style.display = 'none';
                const bookingItemDiv = target.closest('.booking-item');
                const checkOutBtn = bookingItemDiv.querySelector('.check-out-btn');
                if (checkOutBtn) checkOutBtn.style.display = 'inline-block';
                if (typeof showSuccess === 'function') showSuccess(statusDiv, 'Checked in successfully.');
            } catch (error) {
                console.error('Check in failed:', error);
                if (typeof showError === 'function') showError(statusDiv, error.message || 'Check in failed.');
            }
        }

        if (target.classList.contains('check-out-btn')) {
            const bookingId = target.dataset.bookingId;
            if (typeof showLoading === 'function') showLoading(statusDiv, 'Checking out...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_out`, { method: 'POST' });
                target.style.display = 'none';
                if (typeof showSuccess === 'function') showSuccess(statusDiv, 'Checked out successfully.');
            } catch (error) {
                console.error('Check out failed:', error);
                if (typeof showError === 'function') showError(statusDiv, error.message || 'Check out failed.');
            }
        }
    });
    
    // Initial fetch of bookings
    fetchAndDisplayBookings();
});
// Removed modal-specific variables like updateModalElement, updateBookingModalLabel, etc.
// Removed modal-specific event listeners for saveBookingTitleBtn and modalBookingDateInput.
// Removed modal-specific helper functions: showModalStatus, clearAndDisableSlotsSelect, predefinedSlots, parseISODateTime, checkOverlap.
// The old Bootstrap modal instance `updateModal` and its direct handling are also removed.
