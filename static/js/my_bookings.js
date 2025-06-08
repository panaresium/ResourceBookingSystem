document.addEventListener('DOMContentLoaded', () => {
    const upcomingBookingsContainer = document.getElementById('upcoming-bookings-container');
    const pastBookingsContainer = document.getElementById('past-bookings-container');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status'); // Used by multiple functions in this scope

    // Filter Elements
    const statusFilterSelect = document.getElementById('my-bookings-status-filter');
    const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
    const datePickerContainer = document.getElementById('my-bookings-date-picker-container');
    const datePickerInput = document.getElementById('my-bookings-date-picker');
    let flatpickrInstance = null;

    // Visibility Toggles
    const toggleUpcomingCheckbox = document.getElementById('toggle-upcoming-bookings');
    const togglePastCheckbox = document.getElementById('toggle-past-bookings');

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
        updateModalElement.style.display = 'none'; 
    }

    // Pagination State
    let currentUpcomingPage = 1;
    let currentPastPage = 1;
    let itemsPerPage = 10; // Default, will be updated by selector
    let totalUpcomingPages = 1;
    let totalPastPages = 1;

    // Pagination Control Elements (assuming these IDs in HTML)
    const upcomingPaginationControls = document.getElementById('upcoming-bookings-pagination-controls');
    const pastPaginationControls = document.getElementById('past-bookings-pagination-controls');
    const itemsPerPageSelect = document.getElementById('items-per-page-select'); // Assuming one selector for both

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

    function createBookingCardElement(booking, checkInOutEnabled) {
        const bookingItemClone = bookingItemTemplate.content.cloneNode(true);
        const bookingItemDiv = bookingItemClone.querySelector('.booking-item');

        // Apply conditional classes for status
        bookingItemDiv.classList.remove('booking-completed', 'booking-cancelled', 'booking-rejected', 'booking-cancelled-by-admin', 'booking-cancelled-admin-acknowledged');
        const statusClass = `booking-${booking.status.toLowerCase().replace(/_/g, '-')}`;
        bookingItemDiv.classList.add(statusClass);

        bookingItemDiv.dataset.bookingId = booking.id;
        bookingItemDiv.dataset.resourceId = booking.resource_id;
        bookingItemDiv.dataset.startTime = booking.start_time;
        bookingItemDiv.dataset.endTime = booking.end_time;

        // Populate new structure
        bookingItemClone.querySelector('.booking-title-value').textContent = booking.title || 'N/A';
        bookingItemClone.querySelector('.resource-name-value').textContent = booking.resource_name || 'N/A';

        const startDate = new Date(booking.start_time);
        const endDate = new Date(booking.end_time);

        // Date formatting
        const optionsDate = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' };
        const formattedDate = startDate.toLocaleDateString(undefined, optionsDate); // Uses browser locale but with UTC interpretation

        // Time formatting (24-hour format)
        const optionsTime = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' };
        const formattedStartTime = startDate.toLocaleTimeString(undefined, optionsTime);
        const formattedEndTime = endDate.toLocaleTimeString(undefined, optionsTime);

        bookingItemClone.querySelector('.booking-date-value').textContent = formattedDate;
        bookingItemClone.querySelector('.booking-start-time-value').textContent = formattedStartTime;
        bookingItemClone.querySelector('.booking-end-time-value').textContent = formattedEndTime;

        const recurrenceRuleValueSpan = bookingItemClone.querySelector('.recurrence-rule-value');
        if (recurrenceRuleValueSpan) {
            recurrenceRuleValueSpan.textContent = booking.recurrence_rule || 'None';
        }

        // Store original title and ISO times for update modal, if still needed elsewhere.
        // The dataset attributes on bookingItemDiv for start/end time are already ISO.
        // If the update modal relies on specific elements having original values, that needs checking.
        // For now, assume the main display is the priority.
        const titleSpan = bookingItemClone.querySelector('.booking-title-value'); // Already populated
        titleSpan.dataset.originalTitle = booking.title || ''; // Set original title for comparison later

        const updateBtn = bookingItemClone.querySelector('.update-booking-btn');
        updateBtn.dataset.bookingId = booking.id;

        const cancelBtn = bookingItemClone.querySelector('.cancel-booking-btn');
        cancelBtn.dataset.bookingId = booking.id;

        const checkInBtn = bookingItemClone.querySelector('.check-in-btn');
        const checkOutBtn = bookingItemClone.querySelector('.check-out-btn');
        const checkInControls = bookingItemClone.querySelector('.check-in-controls');
        const pinInput = bookingItemClone.querySelector('.booking-pin-input');

        const bookingStatusValueSpan = bookingItemClone.querySelector('.booking-status-value');
        if (bookingStatusValueSpan) {
            let statusText = booking.status ? booking.status.charAt(0).toUpperCase() + booking.status.slice(1).replace(/_/g, ' ') : 'Unknown';
            if (booking.status === 'cancelled_by_admin' || booking.status === 'cancelled_admin_acknowledged') {
                statusText = 'Cancelled by Administrator';
            }
            // Add more user-friendly status text as needed, e.g., for 'approved':
            // else if (booking.status === 'approved') { statusText = 'Approved'; }
            bookingStatusValueSpan.textContent = statusText;
        }

        if (checkInControls) checkInControls.style.display = 'none';
        if (checkOutBtn) checkOutBtn.style.display = 'none';
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
        if (updateBtn) updateBtn.style.display = 'inline-block';

        const terminalStatuses = ['completed', 'cancelled', 'rejected', 'cancelled_by_admin', 'cancelled_admin_acknowledged'];
        if (terminalStatuses.includes(booking.status)) {
            if (checkInControls) checkInControls.style.display = 'none';
            if (checkOutBtn) checkOutBtn.style.display = 'none';
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (updateBtn) updateBtn.style.display = 'none';
        } else if (checkInOutEnabled) {
            if (booking.can_check_in && !booking.checked_in_at) {
                if (checkInControls) checkInControls.style.display = 'inline-block';
            }
            if (booking.checked_in_at && !booking.checked_out_at) {
                if (checkOutBtn) checkOutBtn.style.display = 'inline-block';
                if (checkInControls) checkInControls.style.display = 'none';
            }
        } else {
            if (checkInControls) checkInControls.style.display = 'none';
            if (checkOutBtn) checkOutBtn.style.display = 'none';
        }

        if (checkInBtn) checkInBtn.dataset.bookingId = booking.id;
        if (pinInput) pinInput.dataset.bookingId = booking.id;
        if (checkOutBtn) checkOutBtn.dataset.bookingId = booking.id;

        return bookingItemDiv;
    }

    async function fetchAndDisplayBookings() {
        const myBookingsStatusDiv = document.getElementById('my-bookings-status');

        if (!upcomingBookingsContainer || !pastBookingsContainer) {
            console.error('My Bookings page structure is missing essential container elements.');
            if (myBookingsStatusDiv) showStatusMessage(myBookingsStatusDiv, 'Error: Could not load booking display components.', 'danger');
            return;
        }

        // Show loading messages
        upcomingBookingsContainer.innerHTML = '<p class="loading-message">{{ _("Loading upcoming bookings...") }}</p>';
        pastBookingsContainer.innerHTML = '<p class="loading-message">{{ _("Loading past bookings...") }}</p>';
        if (upcomingPaginationControls) upcomingPaginationControls.innerHTML = ''; // Clear old controls
        if (pastPaginationControls) pastPaginationControls.innerHTML = ''; // Clear old controls
        if (myBookingsStatusDiv) hideStatusMessage(myBookingsStatusDiv);


        let apiUrl = '/api/bookings/my_bookings';
        const params = new URLSearchParams();

        // Append pagination parameters
        params.append('upcoming_page', currentUpcomingPage);
        params.append('upcoming_per_page', itemsPerPage);
        params.append('past_page', currentPastPage);
        params.append('past_per_page', itemsPerPage);

        if (statusFilterSelect && statusFilterSelect.value !== 'all') {
            params.append('status_filter', statusFilterSelect.value);
        }
        if (dateFilterTypeSelect && dateFilterTypeSelect.value === 'specific' && datePickerInput && datePickerInput.value) {
            params.append('date_filter_value', datePickerInput.value);
        }

        apiUrl += `?${params.toString()}`;

        try {
            // Disable controls during fetch
            if (itemsPerPageSelect) itemsPerPageSelect.disabled = true;
            // (Pagination controls will be rebuilt, so disabling existing ones isn't strictly necessary if cleared)

            const apiResponse = await apiCall(apiUrl, {}, myBookingsStatusDiv); // myBookingsStatusDiv for errors

            // Update global pagination state from response
            currentUpcomingPage = apiResponse.upcoming_bookings.page;
            totalUpcomingPages = apiResponse.upcoming_bookings.total_pages;
            currentPastPage = apiResponse.past_bookings.page;
            totalPastPages = apiResponse.past_bookings.total_pages;
            // itemsPerPage is already known globally, but response might confirm it:
            // itemsPerPage = apiResponse.upcoming_bookings.per_page; // if server can override

            const upcomingBookingItems = apiResponse.upcoming_bookings.items;
            const pastBookingItems = apiResponse.past_bookings.items;
            const checkInOutEnabled = apiResponse.check_in_out_enabled;

            upcomingBookingsContainer.innerHTML = '';
            pastBookingsContainer.innerHTML = '';

            if ((!upcomingBookingItems || upcomingBookingItems.length === 0) && (!pastBookingItems || pastBookingItems.length === 0)) {
                if (myBookingsStatusDiv) showStatusMessage(myBookingsStatusDiv, '{{ _("You have no bookings matching the current filters.") }}', 'info');
                upcomingBookingsContainer.innerHTML = '<p>{{ _("No upcoming bookings found.") }}</p>';
                pastBookingsContainer.innerHTML = '<p>{{ _("No past booking history found.") }}</p>';
            } else {
                if (upcomingBookingItems && upcomingBookingItems.length > 0) {
                    upcomingBookingItems.forEach(booking => {
                        const bookingCard = createBookingCardElement(booking, checkInOutEnabled);
                        upcomingBookingsContainer.appendChild(bookingCard);
                    });
                } else {
                    upcomingBookingsContainer.innerHTML = '<p>{{ _("No upcoming bookings found matching your filters.") }}</p>';
                }

                if (pastBookingItems && pastBookingItems.length > 0) {
                    pastBookingItems.forEach(booking => {
                        const bookingCard = createBookingCardElement(booking, checkInOutEnabled);
                        pastBookingsContainer.appendChild(bookingCard);
                    });
                } else {
                    pastBookingsContainer.innerHTML = '<p>{{ _("No past booking history found matching your filters.") }}</p>';
                }
            }

            renderPaginationControls('upcoming', apiResponse.upcoming_bookings);
            renderPaginationControls('past', apiResponse.past_bookings);

            if (myBookingsStatusDiv && myBookingsStatusDiv.textContent === '{{ _("Loading your bookings...") }}' && !myBookingsStatusDiv.classList.contains('alert-danger')) {
                 hideStatusMessage(myBookingsStatusDiv);
            }
        } catch (error) {
            console.error('Error fetching bookings:', error);
            upcomingBookingsContainer.innerHTML = '<p>{{ _("Could not load upcoming bookings.") }}</p>';
            pastBookingsContainer.innerHTML = '<p>{{ _("Could not load past bookings.") }}</p>';
            // apiCall likely already showed an error in myBookingsStatusDiv
        } finally {
            // Re-enable controls
            if (itemsPerPageSelect) itemsPerPageSelect.disabled = false;
        }
    }

    function renderPaginationControls(section, paginationData) {
        const container = section === 'upcoming' ? upcomingPaginationControls : pastPaginationControls;
        if (!container) return;
        container.innerHTML = ''; // Clear previous controls

        if (paginationData.total_pages <= 1) return;

        const nav = document.createElement('nav');
        nav.setAttribute('aria-label', `${section} bookings navigation`);
        const ul = document.createElement('ul');
        ul.className = 'pagination pagination-sm justify-content-center';

        // Previous button
        const prevLi = document.createElement('li');
        prevLi.className = `page-item ${paginationData.page === 1 ? 'disabled' : ''}`;
        const prevLink = document.createElement('a');
        prevLink.className = 'page-link';
        prevLink.href = '#';
        prevLink.innerHTML = '&laquo;'; // Use innerHTML for HTML entities
        prevLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (paginationData.page > 1) {
                if (section === 'upcoming') {
                    currentUpcomingPage--;
                } else {
                    currentPastPage--;
                }
                fetchAndDisplayBookings();
                const myBookingsListElement = document.getElementById('my-bookings-list');
                if (myBookingsListElement) {
                    myBookingsListElement.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
        prevLi.appendChild(prevLink);
        ul.appendChild(prevLi);

        // Page numbers with iter_pages-like logic
        const currentPage = paginationData.page;
        const totalPages = paginationData.total_pages;
        const leftEdge = 1;
        const rightEdge = 1;
        const leftCurrent = 2;
        const rightCurrent = 3;
        let lastPagePrinted = 0;

        for (let p = 1; p <= totalPages; p++) {
            const showPage = (p <= leftEdge) ||
                             (p > totalPages - rightEdge) ||
                             (p >= currentPage - leftCurrent && p <= currentPage + rightCurrent);

            if (showPage) {
                if (p > lastPagePrinted + 1) {
                    // Add ellipsis if there was a gap
                    const ellipsisLi = document.createElement('li');
                    ellipsisLi.className = 'page-item disabled';
                    const ellipsisSpan = document.createElement('span');
                    ellipsisSpan.className = 'page-link';
                    ellipsisSpan.textContent = '...';
                    ellipsisLi.appendChild(ellipsisSpan);
                    ul.appendChild(ellipsisLi);
                }

                const pageLi = document.createElement('li');
                pageLi.className = `page-item ${p === currentPage ? 'active' : ''}`;
                const pageLink = document.createElement('a');
                pageLink.className = 'page-link';
                pageLink.href = '#';
                pageLink.textContent = p;
                pageLink.addEventListener('click', ((pageNum) => (e) => { // IIFE to capture pageNum
                    e.preventDefault();
                    if (section === 'upcoming') {
                        currentUpcomingPage = pageNum;
                    } else {
                        currentPastPage = pageNum;
                    }
                    fetchAndDisplayBookings();
                const myBookingsListElement = document.getElementById('my-bookings-list');
                if (myBookingsListElement) {
                    myBookingsListElement.scrollIntoView({ behavior: 'smooth' });
                }
                })(p));
                pageLi.appendChild(pageLink);
                ul.appendChild(pageLi);
                lastPagePrinted = p;
            } else if (p === lastPagePrinted + 1 && p > leftEdge && p <= totalPages - rightEdge) {
                // Ensure ellipsis is not printed right after leftEdge or before rightEdge if not needed
            }
        }
         // Final ellipsis if needed before the right edge (if lastPagePrinted is far from totalPages - rightEdge + 1)
        if (lastPagePrinted < totalPages - rightEdge && totalPages > (leftEdge + leftCurrent + rightCurrent + rightEdge)) {
             const ellipsisLi = document.createElement('li');
             ellipsisLi.className = 'page-item disabled';
             const ellipsisSpan = document.createElement('span');
             ellipsisSpan.className = 'page-link';
             ellipsisSpan.textContent = '...';
             ellipsisLi.appendChild(ellipsisSpan);
             ul.appendChild(ellipsisLi);
        }


        // Next button
        const nextLi = document.createElement('li');
        nextLi.className = `page-item ${paginationData.page === paginationData.total_pages ? 'disabled' : ''}`;
        const nextLink = document.createElement('a');
        nextLink.className = 'page-link';
        nextLink.href = '#';
        nextLink.innerHTML = '&raquo;'; // Use innerHTML for HTML entities
        nextLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (paginationData.page < paginationData.total_pages) {
                if (section === 'upcoming') {
                    currentUpcomingPage++;
                } else {
                    currentPastPage++;
                }
                fetchAndDisplayBookings();
                const myBookingsListElement = document.getElementById('my-bookings-list');
                if (myBookingsListElement) {
                    myBookingsListElement.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
        nextLi.appendChild(nextLink);
        ul.appendChild(nextLi);

        nav.appendChild(ul);
        container.appendChild(nav);
    }


    // Event listener for dynamically created buttons
    // Using document as the closest static parent, can be refined if #my-bookings-list is always present
    document.addEventListener('click', async (event) => {
        const target = event.target;

        // Check if the click is within the new containers or their children
        // This helps avoid processing clicks on other parts of the page if this listener is too broad.
        const clickedBookingItem = target.closest('.booking-item');
        if (!clickedBookingItem || (!upcomingBookingsContainer.contains(clickedBookingItem) && !pastBookingsContainer.contains(clickedBookingItem))) {
            // If the click is not on a booking item within our containers, do nothing specific here.
            // Modal clicks are handled separately by their own listeners on modal buttons.
            // This check is important if 'document' is used as the listener base.
            if (!target.closest('.modal')) { // Allow clicks inside modals
                 return;
            }
        }

        if (target.classList.contains('cancel-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            if (confirm(`Are you sure you want to cancel booking ID ${bookingId}?`)) {
                showLoading(statusDiv, `Cancelling booking ${bookingId}...`);
                try {
                    await apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' });
                    showSuccess(statusDiv, `Booking ${bookingId} cancelled successfully.`);
                    const bookingItemToRemove = target.closest('.booking-item');
                    const parentContainer = bookingItemToRemove.parentElement; // upcomingBookingsContainer or pastBookingsContainer

                    if (bookingItemToRemove) {
                        bookingItemToRemove.remove();
                    }

                    // Check if specific container is empty
                    if (parentContainer === upcomingBookingsContainer && upcomingBookingsContainer.children.length === 0) {
                        upcomingBookingsContainer.innerHTML = '<p>No upcoming bookings.</p>';
                    } else if (parentContainer === pastBookingsContainer && pastBookingsContainer.children.length === 0) {
                        pastBookingsContainer.innerHTML = '<p>No past booking history.</p>';
                    }

                    // Check if both containers are empty to show overall "no bookings" message
                    if (upcomingBookingsContainer.children.length === 0 && pastBookingsContainer.children.length === 0) {
                        // This might overwrite the specific "no upcoming/past" messages if statusDiv is global.
                        // Consider if a different global message area is better or if this is fine.
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

            if (!bookingItemDiv) {
                console.error('Could not find .booking-item parent for update button.');
                return;
            }

            const titleValueElement = bookingItemDiv.querySelector('.booking-title-value');
            const resourceNameElement = bookingItemDiv.querySelector('.resource-name-value');

            if (!titleValueElement || !resourceNameElement) {
                console.error('Could not find title or resource name element within booking item.');
                return;
            }

            const currentTitle = titleValueElement.dataset.originalTitle || titleValueElement.textContent; // Use originalTitle if available, else current text
            const currentStartTimeISO = bookingItemDiv.dataset.startTime;
            const resourceName = resourceNameElement.textContent;
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
            const pinInput = document.querySelector(`.booking-pin-input[data-booking-id='${bookingId}']`);
            const pinValue = pinInput ? pinInput.value.trim() : null;

            let payload = {};
            if (pinValue && pinValue !== "") {
                payload.pin = pinValue;
            }

            showLoading(statusDiv, 'Checking in...');
            try {
                // Pass CSRF token if your apiCall helper doesn't handle it globally for POST/PUT etc.
                // For now, assuming apiCall or a global fetch wrapper handles CSRF if needed.
                await apiCall(`/api/bookings/${bookingId}/check_in`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }, // Ensure correct header
                    body: JSON.stringify(payload) // Send payload
                });
                // Hide the entire check-in controls (input + button)
                const checkInControls = target.closest('.check-in-controls');
                if (checkInControls) checkInControls.style.display = 'none';

                const bookingItemDiv = target.closest('.booking-item');
                const checkOutBtn = bookingItemDiv.querySelector('.check-out-btn');
                if (checkOutBtn) checkOutBtn.style.display = 'inline-block';
                showSuccess(statusDiv, 'Checked in successfully.');
                if (pinInput) pinInput.value = ''; // Clear PIN input
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
            // This button should no longer be generated for the user view.
            // If it were, this is where its client-side logic would be.
            // For robustness, we can leave the handler, but it shouldn't be triggered from user UI.
            console.warn("'clear-admin-message-btn' was clicked, but this button should not be available to users on my_bookings page.");
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

        // Find the booking item in either upcoming or past container
        let bookingItemDiv = upcomingBookingsContainer.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
        if (!bookingItemDiv) {
            bookingItemDiv = pastBookingsContainer.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
        }
        let noChangesMade = false;

        if (bookingItemDiv) {
            const titleValueElement = bookingItemDiv.querySelector('.booking-title-value');
            const originalTitle = titleValueElement ? (titleValueElement.dataset.originalTitle || titleValueElement.textContent) : '';
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
            
            // Update the UI (find in either upcoming or past container)
            let bookingItemDiv = upcomingBookingsContainer.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
            if (!bookingItemDiv) {
                bookingItemDiv = pastBookingsContainer.querySelector(`.booking-item[data-booking-id="${bookingId}"]`);
            }

            if (bookingItemDiv) {
                const titleValueSpan = bookingItemDiv.querySelector('.booking-title-value');
                if (titleValueSpan) {
                    titleValueSpan.textContent = updatedBooking.title;
                    titleValueSpan.dataset.originalTitle = updatedBooking.title; // Update original title as well
                }

                // Assuming booking-date-value, booking-start-time-value, booking-end-time-value are the correct classes for display
                const dateValueSpan = bookingItemDiv.querySelector('.booking-date-value');
                const startTimeValueSpan = bookingItemDiv.querySelector('.booking-start-time-value');
                const endTimeValueSpan = bookingItemDiv.querySelector('.booking-end-time-value');

                const newStartDate = new Date(updatedBooking.start_time);
                const newEndDate = new Date(updatedBooking.end_time);

                if (dateValueSpan) dateValueSpan.textContent = newStartDate.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
                if (startTimeValueSpan) startTimeValueSpan.textContent = newStartDate.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' });
                if (endTimeValueSpan) endTimeValueSpan.textContent = newEndDate.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' });

                // Update dataset attributes on the .booking-item itself
                bookingItemDiv.dataset.startTime = updatedBooking.start_time;
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
    
    // Event Listeners for filters
    function handleFilterChange() {
        currentUpcomingPage = 1; // Reset to first page on filter change
        currentPastPage = 1;     // Reset to first page on filter change
        fetchAndDisplayBookings();
    }

    if (statusFilterSelect) {
        statusFilterSelect.addEventListener('change', handleFilterChange);
    }

    if (dateFilterTypeSelect) {
        dateFilterTypeSelect.addEventListener('change', function() {
            if (this.value === 'specific') {
                if (datePickerContainer) datePickerContainer.style.display = 'block';
                if (flatpickrInstance) flatpickrInstance.open();
            } else {
                if (datePickerContainer) datePickerContainer.style.display = 'none';
                if (datePickerInput) datePickerInput.value = '';
                if (flatpickrInstance) flatpickrInstance.clear();
                handleFilterChange();
            }
        });
    }

    // Initialize Flatpickr for the date picker
    if (datePickerInput && typeof flatpickr === "function") {
        flatpickrInstance = flatpickr(datePickerInput, {
            dateFormat: "Y-m-d",
            onChange: function(selectedDates, dateStr, instance) {
                if (dateFilterTypeSelect && dateFilterTypeSelect.value === 'specific') {
                    fetchAndDisplayBookings();
                }
            }
        });
    } else {
        console.warn("Flatpickr not available or datePickerInput not found. Date picker will not be initialized.");
    }

    // Items per page selector
    if (itemsPerPageSelect) {
        itemsPerPageSelect.addEventListener('change', function() {
            itemsPerPage = parseInt(this.value, 10);
            currentUpcomingPage = 1;
            currentPastPage = 1;
            fetchAndDisplayBookings();
            const myBookingsListElement = document.getElementById('my-bookings-list');
            if (myBookingsListElement) {
                myBookingsListElement.scrollIntoView({ behavior: 'smooth' });
            }
        });
        // Set initial itemsPerPage from the select, in case HTML has a default selected
        itemsPerPage = parseInt(itemsPerPageSelect.value, 10);
    }


    // Set default status filter before the initial fetch
    if (statusFilterSelect) {
        statusFilterSelect.value = 'approved';
    }

    // Initial fetch of bookings - now uses default filter values
    fetchAndDisplayBookings();

    // Visibility toggles (existing logic from previous step)
    function updateSectionVisibility() {
        const upcomingContainer = document.getElementById('upcoming-bookings-container');
        const pastContainer = document.getElementById('past-bookings-container');

        if (toggleUpcomingCheckbox && upcomingContainer) {
            upcomingContainer.style.display = toggleUpcomingCheckbox.checked ? '' : 'none';
        }
        if (togglePastCheckbox && pastContainer) {
            pastContainer.style.display = togglePastCheckbox.checked ? '' : 'none';
        }
    }

    if (toggleUpcomingCheckbox && togglePastCheckbox) {
        updateSectionVisibility(); // Initial call

        toggleUpcomingCheckbox.addEventListener('change', updateSectionVisibility);
        togglePastCheckbox.addEventListener('change', updateSectionVisibility);
    } else {
        console.warn("Visibility toggle checkboxes not found. Section visibility control will not be active.");
    }
});

