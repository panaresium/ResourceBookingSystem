document.addEventListener('DOMContentLoaded', () => {
    const upcomingBookingsContainer = document.getElementById('upcoming-bookings-container');
    const pastBookingsContainer = document.getElementById('past-bookings-container');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status');

    // Filter Elements
    const statusFilterSelect = document.getElementById('status-filter-my-bookings'); // Corrected ID
    const resourceNameFilterInput = document.getElementById('resource-name-filter'); // New filter
    const applyFiltersBtn = document.getElementById('apply-my-bookings-filters-btn');
    const clearFiltersBtn = document.getElementById('clear-my-bookings-filters-btn');
    // Visibility Toggles
    const toggleUpcomingCheckbox = document.getElementById('toggle-upcoming-bookings');
    const togglePastCheckbox = document.getElementById('toggle-past-bookings');

    // --- Pagination State (Common) ---
    const myBookingsItemsPerPageOptions = [5, 10, 25, 50];

    // --- Upcoming Bookings Pagination State & Elements ---
    let upcomingCurrentPage = 1;
    let upcomingItemsPerPage = myBookingsItemsPerPageOptions[0];
    let upcomingTotalItems = 0;
    let upcomingTotalPages = 0;
    const upcomingPaginationContainer = document.getElementById('upcoming_bk_pg_pagination_controls_container');
    const upcomingPerPageSelect = document.getElementById('upcoming_bk_pg_per_page_select');
    const upcomingPaginationUl = document.getElementById('upcoming_bk_pg_pagination_ul');
    const upcomingTotalResultsDisplay = document.getElementById('upcoming_bk_pg_total_results_display');

    // --- Past Bookings Pagination State & Elements ---
    let pastCurrentPage = 1;
    let pastItemsPerPage = myBookingsItemsPerPageOptions[0];
    let pastTotalItems = 0;
    let pastTotalPages = 0;
    const pastPaginationContainer = document.getElementById('past_bk_pg_pagination_controls_container');
    const pastPerPageSelect = document.getElementById('past_bk_pg_per_page_select');
    const pastPaginationUl = document.getElementById('past_bk_pg_pagination_ul');
    const pastTotalResultsDisplay = document.getElementById('past_bk_pg_total_results_display');
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
        if (!element) return;
        element.textContent = message;
        element.className = `alert alert-${type}`;
        element.style.display = 'block';
    }

    function hideStatusMessage(element) {
        if (!element) return;
        element.style.display = 'none';
    }

    function showModalStatus(message, type = 'info') {
        showStatusMessage(updateModalStatusDiv, message, type);
    }

    function clearAndDisableSlotsSelect(message) {
        const slotsSelect = document.getElementById('modal-available-slots-select');
        if (!slotsSelect) return;
        slotsSelect.innerHTML = `<option value="">${message}</option>`;
        slotsSelect.disabled = true;
    }


    function createBookingCardElement(booking, checkInOutEnabled) {
        if (!bookingItemTemplate) {
            console.error("Booking item template not found!");
            return document.createElement('div'); // Return an empty div or handle error appropriately
        }
        const bookingItemClone = bookingItemTemplate.content.cloneNode(true);
        const bookingCardDiv = bookingItemClone.querySelector('.booking-card'); // Use the main card div

        // Apply conditional classes for status
        bookingCardDiv.classList.remove('booking-completed', 'booking-cancelled', 'booking-rejected', 'booking-cancelled-by-admin', 'booking-cancelled-admin-acknowledged');
        const statusClass = `booking-${booking.status.toLowerCase().replace(/_/g, '-')}`;
        bookingCardDiv.classList.add(statusClass);

        bookingCardDiv.dataset.bookingId = booking.id;
        bookingCardDiv.dataset.resourceId = booking.resource_id;
        bookingCardDiv.dataset.startTime = booking.start_time;
        bookingCardDiv.dataset.endTime = booking.end_time;

        const titleTextSpan = bookingCardDiv.querySelector('.booking-title-text');
        if (titleTextSpan) titleTextSpan.textContent = booking.title || 'N/A';
        const bookingIdDisplay = bookingCardDiv.querySelector('.booking-id-display');
        if (bookingIdDisplay) bookingIdDisplay.textContent = `ID: #${booking.id}`;
        const resourceSpan = bookingCardDiv.querySelector('.booking-resource');
        if (resourceSpan) resourceSpan.textContent = booking.resource_name || 'N/A';

        const startDate = new Date(booking.start_time);
        const endDate = new Date(booking.end_time);
        const optionsDate = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' };
        const formattedDate = startDate.toLocaleDateString(undefined, optionsDate);
        const optionsTime = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' };
        const formattedStartTime = startDate.toLocaleTimeString(undefined, optionsTime);
        const formattedEndTime = endDate.toLocaleTimeString(undefined, optionsTime);

        const dateSpan = bookingCardDiv.querySelector('.booking-date');
        if (dateSpan) dateSpan.textContent = formattedDate;
        const startTimeSpan = bookingCardDiv.querySelector('.booking-start-time');
        if (startTimeSpan) startTimeSpan.textContent = formattedStartTime;
        const endTimeSpan = bookingCardDiv.querySelector('.booking-end-time');
        if (endTimeSpan) endTimeSpan.textContent = formattedEndTime;

        const statusBadge = bookingCardDiv.querySelector('.booking-status');
        if (statusBadge) {
            statusBadge.textContent = booking.status ? booking.status.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Unknown';
            statusBadge.className = `booking-status badge bg-${getBootstrapStatusColor(booking.status)}`;
        }

        const pinSection = bookingCardDiv.querySelector('.booking-pin-section');
        const pinSpan = bookingCardDiv.querySelector('.booking-pin');
        if (booking.pin && pinSection && pinSpan) {
            pinSpan.textContent = booking.pin;
            pinSection.style.display = 'block';
        } else if (pinSection) {
            pinSection.style.display = 'none';
        }

        const adminDeletedMessageSection = bookingCardDiv.querySelector('.admin-deleted-message-section');
        const adminDeletedMessageText = bookingCardDiv.querySelector('.admin-deleted-message-text');
        if (booking.admin_deleted_message && adminDeletedMessageSection && adminDeletedMessageText) {
            adminDeletedMessageText.textContent = booking.admin_deleted_message;
            adminDeletedMessageSection.style.display = 'block';
        } else if (adminDeletedMessageSection) {
            adminDeletedMessageSection.style.display = 'none';
        }

        // Actions (buttons)
        const actionsContainer = bookingCardDiv.querySelector('.booking-actions');
        actionsContainer.innerHTML = ''; // Clear any default/template buttons

        const terminalStatuses = ['completed', 'cancelled', 'rejected', 'cancelled_by_admin', 'cancelled_admin_acknowledged'];
        if (!terminalStatuses.includes(booking.status)) {
            if (checkInOutEnabled) {
                if (booking.can_check_in && !booking.checked_in_at) {
                    const checkInBtn = document.createElement('button');
                    checkInBtn.className = 'btn btn-sm btn-success me-1 check-in-btn';
                    checkInBtn.textContent = 'Check In';
                    checkInBtn.dataset.bookingId = booking.id;
                    actionsContainer.appendChild(checkInBtn);
                    // PIN input could be added here if needed for check-in
                }
                if (booking.checked_in_at && !booking.checked_out_at) {
                    const checkOutBtn = document.createElement('button');
                    checkOutBtn.className = 'btn btn-sm btn-warning me-1 check-out-btn';
                    checkOutBtn.textContent = 'Check Out';
                    checkOutBtn.dataset.bookingId = booking.id;
                    actionsContainer.appendChild(checkOutBtn);
                }
            }
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn btn-sm btn-danger cancel-booking-btn';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.dataset.bookingId = booking.id;
            actionsContainer.appendChild(cancelBtn);
        }
         // Edit title button (already in template, just ensure it has dataset.bookingId)
        const editTitleBtn = bookingCardDiv.querySelector('.edit-title-btn');
        if(editTitleBtn) editTitleBtn.dataset.bookingId = booking.id;


        return bookingCardDiv;
    }

    function getBootstrapStatusColor(status) {
        switch (status) {
            case 'approved': return 'primary';
            case 'pending_approval': return 'info';
            case 'checked_in': return 'success';
            case 'completed': return 'secondary';
            case 'cancelled': return 'warning';
            case 'rejected': return 'danger';
            case 'cancelled_by_admin': return 'dark';
            default: return 'light';
        }
    }

    // Generic initializePerPageSelect
    function initializeMyBookingsPerPageSelect(prefix, selectElement, itemsPerPageVarSetter, currentPageSetter, fetchDataFunction, currentItemsPerPage) {
        if (!selectElement) return;
        selectElement.innerHTML = ''; // Clear existing
        myBookingsItemsPerPageOptions.forEach(optionValue => {
            const option = new Option(optionValue, optionValue);
            if (optionValue === currentItemsPerPage) { // Use passed currentItemsPerPage
                option.selected = true;
            }
            selectElement.add(option);
        });
        // Remove existing listener to prevent duplicates
        const changeHandlerKey = `${prefix}_perPageChangeHandler`;
        if (selectElement[changeHandlerKey]) {
            selectElement.removeEventListener('change', selectElement[changeHandlerKey]);
        }
        selectElement[changeHandlerKey] = function() {
            itemsPerPageVarSetter(parseInt(this.value));
            currentPageSetter(1);
            fetchDataFunction();
        };
        selectElement.addEventListener('change', selectElement[changeHandlerKey]);
    }

    // Generic renderMyBookingsPaginationControls
    function renderMyBookingsPaginationControls(prefix, paginationUl, paginationContainer, totalResultsDisplay, currentPage, totalPages, totalItems, itemsPerPage, fetchDataFunction, currentPageSetter) {
        if (!paginationUl || !paginationContainer || !totalResultsDisplay) {
            console.warn(`Pagination elements for prefix ${prefix} not found.`);
            return;
        }
        paginationUl.innerHTML = '';

        const currentStatusFilter = statusFilterSelect ? statusFilterSelect.value : '';
        const currentResourceFilter = resourceNameFilterInput ? resourceNameFilterInput.value : '';

        if (totalItems === 0 && !currentStatusFilter && !currentResourceFilter) {
             paginationContainer.style.display = 'none';
             totalResultsDisplay.textContent = '';
             return;
        }

        paginationContainer.style.display = 'flex';
        totalResultsDisplay.textContent = totalItems > 0 ? `Total: ${totalItems} results` : 'No results for current filter.';

        if (totalPages === 0 || totalPages === 1 && totalItems <= itemsPerPage) {
            paginationUl.style.display = 'none';
            return;
        }
        paginationUl.style.display = 'flex';

        const createPageLink = (page, text, isDisabled = false, isActive = false) => {
            const li = document.createElement('li');
            li.className = `page-item ${isDisabled ? 'disabled' : ''} ${isActive ? 'active' : ''}`;
            const a = document.createElement('a');
            a.className = 'page-link';
            a.href = '#';
            a.innerHTML = text;
            if (!isDisabled) {
                a.addEventListener('click', (e) => {
                    e.preventDefault();
                    currentPageSetter(page);
                    fetchDataFunction();
                });
            }
            li.appendChild(a);
            return li;
        };

        paginationUl.appendChild(createPageLink(currentPage - 1, '&lt; Previous', currentPage <= 1));

        const showPages = 3;
        let startPage = Math.max(1, currentPage - Math.floor(showPages / 2));
        let endPage = Math.min(totalPages, startPage + showPages - 1);
        if (endPage - startPage + 1 < showPages && totalPages >= showPages) {
            startPage = Math.max(1, endPage - showPages + 1);
        } else if (totalPages < showPages) {
            startPage = 1;
            endPage = totalPages;
        }

        if (startPage > 1) {
            paginationUl.appendChild(createPageLink(1, '1'));
            if (startPage > 2) {
                const ellipsisLi = document.createElement('li');
                ellipsisLi.className = 'page-item disabled';
                ellipsisLi.innerHTML = `<span class="page-link">&hellip;</span>`;
                paginationUl.appendChild(ellipsisLi);
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            paginationUl.appendChild(createPageLink(i, i, false, i === currentPage));
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                const ellipsisLi = document.createElement('li');
                ellipsisLi.className = 'page-item disabled';
                ellipsisLi.innerHTML = `<span class="page-link">&hellip;</span>`;
                paginationUl.appendChild(ellipsisLi);
            }
            paginationUl.appendChild(createPageLink(totalPages, totalPages));
        }
        paginationUl.appendChild(createPageLink(currentPage + 1, 'Next &gt;', currentPage >= totalPages));
    }


    async function fetchUpcomingBookings() {
        if (!upcomingBookingsContainer) return;
        if (!toggleUpcomingCheckbox.checked) {
            upcomingBookingsContainer.innerHTML = '<p>Upcoming bookings hidden.</p>';
            if(upcomingPaginationContainer) upcomingPaginationContainer.style.display = 'none';
            return;
        }
        showLoading(upcomingBookingsContainer, 'Loading upcoming bookings...');

        let url = `/api/bookings/upcoming?page=${upcomingCurrentPage}&per_page=${upcomingItemsPerPage}`;
        const status = statusFilterSelect ? statusFilterSelect.value : '';
        const resourceName = resourceNameFilterInput ? resourceNameFilterInput.value.trim() : '';
        if (status) url += `&status_filter=${encodeURIComponent(status)}`;
        if (resourceName) url += `&resource_name_filter=${encodeURIComponent(resourceName)}`;

        try {
            const data = await apiCall(url, {}, statusDiv); // Use global statusDiv for general API errors
            if (data.success === false) {
                showError(upcomingBookingsContainer, data.message || 'Failed to fetch upcoming bookings.');
                if (upcomingPaginationContainer) upcomingPaginationContainer.style.display = 'none';
                return;
            }

            upcomingTotalItems = data.pagination.total_items;
            upcomingTotalPages = data.pagination.total_pages;
            upcomingCurrentPage = data.pagination.current_page; // Sync with server response

            renderMyBookingsPaginationControls('upcoming_bk_pg_', upcomingPaginationUl, upcomingPaginationContainer, upcomingTotalResultsDisplay, upcomingCurrentPage, upcomingTotalPages, upcomingTotalItems, upcomingItemsPerPage, fetchUpcomingBookings, (val) => upcomingCurrentPage = val);

            upcomingBookingsContainer.innerHTML = ''; // Clear loading
            if (data.bookings && data.bookings.length > 0) {
                data.bookings.forEach(booking => {
                    const bookingCard = createBookingCardElement(booking, data.check_in_out_enabled);
                    upcomingBookingsContainer.appendChild(bookingCard);
                });
            } else {
                upcomingBookingsContainer.innerHTML = '<p>No upcoming bookings found matching your criteria.</p>';
            }
        } catch (error) {
            showError(upcomingBookingsContainer, `Error fetching upcoming bookings: ${error.message}`);
            if (upcomingPaginationContainer) upcomingPaginationContainer.style.display = 'none';
        }
    }

    async function fetchPastBookings() {
        if (!pastBookingsContainer) return;
         if (!togglePastCheckbox.checked) {
            pastBookingsContainer.innerHTML = '<p>Past bookings hidden.</p>';
            if(pastPaginationContainer) pastPaginationContainer.style.display = 'none';
            return;
        }
        showLoading(pastBookingsContainer, 'Loading past bookings...');

        let url = `/api/bookings/past?page=${pastCurrentPage}&per_page=${pastItemsPerPage}`;
        const status = statusFilterSelect ? statusFilterSelect.value : '';
        const resourceName = resourceNameFilterInput ? resourceNameFilterInput.value.trim() : '';
        if (status) url += `&status_filter=${encodeURIComponent(status)}`;
        if (resourceName) url += `&resource_name_filter=${encodeURIComponent(resourceName)}`;

        try {
            const data = await apiCall(url, {}, statusDiv);
             if (data.success === false) {
                showError(pastBookingsContainer, data.message || 'Failed to fetch past bookings.');
                if (pastPaginationContainer) pastPaginationContainer.style.display = 'none';
                return;
            }

            pastTotalItems = data.pagination.total_items;
            pastTotalPages = data.pagination.total_pages;
            pastCurrentPage = data.pagination.current_page;

            renderMyBookingsPaginationControls('past_bk_pg_', pastPaginationUl, pastPaginationContainer, pastTotalResultsDisplay, pastCurrentPage, pastTotalPages, pastTotalItems, pastItemsPerPage, fetchPastBookings, (val) => pastCurrentPage = val);

            pastBookingsContainer.innerHTML = ''; // Clear loading
            if (data.bookings && data.bookings.length > 0) {
                data.bookings.forEach(booking => {
                    const bookingCard = createBookingCardElement(booking, data.check_in_out_enabled);
                    pastBookingsContainer.appendChild(bookingCard);
                });
            } else {
                pastBookingsContainer.innerHTML = '<p>No past bookings found matching your criteria.</p>';
            }
        } catch (error) {
            showError(pastBookingsContainer, `Error fetching past bookings: ${error.message}`);
            if (pastPaginationContainer) pastPaginationContainer.style.display = 'none';
        }
    }


    function displayBookings(bookings, container, template, isUpcoming) {
        // This function is now largely superseded by fetchUpcomingBookings and fetchPastBookings
        // but its core logic for creating cards is now in createBookingCardElement.
        // Kept for reference, but direct calls to createBookingCardElement are now used.
        container.innerHTML = ''; // Clear loading/previous content
        if (bookings && bookings.length > 0) {
            bookings.forEach(booking => {
                // Assume check_in_out_enabled is fetched globally or passed if needed here.
                // For now, createBookingCardElement might need to fetch it or have it passed.
                // The refactored fetch functions now pass it to createBookingCardElement.
                const bookingCard = createBookingCardElement(booking, window.checkInOutEnabledGlobal || false); // Example global
                container.appendChild(bookingCard);
            });
        } else {
            container.innerHTML = `<p>No ${isUpcoming ? 'upcoming' : 'past'} bookings found.</p>`;
        }
    }


    // Original fetchAndDisplayBookings is effectively split into fetchUpcomingBookings and fetchPastBookings
    // The filter application logic will now trigger both.

    document.addEventListener('click', async (event) => {
        const target = event.target;
        const bookingItem = target.closest('.booking-card'); // Changed from .booking-item to .booking-card

        if (target.classList.contains('edit-title-btn')) {
            event.stopPropagation(); // Prevent card click if any
            const bookingId = target.closest('.booking-card').dataset.bookingId;
            const titleValueElement = target.closest('.booking-card').querySelector('.booking-title-text');
            const currentTitle = titleValueElement ? titleValueElement.textContent : '';

            const resourceName = target.closest('.booking-card').querySelector('.booking-resource').textContent;

            if (modalBookingIdInput) modalBookingIdInput.value = bookingId;
            if (newBookingTitleInput) newBookingTitleInput.value = currentTitle;
            if (updateBookingModalLabel) updateBookingModalLabel.textContent = `Update Booking for: ${resourceName}`;

            hideStatusMessage(updateModalStatusDiv);
            if (updateModal) updateModal.show();
            return; // Processed
        }


        if (target.classList.contains('cancel-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            if (confirm(`Are you sure you want to cancel booking ID ${bookingId}?`)) {
                showLoading(statusDiv, `Cancelling booking ${bookingId}...`);
                try {
                    await apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' });
                    showSuccess(statusDiv, `Booking ${bookingId} cancelled successfully.`);
                    // Re-fetch both sections as a cancelled booking might move or affect counts
                    fetchUpcomingBookings();
                    fetchPastBookings();
                } catch (error) {
                    showError(statusDiv, error.message || `Failed to cancel booking ${bookingId}.`);
                }
            }
        }

        if (target.classList.contains('check-in-btn')) {
            const bookingId = target.dataset.bookingId;
            const pinInput = bookingItem ? bookingItem.querySelector('.booking-pin-input') : null; // Not present in new card
            const pinValue = pinInput ? pinInput.value.trim() : null;
            let payload = {};
            if (pinValue) payload.pin = pinValue;

            showLoading(statusDiv, 'Checking in...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_in`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                showSuccess(statusDiv, 'Checked in successfully.');
                fetchUpcomingBookings(); // Refresh to update status and buttons
            } catch (error) {
                showError(statusDiv, error.message || 'Check in failed.');
            }
        }

        if (target.classList.contains('check-out-btn')) {
            const bookingId = target.dataset.bookingId;
            showLoading(statusDiv, 'Checking out...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_out`, { method: 'POST' });
                showSuccess(statusDiv, 'Checked out successfully.');
                fetchUpcomingBookings(); // Refresh
            } catch (error) {
                showError(statusDiv, error.message || 'Check out failed.');
            }
        }
    });

    if (document.getElementById('update-booking-title-form')) {
        document.getElementById('update-booking-title-form').addEventListener('submit', async function(event) {
            event.preventDefault();
            const bookingId = document.getElementById('modal-booking-id').value;
            const newTitle = document.getElementById('new-booking-title').value.trim();

            if (!newTitle) {
                showModalStatus('Title cannot be empty.', 'danger');
                return;
            }
            const originalButtonText = this.querySelector('button[type="submit"]').textContent;
            this.querySelector('button[type="submit"]').textContent = 'Saving...';
            this.querySelector('button[type="submit"]').disabled = true;

            try {
                const updatedBooking = await apiCall(`/api/bookings/${bookingId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }) // Only sending title
                }, updateModalStatusDiv);

                showSuccess(statusDiv, `Booking ${bookingId} title updated successfully.`);
                if (updateModal) updateModal.hide();
                // Refresh relevant section
                // Determine if it was upcoming or past based on current state or re-fetch both
                fetchUpcomingBookings();
                fetchPastBookings();

            } catch (error) {
                // Error is shown by apiCall in updateModalStatusDiv
            } finally {
                this.querySelector('button[type="submit"]').textContent = originalButtonText;
                this.querySelector('button[type="submit"]').disabled = false;
            }
        });
    }

    function handleFilterOrToggleChange() {
        upcomingCurrentPage = 1;
        pastCurrentPage = 1;
        if (toggleUpcomingCheckbox && toggleUpcomingCheckbox.checked) {
            fetchUpcomingBookings();
        } else if(upcomingPaginationContainer) {
            upcomingPaginationContainer.style.display = 'none';
            if(upcomingBookingsContainer) upcomingBookingsContainer.innerHTML = '<p>Upcoming bookings hidden.</p>';
        }
        if (togglePastCheckbox && togglePastCheckbox.checked) {
            fetchPastBookings();
        } else if(pastPaginationContainer) {
            pastPaginationContainer.style.display = 'none';
            if(pastBookingsContainer) pastBookingsContainer.innerHTML = '<p>Past bookings hidden.</p>';
        }
    }

    if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener('click', handleFilterOrToggleChange);
    }
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            if(statusFilterSelect) statusFilterSelect.value = '';
            if(resourceNameFilterInput) resourceNameFilterInput.value = '';
            handleFilterOrToggleChange();
        });
    }

    if (toggleUpcomingCheckbox) {
        toggleUpcomingCheckbox.addEventListener('change', handleFilterOrToggleChange);
    }
    if (togglePastCheckbox) {
        togglePastCheckbox.addEventListener('change', handleFilterOrToggleChange);
    }

    // Initial Load
    initializeMyBookingsPerPageSelect('upcoming_bk_pg_', upcomingPerPageSelect, (val) => upcomingItemsPerPage = val, (val) => upcomingCurrentPage = val, fetchUpcomingBookings, upcomingItemsPerPage);
    initializeMyBookingsPerPageSelect('past_bk_pg_', pastPerPageSelect, (val) => pastItemsPerPage = val, (val) => pastCurrentPage = val, fetchPastBookings, pastItemsPerPage);
    
    handleFilterOrToggleChange(); // Initial fetch based on default filter and toggle states
});
