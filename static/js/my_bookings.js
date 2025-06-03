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

    function showModalStatus(message, type = 'info') { // Renaming for clarity as per plan, or use showStatusMessage directly
        showStatusMessage(updateModalStatusDiv, message, type);
    }

    function clearAndDisableSlotsSelect(message) {
        const slotsSelect = document.getElementById('modal-available-slots-select');
        slotsSelect.innerHTML = `<option value="">${message}</option>`;
        slotsSelect.disabled = true;
    }
    
    async function fetchAndDisplayBookings() {
        showLoading(statusDiv, 'Loading your bookings...');
        try {
            const apiResponse = await apiCall('/api/bookings/my_bookings');
            const bookings = apiResponse.bookings; // Access the bookings array
            const checkInOutEnabled = apiResponse.check_in_out_enabled; // Store the flag

            bookingsListDiv.innerHTML = ''; // Clear loading message or previous bookings

            if (!bookings || bookings.length === 0) { // Check if bookings is undefined or empty
                showStatusMessage(statusDiv, 'You have no bookings.', 'info');
                return;
            }

            bookings.forEach(booking => {
                // Bookings with status 'cancelled_by_admin' will have an admin_deleted_message.
                // This existing block should correctly handle them by displaying the message
                // and not proceeding to the 'else' block which renders action buttons.
                if (booking.admin_deleted_message) {
                    // Create a specific display for admin-deleted bookings
                    const deletedBookingDiv = document.createElement('div');
                    deletedBookingDiv.classList.add('booking-item', 'admin-deleted-item', 'alert', 'alert-warning'); // Added 'admin-deleted-item' for potential specific styling
                    deletedBookingDiv.setAttribute('role', 'alert');

                    const messageHeader = document.createElement('h5');
                    messageHeader.classList.add('alert-heading');
                    messageHeader.textContent = 'Booking Notice'; // Or "Booking Deleted by Admin"

                    const messageParagraph = document.createElement('p');
                    messageParagraph.textContent = booking.admin_deleted_message;

                    deletedBookingDiv.appendChild(messageHeader);
                    deletedBookingDiv.appendChild(messageParagraph);

                    // Optionally, add original booking ID if useful for user reference
                    const bookingIdInfo = document.createElement('p');
                    bookingIdInfo.classList.add('text-muted', 'small');
                    bookingIdInfo.textContent = `(Regarding Booking ID: ${booking.id})`; // Assuming booking.id is still available
                    deletedBookingDiv.appendChild(bookingIdInfo);

                    // Add the new button
                    const clearMessageBtn = document.createElement('button');
                    clearMessageBtn.classList.add('btn', 'btn-sm', 'btn-outline-secondary', 'clear-admin-message-btn', 'mt-2');
                    clearMessageBtn.textContent = 'Dismiss Message';
                    clearMessageBtn.dataset.bookingId = booking.id;
                    deletedBookingDiv.appendChild(clearMessageBtn);

                    bookingsListDiv.appendChild(deletedBookingDiv);

                } else {
                    // Existing logic for rendering active bookings
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

                    // Ensure buttons are hidden by default (if not already by CSS/template)
                    checkInBtn.style.display = 'none';
                    checkOutBtn.style.display = 'none';

                    if (checkInOutEnabled) {
                        if (booking.can_check_in) {
                            checkInBtn.style.display = 'inline-block';
                        }
                        if (booking.checked_in_at && !booking.checked_out_at) {
                            checkOutBtn.style.display = 'inline-block';
                        }
                    }
                    // If checkInOutEnabled is false, buttons remain hidden.

                    bookingsListDiv.appendChild(bookingItemClone);
                }
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

        if (target.classList.contains('clear-admin-message-btn')) {
            const bookingId = target.dataset.bookingId;
            if (!bookingId) {
                console.error('Booking ID not found on dismiss button.');
                showError(statusDiv, 'Could not identify booking to clear message.');
                return;
            }

            // Optional: Add a confirmation dialog
            // if (!confirm(`Are you sure you want to dismiss this message for booking ID ${bookingId}?`)) {
            //     return;
            // }

            showLoading(statusDiv, `Dismissing message for booking ${bookingId}...`);
            try {
                await apiCall(`/api/bookings/${bookingId}/clear_admin_message`, { method: 'POST' });
                showSuccess(statusDiv, `Message for booking ${bookingId} dismissed.`);

                // Remove the entire admin-deleted-item div
                const messageItemDiv = target.closest('.admin-deleted-item');
                if (messageItemDiv) {
                    messageItemDiv.remove();
                } else {
                    // Fallback if the structure is unexpected, try to remove the button's parent at least
                    target.parentElement.remove();
                }

                if (bookingsListDiv.children.length === 0) {
                    showStatusMessage(statusDiv, 'You have no active bookings or messages.', 'info');
                }
            } catch (error) {
                console.error('Error dismissing admin message:', error);
                showError(statusDiv, error.message || `Failed to dismiss message for booking ${bookingId}.`);
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

        // Refined "No Changes" detection
        const originalButtonText = saveBookingTitleBtn.textContent; // Keep this for button state reset later
        const bookingItemDiv = bookingsListDiv.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
        let noChangesMade = false;

        if (bookingItemDiv) {
            const originalTitle = bookingItemDiv.querySelector('.booking-title').dataset.originalTitle;
            const originalStartTimeISO = bookingItemDiv.dataset.startTime; // Full ISO string from booking item
            const originalEndTimeISO = bookingItemDiv.dataset.endTime;     // Full ISO string from booking item

            const titleChanged = newTitle !== originalTitle;
            let timeChanged = false;

            // Selected date and slot are already validated to be present by checks above.
            // isoStartTime and isoEndTime are already constructed based on selectedDate and selectedSlot.
            if (isoStartTime !== originalStartTimeISO || isoEndTime !== originalEndTimeISO) {
                timeChanged = true;
            }

            if (!titleChanged && !timeChanged) {
                noChangesMade = true;
            }
        } else {
            // If bookingItemDiv is not found, something is wrong, proceed with save and let server handle it,
            // or show an error. For now, assume it will be found or error handling later catches issues.
            console.warn(`Could not find booking item div for booking ID ${bookingId} to check for changes.`);
        }

        if (noChangesMade) {
            showStatusMessage(updateModalStatusDiv, 'No changes detected.', 'info');
            // Button state reset is handled by the finally block, but we need to return early.
            // No need to manually reset here if we return BEFORE setting to "Processing..."
            // However, the current structure sets to "Processing..." then tries to save.
            // Let's adjust. This "no changes" check should be before setting to "Processing...".
            // Re-evaluating placement: The "No changes" check should be done BEFORE "Processing..." state.
            // The current diff places this logic *after* originalButtonText is captured, which is fine.
            // The button state will be reset by the finally block if we return now.
            return;
        }

        saveBookingTitleBtn.textContent = 'Processing...';
        saveBookingTitleBtn.disabled = true;
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
            // Ensure showError is available or use showStatusMessage
            if (typeof showError === 'function') {
                 showError(updateModalStatusDiv, error.message || 'Failed to update booking.');
            } else {
                showStatusMessage(updateModalStatusDiv, error.message || 'Failed to update booking.', 'danger');
            }
        } finally {
            saveBookingTitleBtn.textContent = originalButtonText;
            saveBookingTitleBtn.disabled = false;
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
                let resourceMaintenanceStatus = { is_under_maintenance: false, maintenance_until: null };
                const selectedDateString = modalBookingDateInput.value; // Ensure this is in YYYY-MM-DD

                try {
                    // This call will either return booked slots (200 OK) or an error if resource is unavailable/under maintenance.
                    // We are primarily interested in the error case for maintenance.
                    await apiCall(`/api/resources/${resourceId}/availability?date=${selectedDateString}`);
                    // If the call succeeds (200 OK), it means the resource is generally available for booking on this date,
                    // so we assume it's not under prohibitive maintenance for this date.
                } catch (error) {
                    if (error.response && error.response.status === 403) {
                        try {
                            const errorData = await error.response.json();
                            if (errorData.error && errorData.error.toLowerCase().includes('maintenance')) {
                                resourceMaintenanceStatus.is_under_maintenance = true;
                                // 'maintenance_until' is not directly available from this error structure,
                                // but the 403 implies maintenance for the selectedDate.
                                console.log(`Resource ${resourceId} is under maintenance on ${selectedDateString}. Error: ${errorData.error}`);
                            } else {
                                console.warn(`Received 403 from /availability for resource ${resourceId} but error message doesn't indicate maintenance:`, errorData.error);
                                // Potentially treat as other critical error if slot calculation depends on availability data not just maintenance.
                                // For now, if not maintenance, assume other 403s might still allow slot display if other data is fetched.
                                // However, the current logic path after this try-catch doesn't rely on successful data from /availability,
                                // so a non-maintenance 403 might not break things unless it was meant to provide data.
                                // If the error is critical enough to stop, use clearAndDisableSlotsSelect and return.
                            }
                        } catch (parseError) {
                            console.warn(`Could not parse JSON from 403 error response for /availability on resource ${resourceId}:`, parseError);
                            // Treat as a general failure to get maintenance status, could default to not maintained or stop.
                            // To be safe, if we can't parse the specific error, we might not know if it's safe to proceed.
                        }
                    } else if (error.response && error.response.status === 404) {
                        console.error(`Resource ${resourceId} not found when checking availability.`);
                        showModalStatus(`Error: Resource details not found (ID: ${resourceId}).`, 'danger');
                        clearAndDisableSlotsSelect("Error fetching resource details.");
                        return; // Stop further processing for slots
                    } else {
                        // Other unexpected errors (e.g., 500, network error)
                        console.error(`Error fetching resource availability for ${resourceId} on ${selectedDateString}:`, error);
                        showModalStatus('Error checking resource availability. Please try again.', 'danger');
                        clearAndDisableSlotsSelect("Error checking resource availability.");
                        return; // Stop further processing for slots
                    }
                }

                // Fetch user's own bookings for the selected date
                // The endpoint /api/bookings/my_bookings_for_date?date=${selectedDateString} needs to be implemented
                // For now, let's assume it exists or adapt.
                // If not, we might need to fetch all user bookings and filter, which is less ideal.
                // Let's placeholder the call:
                let usersBookingsOnDate = [];
                try {
                    // Use selectedDateString for consistency
                    usersBookingsOnDate = await apiCall(`/api/bookings/my_bookings_for_date?date=${selectedDateString}`);
                } catch (e) {
                    // If endpoint doesn't exist, this will fail. Log and continue, conflict check will be partial.
                    console.warn(`Could not fetch user's bookings for date ${selectedDateString}. User conflict check might be incomplete. Error: ${e.message}`);
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
                    if (isAvailable && resourceMaintenanceStatus.is_under_maintenance) {
                        // If the /availability call returned a 403 due to maintenance for the selectedDate,
                        // then all slots on this day for this resource are considered unavailable due to maintenance.
                        console.log(`Slot ${slot.name} on ${selectedDateString} for resource ${resourceId} is unavailable due to maintenance.`);
                        isAvailable = false;
                        unavailabilityReason = " (Resource under maintenance)";
                    }

                    // User's Own Bookings Check (excluding the current booking being edited)
                    if (isAvailable && usersBookingsOnDate && usersBookingsOnDate.length > 0) {
                        for (const userBooking of usersBookingsOnDate) {
                            // Ensure currentBookingId is a string if userBooking.id is a number, or vice-versa, for comparison.
                            // Assuming userBooking.booking_id from the API.
                            if (userBooking.booking_id && userBooking.booking_id.toString() === currentBookingId) {
                                continue;
                            }
                            // Defensive check for start_time and end_time
                            if (!userBooking || typeof userBooking.start_time !== 'string' || !userBooking.start_time.trim() ||
                                typeof userBooking.end_time !== 'string' || !userBooking.end_time.trim()) {
                                console.warn('Skipping a user booking due to missing or invalid start/end time:', userBooking);
                                continue; // Skip this iteration
                            }

                            // Construct full Date objects for user's other bookings using selectedDateString
                            const userBookingStartDateTime = new Date(`${selectedDateString}T${userBooking.start_time}Z`); // Assume times are UTC
                            const userBookingEndDateTime = new Date(`${selectedDateString}T${userBooking.end_time}Z`);   // Assume times are UTC

                            // Validate date objects
                            if (isNaN(userBookingStartDateTime.getTime()) || isNaN(userBookingEndDateTime.getTime())) {
                                console.warn('Skipping a user booking due to invalid date construction from start/end time:', userBooking);
                                continue;
                            }

                            if (checkOverlap(slotStartDateTime, slotEndDateTime, userBookingStartDateTime, userBookingEndDateTime)) {
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
                showModalStatus(`Error loading slots: ${error.message}`, 'danger'); // Use showModalStatus
                clearAndDisableSlotsSelect("Error loading slots."); // Use helper
            }
        });
    }

    // Helper functions
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
