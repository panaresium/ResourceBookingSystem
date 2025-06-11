document.addEventListener('DOMContentLoaded', () => {
    const upcomingBookingsContainer = document.getElementById('upcoming-bookings-container');
    const pastBookingsContainer = document.getElementById('past-bookings-container');
    const bookingItemTemplate = document.getElementById('booking-item-template');
    const statusDiv = document.getElementById('my-bookings-status');

    // Filter Elements
    const statusFilterSelect = document.getElementById('my-bookings-status-filter'); // Corrected ID as per subtask
    const resourceNameFilterInput = document.getElementById('resource-name-filter'); // New filter
    const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
    const datePickerContainer = document.getElementById('my-bookings-date-picker-container');
    const datePickerInput = document.getElementById('my-bookings-date-picker');
    const applyFiltersBtn = document.getElementById('apply-my-bookings-filters-btn');
    const clearFiltersBtn = document.getElementById('clear-my-bookings-filters-btn');
    // Visibility Toggles
    const toggleUpcomingCheckbox = document.getElementById('toggle-upcoming-bookings');
    const togglePastCheckbox = document.getElementById('toggle-past-bookings');

    // --- Flatpickr Instance ---
    let flatpickrInstance = null;

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


    function createBookingCardElement(booking, checkInOutEnabled, allow_check_in_without_pin) {
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

        const titleTextSpan = bookingCardDiv.querySelector('.booking-title-value');
        if (titleTextSpan) titleTextSpan.textContent = booking.title || 'N/A';
        const bookingIdDisplay = bookingCardDiv.querySelector('.booking-id-display');
        if (bookingIdDisplay) bookingIdDisplay.textContent = `ID: #${booking.id}`;
        const resourceSpan = bookingCardDiv.querySelector('.resource-name-value');
        if (resourceSpan) resourceSpan.textContent = booking.resource_name || 'N/A';

        const startDate = new Date(booking.start_time);
        const endDate = new Date(booking.end_time);
        const optionsDate = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' };
        const formattedDate = startDate.toLocaleDateString(undefined, optionsDate);
        const optionsTime = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' };
        const formattedStartTime = startDate.toLocaleTimeString(undefined, optionsTime);
        const formattedEndTime = endDate.toLocaleTimeString(undefined, optionsTime);

        const dateSpan = bookingCardDiv.querySelector('.booking-date-value');
        if (dateSpan) dateSpan.textContent = formattedDate;
        const startTimeSpan = bookingCardDiv.querySelector('.booking-start-time-value');
        if (startTimeSpan) startTimeSpan.textContent = formattedStartTime;
        const endTimeSpan = bookingCardDiv.querySelector('.booking-end-time-value');
        if (endTimeSpan) endTimeSpan.textContent = formattedEndTime;

        const statusBadge = bookingCardDiv.querySelector('.booking-status-value');
        if (statusBadge) {
            statusBadge.textContent = booking.status ? booking.status.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Unknown';
            statusBadge.className = `booking-status-value badge bg-${getBootstrapStatusColor(booking.status)}`;
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
        // actionsContainer.innerHTML = ''; // Clear any default/template buttons - REMOVED

        // Locate existing controls
        const checkInControls = bookingCardDiv.querySelector('.check-in-controls');
        const pinInput = checkInControls ? checkInControls.querySelector('.booking-pin-input') : null;
        const checkInBtnExisting = checkInControls ? checkInControls.querySelector('.check-in-btn') : null;
        const checkOutBtnExisting = bookingCardDiv.querySelector('.check-out-btn');
        const cancelBtnExisting = bookingCardDiv.querySelector('.cancel-booking-btn');

        // Control Visibility and Attributes
        const terminalStatuses = ['completed', 'cancelled', 'rejected', 'cancelled_by_admin', 'cancelled_admin_acknowledged'];

        // Check-In Controls
        if (checkInControls && pinInput && checkInBtnExisting) {
            if (checkInOutEnabled && booking.can_check_in && !booking.checked_in_at) {
                checkInControls.style.display = 'inline-block';
                checkInBtnExisting.dataset.bookingId = booking.id; // Set for button regardless of PIN field

                // PIN Input specific logic
                if (pinInput) {
                    pinInput.dataset.bookingId = booking.id; // Set bookingId on PIN input
                    // Use booking.resource_has_active_pin (boolean) from backend now
                    if (allow_check_in_without_pin === true || !booking.resource_has_active_pin) {
                        pinInput.style.display = 'none';
                    } else {
                        pinInput.style.display = 'inline-block'; // Or its default display style
                    }
                }
            } else {
                checkInControls.style.display = 'none';
            }
        }

        // Check-Out Button
        if (checkOutBtnExisting) {
            if (checkInOutEnabled && booking.checked_in_at && !booking.checked_out_at) {
                checkOutBtnExisting.style.display = 'inline-block';
                checkOutBtnExisting.dataset.bookingId = booking.id;
            } else {
                checkOutBtnExisting.style.display = 'none';
            }
        }

        // Cancel Button
        if (cancelBtnExisting) {
            if (!terminalStatuses.includes(booking.status)) {
                cancelBtnExisting.style.display = 'inline-block';
                cancelBtnExisting.dataset.bookingId = booking.id;
            } else {
                cancelBtnExisting.style.display = 'none';
            }
        }
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

    function initializeMyBookingsPerPageSelect(prefix, selectElement, itemsPerPageVarSetter, currentPageSetter, fetchDataFunction, currentItemsPerPage) {
        if (!selectElement) return;
        selectElement.innerHTML = '';
        myBookingsItemsPerPageOptions.forEach(optionValue => {
            const option = new Option(optionValue, optionValue);
            if (optionValue === currentItemsPerPage) {
                option.selected = true;
            }
            selectElement.add(option);
        });
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

    function renderMyBookingsPaginationControls(prefix, paginationUl, paginationContainer, currentPage, totalPages, totalItems, itemsPerPage, fetchDataFunction, currentPageSetter, itemsPerPageVarSetter) {
        if (!paginationUl || !paginationContainer) {
            console.warn(`Pagination UL or Container for prefix ${prefix} not found.`);
            return;
        }
        paginationUl.innerHTML = '';
        paginationUl.classList.add('d-flex', 'flex-wrap', 'align-items-baseline');

        const currentStatusFilter = statusFilterSelect ? statusFilterSelect.value : '';
        const currentResourceFilter = resourceNameFilterInput ? resourceNameFilterInput.value : '';
        const currentDateFilterType = dateFilterTypeSelect ? dateFilterTypeSelect.value : 'any';
        const currentDateFilterValue = (flatpickrInstance && flatpickrInstance.selectedDates.length > 0) ? flatpickrInstance.selectedDates[0] : null;

        // Hide pagination if no items AND no filters are active (including date filter)
        if (totalItems === 0 && !currentStatusFilter && !currentResourceFilter && (currentDateFilterType === 'any' || !currentDateFilterValue)) {
             paginationContainer.style.display = 'none';
             return;
        }
        paginationContainer.style.display = 'block';

        const totalResultsLi = document.createElement('li');
        totalResultsLi.className = 'page-item total-results-li';
        const totalDiv = document.createElement('div');
        totalDiv.id = `${prefix}total_results_display`;
        totalDiv.className = 'text-muted p-2';
        totalDiv.textContent = totalItems > 0 ? `Total: ${totalItems} results` : 'No results for current filter.';
        totalResultsLi.appendChild(totalDiv);
        const totalResultsSpacer = document.createElement('span');
        totalResultsSpacer.className = 'pagination-controls-spacer me-3';
        totalResultsLi.appendChild(totalResultsSpacer);
        paginationUl.appendChild(totalResultsLi);

        const perPageLi = document.createElement('li');
        perPageLi.className = 'page-item per-page-li';
        const perPageWrapperSpan = document.createElement('span');
        const label = document.createElement('label');
        label.htmlFor = `${prefix}per_page_select`;
        label.className = 'form-label me-2';
        label.textContent = 'Per Page:';
        const select = document.createElement('select');
        select.id = `${prefix}per_page_select`;
        select.className = 'form-select form-select-sm d-inline-block';
        select.style.width = 'auto';
        initializeMyBookingsPerPageSelect(prefix, select, itemsPerPageVarSetter, currentPageSetter, fetchDataFunction, itemsPerPage);
        const perPageOriginalSpacer = document.createElement('span');
        perPageOriginalSpacer.className = 'me-3 pagination-controls-spacer';
        perPageWrapperSpan.appendChild(label);
        perPageWrapperSpan.appendChild(select);
        perPageWrapperSpan.appendChild(perPageOriginalSpacer);
        perPageLi.appendChild(perPageWrapperSpan);
        paginationUl.appendChild(perPageLi);

        const createOuterPageLink = (page, text, isDisabled = false) => {
            const li = document.createElement('li');
            li.className = `page-item ${isDisabled ? 'disabled' : ''}`;
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

        if (totalPages > 1) {
            paginationUl.appendChild(createOuterPageLink(currentPage - 1, '&lt; Previous', currentPage <= 1));
            const pageNumbersLi = document.createElement('li');
            pageNumbersLi.className = 'page-item';
            const innerSpan = document.createElement('span');
            innerSpan.className = 'page-link page-numbers-span-container';
            innerSpan.appendChild(document.createTextNode('['));
            const pageElements = [];
            const showPages = 3;
            let startPage = Math.max(1, currentPage - Math.floor(showPages / 2));
            let endPage = Math.min(totalPages, startPage + showPages - 1);
            if (endPage - startPage + 1 < showPages && totalPages >= showPages) {
                if (currentPage <= Math.ceil(showPages / 2)) {
                    endPage = Math.min(totalPages, showPages);
                } else if (currentPage > totalPages - Math.ceil(showPages / 2)) {
                    startPage = Math.max(1, totalPages - showPages + 1);
                } else {
                    startPage = Math.max(1, endPage - showPages + 1);
                }
            } else if (totalPages < showPages) {
                startPage = 1;
                endPage = totalPages;
            }
            const createInternalPageLink = (page, textDisplay) => {
                const a = document.createElement('a');
                a.href = '#';
                a.textContent = textDisplay || page;
                a.className = 'internal-page-link';
                if (page === currentPage) { a.classList.add('active-page-link'); }
                a.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (page !== currentPage) { currentPageSetter(page); fetchDataFunction(); }
                });
                return a;
            };
            if (startPage > 1) {
                pageElements.push(createInternalPageLink(1, '1'));
                if (startPage > 2) { pageElements.push(document.createTextNode('...')); }
            }
            for (let i = startPage; i <= endPage; i++) { pageElements.push(createInternalPageLink(i, i.toString())); }
            if (endPage < totalPages) {
                if (endPage < totalPages - 1) { pageElements.push(document.createTextNode('...')); }
                pageElements.push(createInternalPageLink(totalPages, totalPages.toString()));
            }
            pageElements.forEach((el, index) => {
                innerSpan.appendChild(el);
                if (index < pageElements.length - 1) { innerSpan.appendChild(document.createTextNode(', ')); }
            });
            innerSpan.appendChild(document.createTextNode(']'));
            pageNumbersLi.appendChild(innerSpan);
            paginationUl.appendChild(pageNumbersLi);
            paginationUl.appendChild(createOuterPageLink(currentPage + 1, 'Next &gt;', currentPage >= totalPages));
        }
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

        if (dateFilterTypeSelect && dateFilterTypeSelect.value === 'specific' && flatpickrInstance && flatpickrInstance.selectedDates.length > 0) {
            const selectedDate = flatpickrInstance.selectedDates[0];
            const year = selectedDate.getFullYear();
            const month = ('0' + (selectedDate.getMonth() + 1)).slice(-2);
            const day = ('0' + selectedDate.getDate()).slice(-2);
            const formattedDate = `${year}-${month}-${day}`;
            url += `&date_filter=${formattedDate}`;
        }

        try {
            const data = await apiCall(url, {}, statusDiv);
            if (data.success === false) {
                showError(upcomingBookingsContainer, data.message || 'Failed to fetch upcoming bookings.');
                if (upcomingPaginationContainer) upcomingPaginationContainer.style.display = 'none';
                return;
            }
            upcomingTotalItems = data.pagination.total_items;
            upcomingTotalPages = data.pagination.total_pages;
            upcomingCurrentPage = data.pagination.current_page;
            const allowCheckInWithoutPinUpcoming = data.allow_check_in_without_pin;

            renderMyBookingsPaginationControls('upcoming_bk_pg_', upcomingPaginationUl, upcomingPaginationContainer,
                upcomingCurrentPage, upcomingTotalPages, upcomingTotalItems, upcomingItemsPerPage,
                fetchUpcomingBookings, (val) => upcomingCurrentPage = val, (val) => upcomingItemsPerPage = val);
            upcomingBookingsContainer.innerHTML = '';
            if (data.bookings && data.bookings.length > 0) {
                data.bookings.forEach(booking => {
                    const bookingCard = createBookingCardElement(booking, data.check_in_out_enabled, allowCheckInWithoutPinUpcoming);
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

        if (dateFilterTypeSelect && dateFilterTypeSelect.value === 'specific' && flatpickrInstance && flatpickrInstance.selectedDates.length > 0) {
            const selectedDate = flatpickrInstance.selectedDates[0];
            const year = selectedDate.getFullYear();
            const month = ('0' + (selectedDate.getMonth() + 1)).slice(-2);
            const day = ('0' + selectedDate.getDate()).slice(-2);
            const formattedDate = `${year}-${month}-${day}`;
            url += `&date_filter=${formattedDate}`;
        }

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
            const allowCheckInWithoutPinPast = data.allow_check_in_without_pin;

            renderMyBookingsPaginationControls('past_bk_pg_', pastPaginationUl, pastPaginationContainer,
                pastCurrentPage, pastTotalPages, pastTotalItems, pastItemsPerPage,
                fetchPastBookings, (val) => pastCurrentPage = val, (val) => pastItemsPerPage = val);
            pastBookingsContainer.innerHTML = '';
            if (data.bookings && data.bookings.length > 0) {
                data.bookings.forEach(booking => {
                    const bookingCard = createBookingCardElement(booking, data.check_in_out_enabled, allowCheckInWithoutPinPast);
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
                // Also, allow_check_in_without_pin would need to be passed. Defaulting to true for this obsolete function.
                const bookingCard = createBookingCardElement(booking, window.checkInOutEnabledGlobal || false, true);
                container.appendChild(bookingCard);
            });
        } else {
            container.innerHTML = `<p>No ${isUpcoming ? 'upcoming' : 'past'} bookings found.</p>`;
        }
    }

    document.addEventListener('click', async (event) => {
        const target = event.target;
        const bookingItem = target.closest('.booking-card');
        if (target.classList.contains('cancel-booking-btn')) {
            const bookingId = target.dataset.bookingId;
            if (confirm(`Are you sure you want to cancel booking ID ${bookingId}?`)) {
                showLoading(statusDiv, `Cancelling booking ${bookingId}...`);
                try {
                    await apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' });
                    showSuccess(statusDiv, `Booking ${bookingId} cancelled successfully.`);
                    fetchUpcomingBookings();
                    fetchPastBookings();
                } catch (error) {
                    showError(statusDiv, error.message || `Failed to cancel booking ${bookingId}.`);
                }
            }
        }
        if (target.classList.contains('check-in-btn')) {
            const bookingId = target.dataset.bookingId;
            const pinInput = bookingItem ? bookingItem.querySelector('.booking-pin-input') : null;
            const pinValue = pinInput ? pinInput.value.trim() : null;
            let payload = {};
            // Only include PIN in payload if the input field was visible and has a value.
            // The visibility of pinInput is handled by createBookingCardElement.
            // If pinInput.style.display is 'none', pinValue would likely be empty or not relevant.
            if (pinInput && pinInput.style.display !== 'none' && pinValue) {
                 payload.pin = pinValue;
            }
            showLoading(statusDiv, 'Checking in...');
            try {
                await apiCall(`/api/bookings/${bookingId}/check_in`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                showSuccess(statusDiv, 'Checked in successfully.');
                fetchUpcomingBookings();
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
                fetchUpcomingBookings();
            } catch (error) {
                showError(statusDiv, error.message || 'Check out failed.');
            }
        }
    });

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
    if (statusFilterSelect) { // Auto-refresh on status change
        statusFilterSelect.addEventListener('change', handleFilterOrToggleChange);
    }
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            if(statusFilterSelect) statusFilterSelect.value = '';
            if(resourceNameFilterInput) resourceNameFilterInput.value = '';
            if(dateFilterTypeSelect) {
                dateFilterTypeSelect.value = 'any';
                // Manually trigger the state update for date picker visibility
                setupInitialDateFilterState.call(dateFilterTypeSelect);
            }
            if(flatpickrInstance) flatpickrInstance.clear();
            handleFilterOrToggleChange();
        });
    }

    // Function to manage date picker visibility and initialization
    function setupInitialDateFilterState() {
        // Ensure elements exist. `this` is expected to be dateFilterTypeSelect.
        if (!this || !datePickerContainer || !datePickerInput) {
            console.warn('Date filter elements not ready for setupInitialDateFilterState');
            return;
        }

        const selectedValue = this.value;
        // console.log('Date filter type changed/evaluated:', selectedValue); // Removed

        if (selectedValue === 'specific') {
            // console.log('Showing date picker container'); // Removed
            datePickerContainer.classList.remove('d-none');
            datePickerContainer.style.display = 'flex'; // Use flex or block as appropriate for layout
            if (!flatpickrInstance) {
                // console.log('Initializing Flatpickr on:', datePickerInput); // Removed
                flatpickrInstance = flatpickr(datePickerInput, {
                    dateFormat: "Y-m-d",
                    altInput: true,
                    altFormat: "F j, Y",
                });
            }
        } else { // 'any' or other
            // console.log('Hiding date picker container'); // Removed
            datePickerContainer.classList.add('d-none');
            datePickerContainer.style.display = 'none'; // Fallback
        }
    }

    if (dateFilterTypeSelect) { // Check if the main select exists
        dateFilterTypeSelect.addEventListener('change', function() {
            setupInitialDateFilterState.call(this);
            // Note: Filters are applied by clicking "Apply Filters", not directly on change here.
        });
    }

    if (toggleUpcomingCheckbox) {
        toggleUpcomingCheckbox.addEventListener('change', handleFilterOrToggleChange);
    }
    if (togglePastCheckbox) {
        togglePastCheckbox.addEventListener('change', handleFilterOrToggleChange);
    }

    initializeMyBookingsPerPageSelect('upcoming_bk_pg_', upcomingPerPageSelect, (val) => upcomingItemsPerPage = val, (val) => upcomingCurrentPage = val, fetchUpcomingBookings, upcomingItemsPerPage);
    initializeMyBookingsPerPageSelect('past_bk_pg_', pastPerPageSelect, (val) => pastItemsPerPage = val, (val) => pastCurrentPage = val, fetchPastBookings, pastItemsPerPage);
    
    // Initial setup calls at the end of DOMContentLoaded
    if (dateFilterTypeSelect) { // Ensure element exists
        setupInitialDateFilterState.call(dateFilterTypeSelect); // Set initial state of date picker
    }
    handleFilterOrToggleChange(); // Initial fetch of bookings based on all filters
});
