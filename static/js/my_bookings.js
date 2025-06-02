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

    const predefinedSlots = [
        { name: "Morning (08:00 - 12:00 UTC)", start: "08:00", end: "12:00" },
        { name: "Afternoon (13:00 - 17:00 UTC)", start: "13:00", end: "17:00" },
        { name: "Full Day (08:00 - 17:00 UTC)", start: "08:00", end: "17:00" }
    ];

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
                bookingItemDiv.dataset.resourceId = booking.resource_id; // Store resource ID
                bookingItemDiv.dataset.startTime = booking.start_time; // Store full start time
                bookingItemDiv.dataset.endTime = booking.end_time; // Store full end time

                bookingItemClone.querySelector('.resource-name').textContent = booking.resource_name;
                const titleSpan = bookingItemClone.querySelector('.booking-title');
                titleSpan.textContent = booking.title || 'N/A';
                titleSpan.dataset.originalTitle = booking.title || ''; // Store original title

                const startTimeSpan = bookingItemClone.querySelector('.start-time');
                startTimeSpan.textContent = new Date(booking.start_time).toUTCString();
                startTimeSpan.dataset.originalStartTime = booking.start_time;

                const endTimeSpan = bookingItemClone.querySelector('.end-time');
                endTimeSpan.textContent = new Date(booking.end_time).toUTCString();
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
            // const currentEndTimeISO = bookingItemDiv.dataset.endTime; // Not immediately needed for new modal
            const resourceName = bookingItemDiv.querySelector('.resource-name').textContent;
            const resourceId = bookingItemDiv.dataset.resourceId;

            modalBookingIdInput.value = bookingId;
            newBookingTitleInput.value = currentTitle;

            // Store resourceId on the modal itself or a hidden input within the modal
            updateModalElement.dataset.resourceId = resourceId; // Storing on modal element

            // Populate new date field
            const startDate = new Date(currentStartTimeISO);
            const modalBookingDateInput = document.getElementById('modal-booking-date');
            if (modalBookingDateInput) {
                modalBookingDateInput.value = startDate.toISOString().split('T')[0];
                // Trigger change event to load slots for the current date
                modalBookingDateInput.dispatchEvent(new Event('change'));
            }

            // Clear old time fields (if they are still in HTML, eventually they'll be removed)
            const oldStartDateInput = document.getElementById('new-booking-start-date');
            if (oldStartDateInput) oldStartDateInput.value = '';
            const oldStartTimeInput = document.getElementById('new-booking-start-time');
            if (oldStartTimeInput) oldStartTimeInput.value = '';
            const oldEndDateInput = document.getElementById('new-booking-end-date');
            if (oldEndDateInput) oldEndDateInput.value = '';
            const oldEndTimeInput = document.getElementById('new-booking-end-time');
            if (oldEndTimeInput) oldEndTimeInput.value = '';
            
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
        const selectedDate = document.getElementById('modal-booking-date').value;
        const selectedSlot = document.getElementById('modal-available-slots-select').value;

        if (!newTitle) {
            showStatusMessage(updateModalStatusDiv, 'Title cannot be empty.', 'danger');
            return;
        }
        if (!selectedDate) {
            showStatusMessage(updateModalStatusDiv, 'Please select a date.', 'danger');
            return;
        }
        if (!selectedSlot) {
            showStatusMessage(updateModalStatusDiv, 'Please select an available time slot.', 'danger');
            return;
        }

        const [slotStart, slotEnd] = selectedSlot.split(',');
        const isoStartTime = `${selectedDate}T${slotStart}:00Z`; // Assuming slot times are UTC
        const isoEndTime = `${selectedDate}T${slotEnd}:00Z`;   // Assuming slot times are UTC

        const payload = {
            title: newTitle,
            start_time: isoStartTime,
            end_time: isoEndTime
        };

        // Optional: Check if any actual change was made (more complex with new date/slot structure)
        // For now, we assume if "Save" is clicked with valid inputs, an update is intended.

        showLoading(updateModalStatusDiv, 'Saving changes...');

        try {
            const updatedBooking = await apiCall(`/api/bookings/${bookingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            // Update the UI
            const bookingItemDiv = bookingsListDiv.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
            if (bookingItemDiv) {
                const titleSpan = bookingItemDiv.querySelector('.booking-title');
                titleSpan.textContent = updatedBooking.title;
                titleSpan.dataset.originalTitle = updatedBooking.title;

                const startTimeSpan = bookingItemDiv.querySelector('.start-time');
                startTimeSpan.textContent = new Date(updatedBooking.start_time).toUTCString();
                bookingItemDiv.dataset.startTime = updatedBooking.start_time;

                const endTimeSpan = bookingItemDiv.querySelector('.end-time');
                endTimeSpan.textContent = new Date(updatedBooking.end_time).toUTCString();
                bookingItemDiv.dataset.endTime = updatedBooking.end_time;
            }
            
            showSuccess(statusDiv, `Booking ${bookingId} updated successfully.`);
            updateModal.hide();
            // Consider re-fetching all bookings for simplicity and to ensure all states are correct.
            // fetchAndDisplayBookings(); 
        } catch (error) {
            console.error('Error updating booking:', error);
            showError(updateModalStatusDiv, error.message || 'Failed to update booking.');
        }
    });

    // Event listener for modal date change
    const modalBookingDateInput = document.getElementById('modal-booking-date');
    if (modalBookingDateInput) {
        modalBookingDateInput.addEventListener('change', async () => {
            const availableSlotsSelect = document.getElementById('modal-available-slots-select');
            const resourceId = updateModalElement.dataset.resourceId;
            const selectedDate = modalBookingDateInput.value;
            const currentBookingId = modalBookingIdInput.value; // Booking being edited

            if (!selectedDate || !resourceId) {
                availableSlotsSelect.innerHTML = '<option value="">Select a date first</option>';
                return;
            }

            availableSlotsSelect.innerHTML = '<option value="">Loading...</option>';
            availableSlotsSelect.disabled = true;

            try {
                // Step 3: Fetch necessary data
                // Fetch resource details (for maintenance status)
                const resource = await apiCall(`/api/resources/${resourceId}`);

                // Fetch user's own bookings for the selected date
                // The endpoint /api/bookings/my_bookings_for_date?date=${selectedDate} needs to be implemented
                // For now, let's assume it exists or adapt.
                // If not, we might need to fetch all user bookings and filter, which is less ideal.
                // Let's placeholder the call:
                let usersBookingsOnDate = [];
                try {
                    usersBookingsOnDate = await apiCall(`/api/bookings/my_bookings_for_date?date=${selectedDate}`);
                } catch (e) {
                    // If endpoint doesn't exist, this will fail. Log and continue, conflict check will be partial.
                    console.warn(`Could not fetch user's bookings for date ${selectedDate}. User conflict check might be incomplete. Error: ${e.message}`);
                }


                // Step 5: Filter Slots
                availableSlotsSelect.innerHTML = ''; // Clear "Loading..."
                let availableSlotsFound = 0;

                const selectedDateObj = new Date(selectedDate + "T00:00:00Z"); // Ensure date is treated as UTC midnight

                for (const slot of predefinedSlots) {
                    const slotStartDateTime = new Date(`${selectedDate}T${slot.start}:00Z`);
                    const slotEndDateTime = new Date(`${selectedDate}T${slot.end}:00Z`);
                    let isAvailable = true;
                    let unavailabilityReason = "";

                    // Past Date/Time Check
                    const now = new Date();
                    if (slotEndDateTime < now) {
                        isAvailable = false;
                        unavailabilityReason = " (Past)";
                    }

                    // Resource Maintenance Check
                    if (isAvailable && resource.is_under_maintenance) {
                        if (!resource.maintenance_until) { // Indefinite maintenance
                            isAvailable = false;
                            unavailabilityReason = " (Resource under maintenance)";
                        } else {
                            const maintenanceUntilDate = new Date(resource.maintenance_until);
                            // If slot starts before maintenance ends OR slot ends after maintenance starts (assuming maintenance_from exists or is now)
                            // For simplicity, if maintenance_until is on selectedDate or in future, check overlap.
                            // This check assumes maintenance_until is the END of maintenance.
                            // A more precise check would involve maintenance_from.
                            // If slot is within a defined maintenance period.
                            // Simplified: if selectedDate is before or on the day of maintenance_until, and slot is within it.
                            // This logic needs to be robust based on how maintenance_until is defined (end of day? specific time?)
                            // For now: if slot ends after "now" and starts before maintenance ends.
                            if (slotStartDateTime < maintenanceUntilDate) { // Basic check: if slot starts before maintenance period ends.
                                isAvailable = false;
                                unavailabilityReason = " (Resource maintenance)";
                            }
                        }
                    }

                    // User's Own Bookings Check (excluding the current booking being edited)
                    if (isAvailable) {
                        for (const userBooking of usersBookingsOnDate) {
                            if (userBooking.id.toString() === currentBookingId) continue;

                            const userBookingStart = new Date(userBooking.start_time);
                            const userBookingEnd = new Date(userBooking.end_time);

                            if (checkOverlap(slotStartDateTime, slotEndDateTime, userBookingStart, userBookingEnd)) {
                                isAvailable = false;
                                unavailabilityReason = " (Conflicts with your other booking)";
                                break;
                            }
                        }
                    }

                    // Server-side will handle resource booking conflicts.

                    const option = document.createElement('option');
                    option.value = `${slot.start},${slot.end}`;
                    option.textContent = `${slot.name}${isAvailable ? '' : unavailabilityReason}`;
                    option.disabled = !isAvailable;
                    if (isAvailable) {
                        availableSlotsFound++;
                    }
                    availableSlotsSelect.appendChild(option);
                }

                if (availableSlotsFound === 0) {
                    availableSlotsSelect.innerHTML = '<option value="">No available slots</option>';
                }
                availableSlotsSelect.disabled = false;

            } catch (error) {
                console.error('Error fetching slot availability:', error);
                showStatusMessage(updateModalStatusDiv, `Error loading slots: ${error.message}`, 'danger');
                availableSlotsSelect.innerHTML = '<option value="">Error loading slots</option>';
                availableSlotsSelect.disabled = true;
            }
        });
    }

    // Helper functions (to be implemented or ensured they are available)
    function parseISODateTime(dateTimeStr) {
        return new Date(dateTimeStr);
    }

    function checkOverlap(startA, endA, startB, endB) {
        // Ensure these are Date objects
        const aStart = startA instanceof Date ? startA : new Date(startA);
        const aEnd = endA instanceof Date ? endA : new Date(endA);
        const bStart = startB instanceof Date ? startB : new Date(startB);
        const bEnd = endB instanceof Date ? endB : new Date(endB);

        // Check if one interval starts after the other ends, or vice-versa
        // No overlap if (A ends before B starts) OR (A starts after B ends)
        const noOverlap = (aEnd <= bStart) || (aStart >= bEnd);
        return !noOverlap; // Overlap is true if it's not "no overlap"
    }
    
    // Initial fetch of bookings
    fetchAndDisplayBookings();
});
