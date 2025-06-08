// JavaScript for User Management Page

document.addEventListener('DOMContentLoaded', function() {
    console.log("User Management JS Loaded");

    const userManagementStatusDiv = document.getElementById('user-management-status');
    const usersTableBody = document.querySelector('#users-table tbody');
    
    const userFormModal = document.getElementById('user-form-modal');
    const userForm = document.getElementById('user-form');
    const addNewUserBtn = document.getElementById('add-new-user-btn');
    const userFormModalTitle = document.getElementById('user-form-modal-title');
    const userFormModalStatusDiv = document.getElementById('user-form-modal-status');
    const closeModalBtn = userFormModal ? userFormModal.querySelector('.close-modal-btn') : null;

    const exportUsersBtn = document.getElementById('export-users-btn'); // For JSON export
    const exportUsersCsvBtn = document.getElementById('export-users-csv-btn'); // For CSV export
    const importUsersBtn = document.getElementById('import-users-btn'); // For JSON import
    const importUsersFile = document.getElementById('import-users-file');
    const importUsersCsvBtn = document.getElementById('import-users-csv-btn'); // For CSV import
    const importUsersCsvFile = document.getElementById('import-users-csv-file');
    const deleteSelectedUsersBtn = document.getElementById('delete-selected-users-btn');
    const selectAllUsersCheckbox = document.getElementById('select-all-users');

    const userIdInput = document.getElementById('user-id');
    const usernameInput = document.getElementById('username');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    const isAdminCheckbox = document.getElementById('is-admin');
    const userRolesCheckboxContainer = document.getElementById('user-roles-checkbox-container'); // For user edit modal

    const userFilterUsernameInput = document.getElementById('user-filter-username');
    const userFilterAdminSelect = document.getElementById('user-filter-admin');
    const userApplyFiltersBtn = document.getElementById('user-apply-filters-btn');
    const userClearFiltersBtn = document.getElementById('user-clear-filters-btn');

    // New Bulk Operations Elements
    const bulkAddUsersBtn = document.getElementById('bulk-add-users-btn');
    const bulkAddUsersModal = document.getElementById('bulk-add-users-modal');
    const bulkAddUsersForm = document.getElementById('bulk-add-users-form');
    const bulkAddDataTextarea = document.getElementById('bulk-add-data');
    const bulkAddStatusDiv = document.getElementById('bulk-add-status');
    const closeBulkAddModalBtn = bulkAddUsersModal ? bulkAddUsersModal.querySelector('.close-modal-btn') : null;

    const bulkEditSelectedUsersBtn = document.getElementById('bulk-edit-selected-users-btn');
    const bulkEditUsersModal = document.getElementById('bulk-edit-users-modal');
    const bulkEditUsersForm = document.getElementById('bulk-edit-users-form');
    const bulkEditSelectedCountSpan = document.getElementById('bulk-edit-selected-count');
    const bulkEditPasswordInput = document.getElementById('bulk-edit-password');
    const bulkEditConfirmPasswordInput = document.getElementById('bulk-edit-confirm-password');
    const bulkEditIsAdminEnableCheckbox = document.getElementById('bulk-edit-is-admin-enable');
    const bulkEditIsAdminSelect = document.getElementById('bulk-edit-is-admin');
    const bulkEditRolesEnableCheckbox = document.getElementById('bulk-edit-roles-enable');
    const bulkEditRolesCheckboxContainer = document.getElementById('bulk-edit-roles-checkbox-container');
    const bulkEditStatusDiv = document.getElementById('bulk-edit-status');
    const closeBulkEditModalBtn = bulkEditUsersModal ? bulkEditUsersModal.querySelector('.close-modal-btn') : null;

    const bulkAddPatternBtn = document.getElementById('bulk-add-pattern-btn');
    const bulkAddPatternModal = document.getElementById('bulk-add-pattern-modal');
    const bulkAddPatternForm = document.getElementById('bulk-add-pattern-form');
    const bulkAddPatternStatusDiv = document.getElementById('bulk-add-pattern-status');
    const patternRolesCheckboxContainer = document.getElementById('pattern-roles-checkbox-container');
    const closeBulkAddPatternModalBtn = bulkAddPatternModal ? bulkAddPatternModal.querySelector('.close-modal-btn') : null;


    let currentFilters = {};

    let localUsersCache = []; // To store fetched users for editing
    let allAvailableRolesCache = null; // To cache all available roles

    // --- Helper Function Availability (Assume from script.js) ---
    // apiCall, showLoading, showSuccess, showError, hideMessage

    function resetForm() {
        if (userForm) userForm.reset();
        if (userIdInput) userIdInput.value = '';
        if (userFormModalStatusDiv) hideMessage(userFormModalStatusDiv);
        if (passwordInput) {
            passwordInput.required = false; // Default to not required for edit
            passwordInput.placeholder = "Leave blank to keep current";
        }
        if (confirmPasswordInput) confirmPasswordInput.placeholder = "";

    }

    async function fetchAndDisplayUsers(filters = {}) {
        if (!usersTableBody) return;
        showLoading(userManagementStatusDiv, 'Fetching users...');
        try {
            const params = new URLSearchParams();
            params.append('page', currentUsersPage);
            params.append('per_page', usersItemsPerPage);

            if (currentFilters.username) params.append('username_filter', currentFilters.username);
            if (currentFilters.isAdmin !== undefined && currentFilters.isAdmin !== '') params.append('is_admin', currentFilters.isAdmin);
            // Add other filters like role_id if implemented
            // if (currentFilters.roleId) params.append('role_id', currentFilters.roleId);

            const data = await apiCall(`/api/admin/users?${params.toString()}`);

            localUsersCache = data.users || []; // Update cache with current page's users

            const usersTable = document.getElementById('users-table');
            const tableWrapper = usersTable ? usersTable.closest('.responsive-table-container') : null;
            if (tableWrapper) {
                if (data.pagination && data.pagination.total_pages > 1) {
                    tableWrapper.classList.add('scrollable-when-paginated');
                } else {
                    tableWrapper.classList.remove('scrollable-when-paginated');
                }
            }
            
            usersTableBody.innerHTML = ''; // Clear existing rows
            if (users && users.length > 0) {
                users.forEach(user => {
                    const row = usersTableBody.insertRow();
                    const selectCell = row.insertCell();
                    selectCell.innerHTML = `<input type="checkbox" class="select-user-checkbox" data-user-id="${user.id}">`;
                    row.insertCell().textContent = user.id;
                    row.insertCell().textContent = user.username;
                    row.insertCell().textContent = user.email;
                    row.insertCell().textContent = user.is_admin ? 'Yes' : 'No';
                    row.insertCell().textContent = user.roles.map(role => role.name).join(', ') || 'N/A'; // Display roles
                    row.insertCell().textContent = user.google_id ? 'Yes' : 'No';

                    const actionsCell = row.insertCell();
                    actionsCell.innerHTML = `
                        <button class="button edit-user-btn" data-user-id="${user.id}">Edit</button>
                        <button class="button danger delete-user-btn" data-user-id="${user.id}" data-username="${user.username}">Delete</button>
                        <button class="button assign-google-btn" data-user-id="${user.id}" ${user.google_id ? 'disabled' : ''}>
                            ${user.google_id ? 'Google Linked' : 'Link Google'}
                        </button>
                    `;
                });
                hideMessage(userManagementStatusDiv);
            } else {
                usersTableBody.innerHTML = '<tr><td colspan="7">No users found.</td></tr>';
                showSuccess(userManagementStatusDiv, 'No users to display.');
            }
        } catch (error) {
            showError(userManagementStatusDiv, `Error fetching users: ${error.message}`);
            localUsersCache = []; // Clear cache on error
        }
    }

    if (userApplyFiltersBtn) {
        userApplyFiltersBtn.addEventListener('click', () => {
            currentFilters.username = userFilterUsernameInput.value.trim();
            currentFilters.isAdmin = userFilterAdminSelect.value;
            fetchAndDisplayUsers(currentFilters);
        });
    }

    if (userClearFiltersBtn) {
        userClearFiltersBtn.addEventListener('click', () => {
            if (userFilterUsernameInput) userFilterUsernameInput.value = '';
            if (userFilterAdminSelect) userFilterAdminSelect.value = '';
            currentFilters = {};
            fetchAndDisplayUsers(currentFilters);
        });
    }

    if (exportUsersBtn) {
        exportUsersBtn.addEventListener('click', async () => {
            showLoading(userManagementStatusDiv, 'Exporting users...');
            try {
                const data = await apiCall('/api/admin/users/export');
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'users_export.json';
                a.click();
                URL.revokeObjectURL(url);
                showSuccess(userManagementStatusDiv, 'Export complete.');
            } catch (err) {
                console.error(err);
                showError(userManagementStatusDiv, 'JSON export failed: ' + err.message);
            }
        });
    }

    if (importUsersCsvBtn && importUsersCsvFile) {
        importUsersCsvBtn.addEventListener('click', () => importUsersCsvFile.click());
        importUsersCsvFile.addEventListener('change', async () => {
            const file = importUsersCsvFile.files[0];
            if (!file) return;

            showLoading(userManagementStatusDiv, 'Importing users from CSV...');
            const formData = new FormData();
            formData.append('file', file);

            try {
                // apiCall might need adjustment if it strictly sets Content-Type to application/json
                // For FormData, the browser sets it to multipart/form-data automatically with the correct boundary.
                // Let's assume apiCall can handle this or use fetch directly if not.
                // If using apiCall and it has a default 'Content-Type' header, it needs to be omitted for FormData.

                // Using fetch directly for clarity with FormData
                const csrfTokenTag = document.querySelector('meta[name="csrf-token"]');
                const csrfToken = csrfTokenTag ? csrfTokenTag.content : null;

                const fetchOptions = {
                    method: 'POST',
                    body: formData,
                    headers: {} // Initialize headers
                };
                if (csrfToken) {
                    fetchOptions.headers['X-CSRFToken'] = csrfToken;
                }

                const response = await fetch('/api/admin/users/import/csv', fetchOptions);

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || `HTTP error! status: ${response.status}`);
                }

                let message = `CSV Import finished. Created: ${result.users_created || 0}, Updated: ${result.users_updated || 0}.`;
                if (result.errors && result.errors.length > 0) {
                    const errorDetails = result.errors.map(err =>
                        `Row ${err.row} (User: ${err.username || 'N/A'}): ${err.error}`
                    ).join('<br>- ');
                    showError(userManagementStatusDiv, `${message}<br>Errors:<br>- ${errorDetails}`);
                } else {
                    showSuccess(userManagementStatusDiv, message);
                }

                if ((result.users_created || 0) > 0 || (result.users_updated || 0) > 0) {
                    fetchAndDisplayUsers(currentFilters); // Refresh table
                }

            } catch (e) {
                console.error('CSV Import error:', e);
                showError(userManagementStatusDiv, 'CSV Import failed: ' + e.message);
            } finally {
                importUsersCsvFile.value = ''; // Reset file input
            }
        });
    }

    if (exportUsersCsvBtn) {
        exportUsersCsvBtn.addEventListener('click', async () => {
            showLoading(userManagementStatusDiv, 'Exporting users to CSV...');
            try {
                const response = await fetch('/api/admin/users/export/csv');
                if (!response.ok) {
                    // Try to parse error from JSON response if API returns one for errors
                    let errorMsg = 'Network response was not ok: ' + response.statusText;
                    try {
                        const errData = await response.json();
                        if (errData && errData.error) {
                            errorMsg = errData.error;
                        }
                    } catch (e) {
                        // Ignore if error response is not JSON
                    }
                    throw new Error(errorMsg);
                }

                const disposition = response.headers.get('content-disposition');
                let filename = 'users_export.csv'; // Default filename
                if (disposition && disposition.indexOf('attachment') !== -1) {
                    const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                    const matches = filenameRegex.exec(disposition);
                    if (matches != null && matches[1]) {
                        filename = matches[1].replace(/['"]/g, '');
                    }
                }

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
                showSuccess(userManagementStatusDiv, 'Users exported to CSV successfully.');
            } catch (error) {
                console.error('Error exporting users to CSV:', error);
                showError(userManagementStatusDiv, 'CSV Export failed: ' + error.message);
            }
        });
    }

    if (importUsersBtn && importUsersFile) {
        importUsersBtn.addEventListener('click', () => importUsersFile.click());
        importUsersFile.addEventListener('change', async () => {
            const file = importUsersFile.files[0];
            if (!file) return;
            try {
                const text = await file.text();
                const json = JSON.parse(text);
                showLoading(userManagementStatusDiv, 'Importing users...');
                await apiCall('/api/admin/users/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(json)
                }, userManagementStatusDiv);
                fetchAndDisplayUsers(currentFilters);
            } catch (e) {
                console.error(e);
                showError(userManagementStatusDiv, 'Import failed.');
            } finally {
                importUsersFile.value = '';
            }
        });
    }

    if (selectAllUsersCheckbox) {
        selectAllUsersCheckbox.addEventListener('change', () => {
            const checkboxes = usersTableBody.querySelectorAll('.select-user-checkbox');
            checkboxes.forEach(cb => cb.checked = selectAllUsersCheckbox.checked);
        });
    }

    if (deleteSelectedUsersBtn) {
        deleteSelectedUsersBtn.addEventListener('click', async () => {
            const ids = Array.from(usersTableBody.querySelectorAll('.select-user-checkbox:checked')).map(cb => parseInt(cb.dataset.userId, 10));
            if (ids.length === 0) {
                showError(userManagementStatusDiv, 'No users selected.');
                return;
            }
            if (!confirm(`Are you sure you want to delete ${ids.length} selected users?`)) return;
            showLoading(userManagementStatusDiv, 'Deleting users...');
            try {
                await apiCall('/api/admin/users/bulk', {
                    method: 'DELETE',
                    body: JSON.stringify({ ids })
                }, userManagementStatusDiv);
                fetchAndDisplayUsers(currentFilters);
            } catch (err) {
                console.error(err);
            }
        });
    }

    // Modal Handling
    if (addNewUserBtn) {
        addNewUserBtn.addEventListener('click', async () => {
            resetForm();
            if (userFormModalTitle) userFormModalTitle.textContent = 'Add New User';
            if (passwordInput) {
                passwordInput.required = true;
                passwordInput.placeholder = "Enter password";
            }
            if (confirmPasswordInput) confirmPasswordInput.placeholder = "Confirm password";

            if (userFormModal) userFormModal.style.display = 'block';
            
            // Populate roles checkboxes
            await populateRolesForUserForm([]);
        });
    }

    async function populateRolesForUserForm(assignedRoleIds = []) {
        if (!userRolesCheckboxContainer) return;
        showLoading(userRolesCheckboxContainer, 'Loading roles...');

        try {
            if (!allAvailableRolesCache) {
                allAvailableRolesCache = await apiCall('/api/admin/roles');
            }
            userRolesCheckboxContainer.innerHTML = ''; // Clear previous

            if (!allAvailableRolesCache || allAvailableRolesCache.length === 0) {
                userRolesCheckboxContainer.innerHTML = '<small>No roles available.</small>';
                return;
            }

            allAvailableRolesCache.forEach(role => {
                const checkboxDiv = document.createElement('div');
                checkboxDiv.classList.add('checkbox-item');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `user-role-${role.id}`;
                checkbox.value = role.id;
                checkbox.name = 'role_ids';
                if (assignedRoleIds.includes(role.id)) {
                    checkbox.checked = true;
                }
                
                const label = document.createElement('label');
                label.htmlFor = `user-role-${role.id}`;
                label.textContent = role.name;

                checkboxDiv.appendChild(checkbox);
                checkboxDiv.appendChild(label);
                userRolesCheckboxContainer.appendChild(checkboxDiv);
            });
        } catch (error) {
            showError(userRolesCheckboxContainer, 'Failed to load roles for assignment.');
            console.error("Error populating roles checkboxes:", error);
        }
    }


    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            if (userFormModal) userFormModal.style.display = 'none';
        });
    }

    window.addEventListener('click', (event) => {
        if (event.target === userFormModal) {
            if (userFormModal) userFormModal.style.display = 'none';
        }
    });

    // Event Delegation for Edit/Delete/Link Google buttons
    if (usersTableBody) {
        usersTableBody.addEventListener('click', async (event) => {
            const target = event.target;
            if (target.classList.contains('edit-user-btn')) {
                const userId = target.dataset.userId;
                const user = localUsersCache.find(u => String(u.id) === userId);
                if (user) {
                    resetForm();
                    if (userFormModalTitle) userFormModalTitle.textContent = 'Edit User';
                    
                    if (userIdInput) userIdInput.value = user.id;
                    if (usernameInput) usernameInput.value = user.username;
                    if (emailInput) emailInput.value = user.email;
                    if (isAdminCheckbox) isAdminCheckbox.checked = user.is_admin;
                    
                    if (passwordInput) {
                        passwordInput.required = false; // Not required for edit unless changing
                        passwordInput.placeholder = "Leave blank to keep current";
                    }
                     if (confirmPasswordInput) confirmPasswordInput.placeholder = "Leave blank to keep current";

                    if (userFormModal) userFormModal.style.display = 'block';
                     // Populate roles for this user
                    await populateRolesForUserForm(user.roles.map(r => r.id));
                } else {
                    showError(userManagementStatusDiv, "Could not find user data to edit.");
                }
            } else if (target.classList.contains('delete-user-btn')) {
                const userId = target.dataset.userId;
                const username = target.dataset.username;
                // Placeholder for Delete User functionality (to be implemented in a later step)
                const usernameForConfirmation = target.dataset.username || 'this user';
                if (confirm(`Are you sure you want to delete user '${usernameForConfirmation}' (ID: ${userId})? This action cannot be undone.`)) {
                    showLoading(userManagementStatusDiv, `Deleting user ${username}...`);
                    apiCall(`/api/admin/users/${userId}`, { method: 'DELETE' }, userManagementStatusDiv)
                        .then(response => {
                            // apiCall's default behavior is to show response.message on success, 
                            // or hide messageElement if no message. We want a consistent success message.
                            showSuccess(userManagementStatusDiv, response.message || `User '${usernameForConfirmation}' deleted successfully.`);
                            fetchAndDisplayUsers(currentFilters); // Refresh the table
                        })
                        .catch(error => {
                            // apiCall already shows the error in userManagementStatusDiv
                            console.error(`Error deleting user ${userId}:`, error.message);
                            // Ensure a message is shown if apiCall's default didn't (e.g. network error before request)
                            if (!userManagementStatusDiv.textContent || userManagementStatusDiv.style.display === 'none') {
                                showError(userManagementStatusDiv, `Failed to delete user: ${error.message}`);
                            }
                        });
                }
            } else if (target.classList.contains('assign-google-btn')) {
                const userId = target.dataset.userId;
                const username = target.closest('tr').cells[1].textContent; // Get username from table cell

                if (target.disabled) {
                    return; // Button is disabled, do nothing
                }

                const googleIdToAssign = prompt(`Enter the Google ID to associate with user '${username}' (ID: ${userId}):`);

                if (googleIdToAssign && googleIdToAssign.trim() !== "") {
                    showLoading(userManagementStatusDiv, `Assigning Google ID to ${username}...`);
                    apiCall(`/api/admin/users/${userId}/assign_google_auth`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ google_id: googleIdToAssign.trim() })
                    }, userManagementStatusDiv)
                    .then(response => {
                        showSuccess(userManagementStatusDiv, response.message || `Google ID successfully assigned to '${username}'.`);
                        fetchAndDisplayUsers(currentFilters); // Refresh table
                    })
                    .catch(error => {
                        // apiCall already shows the error in userManagementStatusDiv
                        console.error(`Error assigning Google ID to user ${userId}:`, error.message);
                        if (!userManagementStatusDiv.textContent || userManagementStatusDiv.style.display === 'none') {
                             showError(userManagementStatusDiv, `Failed to assign Google ID: ${error.message}`);
                        }
                    });
                } else if (googleIdToAssign !== null) { // User pressed OK but input was empty
                    showError(userManagementStatusDiv, "Google ID cannot be empty. Assignment cancelled.");
                } else { // User cancelled the prompt
                    hideMessage(userManagementStatusDiv); // Clear any previous messages
                }
            }
        });
    }

    // Form Submission
    if (userForm) {
        userForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(userFormModalStatusDiv, 'Saving user...');

            const id = userIdInput.value;
            const username = usernameInput.value.trim();
            const email = emailInput.value.trim();
            const password = passwordInput.value; // No trim for password
            const confirmPassword = confirmPasswordInput.value;
            const isAdmin = isAdminCheckbox.checked;
            const selectedRoleIds = Array.from(userRolesCheckboxContainer.querySelectorAll('input[name="role_ids"]:checked'))
                                       .map(cb => parseInt(cb.value, 10));

            if (!username || !email) {
                showError(userFormModalStatusDiv, 'Username and Email are required.');
                return;
            }
            
            // Password validation
            if (!id || (id && password)) { // New user (no id) OR existing user and password field is filled
                if (!password) {
                    showError(userFormModalStatusDiv, 'Password is required for new users or when changing password.');
                    return;
                }
                if (password !== confirmPassword) {
                    showError(userFormModalStatusDiv, 'Passwords do not match.');
                    return;
                }
            }

            const userData = {
                username,
                email,
                is_admin: isAdmin,
                role_ids: selectedRoleIds // Add selected role IDs to the payload
            };

            if (password) { // Only include password if provided
                userData.password = password;
            }

            let response;
            try {
                if (id) { // Edit User
                    response = await apiCall(`/api/admin/users/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(userData)
                    }, userFormModalStatusDiv);
                } else { // Add User
                    response = await apiCall('/api/admin/users', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(userData)
                    }, userFormModalStatusDiv);
                }

                // apiCall now handles showing success/error in the passed message div
                // If no error was thrown by apiCall, it means it was successful.
                // The specific success message from API (if any) would be shown by apiCall.
                // If apiCall just hides the loading message on success, we might need our own.
                if (response && (response.id || response.message)) { // Check for successful response indicators
                    showSuccess(userManagementStatusDiv, `User ${id ? 'updated' : 'added'} successfully!`);
                    if (userFormModal) userFormModal.style.display = 'none';
                    fetchAndDisplayUsers(currentFilters); // Refresh the table
                } else if (!userFormModalStatusDiv.textContent || userFormModalStatusDiv.style.display === 'none') {
                    // If apiCall didn't show a message (e.g. 204 No Content or just hid loading)
                    showError(userFormModalStatusDiv, "Operation completed, but no specific confirmation received.");
                }

            } catch (error) {
                // Error should have been shown by apiCall in userFormModalStatusDiv.
                // If not, or for additional logging:
                console.error(`Failed to ${id ? 'update' : 'add'} user:`, error.message);
                if (!userFormModalStatusDiv.textContent || userFormModalStatusDiv.style.display === 'none') {
                     showError(userFormModalStatusDiv, `Operation failed: ${error.message}`);
                }
            }
        });
    }

    // Initial Setup
    if (userFormModal) userFormModal.style.display = 'none'; // Ensure modal is hidden initially
    if (bulkAddUsersModal) bulkAddUsersModal.style.display = 'none'; // Hide bulk add modal initially
    if (bulkEditUsersModal) bulkEditUsersModal.style.display = 'none'; // Hide bulk edit modal initially
    if (bulkAddPatternModal) bulkAddPatternModal.style.display = 'none'; // Hide pattern modal initially

    fetchAndDisplayUsers(currentFilters); // Fetch and display users on page load

    // --- Bulk Add Users ---
    if (bulkAddUsersBtn && bulkAddUsersModal) {
        bulkAddUsersBtn.addEventListener('click', () => {
            if (bulkAddUsersForm) bulkAddUsersForm.reset();
            hideMessage(bulkAddStatusDiv);
            bulkAddUsersModal.style.display = 'block';
        });
    }

    if (closeBulkAddModalBtn) {
        closeBulkAddModalBtn.addEventListener('click', () => {
            if (bulkAddUsersModal) bulkAddUsersModal.style.display = 'none';
        });
    }

    if (bulkAddUsersForm) {
        bulkAddUsersForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(bulkAddStatusDiv, 'Processing bulk add...');
            const rawData = bulkAddDataTextarea.value.trim();
            const lines = rawData.split('\n');
            const usersPayload = [];
            let parseErrors = [];

            lines.forEach((line, index) => {
                if (!line.trim()) return; // Skip empty lines
                const parts = line.split(',').map(p => p.trim());
                const [username, email, password, isAdminStr, ...roleIdsStr] = parts;

                if (!username || !email || !password) {
                    parseErrors.push(`Line ${index + 1}: Username, email, and password are required.`);
                    return;
                }

                const user = { username, email, password };
                if (isAdminStr) {
                    if (isAdminStr.toLowerCase() === 'true') user.is_admin = true;
                    else if (isAdminStr.toLowerCase() === 'false') user.is_admin = false;
                    // else ignore invalid isAdmin value, defaults to false on backend or per model
                }

                const role_ids = roleIdsStr.join(',').split(',').map(id => parseInt(id.trim(), 10)).filter(id => !isNaN(id) && id > 0);
                if (role_ids.length > 0) {
                    user.role_ids = role_ids;
                }
                usersPayload.push(user);
            });

            if (parseErrors.length > 0) {
                showError(bulkAddStatusDiv, `Parsing errors: <br>- ${parseErrors.join('<br>- ')}`);
                return;
            }

            if (usersPayload.length === 0) {
                showError(bulkAddStatusDiv, 'No valid user data to submit.');
                return;
            }

            try {
                const response = await apiCall('/api/admin/users/bulk_add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(usersPayload)
                }, bulkAddStatusDiv); // apiCall will show message in bulkAddStatusDiv

                // Display detailed results
                let resultSummary = `Bulk add completed. Added: ${response.users_added || 0}.`;
                if (response.errors && response.errors.length > 0) {
                    resultSummary += ` Errors: ${response.errors.length}.`;
                    const errorDetails = response.errors.map(err =>
                        `User (data: ${JSON.stringify(err.user_data)}): ${err.error}`
                    ).join('<br>- ');
                    showError(userManagementStatusDiv, `${resultSummary}<br>Error details:<br>- ${errorDetails}`);
                } else {
                    showSuccess(userManagementStatusDiv, resultSummary);
                }

                if ((response.users_added || 0) > 0) {
                    fetchAndDisplayUsers(currentFilters); // Refresh table
                }
                if (bulkAddUsersModal && (!response.errors || response.errors.length === 0) ) { // Close modal if no errors
                    bulkAddUsersModal.style.display = 'none';
                }

            } catch (error) {
                // apiCall should have handled showing the error in bulkAddStatusDiv
                // If not, or for general fallback:
                if (!bulkAddStatusDiv.textContent || bulkAddStatusDiv.style.display === 'none') {
                     showError(bulkAddStatusDiv, `Bulk add failed: ${error.message}`);
                }
                showError(userManagementStatusDiv, `Bulk add operation failed. Check modal for details.`);
            }
        });
    }

    // --- Bulk Edit Users ---
    async function populateRolesForBulkEditForm(selectedRoleIds = []) {
        if (!bulkEditRolesCheckboxContainer) return;
        showLoading(bulkEditRolesCheckboxContainer, 'Loading roles...');

        try {
            if (!allAvailableRolesCache) { // Assuming allAvailableRolesCache is populated by user form logic or similar
                allAvailableRolesCache = await apiCall('/api/admin/roles');
            }
            bulkEditRolesCheckboxContainer.innerHTML = ''; // Clear previous

            if (!allAvailableRolesCache || allAvailableRolesCache.length === 0) {
                bulkEditRolesCheckboxContainer.innerHTML = '<small>No roles available.</small>';
                return;
            }

            allAvailableRolesCache.forEach(role => {
                const checkboxDiv = document.createElement('div');
                checkboxDiv.classList.add('checkbox-item');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `bulk-edit-role-${role.id}`;
                checkbox.value = role.id;
                checkbox.name = 'bulk_edit_role_ids';
                // For bulk edit, "Set Roles" typically means you select the roles you want them to have.
                // So, pre-selection is not based on current user roles but what you want to set.
                // If implementing "Add Roles" or "Remove Roles", this logic would be different.
                // For "Set Roles", no pre-selection is typical unless loading a saved bulk template.
                // checkbox.checked = selectedRoleIds.includes(role.id);

                const label = document.createElement('label');
                label.htmlFor = `bulk-edit-role-${role.id}`;
                label.textContent = role.name;

                checkboxDiv.appendChild(checkbox);
                checkboxDiv.appendChild(label);
                bulkEditRolesCheckboxContainer.appendChild(checkboxDiv);
            });
             // Initially disable role checkboxes until "Change Roles?" is checked
            bulkEditRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.disabled = true);
        } catch (error) {
            showError(bulkEditRolesCheckboxContainer, 'Failed to load roles for bulk edit.');
            console.error("Error populating roles for bulk edit:", error);
        }
    }

    if (bulkEditIsAdminEnableCheckbox && bulkEditIsAdminSelect) {
        bulkEditIsAdminEnableCheckbox.addEventListener('change', function() {
            bulkEditIsAdminSelect.disabled = !this.checked;
        });
    }
    if (bulkEditRolesEnableCheckbox && bulkEditRolesCheckboxContainer) {
        bulkEditRolesEnableCheckbox.addEventListener('change', function() {
            bulkEditRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.disabled = !this.checked);
        });
    }


    if (bulkEditSelectedUsersBtn && bulkEditUsersModal) {
        bulkEditSelectedUsersBtn.addEventListener('click', async () => {
            const selectedUserIds = Array.from(usersTableBody.querySelectorAll('.select-user-checkbox:checked'))
                                      .map(cb => parseInt(cb.dataset.userId, 10));

            if (selectedUserIds.length === 0) {
                showError(userManagementStatusDiv, 'No users selected for bulk edit.');
                return;
            }

            if (bulkEditUsersForm) bulkEditUsersForm.reset();
            hideMessage(bulkEditStatusDiv);
            if (bulkEditSelectedCountSpan) bulkEditSelectedCountSpan.textContent = selectedUserIds.length;

            // Reset enable checkboxes and disable corresponding fields
            if (bulkEditIsAdminEnableCheckbox) bulkEditIsAdminEnableCheckbox.checked = false;
            if (bulkEditIsAdminSelect) bulkEditIsAdminSelect.disabled = true;
            if (bulkEditRolesEnableCheckbox) bulkEditRolesEnableCheckbox.checked = false;

            await populateRolesForBulkEditForm(); // Populates roles, initially disabled

            bulkEditUsersModal.style.display = 'block';
        });
    }

    if (closeBulkEditModalBtn) {
        closeBulkEditModalBtn.addEventListener('click', () => {
            if (bulkEditUsersModal) bulkEditUsersModal.style.display = 'none';
        });
    }

    if (bulkEditUsersForm) {
        bulkEditUsersForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(bulkEditStatusDiv, 'Processing bulk edit...');

            const selectedUserIds = Array.from(usersTableBody.querySelectorAll('.select-user-checkbox:checked'))
                                      .map(cb => parseInt(cb.dataset.userId, 10));

            if (selectedUserIds.length === 0) {
                showError(bulkEditStatusDiv, 'No users were selected (selection might have changed). Please re-select and try again.');
                showError(userManagementStatusDiv, 'Bulk edit failed: No users selected.');
                return;
            }

            const password = bulkEditPasswordInput.value;
            const confirmPassword = bulkEditConfirmPasswordInput.value;

            if (password && password !== confirmPassword) {
                showError(bulkEditStatusDiv, 'Passwords do not match.');
                return;
            }

            const payloadItems = [];
            selectedUserIds.forEach(id => {
                const updateData = { id };
                let hasUpdate = false;

                if (password) {
                    updateData.password = password;
                    hasUpdate = true;
                }
                if (bulkEditIsAdminEnableCheckbox.checked) {
                    updateData.is_admin = bulkEditIsAdminSelect.value === 'true';
                    hasUpdate = true;
                }
                if (bulkEditRolesEnableCheckbox.checked) {
                    updateData.role_ids = Array.from(bulkEditRolesCheckboxContainer.querySelectorAll('input[name="bulk_edit_role_ids"]:checked'))
                                            .map(cb => parseInt(cb.value, 10));
                    hasUpdate = true;
                }

                if(hasUpdate) {
                    payloadItems.push(updateData);
                }
            });

            if (payloadItems.length === 0) {
                showError(bulkEditStatusDiv, 'No changes specified for bulk edit.');
                return;
            }

            // It's possible that some users were deselected or form changed,
            // so we only send items for users that are still selected AND have changes.
            // However, the current logic is to prepare payload for all initially selected users if any field is to be changed.
            // For simplicity, we'll send the payload if any change was intended for the selected group.
            // The backend will process each item.
            // A more robust approach might re-check selection against payloadItems.

            try {
                const response = await apiCall('/api/admin/users/bulk_edit', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payloadItems) // Send only items with actual changes
                }, bulkEditStatusDiv);

                let resultSummary = `Bulk edit completed. Updated: ${response.users_updated || 0}.`;
                 if (response.errors && response.errors.length > 0) {
                    resultSummary += ` Errors: ${response.errors.length}.`;
                    const errorDetails = response.errors.map(err =>
                        `User ID ${err.id || (err.user_data ? err.user_data.id : 'N/A')}: ${err.error}`
                    ).join('<br>- ');
                    showError(userManagementStatusDiv, `${resultSummary}<br>Error details:<br>- ${errorDetails}`);
                } else {
                    showSuccess(userManagementStatusDiv, resultSummary);
                }

                if ((response.users_updated || 0) > 0) {
                    fetchAndDisplayUsers(currentFilters); // Refresh table
                }
                 if (bulkEditUsersModal && (!response.errors || response.errors.length === 0) ) { // Close modal if no errors
                    bulkEditUsersModal.style.display = 'none';
                }
            } catch (error) {
                 if (!bulkEditStatusDiv.textContent || bulkEditStatusDiv.style.display === 'none') {
                     showError(bulkEditStatusDiv, `Bulk edit failed: ${error.message}`);
                }
                showError(userManagementStatusDiv, `Bulk edit operation failed. Check modal for details.`);
            }
        });
    }


    // Window event listener for closing modals (generic, should cover new modals too)
    window.addEventListener('click', (event) => {
        if (event.target === userFormModal) {
            if (userFormModal) userFormModal.style.display = 'none';
        }
        if (event.target === roleFormModal) { // Existing from original script
            if (roleFormModal) roleFormModal.style.display = 'none';
        }
        if (event.target === bulkAddUsersModal) {
            if (bulkAddUsersModal) bulkAddUsersModal.style.display = 'none';
        }
        if (event.target === bulkEditUsersModal) {
            if (bulkEditUsersModal) bulkEditUsersModal.style.display = 'none';
        }
        if (event.target === bulkAddPatternModal) {
            if (bulkAddPatternModal) bulkAddPatternModal.style.display = 'none';
        }
    });

    // --- Bulk Add Users with Pattern ---
    async function populateRolesForPatternForm() { // Similar to populateRolesForUserForm but for pattern modal
        if (!patternRolesCheckboxContainer) return;
        showLoading(patternRolesCheckboxContainer, 'Loading roles...');
        try {
            if (!allAvailableRolesCache) {
                allAvailableRolesCache = await apiCall('/api/admin/roles');
            }
            patternRolesCheckboxContainer.innerHTML = ''; // Clear previous

            if (!allAvailableRolesCache || allAvailableRolesCache.length === 0) {
                patternRolesCheckboxContainer.innerHTML = '<small>No roles available.</small>';
                return;
            }
            allAvailableRolesCache.forEach(role => {
                const checkboxDiv = document.createElement('div');
                checkboxDiv.classList.add('checkbox-item');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `pattern-role-${role.id}`;
                checkbox.value = role.id;
                checkbox.name = 'pattern_role_ids';

                const label = document.createElement('label');
                label.htmlFor = `pattern-role-${role.id}`;
                label.textContent = role.name;

                checkboxDiv.appendChild(checkbox);
                checkboxDiv.appendChild(label);
                patternRolesCheckboxContainer.appendChild(checkboxDiv);
            });
        } catch (error) {
            showError(patternRolesCheckboxContainer, 'Failed to load roles.');
            console.error("Error populating roles for pattern form:", error);
        }
    }

    if (bulkAddPatternBtn && bulkAddPatternModal) {
        bulkAddPatternBtn.addEventListener('click', async () => {
            if (bulkAddPatternForm) bulkAddPatternForm.reset();
            hideMessage(bulkAddPatternStatusDiv);
            await populateRolesForPatternForm(); // Populate roles when modal is opened
            bulkAddPatternModal.style.display = 'block';
        });
    }

    if (closeBulkAddPatternModalBtn) {
        closeBulkAddPatternModalBtn.addEventListener('click', () => {
            if (bulkAddPatternModal) bulkAddPatternModal.style.display = 'none';
        });
    }

    if (bulkAddPatternForm) {
        bulkAddPatternForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(bulkAddPatternStatusDiv, 'Processing pattern bulk add...');

            const usernamePrefix = document.getElementById('pattern-username-prefix').value.trim();
            const usernameSuffix = document.getElementById('pattern-username-suffix').value.trim();
            const startNumber = parseInt(document.getElementById('pattern-start-number').value, 10);
            const count = parseInt(document.getElementById('pattern-count').value, 10);
            const emailDomain = document.getElementById('pattern-email-domain').value.trim();
            const emailPattern = document.getElementById('pattern-email-pattern').value.trim();
            const defaultPassword = document.getElementById('pattern-default-password').value;
            const confirmPassword = document.getElementById('pattern-confirm-password').value;
            const isAdmin = document.getElementById('pattern-is-admin').checked;
            const selectedRoleIds = Array.from(patternRolesCheckboxContainer.querySelectorAll('input[name="pattern_role_ids"]:checked'))
                                       .map(cb => parseInt(cb.value, 10));

            // Frontend Validations
            if (!usernamePrefix) {
                showError(bulkAddPatternStatusDiv, 'Username prefix is required.'); return;
            }
            if (isNaN(startNumber) || startNumber < 0) {
                showError(bulkAddPatternStatusDiv, 'Start number must be a non-negative integer.'); return;
            }
            if (isNaN(count) || count < 1 || count > 100) {
                showError(bulkAddPatternStatusDiv, 'Count must be between 1 and 100.'); return;
            }
            if (!emailDomain && !emailPattern) {
                showError(bulkAddPatternStatusDiv, 'Either Email Domain or Email Pattern is required.'); return;
            }
            if (emailDomain && emailPattern) {
                showError(bulkAddPatternStatusDiv, 'Provide either Email Domain or Email Pattern, not both.'); return;
            }
            if (emailPattern && !emailPattern.includes('{username}')) {
                 showError(bulkAddPatternStatusDiv, 'Email Pattern must contain "{username}" placeholder.'); return;
            }
            if (!defaultPassword) {
                showError(bulkAddPatternStatusDiv, 'Default password is required.'); return;
            }
            if (defaultPassword !== confirmPassword) {
                showError(bulkAddPatternStatusDiv, 'Passwords do not match.'); return;
            }

            const payload = {
                username_prefix: usernamePrefix,
                username_suffix: usernameSuffix,
                start_number: startNumber,
                count: count,
                email_domain: emailDomain || null, // Send null if empty
                email_pattern: emailPattern || null, // Send null if empty
                default_password: defaultPassword,
                is_admin: isAdmin,
                role_ids: selectedRoleIds
            };

            try {
                const response = await apiCall('/api/admin/users/bulk_add_pattern', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, bulkAddPatternStatusDiv); // apiCall will show message in modal status div

                let summaryMessage = `Pattern bulk add completed. Added: ${response.users_added || 0}.`;
                if (response.errors_warnings && response.errors_warnings.length > 0) {
                    summaryMessage += ` Skipped/Errors: ${response.errors_warnings.length}.`;
                    const errorDetails = response.errors_warnings.map(err =>
                        `Attempted User (Username: ${err.username || err.username_attempt || 'N/A'}, Email: ${err.email || err.email_attempt || 'N/A'}): ${err.error}`
                    ).join('<br>- ');
                    showError(userManagementStatusDiv, `${summaryMessage}<br>Details:<br>- ${errorDetails}`);
                } else {
                    showSuccess(userManagementStatusDiv, summaryMessage);
                }

                if ((response.users_added || 0) > 0) {
                    fetchAndDisplayUsers(currentFilters); // Refresh table
                }
                // Close modal only if fully successful or if only warnings (e.g. skips)
                if (bulkAddPatternModal && (!response.errors_warnings || response.errors_warnings.every(e => e.error.includes("already exists")))) {
                    // Consider closing if errors are just skips. For now, keeps modal open if any error/warning.
                    // if (bulkAddPatternModal && (!response.errors_warnings || response.errors_warnings.length === 0)) {
                    //    bulkAddPatternModal.style.display = 'none';
                    // }
                // The above commented out block was part of the previous erroneous fix attempt.
                // The correct logic is to ensure the try block is properly closed before the catch.
                // The following line for closing the modal if no errors is correct.
                if (bulkAddPatternModal && (!response.errors_warnings || response.errors_warnings.length === 0)) {
                    bulkAddPatternModal.style.display = 'none';
                }
				}
            // This is where the try block should end.
            } catch (error) { // This is the catch block
                // Error should have been shown by apiCall. If not, this is a fallback.
                if (!bulkAddPatternStatusDiv.textContent || bulkAddPatternStatusDiv.style.display === 'none') {
                     showError(bulkAddPatternStatusDiv, `Pattern bulk add failed: ${error.message}`);
                }
                showError(userManagementStatusDiv, `Pattern bulk add operation failed. Check modal for details.`);
            }
        });
    }

    // --- Role Management ---
    const roleManagementStatusDiv = document.getElementById('role-management-status');
    const rolesTableBody = document.querySelector('#roles-table tbody');
    const roleFormModal = document.getElementById('role-form-modal');
    const roleForm = document.getElementById('role-form');
    const addNewRoleBtn = document.getElementById('add-new-role-btn');
    const roleFormModalTitle = document.getElementById('role-form-modal-title');
    const roleFormModalStatusDiv = document.getElementById('role-form-modal-status');
    const closeRoleModalBtn = roleFormModal ? roleFormModal.querySelector('.close-modal-btn[data-modal-id="role-form-modal"]') : null;

    const roleIdInput = document.getElementById('role-id');
    const roleNameInput = document.getElementById('role-name');
    const roleDescriptionInput = document.getElementById('role-description');
    const rolePermissionsContainer = document.getElementById('role-permissions-container');

    const AVAILABLE_PERMISSIONS = [
        { id: 'make_bookings', label: 'Make Bookings' },
        { id: 'view_resources', label: 'View Resources' },
        { id: 'manage_users', label: 'Manage Users' },
        { id: 'manage_floor_maps', label: 'Manage Floor Maps' },
        { id: 'manage_resources', label: 'Manage Resources' },
        { id: 'manage_roles', label: 'Manage Roles' },
        { id: 'view_audit_logs', label: 'View Audit Logs' },
        { id: 'view_analytics', label: 'View Analytics' },
        { id: 'all_permissions', label: 'All Permissions' }
    ];

    function populatePermissionCheckboxes(selected = []) {
        if (!rolePermissionsContainer) return;
        rolePermissionsContainer.innerHTML = '';
        AVAILABLE_PERMISSIONS.forEach(perm => {
            const div = document.createElement('div');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `perm-${perm.id}`;
            checkbox.value = perm.id;
            if (selected.includes(perm.id)) checkbox.checked = true;
            const label = document.createElement('label');
            label.htmlFor = `perm-${perm.id}`;
            label.textContent = perm.label;
            div.appendChild(checkbox);
            div.appendChild(label);
            rolePermissionsContainer.appendChild(div);
        });
    }

    function getSelectedPermissions() {
        if (!rolePermissionsContainer) return [];
        return Array.from(rolePermissionsContainer.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
    }

    let localRolesCache = []; // To store fetched roles

    function resetRoleForm() {
        if (roleForm) roleForm.reset();
        if (roleIdInput) roleIdInput.value = '';
        if (roleFormModalStatusDiv) hideMessage(roleFormModalStatusDiv);
        populatePermissionCheckboxes([]);
    }

    async function fetchAndDisplayRoles() {
        if (!rolesTableBody) return;
        showLoading(roleManagementStatusDiv, 'Fetching roles...');
        try {
            const roles = await apiCall('/api/admin/roles'); // Assumes apiCall is global
            localRolesCache = roles;
            
            rolesTableBody.innerHTML = ''; // Clear existing rows
            if (roles && roles.length > 0) {
                roles.forEach(role => {
                    const row = rolesTableBody.insertRow();
                    row.insertCell().textContent = role.id;
                    row.insertCell().textContent = role.name;
                    row.insertCell().textContent = role.description || '';
                    row.insertCell().textContent = role.permissions || '';

                    const actionsCell = row.insertCell();
                    actionsCell.innerHTML = `
                        <button class="button edit-role-btn" data-role-id="${role.id}">Edit</button>
                        <button class="button danger delete-role-btn" data-role-id="${role.id}" data-role-name="${role.name}">Delete</button>
                    `;
                });
                hideMessage(roleManagementStatusDiv);
            } else {
                rolesTableBody.innerHTML = '<tr><td colspan="5">No roles found.</td></tr>';
                showSuccess(roleManagementStatusDiv, 'No roles defined yet.');
            }
        } catch (error) {
            showError(roleManagementStatusDiv, `Error fetching roles: ${error.message}`);
            localRolesCache = [];
        }
    }

    // Role Modal Handling
    if (addNewRoleBtn) {
        addNewRoleBtn.addEventListener('click', () => {
            resetRoleForm();
            if (roleFormModalTitle) roleFormModalTitle.textContent = 'Add New Role';
            if (roleFormModal) roleFormModal.style.display = 'block';
        });
    }

    if (closeRoleModalBtn) {
        closeRoleModalBtn.addEventListener('click', () => {
            if (roleFormModal) roleFormModal.style.display = 'none';
        });
    }

    window.addEventListener('click', (event) => { // Also handles role modal
        if (event.target === userFormModal) {
            if (userFormModal) userFormModal.style.display = 'none';
        }
        if (event.target === roleFormModal) {
            if (roleFormModal) roleFormModal.style.display = 'none';
        }
        // The bulk modals event listeners for window click are already present
        // in the main section (around line 772), so no need to repeat here.
        // if (event.target === bulkAddUsersModal) {
        //     if (bulkAddUsersModal) bulkAddUsersModal.style.display = 'none';
        // }
        // if (event.target === bulkEditUsersModal) {
        //     if (bulkEditUsersModal) bulkEditUsersModal.style.display = 'none';
        // }
        // if (event.target === bulkAddPatternModal) {
        //     if (bulkAddPatternModal) bulkAddPatternModal.style.display = 'none';
        // }
    });


    // Event Delegation for Edit/Delete Role buttons
    if (rolesTableBody) {
        rolesTableBody.addEventListener('click', (event) => {
            const target = event.target;
            if (target.classList.contains('edit-role-btn')) {
                const roleId = target.dataset.roleId;
                const role = localRolesCache.find(r => String(r.id) === roleId);
                if (role) {
                    resetRoleForm();
                    if (roleFormModalTitle) roleFormModalTitle.textContent = 'Edit Role';
                    
                    if (roleIdInput) roleIdInput.value = role.id;
                    if (roleNameInput) roleNameInput.value = role.name;
                    if (roleDescriptionInput) roleDescriptionInput.value = role.description || '';
                    const selectedPerms = role.permissions ? role.permissions.split(',').map(p => p.trim()).filter(p => p) : [];
                    populatePermissionCheckboxes(selectedPerms);
                    
                    if (roleFormModal) roleFormModal.style.display = 'block';
                } else {
                    showError(roleManagementStatusDiv, "Could not find role data to edit.");
                }
            } else if (target.classList.contains('delete-role-btn')) {
                const roleId = target.dataset.roleId;
                const roleName = target.dataset.roleName || 'this role';
                if (confirm(`Are you sure you want to delete role '${roleName}' (ID: ${roleId})? This action cannot be undone.`)) {
                    showLoading(roleManagementStatusDiv, `Deleting role ${roleName}...`);
                    apiCall(`/api/admin/roles/${roleId}`, { method: 'DELETE' }, roleManagementStatusDiv)
                        .then(response => {
                            showSuccess(roleManagementStatusDiv, response.message || `Role '${roleName}' deleted successfully.`);
                            fetchAndDisplayRoles(); 
                        })
                        .catch(error => {
                             console.error(`Error deleting role ${roleId}:`, error.message);
                            if (!roleManagementStatusDiv.textContent || roleManagementStatusDiv.style.display === 'none') {
                                showError(roleManagementStatusDiv, `Failed to delete role: ${error.message}`);
                            }
                        });
                }
            }
        });
    }

    // Role Form Submission
    if (roleForm) {
        roleForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(roleFormModalStatusDiv, 'Saving role...');

            const id = roleIdInput.value;
            const name = roleNameInput.value.trim();
            const description = roleDescriptionInput.value.trim();

            if (!name) {
                showError(roleFormModalStatusDiv, 'Role Name is required.');
                return;
            }

            const roleData = { name, description, permissions: getSelectedPermissions() };
            let response;
            try {
                if (id) { // Edit Role
                    response = await apiCall(`/api/admin/roles/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(roleData)
                    }, roleFormModalStatusDiv);
                } else { // Add Role
                    response = await apiCall('/api/admin/roles', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(roleData)
                    }, roleFormModalStatusDiv);
                }

                if (response && (response.id || response.message)) {
                    showSuccess(roleManagementStatusDiv, `Role ${id ? 'updated' : 'added'} successfully!`);
                    if (roleFormModal) roleFormModal.style.display = 'none';
                    fetchAndDisplayRoles(); 
                } else if (!roleFormModalStatusDiv.textContent || roleFormModalStatusDiv.style.display === 'none') {
                    showError(roleFormModalStatusDiv, "Operation completed, but no specific confirmation received.");
                }
            } catch (error) {
                console.error(`Failed to ${id ? 'update' : 'add'} role:`, error.message);
                 if (!roleFormModalStatusDiv.textContent || roleFormModalStatusDiv.style.display === 'none') {
                     showError(roleFormModalStatusDiv, `Operation failed: ${error.message}`);
                }
            }
        });
    }

    // Initial load for roles
    if (roleFormModal) roleFormModal.style.display = 'none';
    // bulkEditUserModal and bulkAddUserModal are handled by the primary implementations
    // and their initial display:none is set earlier.

    fetchAndDisplayRoles(); // This also populates allAvailableRolesCache for user forms

});
