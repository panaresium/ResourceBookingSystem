// static/js/booking_modal_handler.js
// Ensure this script is loaded after Bootstrap's JS

// Store the Bootstrap modal instance globally within this handler's scope
let bookingSlotModalInstance;
let currentModalOptions = {}; // To store options for current modal session

document.addEventListener('DOMContentLoaded', () => {
    const modalElement = document.getElementById('booking-slot-modal');
    if (modalElement) {
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            bookingSlotModalInstance = new bootstrap.Modal(modalElement);
            // Explicitly hide modal on initialization to counter any premature display issues.
            if (bookingSlotModalInstance) {
                bookingSlotModalInstance.hide();
                console.log('Modal #booking-slot-modal explicitly hidden by JS on init via booking_modal_handler.js.');
            }
        } else {
            console.error("Bootstrap Modal class not found. Booking modal may not function correctly.");
            // Basic fallback for showing/hiding if Bootstrap JS fails to load (very basic)
            bookingSlotModalInstance = {
                show: () => { modalElement.style.display = 'block'; },
                hide: () => { modalElement.style.display = 'none'; }
            };
        }
    } else {
        console.error("Booking modal element (#booking-slot-modal) not found.");
        return; // Stop if modal element doesn't exist
    }

    // Attach event listener for the save button within the modal
    const saveBtn = document.getElementById('modal-save-booking-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', handleSaveBooking);
    }

    // Attach event listener for date change to load slots
    const dateInput = document.getElementById('modal-booking-date');
    if (dateInput) {
        dateInput.addEventListener('change', loadAvailableSlotsForModal);
    }

    // Add event listener for when the modal is hidden
    if (modalElement) {
        modalElement.addEventListener('hidden.bs.modal', function () {
            const closeButton = document.querySelector('#booking-slot-modal .modal-footer .btn-secondary[data-bs-dismiss="modal"]');
            if (closeButton) {
                closeButton.setAttribute('tabindex', '-1');
                console.log('Modal hidden: Close button tabindex set to -1.');
            }
        });
    }
});

// Helper to show messages within the modal
function showModalStatus(message, type = 'info') {
    const statusDiv = document.getElementById('modal-status-div');
    if (statusDiv) {
        statusDiv.textContent = message;
        statusDiv.className = `alert alert-${type}`; // Assumes Bootstrap alert classes
        statusDiv.style.display = 'block';
    }
}

function hideModalStatus() {
    const statusDiv = document.getElementById('modal-status-div');
    if (statusDiv) {
        statusDiv.style.display = 'none';
    }
}

// Helper to clear and disable slot selection
function clearAndDisableSlotsSelect(message) {
    const slotsSelect = document.getElementById('modal-available-slots-select');
    if (slotsSelect) {
        slotsSelect.innerHTML = `<option value="">${message}</option>`;
        slotsSelect.disabled = true;
    }
}


async function loadAvailableSlotsForModal() {
    if (!currentModalOptions.resourceId) {
        console.error("Resource ID not set for loading slots.");
        clearAndDisableSlotsSelect("Resource ID missing.");
        return;
    }

    const resourceId = currentModalOptions.resourceId;
    const selectedDateString = document.getElementById('modal-booking-date').value;
    const slotsSelect = document.getElementById('modal-available-slots-select');
    const currentEditingBookingId = (currentModalOptions.mode === 'update') ? currentModalOptions.bookingId : null;

    if (!selectedDateString) {
        clearAndDisableSlotsSelect("Select a date first.");
        return;
    }

    slotsSelect.innerHTML = '<option value="">Loading available slots...</option>';
    slotsSelect.disabled = true;
    hideModalStatus();

    try {
        let resourceMaintenanceStatus = { is_under_maintenance: false, maintenance_until: null };
        try {
            await apiCall(`/api/resources/${resourceId}/availability?date=${selectedDateString}`);
        } catch (error) {
            if (error.response && error.response.status === 403) {
                const errorData = await error.response.json();
                if (errorData.error && errorData.error.toLowerCase().includes('maintenance')) {
                    resourceMaintenanceStatus.is_under_maintenance = true;
                }
            } else if (error.response && error.response.status === 404) {
                showModalStatus(`Error: Resource (ID: ${resourceId}) not found.`, 'danger');
                clearAndDisableSlotsSelect("Resource not found.");
                return;
            } else {
                showModalStatus('Error checking resource availability.', 'danger');
                clearAndDisableSlotsSelect("Error checking availability.");
                return;
            }
        }

        const usersBookingsOnDate = await apiCall(`/api/bookings/my_bookings_for_date?date=${selectedDateString}`);

        const predefinedSlots = [
            { name: "Morning (08:00-12:00 UTC)", start: "08:00", end: "12:00" },
            { name: "Afternoon (13:00-17:00 UTC)", start: "13:00", end: "17:00" },
            { name: "Full Day (08:00-17:00 UTC)", start: "08:00", end: "17:00" }
        ];
        slotsSelect.innerHTML = '<option value="">-- Select a time slot --</option>';
        let availableSlotsFound = 0;

        const now = new Date();
        // const selectedDateObj = new Date(selectedDateString + "T00:00:00Z"); // Treat selectedDateString as UTC

        for (const slot of predefinedSlots) {
            let isAvailable = true;
            let unavailableReason = "";

            const slotStartDateTime = new Date(`${selectedDateString}T${slot.start}:00Z`);
            const slotEndDateTime = new Date(`${selectedDateString}T${slot.end}:00Z`);

            if (slotEndDateTime < now) {
                isAvailable = false;
                unavailableReason = " (Past)";
            }

            if (isAvailable && resourceMaintenanceStatus.is_under_maintenance) {
                isAvailable = false;
                unavailableReason = " (Resource Maintenance)";
            }

            if (isAvailable && usersBookingsOnDate && usersBookingsOnDate.length > 0) {
                for (const userBooking of usersBookingsOnDate) {
                    if (currentEditingBookingId && userBooking.booking_id && userBooking.booking_id.toString() === currentEditingBookingId.toString()) {
                        continue;
                    }
                    if (!userBooking || typeof userBooking.start_time !== 'string' || !userBooking.start_time.trim() ||
                        typeof userBooking.end_time !== 'string' || !userBooking.end_time.trim()) {
                        console.warn('Skipping a user booking due to missing or invalid start/end time:', userBooking);
                        continue;
                    }
                    const userBookingStartDateTime = new Date(`${selectedDateString}T${userBooking.start_time}Z`);
                    const userBookingEndDateTime = new Date(`${selectedDateString}T${userBooking.end_time}Z`);
                    if (isNaN(userBookingStartDateTime.getTime()) || isNaN(userBookingEndDateTime.getTime())) {
                         console.warn('Skipping user booking due to invalid date construction:', userBooking);
                         continue;
                    }

                    if (checkOverlap(slotStartDateTime, slotEndDateTime, userBookingStartDateTime, userBookingEndDateTime)) {
                        isAvailable = false;
                        unavailableReason = " (Your Conflict)";
                        break;
                    }
                }
            }

            const option = new Option(`${slot.name}${isAvailable ? '' : unavailableReason}`, `${slot.start},${slot.end}`);
            option.disabled = !isAvailable;
            slotsSelect.add(option);
            if (isAvailable) availableSlotsFound++;
        }

        if (availableSlotsFound === 0 && slotsSelect.options.length > 1) {
             // Handled by disabling options
        } else if (slotsSelect.options.length <=1 && availableSlotsFound === 0) {
             slotsSelect.innerHTML = '<option value="">No available slots found.</option>';
        }
        slotsSelect.disabled = false;

    } catch (error) {
        console.error('Error fetching slot availability:', error);
        showModalStatus(error.message || 'Failed to load slots.', 'danger');
        clearAndDisableSlotsSelect('Error loading slots.');
    }
}

// Main function to open and configure the modal
// options: { mode: 'create'|'update', resourceId, resourceName, bookingId?, currentTitle?, currentStartTimeISO?, currentEndTimeISO?, userNameForRecord, onSaveSuccess: callback }
function openBookingModal(options) {
    currentModalOptions = options; // Store for use by event handlers

    const modalTitleEl = document.getElementById('bookingSlotModalLabel');
    const resourceNameDisplayEl = document.getElementById('modal-resource-name-display');
    const bookingTitleInputEl = document.getElementById('modal-booking-title');
    const dateInputEl = document.getElementById('modal-booking-date');
    const slotsSelectEl = document.getElementById('modal-available-slots-select');
    const saveBtnEl = document.getElementById('modal-save-booking-btn');
    const bookingIdInputEl = document.getElementById('modal-booking-id');
    const resourceIdInputEl = document.getElementById('modal-resource-id');

    // Set common fields
    resourceNameDisplayEl.value = options.resourceName || 'N/A';
    resourceIdInputEl.value = options.resourceId || '';
    hideModalStatus();

    if (options.mode === 'update') {
        modalTitleEl.textContent = `Update Booking for: ${options.resourceName}`;
        saveBtnEl.textContent = 'Save Changes';
        bookingTitleInputEl.value = options.currentTitle || '';
        bookingIdInputEl.value = options.bookingId || '';

        if (options.currentStartTimeISO) {
            const startDate = new Date(options.currentStartTimeISO);
            dateInputEl.value = startDate.toISOString().split('T')[0];
        } else {
            dateInputEl.value = '';
        }
    } else { // mode === 'create'
        modalTitleEl.textContent = `Book Resource: ${options.resourceName}`;
        saveBtnEl.textContent = 'Create Booking';
        bookingTitleInputEl.value = '';
        bookingIdInputEl.value = '';
        dateInputEl.value = '';
    }

    slotsSelectEl.innerHTML = '<option value="">-- Select a date first --</option>';
    slotsSelectEl.disabled = true;

    if (dateInputEl.value) {
        loadAvailableSlotsForModal();
    }

    // Make footer close button focusable when modal opens
    const closeButton = document.querySelector('#booking-slot-modal .modal-footer .btn-secondary[data-bs-dismiss="modal"]');
    if (closeButton) {
        closeButton.removeAttribute('tabindex');
        console.log('Modal open: Close button tabindex removed.');
    }

    if (bookingSlotModalInstance) {
        bookingSlotModalInstance.show();
    }
}

async function handleSaveBooking() {
    const saveBtn = document.getElementById('modal-save-booking-btn');
    const originalButtonText = saveBtn.textContent;

    const bookingId = document.getElementById('modal-booking-id').value;
    const resourceId = document.getElementById('modal-resource-id').value;
    const title = document.getElementById('modal-booking-title').value.trim();
    const selectedDate = document.getElementById('modal-booking-date').value;
    const selectedSlotValue = document.getElementById('modal-available-slots-select').value;

    if (!title) {
        showModalStatus('Title cannot be empty.', 'danger');
        return;
    }
    if (!selectedDate || !selectedSlotValue) {
        showModalStatus('Please select a date and a time slot.', 'danger');
        return;
    }

    const [slotStart, slotEnd] = selectedSlotValue.split(',');
    const isoStartTime = new Date(`${selectedDate}T${slotStart}:00Z`).toISOString();
    const isoEndTime = new Date(`${selectedDate}T${slotEnd}:00Z`).toISOString();

    if (currentModalOptions.mode === 'update') {
        let titleChanged = title !== (currentModalOptions.currentTitle || '');
        let timeChanged = (isoStartTime !== currentModalOptions.currentStartTimeISO) || (isoEndTime !== currentModalOptions.currentEndTimeISO);
        if (!titleChanged && !timeChanged) {
            showModalStatus('No changes detected.', 'info');
            return;
        }
    }

    saveBtn.textContent = 'Processing...';
    saveBtn.disabled = true;
    showModalStatus('Saving booking...', 'info');

    try {
        let responseData;
        const payload = {
            title: title,
            start_time: isoStartTime,
            end_time: isoEndTime,
        };

        if (currentModalOptions.mode === 'update') {
            responseData = await apiCall(`/api/bookings/${bookingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else { // 'create' mode
            payload.resource_id = resourceId;
            if (!currentModalOptions.userNameForRecord) {
                 console.error("User name for record not provided for creating booking.");
                 throw new Error("User name for record not available. Cannot create booking.");
            }
            payload.user_name = currentModalOptions.userNameForRecord;

            responseData = await apiCall('/api/bookings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        if (bookingSlotModalInstance) {
            bookingSlotModalInstance.hide();
        }
        if (currentModalOptions.onSaveSuccess && typeof currentModalOptions.onSaveSuccess === 'function') {
            currentModalOptions.onSaveSuccess(responseData);
        }

    } catch (error) {
        console.error(`Error ${currentModalOptions.mode === 'update' ? 'updating' : 'creating'} booking:`, error);
        showModalStatus(error.message || `Failed to ${currentModalOptions.mode} booking.`, 'danger');
    } finally {
        saveBtn.textContent = (currentModalOptions.mode === 'update') ? 'Save Changes' : 'Create Booking';
        saveBtn.disabled = false;
    }
}

function checkOverlap(startA, endA, startB, endB) {
    const dAStart = new Date(startA);
    const dAEnd = new Date(endA);
    const dBStart = new Date(startB);
    const dBEnd = new Date(endB);
    return dAStart < dBEnd && dAEnd > dBStart;
}
