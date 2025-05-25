// JavaScript for Audit Log View Page

document.addEventListener('DOMContentLoaded', function() {
    console.log("Log View JS Loaded");

    const logTableBody = document.querySelector('#audit-log-table tbody');
    const logViewStatusDiv = document.getElementById('log-view-status');
    
    // Pagination elements
    const prevPageBtn = document.getElementById('prev-page-btn');
    const nextPageBtn = document.getElementById('next-page-btn');
    const pageInfoSpan = document.getElementById('page-info');
    const totalLogsInfoSpan = document.getElementById('total-logs-info'); // Added

    // Filter elements
    const filterForm = document.getElementById('filter-form'); // Assuming the form wrapping filters
    const logFilterStartDateInput = document.getElementById('log-filter-start-date'); // Changed ID from prompt for consistency
    const logFilterEndDateInput = document.getElementById('log-filter-end-date');   // Changed ID
    const logFilterUsernameInput = document.getElementById('log-filter-username'); // Changed ID
    const logFilterActionInput = document.getElementById('log-filter-action');     // Changed ID
    // const logApplyFiltersBtn = document.getElementById('log-apply-filters-btn'); // This will be the form submit
    const logClearFiltersBtn = document.getElementById('log-clear-filters-btn');

    let currentPage = 1;
    const defaultPerPage = 30; 
    let currentFilters = {}; // Store current filter values

    // --- Helper Function Availability (Assume from script.js) ---
    // apiCall, showLoading, showSuccess, showError, hideMessage
    // These are assumed to be globally available from script.js

    function formatTimestamp(isoString) {
        if (!isoString) return 'N/A';
        const date = new Date(isoString);
        // Example: "2023-10-26, 14:35:02" - adjust as needed
        return date.toLocaleString(undefined, { 
            year: 'numeric', month: '2-digit', day: '2-digit', 
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false 
        });
    }
    
    function updatePaginationControls(apiResponse) {
        if (!apiResponse) return;

        currentPage = apiResponse.current_page;
        const totalPages = apiResponse.total_pages;

        if (pageInfoSpan) pageInfoSpan.textContent = `Page ${currentPage} of ${totalPages}`;
        if (totalLogsInfoSpan) totalLogsInfoSpan.textContent = `Total logs: ${apiResponse.total_logs}`;

        if (prevPageBtn) prevPageBtn.disabled = currentPage <= 1;
        if (nextPageBtn) nextPageBtn.disabled = currentPage >= totalPages;
    }


    async function fetchLogs(page = 1, filters = {}) {
        if (!logTableBody || !logViewStatusDiv) {
            console.error("Required table elements not found for displaying logs.");
            return;
        }
        showLoading(logViewStatusDiv, 'Fetching audit logs...');
        
        let queryParams = `page=${page}&per_page=${defaultPerPage}`;
        
        // Use the global currentFilters if filters arg is not explicitly passed with new values
        const activeFilters = Object.keys(filters).length > 0 ? filters : currentFilters;

        if (activeFilters.startDate) queryParams += `&start_date=${encodeURIComponent(activeFilters.startDate)}`;
        if (activeFilters.endDate) queryParams += `&end_date=${encodeURIComponent(activeFilters.endDate)}`;
        if (activeFilters.username) queryParams += `&username_filter=${encodeURIComponent(activeFilters.username)}`;
        if (activeFilters.action) queryParams += `&action_filter=${encodeURIComponent(activeFilters.action)}`;

        try {
            const response = await apiCall(`/api/admin/logs?${queryParams}`); 
            
            logTableBody.innerHTML = ''; // Clear existing rows
            if (response.logs && response.logs.length > 0) {
                response.logs.forEach(log => {
                    const row = logTableBody.insertRow();
                    row.insertCell().textContent = formatTimestamp(log.timestamp);
                    row.insertCell().textContent = log.user_id || 'N/A';
                    row.insertCell().textContent = log.username || 'N/A';
                    row.insertCell().textContent = log.action;
                    row.insertCell().textContent = log.details || '';
                });
                hideMessage(logViewStatusDiv);
            } else {
                logTableBody.innerHTML = '<tr><td colspan="5">No audit log entries found.</td></tr>';
                showSuccess(logViewStatusDiv, 'No logs to display for the current filters/page.');
            }
            updatePaginationControls(response);

        } catch (error) {
            showError(logViewStatusDiv, `Error fetching audit logs: ${error.message}`);
            if (logTableBody) logTableBody.innerHTML = '<tr><td colspan="5">Error loading logs.</td></tr>';
            // Reset pagination on error
            if (pageInfoSpan) pageInfoSpan.textContent = 'Page 1 of 1';
            if (totalLogsInfoSpan) totalLogsInfoSpan.textContent = 'Total logs: 0';
            if (prevPageBtn) prevPageBtn.disabled = true;
            if (nextPageBtn) nextPageBtn.disabled = true;
        }
    }

    // Pagination Controls Event Listeners
    if (prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                fetchLogs(currentPage - 1, currentFilters); 
            }
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            // totalPages is updated by updatePaginationControls
            const totalPages = parseInt(pageInfoSpan.textContent.split(' of ')[1] || '1', 10); 
            if (currentPage < totalPages) {
                fetchLogs(currentPage + 1, currentFilters);
            }
        });
    }
    
    // Filter Form Event Listener
    // The prompt used id "filter-form", but existing HTML has individual inputs and buttons.
    // I'll use the existing button "log-apply-filters-btn" from the HTML.
    const applyFiltersButton = document.getElementById('log-apply-filters-btn');
    if (applyFiltersButton) { // Check if the button exists
        applyFiltersButton.addEventListener('click', () => { // Changed from form submit to button click
            currentFilters = {
                startDate: logFilterStartDateInput.value,
                endDate: logFilterEndDateInput.value,
                username: logFilterUsernameInput.value.trim(),
                action: logFilterActionInput.value.trim()
            };
            // Remove empty filters to avoid sending empty params
            for (const key in currentFilters) {
                if (!currentFilters[key]) {
                    delete currentFilters[key];
                }
            }
            fetchLogs(1, currentFilters); // Reset to page 1, use currentFilters
        });
    }


    if (logClearFiltersBtn) {
        logClearFiltersBtn.addEventListener('click', () => {
            if (logFilterStartDateInput) logFilterStartDateInput.value = '';
            if (logFilterEndDateInput) logFilterEndDateInput.value = '';
            if (logFilterUsernameInput) logFilterUsernameInput.value = '';
            if (logFilterActionInput) logFilterActionInput.value = '';
            currentFilters = {};
            fetchLogs(1, currentFilters); 
        });
    }

    // Initial Load
    fetchLogs(1, currentFilters); 
});
