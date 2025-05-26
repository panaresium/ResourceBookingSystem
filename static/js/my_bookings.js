document.addEventListener('DOMContentLoaded', () => {
    const bookingsListDiv = document.getElementById('my-bookings-list');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status');

    const updateModal = new bootstrap.Modal(document.getElementById('update-booking-modal'));
    const updateModalElement = document.getElementById('update-booking-modal');
    const updateBookingModalLabel = document.getElementById('updateBookingModalLabel');
    const modalBookingIdInput = document.getElementById('modal-booking-id');
    const newBookingTitleInput = document.getElementById('new-booking-title');
    const saveBookingTitleBtn = document.getElementById('save-booking-title-btn');
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

                bookingItemClone.querySelector('.resource-name').textContent = booking.resource_name;
                const titleSpan = bookingItemClone.querySelector('.booking-title');
                titleSpan.textContent = booking.title || 'N/A';
                titleSpan.dataset.originalTitle = booking.title || ''; // Store original title

                bookingItemClone.querySelector('.start-time').textContent = new Date(booking.start_time).toLocaleString();
                bookingItemClone.querySelector('.end-time').textContent = new Date(booking.end_time).toLocaleString();
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
            const resourceName = bookingItemDiv.querySelector('.resource-name').textContent;

            modalBookingIdInput.value = bookingId;
            newBookingTitleInput.value = currentTitle;
            updateBookingModalLabel.textContent = `Update Booking Title for: ${resourceName}`;
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

    // Handle modal form submission for updating title
    saveBookingTitleBtn.addEventListener('click', async () => {
        const bookingId = modalBookingIdInput.value;
        const newTitle = newBookingTitleInput.value.trim();

        if (!newTitle) {
            showStatusMessage(updateModalStatusDiv, 'Title cannot be empty.', 'danger');
            return;
        }
        showLoading(updateModalStatusDiv, 'Saving changes...');

        try {
            const updatedBooking = await apiCall(`/api/bookings/${bookingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle })
            });
            
            // Update the UI
            const bookingItemDiv = bookingsListDiv.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
            if (bookingItemDiv) {
                const titleSpan = bookingItemDiv.querySelector('.booking-title');
                titleSpan.textContent = updatedBooking.title;
                titleSpan.dataset.originalTitle = updatedBooking.title;
            }
            
            showSuccess(statusDiv, `Booking ${bookingId} title updated successfully.`);
            updateModal.hide();
        } catch (error) {
            console.error('Error updating booking title:', error);
            showError(updateModalStatusDiv, error.message || 'Failed to update title.');
        }
    });
    
    // Initial fetch of bookings
    fetchAndDisplayBookings();
});
