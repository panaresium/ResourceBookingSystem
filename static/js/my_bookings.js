document.addEventListener('DOMContentLoaded', () => {
    const bookingsListDiv = document.getElementById('my-bookings-list');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status');

    const updateModalElement = document.getElementById('update-booking-modal');
    let updateModal;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        updateModal = new bootstrap.Modal(updateModalElement);
    } else {
        updateModal = {
            show: () => { if (updateModalElement) updateModalElement.style.display = 'block'; },
            hide: () => { if (updateModalElement) updateModalElement.style.display = 'none'; }
        };
    }

    // Explicitly hide the modal on initialization
    if (updateModal && typeof updateModal.hide === 'function') {
        updateModal.hide(); // For Bootstrap modal object
    } else if (updateModalElement) {
        // This is the primary fallback if Bootstrap's JS isn't loaded or `new bootstrap.Modal` failed silently.
        // It also covers the custom fallback object's hide method if it were more complex.
        updateModalElement.style.display = 'none'; 
    }

    const updateBookingModalLabel = document.getElementById('updateBookingModalLabel');
    const modalBookingIdInput = document.getElementById('modal-booking-id');
    const newBookingTitleInput = document.getElementById('new-booking-title');
    const saveBookingTitleBtn = document.getElementById('save-booking-title-btn');

    // Add explicit event listeners for modal close buttons
    const modalHeaderCloseButton = updateModalElement.querySelector('.modal-header .btn-close');
    const modalFooterCloseButton = updateModalElement.querySelector('.modal-footer .btn-secondary[data-bs-dismiss="modal"]');

    if (modalHeaderCloseButton) {
        modalHeaderCloseButton.addEventListener('click', () => {
            if (updateModal && typeof updateModal.hide === 'function') {
                updateModal.hide();
            } else if (updateModalElement) { // Fallback if Bootstrap instance not available
                updateModalElement.style.display = 'none';
            }
        });
    }

    if (modalFooterCloseButton) {
        modalFooterCloseButton.addEventListener('click', () => {
            if (updateModal && typeof updateModal.hide === 'function') {
                updateModal.hide();
            } else if (updateModalElement) { // Fallback
                updateModalElement.style.display = 'none';
            }
        });
    }

    const updateModalStatusDiv = document.getElementById('update-modal-status');

    // Helper to display status messages (could be moved to script.js if used globally)
    function showStatusMessage(element, message, type = 'info') {
        element.textContent = message;
        element.className = `alert alert-${type}`;
        element.style.display = 'block';
    }

    function hideStatusMessage(element) {
        element.style.display = 'none';
    }
    
    async function fetchAndDisplayBookings() {
        showLoading(statusDiv, 'Loading your bookings...');
        try {
            const bookings = await apiCall('/api/bookings/my_bookings');
            bookingsListDiv.innerHTML = ''; // Clear loading message or previous bookings

            if (bookings.length === 0) {
                showStatusMessage(statusDiv, 'You have no bookings.', 'info');
                return;
            }

            bookings.forEach(booking => {
                const bookingItemClone = bookingItemTemplate.content.cloneNode(true);
                const bookingItemDiv = bookingItemClone.querySelector('.booking-item');

                bookingItemDiv.dataset.bookingId = booking.id; // Store booking ID on the item div
                bookingItemDiv.dataset.startTime = booking.start_time; // Store full start time
                bookingItemDiv.dataset.endTime = booking.end_time; // Store full end time

                bookingItemClone.querySelector('.resource-name').textContent = booking.resource_name;
                const titleSpan = bookingItemClone.querySelector('.booking-title');
                titleSpan.textContent = booking.title || 'N/A';
                titleSpan.dataset.originalTitle = booking.title || ''; // Store original title

                const startTimeSpan = bookingItemClone.querySelector('.start-time');
                startTimeSpan.textContent = new Date(booking.start_time).toLocaleString();
                startTimeSpan.dataset.originalStartTime = booking.start_time;

                const endTimeSpan = bookingItemClone.querySelector('.end-time');
                endTimeSpan.textContent = new Date(booking.end_time).toLocaleString();
                endTimeSpan.dataset.originalEndTime = booking.end_time;
                
                bookingItemClone.querySelector('.recurrence-rule').textContent = booking.recurrence_rule || '';
                
                const updateBtn = bookingItemClone.querySelector('.update-booking-btn');
                updateBtn.dataset.bookingId = booking.id;

                const cancelBtn = bookingItemClone.querySelector('.cancel-booking-btn');
                cancelBtn.dataset.bookingId = booking.id;

                const checkInBtn = bookingItemClone.querySelector('.check-in-btn');
                const checkOutBtn = bookingItemClone.querySelector('.check-out-btn');
                checkInBtn.dataset.bookingId = booking.id;
                checkOutBtn.dataset.bookingId = booking.id;
                if (booking.can_check_in) {
                    checkInBtn.style.display = 'inline-block';
                }
                if (booking.checked_in_at && !booking.checked_out_at) {
                    checkOutBtn.style.display = 'inline-block';
                }

                bookingsListDiv.appendChild(bookingItemClone);
            });
            hideStatusMessage(statusDiv);
        } catch (error) {
            console.error('Error fetching bookings:', error);
            if (error.message && error.message.includes('401')) {
                showError(statusDiv, 'Please log in to view your bookings.');
            } else {
                showError(statusDiv, error.message || 'Failed to load bookings. Please try again.');
            }
        }
    }

    // Event listener for dynamically created buttons
    bookingsListDiv.addEventListener('click', async (event) => {
        const target = event.target;

        if (target.classList.contains('cancel-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            if (confirm(`Are you sure you want to cancel booking ID ${bookingId}?`)) {
                showLoading(statusDiv, `Cancelling booking ${bookingId}...`);
                try {
                    await apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' });
                    showSuccess(statusDiv, `Booking ${bookingId} cancelled successfully.`);
                    // Remove the booking item from the UI
                    target.closest('.booking-item').remove();
                    if (bookingsListDiv.children.length === 0) {
                        showStatusMessage(statusDiv, 'You have no bookings remaining.', 'info');
                    }
                } catch (error) {
                    console.error('Error cancelling booking:', error);
                    showError(statusDiv, error.message || `Failed to cancel booking ${bookingId}.`);
                }
            }
        }

        if (target.classList.contains('update-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            const bookingItemDiv = target.closest('.booking-item');
            const currentTitle = bookingItemDiv.querySelector('.booking-title').dataset.originalTitle;
            const currentStartTimeISO = bookingItemDiv.dataset.startTime;
            const currentEndTimeISO = bookingItemDiv.dataset.endTime;
            const resourceName = bookingItemDiv.querySelector('.resource-name').textContent;

            modalBookingIdInput.value = bookingId;
            newBookingTitleInput.value = currentTitle;

            // Populate date and time fields
            const startDate = new Date(currentStartTimeISO);
            document.getElementById('new-booking-start-date').value = startDate.toISOString().split('T')[0];
            document.getElementById('new-booking-start-time').value = startDate.toTimeString().slice(0,5);

            const endDate = new Date(currentEndTimeISO);
            document.getElementById('new-booking-end-date').value = endDate.toISOString().split('T')[0];
            document.getElementById('new-booking-end-time').value = endDate.toTimeString().slice(0,5);
            
            updateBookingModalLabel.textContent = `Update Booking for: ${resourceName}`;
            hideStatusMessage(updateModalStatusDiv);
            updateModal.show();
        }

        if (target.classList.contains('check-in-btn')) {
            const bookingId = target.dataset.bookingId;
            showLoading(statusDiv, 'Checking in...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_in`, { method: 'POST' });
                target.style.display = 'none';
                const bookingItemDiv = target.closest('.booking-item');
                const checkOutBtn = bookingItemDiv.querySelector('.check-out-btn');
                if (checkOutBtn) checkOutBtn.style.display = 'inline-block';
                showSuccess(statusDiv, 'Checked in successfully.');
            } catch (error) {
                console.error('Check in failed:', error);
                showError(statusDiv, error.message || 'Check in failed.');
            }
        }

        if (target.classList.contains('check-out-btn')) {
            const bookingId = target.dataset.bookingId;
            showLoading(statusDiv, 'Checking out...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_out`, { method: 'POST' });
                target.style.display = 'none';
                showSuccess(statusDiv, 'Checked out successfully.');
            } catch (error) {
                console.error('Check out failed:', error);
                showError(statusDiv, error.message || 'Check out failed.');
            }
        }
    });

    // Handle modal form submission for updating booking
    saveBookingTitleBtn.addEventListener('click', async () => {
        const bookingId = modalBookingIdInput.value;
        const newTitle = newBookingTitleInput.value.trim();

        const newStartDate = document.getElementById('new-booking-start-date').value;
        const newStartTime = document.getElementById('new-booking-start-time').value;
        const newEndDate = document.getElementById('new-booking-end-date').value;
        const newEndTime = document.getElementById('new-booking-end-time').value;

        if (!newTitle) {
            showStatusMessage(updateModalStatusDiv, 'Title cannot be empty.', 'danger');
            return;
        }

        const payload = { title: newTitle };
        let timesProvided = false;
        let timesComplete = false;

        if (newStartDate && newStartTime && newEndDate && newEndTime) {
            timesProvided = true;
            timesComplete = true;
            payload.start_time = `${newStartDate}T${newStartTime}:00`; // Add seconds
            payload.end_time = `${newEndDate}T${newEndTime}:00`;     // Add seconds
        } else if (newStartDate || newStartTime || newEndDate || newEndTime) {
            // Some time fields are filled but not all, which is an incomplete input for time update
            timesProvided = true;
            timesComplete = false;
        }

        if (timesProvided && !timesComplete) {
            showStatusMessage(updateModalStatusDiv, 'Please provide both date and time for start and end if you wish to update the booking time.', 'danger');
            return;
        }
        
        // Check if any actual change was made
        const bookingItemDiv = bookingsListDiv.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
        const originalTitle = bookingItemDiv.querySelector('.booking-title').dataset.originalTitle;
        const originalStartTimeISO = bookingItemDiv.dataset.startTime;
        const originalEndTimeISO = bookingItemDiv.dataset.endTime;

        let noChangesMade = true;
        if (newTitle !== originalTitle) {
            noChangesMade = false;
        }
        if (timesComplete) {
            // Compare with original times, needs careful ISO string comparison or Date object comparison
            // For simplicity, we'll assume if times are provided and valid, it's a change.
            // A more robust check would convert payload.start_time and originalStartTimeISO to Date objects and compare.
            if (payload.start_time !== originalStartTimeISO || payload.end_time !== originalEndTimeISO) {
                 noChangesMade = false;
            }
        }
        
        if (noChangesMade && !timesComplete) { // No title change and no complete time change attempted
             showStatusMessage(updateModalStatusDiv, 'No changes detected.', 'info');
             return;
        }


        showLoading(updateModalStatusDiv, 'Saving changes...');

        try {
            const updatedBooking = await apiCall(`/api/bookings/${bookingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            // Update the UI
            if (bookingItemDiv) {
                const titleSpan = bookingItemDiv.querySelector('.booking-title');
                titleSpan.textContent = updatedBooking.title;
                titleSpan.dataset.originalTitle = updatedBooking.title;

                const startTimeSpan = bookingItemDiv.querySelector('.start-time');
                startTimeSpan.textContent = new Date(updatedBooking.start_time).toLocaleString();
                bookingItemDiv.dataset.startTime = updatedBooking.start_time; // Update stored full start time

                const endTimeSpan = bookingItemDiv.querySelector('.end-time');
                endTimeSpan.textContent = new Date(updatedBooking.end_time).toLocaleString();
                bookingItemDiv.dataset.endTime = updatedBooking.end_time; // Update stored full end time
            }
            
            showSuccess(statusDiv, `Booking ${bookingId} updated successfully.`);
            updateModal.hide();
            // Consider re-fetching or more granular UI update for check-in/out button visibility
            // For now, only title and times are updated. A full refresh might be simpler:
            // fetchAndDisplayBookings(); 
        } catch (error) {
            console.error('Error updating booking:', error);
            showError(updateModalStatusDiv, error.message || 'Failed to update booking.');
        }
    });
    
    // Initial fetch of bookings
    fetchAndDisplayBookings();
});
