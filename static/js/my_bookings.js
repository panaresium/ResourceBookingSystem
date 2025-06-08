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
    const modalBookingDateInput = document.getElementById('modal-booking-date');
    const modalAvailableSlotsSelect = document.getElementById('modal-available-slots-select');
    const saveBookingTitleBtn = document.getElementById('save-booking-title-btn'); // Note: This is the submit button of the form

    // Store original booking times for comparison on save
    let originalBookingStartTime = null;
    let originalBookingEndTime = null;
    let lastFocusedButtonForModal = null; // For returning focus after modal closes

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
            // Note: The class name for styling the badge itself (e.g., 'booking-status') might be different from the value span.
            // Assuming 'booking-status-value' is for the text content and it might also have general badge styling.
            // If 'booking-status' was also meant for styling the badge container, that might need to be preserved or handled differently.
            // For now, aligning with the pattern of other ".xxxx-value" selectors for text content.
            // The original line for class name was: statusBadge.className = `booking-status badge bg-${getBootstrapStatusColor(booking.status)}`;
            // This might need to be:
            // statusBadge.className = `booking-status-value badge bg-${getBootstrapStatusColor(booking.status)}`;
            // or the template might have a separate element for the badge background and this span is just for text.
            // Based on template structure, booking-status-value is likely just for text.
            // The template has: <strong>Status:</strong> <span class="booking-status-value"></span>
            // So, the badge color/background should be applied to this span or its parent if needed.
            // Let's assume for now that `booking-status-value` is the target for text and styling.
            statusBadge.className = `booking-status-value badge bg-${getBootstrapStatusColor(booking.status)}`;
        }

        const recurrenceRuleSpan = bookingCardDiv.querySelector('.recurrence-rule-value');
        if (recurrenceRuleSpan) recurrenceRuleSpan.textContent = booking.recurrence_rule || 'N/A';

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
            // Add Edit button
            const editButton = document.createElement('button');
            editButton.textContent = 'Edit';
            editButton.className = 'btn btn-sm btn-primary edit-title-btn me-1';
            editButton.dataset.bookingId = booking.id;
            actionsContainer.appendChild(editButton);

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
        // The following lines are removed as the edit button is now conditionally added above.
        // const editTitleBtn = bookingCardDiv.querySelector('.edit-title-btn');
        // if(editTitleBtn) editTitleBtn.dataset.bookingId = booking.id;


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
    function renderMyBookingsPaginationControls(prefix, paginationUl, paginationContainer, currentPage, totalPages, totalItems, itemsPerPage, fetchDataFunction, currentPageSetter, itemsPerPageVarSetter) {
        if (!paginationUl || !paginationContainer) {
            console.warn(`Pagination UL or Container for prefix ${prefix} not found.`);
            return;
        }
        paginationUl.innerHTML = ''; // Clear existing content
        paginationUl.classList.add('d-flex', 'flex-wrap', 'align-items-baseline');


        const currentStatusFilter = statusFilterSelect ? statusFilterSelect.value : ''; // Assuming statusFilterSelect is globally accessible or passed
        const currentResourceFilter = resourceNameFilterInput ? resourceNameFilterInput.value : ''; // Assuming resourceNameFilterInput is globally accessible or passed

        if (totalItems === 0 && !currentStatusFilter && !currentResourceFilter) {
             paginationContainer.style.display = 'none';
             // No totalResultsDisplay element to clear text from directly here anymore
             return;
        }
        paginationContainer.style.display = 'block';

        // --- Create "Total Results" Element (as an <li>) ---
        const totalResultsLi = document.createElement('li');
        // Assuming 'total-results-li' class might be used for specific styling of this non-interactive item.
        // Not using ms-auto here as it's the first element now.
        totalResultsLi.className = 'page-item total-results-li';

        const totalDiv = document.createElement('div');
        totalDiv.id = `${prefix}total_results_display`;
        totalDiv.className = 'text-muted p-2';
        totalDiv.textContent = totalItems > 0 ? `Total: ${totalItems} results` : 'No results for current filter.';
        // TODO: Add localization for "Total: X results" and "No results for current filter."

        totalResultsLi.appendChild(totalDiv);

        // New spacer inside totalResultsLi, after the text div
        const totalResultsSpacer = document.createElement('span');
        totalResultsSpacer.className = 'pagination-controls-spacer me-3';
        totalResultsLi.appendChild(totalResultsSpacer);

        paginationUl.appendChild(totalResultsLi);

        // --- Create "Per Page" Element (as an <li>) ---
        const perPageLi = document.createElement('li');
        perPageLi.className = 'page-item per-page-li'; // Added hypothetical class for styling

        const perPageWrapperSpan = document.createElement('span');
        // This span does not get 'page-link' to avoid link-like styling for the whole per-page block

        const label = document.createElement('label');
        label.htmlFor = `${prefix}per_page_select`;
        label.className = 'form-label me-2';
        label.textContent = 'Per Page:'; // TODO: Add localization if needed

        const select = document.createElement('select');
        select.id = `${prefix}per_page_select`;
        select.className = 'form-select form-select-sm d-inline-block';
        select.style.width = 'auto';

        initializeMyBookingsPerPageSelect(prefix, select, itemsPerPageVarSetter, currentPageSetter, fetchDataFunction, itemsPerPage);

        // This is the original spacer for "Per Page" that was inside perPageWrapperSpan
        const perPageOriginalSpacer = document.createElement('span');
        perPageOriginalSpacer.className = 'me-3 pagination-controls-spacer';

        perPageWrapperSpan.appendChild(label);
        perPageWrapperSpan.appendChild(select);
        perPageWrapperSpan.appendChild(perPageOriginalSpacer);
        perPageLi.appendChild(perPageWrapperSpan);
        paginationUl.appendChild(perPageLi);

        // Helper for "Previous" and "Next" links
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

        if (totalPages > 1) { // Only show Prev/Next and page numbers if more than one page
            paginationUl.appendChild(createOuterPageLink(currentPage - 1, '&lt; Previous', currentPage <= 1));

            // --- Create Page Numbers [1, ..., n] (as an <li>) ---
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
                if (page === currentPage) {
                    a.classList.add('active-page-link');
                }
                a.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (page !== currentPage) {
                        currentPageSetter(page);
                        fetchDataFunction();
                    }
                });
                return a;
            };

            if (startPage > 1) {
                pageElements.push(createInternalPageLink(1, '1'));
                if (startPage > 2) {
                    pageElements.push(document.createTextNode('...'));
                }
            }

            for (let i = startPage; i <= endPage; i++) {
                pageElements.push(createInternalPageLink(i, i.toString()));
            }

            if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                    pageElements.push(document.createTextNode('...'));
                }
                pageElements.push(createInternalPageLink(totalPages, totalPages.toString()));
            }

            pageElements.forEach((el, index) => {
                innerSpan.appendChild(el);
                if (index < pageElements.length - 1) {
                    innerSpan.appendChild(document.createTextNode(', '));
                }
            });

            innerSpan.appendChild(document.createTextNode(']'));
            pageNumbersLi.appendChild(innerSpan);
            paginationUl.appendChild(pageNumbersLi);

            paginationUl.appendChild(createOuterPageLink(currentPage + 1, 'Next &gt;', currentPage >= totalPages));
        }

        // "Previous", Page Numbers, and "Next" are appended after "Per Page"
        // and only if totalPages > 1
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

            renderMyBookingsPaginationControls(
                'upcoming_bk_pg_',
                upcomingPaginationUl,
                upcomingPaginationContainer,
                upcomingCurrentPage,
                upcomingTotalPages,
                upcomingTotalItems,
                upcomingItemsPerPage,
                fetchUpcomingBookings,
                (val) => upcomingCurrentPage = val,
                (val) => upcomingItemsPerPage = val // Pass the setter for itemsPerPage
            );

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

            renderMyBookingsPaginationControls(
                'past_bk_pg_',
                pastPaginationUl,
                pastPaginationContainer,
                pastCurrentPage,
                pastTotalPages,
                pastTotalItems,
                pastItemsPerPage,
                fetchPastBookings,
                (val) => pastCurrentPage = val,
                (val) => pastItemsPerPage = val // Pass the setter for itemsPerPage
            );

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

    async function loadAvailableSlotsForModal(resourceId, dateString, initialStartTime) {
        if (!modalAvailableSlotsSelect) return;

        modalAvailableSlotsSelect.innerHTML = '<option value="">Loading...</option>';
        modalAvailableSlotsSelect.disabled = true;

        // Ensure dateString is in YYYY-MM-DD format for the API
        let formattedDateString = dateString;
        if (dateString.includes('T')) { // If it's an ISO string
            formattedDateString = dateString.split('T')[0];
        }

        try {
            // Use updateModalStatusDiv for displaying errors from this specific API call too
            const data = await apiCall(`/api/resources/${resourceId}/available_slots?date=${formattedDateString}`, {}, updateModalStatusDiv);
            modalAvailableSlotsSelect.innerHTML = ''; // Clear loading

            if (data && data.available_slots && data.available_slots.length > 0) {
                data.available_slots.forEach(slot => {
                    const option = document.createElement('option');
                    // Assuming slot.start_time and slot.end_time are full ISO strings
                    const displayStartTime = slot.start_time.substring(11, 16);
                    const displayEndTime = slot.end_time.substring(11, 16);
                    option.textContent = `${displayStartTime} - ${displayEndTime}`;
                    option.value = slot.start_time; // Store full start ISO string
                    option.dataset.endTime = slot.end_time; // Store full end ISO string

                    if (initialStartTime && initialStartTime === slot.start_time) {
                        option.selected = true;
                    }
                    modalAvailableSlotsSelect.appendChild(option);
                });
                modalAvailableSlotsSelect.disabled = false;
            } else {
                modalAvailableSlotsSelect.innerHTML = '<option value="">No slots available</option>';
                modalAvailableSlotsSelect.disabled = true;
            }
        } catch (error) {
            console.error('Error loading available slots:', error);
            modalAvailableSlotsSelect.innerHTML = '<option value="">Error loading slots</option>';
            modalAvailableSlotsSelect.disabled = true;
            // Ensure apiCall itself shows the error in updateModalStatusDiv, or:
            if (!updateModalStatusDiv.textContent || updateModalStatusDiv.style.display === 'none') {
                 showModalStatus('Failed to load available time slots. ' + (error.message || ''), 'danger');
            }
        }
    }

    if (modalBookingDateInput) {
        modalBookingDateInput.addEventListener('change', function() {
            const resourceId = modalBookingIdInput.dataset.resourceId;
            const newDateString = this.value;
            if (resourceId && newDateString) {
                // When date changes, we don't have an 'initialStartTime' to preselect for the new date.
                loadAvailableSlotsForModal(resourceId, newDateString, null);
            }
        });
    }

    document.addEventListener('click', async (event) => {
        const target = event.target;
        const bookingItem = target.closest('.booking-card'); // Changed from .booking-item to .booking-card

        if (target.classList.contains('edit-title-btn')) {
            event.stopPropagation(); // Prevent card click if any
            const bookingCardDiv = target.closest('.booking-card');
            if (!bookingCardDiv) return;

            const bookingId = bookingCardDiv.dataset.bookingId;
            const resourceId = bookingCardDiv.dataset.resourceId;
            const currentStartTimeISO = bookingCardDiv.dataset.startTime;
            const currentEndTimeISO = bookingCardDiv.dataset.endTime;

            // Store original times for comparison on save
            originalBookingStartTime = currentStartTimeISO;
            originalBookingEndTime = currentEndTimeISO;

            const titleValueElement = bookingCardDiv.querySelector('.booking-title-value');
            const currentTitle = titleValueElement ? titleValueElement.textContent : '';
            const resourceName = bookingCardDiv.querySelector('.resource-name-value').textContent;

            if (modalBookingIdInput) {
                modalBookingIdInput.value = bookingId;
                modalBookingIdInput.dataset.resourceId = resourceId; // For date change listener
                // Storing original times on the modalBookingIdInput's dataset as well, for access in submit handler
                modalBookingIdInput.dataset.originalStartTime = currentStartTimeISO;
                modalBookingIdInput.dataset.originalEndTime = currentEndTimeISO;
            }
            if (newBookingTitleInput) newBookingTitleInput.value = currentTitle;
            if (updateBookingModalLabel) updateBookingModalLabel.textContent = `Update Booking for: ${resourceName}`;

            if (modalBookingDateInput && currentStartTimeISO) {
                modalBookingDateInput.value = currentStartTimeISO.split('T')[0]; // Format YYYY-MM-DD
            }

            hideStatusMessage(updateModalStatusDiv); // Clear previous modal messages

            if (resourceId && currentStartTimeISO) {
                // Pass full currentStartTimeISO for potential pre-selection
                await loadAvailableSlotsForModal(resourceId, currentStartTimeISO.split('T')[0], currentStartTimeISO);
            } else {
                clearAndDisableSlotsSelect('Select date to see slots.'); // Or some other placeholder
            }

            lastFocusedButtonForModal = target; // Store the button that triggered the modal
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
            const bookingId = modalBookingIdInput.value;
            const newTitle = newBookingTitleInput.value.trim();
            const newDateValue = modalBookingDateInput.value; // YYYY-MM-DD from date picker
            const selectedSlotOption = modalAvailableSlotsSelect.options[modalAvailableSlotsSelect.selectedIndex];

            // Retrieve original times from the modalBookingIdInput's dataset for reliable comparison
            const originalStartTimeFromDataset = modalBookingIdInput.dataset.originalStartTime;
            const originalEndTimeFromDataset = modalBookingIdInput.dataset.originalEndTime;

            if (!newTitle) {
                showModalStatus('Title cannot be empty.', 'danger');
                return;
            }

            let payload = { title: newTitle };
            let dateTimeChanged = false;

            if (newDateValue && selectedSlotOption && selectedSlotOption.value) {
                const selectedSlotStartTime = selectedSlotOption.value; // Full ISO string
                const selectedSlotEndTime = selectedSlotOption.dataset.endTime; // Full ISO string

                // Check if date or time actually changed
                if (selectedSlotStartTime !== originalStartTimeFromDataset || selectedSlotEndTime !== originalEndTimeFromDataset) {
                    payload.start_time = selectedSlotStartTime;
                    payload.end_time = selectedSlotEndTime;
                    dateTimeChanged = true;
                }
            } else if (newDateValue && (!selectedSlotOption || !selectedSlotOption.value)) {
                // Date is present, but no slot selected. This is an issue if the date differs from original.
                const originalDateFromDataset = originalStartTimeFromDataset.split('T')[0];
                if (newDateValue !== originalDateFromDataset) {
                    showModalStatus('Please select an available time slot for the new date.', 'danger');
                    return;
                }
                // If date is same as original and no new slot selected, means time is not changing.
            }


            const submitButton = this.querySelector('button[type="submit"]'); // This is saveBookingTitleBtn
            const originalButtonText = submitButton.textContent;
            submitButton.textContent = 'Saving...';
            submitButton.disabled = true;
            hideStatusMessage(updateModalStatusDiv); // Clear previous specific modal status messages

            try {
                const responseData = await apiCall(`/api/bookings/${bookingId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, updateModalStatusDiv); // Pass status div for direct error display by apiCall

                if (responseData && responseData.success !== false) {
                    showSuccess(statusDiv, `Booking ${bookingId} details updated successfully.`); // Global success message
                    if (updateModal) updateModal.hide();
                    fetchUpcomingBookings();
                    fetchPastBookings();
                } else {
                    // Error message (e.g. validation from server) should have been displayed by apiCall in updateModalStatusDiv
                    // If not, or if responseData is null/undefined but no exception, show a generic one.
                    if (!updateModalStatusDiv.textContent || updateModalStatusDiv.style.display === 'none') {
                        showModalStatus(responseData?.message || 'Failed to update booking. Please check details.', 'danger');
                    }
                }
            } catch (error) {
                // This catch is for network errors or if apiCall itself throws an unexpected error
                console.error("Error submitting booking update form:", error);
                // apiCall should have shown the error. If not, this is a fallback.
                 if (!updateModalStatusDiv.textContent || updateModalStatusDiv.style.display === 'none') {
                    showModalStatus(error.message || 'An unexpected error occurred while updating booking.', 'danger');
                }
            } finally {
                submitButton.textContent = originalButtonText;
                submitButton.disabled = false;
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

    // Accessibility: Handle aria-hidden and focus for the update modal
    if (updateModalElement) {
        updateModalElement.addEventListener('shown.bs.modal', () => {
            updateModalElement.setAttribute('aria-hidden', 'false');
            if (newBookingTitleInput) {
                newBookingTitleInput.focus();
            }
        });

        updateModalElement.addEventListener('hidden.bs.modal', () => {
            updateModalElement.setAttribute('aria-hidden', 'true');
            if (lastFocusedButtonForModal) {
                lastFocusedButtonForModal.focus();
                lastFocusedButtonForModal = null; // Clear the reference
            }
        });
    }
});
