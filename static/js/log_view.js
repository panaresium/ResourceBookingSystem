// JavaScript for Audit Log View Page

document.addEventListener('DOMContentLoaded', function() {
    console.log("Log View JS Loaded");

    const logTableBody = document.querySelector('#audit-log-table tbody');
    const logViewStatusDiv = document.getElementById('log-view-status');
    const prevPageBtn = document.getElementById('prev-page-btn');
    const nextPageBtn = document.getElementById('next-page-btn');
    const pageInfoSpan = document.getElementById('page-info');
    
    const logFilterStartDateInput = document.getElementById('log-filter-start-date');
    const logFilterEndDateInput = document.getElementById('log-filter-end-date');
    const logFilterUsernameInput = document.getElementById('log-filter-username');
    const logFilterActionInput = document.getElementById('log-filter-action');
    const logApplyFiltersBtn = document.getElementById('log-apply-filters-btn');
    const logClearFiltersBtn = document.getElementById('log-clear-filters-btn');

    let currentPage = 1;
    const defaultPerPage = 30; 
    let totalPages = 1;
    let currentLogFilters = {}; // Store current filter values

    // --- Helper Function Availability (Assume from script.js) ---
    // apiCall, showLoading, showSuccess, showError, hideMessage
    // If not global, these would need to be defined or imported.

    function formatTimestamp(isoString) {
        if (!isoString) return 'N/A';
        const date = new Date(isoString);
        return date.toLocaleString(); // Adjust format as needed, e.g., to 'YYYY-MM-DD HH:mm:ss'
    }

    async function fetchAndDisplayLogs(page = 1, perPage = defaultPerPage) {
        if (!logTableBody || !logViewStatusDiv) {
            console.error("Required table elements not found for displaying logs.");
            return;
        }
        showLoading(logViewStatusDiv, 'Fetching audit logs...');
        
        let queryParams = `page=${page}&per_page=${perPage}`;
        
        if (currentLogFilters.startDate) queryParams += `&start_date=${encodeURIComponent(currentLogFilters.startDate)}`;
        if (currentLogFilters.endDate) queryParams += `&end_date=${encodeURIComponent(currentLogFilters.endDate)}`;
        if (currentLogFilters.username) queryParams += `&username_filter=${encodeURIComponent(currentLogFilters.username)}`;
        if (currentLogFilters.action) queryParams += `&action_filter=${encodeURIComponent(currentLogFilters.action)}`;

        try {
            const response = await apiCall(`/api/admin/logs?${queryParams}`); // Assumes apiCall is global
            
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

            // Update pagination info
            currentPage = response.current_page;
            totalPages = response.total_pages;
            if (pageInfoSpan) pageInfoSpan.textContent = `Page ${currentPage} of ${totalPages}`;

            if (prevPageBtn) prevPageBtn.disabled = currentPage <= 1;
            if (nextPageBtn) nextPageBtn.disabled = currentPage >= totalPages;

        } catch (error) {
            showError(logViewStatusDiv, `Error fetching audit logs: ${error.message}`);
            if (logTableBody) logTableBody.innerHTML = '<tr><td colspan="5">Error loading logs.</td></tr>';
        }
    }

    // Pagination Controls
    if (prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                fetchAndDisplayLogs(currentPage - 1, defaultPerPage); // Pass perPage and use global filters
            }
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                fetchAndDisplayLogs(currentPage + 1, defaultPerPage); // Pass perPage and use global filters
            }
        });
    }
    
    if (logApplyFiltersBtn) {
        logApplyFiltersBtn.addEventListener('click', () => {
            currentLogFilters = {
                startDate: logFilterStartDateInput.value,
                endDate: logFilterEndDateInput.value,
                username: logFilterUsernameInput.value.trim(),
                action: logFilterActionInput.value.trim()
            };
            // Remove empty filters to avoid sending empty params
            for (const key in currentLogFilters) {
                if (!currentLogFilters[key]) {
                    delete currentLogFilters[key];
                }
            }
            fetchAndDisplayLogs(1, defaultPerPage); // Reset to page 1, use global filters
        });
    }

    if (logClearFiltersBtn) {
        logClearFiltersBtn.addEventListener('click', () => {
            logFilterStartDateInput.value = '';
            logFilterEndDateInput.value = '';
            logFilterUsernameInput.value = '';
            logFilterActionInput.value = '';
            currentLogFilters = {};
            fetchAndDisplayLogs(1, defaultPerPage); // Reset to page 1, use empty global filters
        });
    }

    // Initial Load
    fetchAndDisplayLogs(1, defaultPerPage); // Use global filters (initially empty)
});
