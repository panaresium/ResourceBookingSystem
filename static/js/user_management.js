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

    const exportUsersBtn = document.getElementById('export-users-btn');
    const importUsersBtn = document.getElementById('import-users-btn');
    const importUsersFile = document.getElementById('import-users-file');
    const deleteSelectedUsersBtn = document.getElementById('delete-selected-users-btn');
    const selectAllUsersCheckbox = document.getElementById('select-all-users');
    const bulkEditUsersBtn = document.getElementById('bulk-edit-users-btn'); // New

    // Bulk Edit Modal Elements
    const bulkEditUserModal = document.getElementById('bulk-edit-user-modal'); // New
    const bulkEditUserForm = document.getElementById('bulk-edit-user-form'); // New
    const bulkSetAdminSelect = document.getElementById('bulk-set-admin'); // New
    const bulkEdit_addRolesContainer = document.getElementById('bulk-add-roles-container'); // Renamed for clarity and to avoid collision
    const bulkRemoveRolesContainer = document.getElementById('bulk-remove-roles-container'); // New
    const bulkEditUserModalStatusDiv = document.getElementById('bulk-edit-user-modal-status'); // New
    const bulkEditSelectedCountSpan = document.getElementById('bulk-edit-selected-count'); // New
    const closeBulkEditModalBtn = bulkEditUserModal ? bulkEditUserModal.querySelector('.close-modal-btn') : null; //New

    // Bulk Add Users (Pattern) Modal Elements
    const bulkAddUsersBtn = document.getElementById('bulk-add-users-btn'); // New
    const bulkAddUserModal = document.getElementById('bulk-add-user-modal'); // New
    const bulkAddUserForm = document.getElementById('bulk-add-user-form'); // New
    const bulkAddUsernamePatternInput = document.getElementById('bulk-add-username-pattern'); // New
    const bulkAddStartIndexInput = document.getElementById('bulk-add-start-index'); // New
    const bulkAddCountInput = document.getElementById('bulk-add-count'); // New
    const bulkAddDefaultPasswordInput = document.getElementById('bulk-add-default-password'); // New
    const bulkAddEmailPatternInput = document.getElementById('bulk-add-email-pattern'); // New
    const bulkAddIsAdminCheckbox = document.getElementById('bulk-add-is-admin'); // New
    // Assumes HTML ID will be changed to 'bulk-add-pattern-roles-container' for this distinct element
    const bulkAddPattern_rolesContainer = document.getElementById('bulk-add-pattern-roles-container'); // Renamed and ID corrected
    const bulkAddUserModalStatusDiv = document.getElementById('bulk-add-user-modal-status'); // New
    const closeBulkAddModalBtn = bulkAddUserModal ? bulkAddUserModal.querySelector('.close-modal-btn') : null; // New


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
            let queryParams = [];
            const activeFilters = Object.keys(filters).length > 0 ? filters : currentFilters;
            if (activeFilters.username) queryParams.push(`username_filter=${encodeURIComponent(activeFilters.username)}`);
            if (activeFilters.isAdmin !== undefined && activeFilters.isAdmin !== '') queryParams.push(`is_admin=${activeFilters.isAdmin}`);
            const queryString = queryParams.length ? `?${queryParams.join('&')}` : '';

            const users = await apiCall(`/api/admin/users${queryString}`); // Assumes apiCall is global
            localUsersCache = users; // Store for local use (e.g., populating edit form)
            
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
    fetchAndDisplayUsers(currentFilters); // Fetch and display users on page load

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
        if (event.target === bulkEditUserModal) { // New for bulk edit modal
            if (bulkEditUserModal) bulkEditUserModal.style.display = 'none';
        }
        if (event.target === bulkAddUserModal) { // New for bulk add modal
            if (bulkAddUserModal) bulkAddUserModal.style.display = 'none';
        }
    });

    // --- Bulk User Edit Functionality ---
    function populateRolesForBulkEditModal(selectedAddIds = [], selectedRemoveIds = []) {
        if (!bulkEdit_addRolesContainer || !bulkRemoveRolesContainer) return; // Use renamed variable

        showLoading(bulkEdit_addRolesContainer, 'Loading roles...'); // Use renamed variable
        showLoading(bulkRemoveRolesContainer, 'Loading roles...');

        // Use cached roles if available, otherwise fetch
        const rolesPromise = allAvailableRolesCache ? Promise.resolve(allAvailableRolesCache) : apiCall('/api/admin/roles');

        rolesPromise.then(roles => {
            if (!allAvailableRolesCache) {
                allAvailableRolesCache = roles; // Cache them if fetched now
            }

            bulkEdit_addRolesContainer.innerHTML = ''; // Clear previous - Use renamed variable
            bulkRemoveRolesContainer.innerHTML = '';

            if (!roles || roles.length === 0) {
                const noRolesMsg = '<small>No roles available.</small>';
                bulkEdit_addRolesContainer.innerHTML = noRolesMsg; // Use renamed variable
                bulkRemoveRolesContainer.innerHTML = noRolesMsg;
                return;
            }

            roles.forEach(role => {
                // Populate Add Roles Container
                const addCheckboxDiv = document.createElement('div');
                addCheckboxDiv.classList.add('checkbox-item');
                const addCheckbox = document.createElement('input');
                addCheckbox.type = 'checkbox';
                addCheckbox.id = `bulk-edit-add-role-${role.id}`; // Changed ID prefix for uniqueness
                addCheckbox.value = role.id;
                addCheckbox.name = 'bulk_edit_add_role_ids'; // Changed name for clarity
                if (selectedAddIds.includes(role.id)) addCheckbox.checked = true;

                const addLabel = document.createElement('label');
                addLabel.htmlFor = `bulk-edit-add-role-${role.id}`; // Changed ID prefix
                addLabel.textContent = role.name;

                addCheckboxDiv.appendChild(addCheckbox);
                addCheckboxDiv.appendChild(addLabel);
                bulkEdit_addRolesContainer.appendChild(addCheckboxDiv); // Use renamed variable

                // Populate Remove Roles Container
                const removeCheckboxDiv = document.createElement('div');
                removeCheckboxDiv.classList.add('checkbox-item');
                const removeCheckbox = document.createElement('input');
                removeCheckbox.type = 'checkbox';
                removeCheckbox.id = `bulk-edit-remove-role-${role.id}`; // Changed ID prefix for uniqueness
                removeCheckbox.value = role.id;
                removeCheckbox.name = 'bulk_edit_remove_role_ids'; // Changed name for clarity
                if (selectedRemoveIds.includes(role.id)) removeCheckbox.checked = true;

                const removeLabel = document.createElement('label');
                removeLabel.htmlFor = `bulk-edit-remove-role-${role.id}`; // Changed ID prefix
                removeLabel.textContent = role.name;

                removeCheckboxDiv.appendChild(removeCheckbox);
                removeCheckboxDiv.appendChild(removeLabel);
                bulkRemoveRolesContainer.appendChild(removeCheckboxDiv);
            });
        }).catch(error => {
            showError(bulkEdit_addRolesContainer, 'Failed to load roles.'); // Use renamed variable
            showError(bulkRemoveRolesContainer, 'Failed to load roles.');
            console.error("Error populating roles for bulk edit:", error);
        });
    }

    if (bulkEditUsersBtn) {
        bulkEditUsersBtn.addEventListener('click', async () => {
            const selectedUserIds = Array.from(usersTableBody.querySelectorAll('.select-user-checkbox:checked'))
                                       .map(cb => parseInt(cb.dataset.userId, 10));

            if (selectedUserIds.length === 0) {
                showError(userManagementStatusDiv, 'No users selected for bulk edit.');
                return;
            }

            if (bulkEditUserForm) bulkEditUserForm.reset();
            if (bulkEditUserModalStatusDiv) hideMessage(bulkEditUserModalStatusDiv);
            if (bulkSetAdminSelect) bulkSetAdminSelect.value = ""; // Reset to "No Change"
            if (bulkEditSelectedCountSpan) bulkEditSelectedCountSpan.textContent = selectedUserIds.length;


            // Populate roles (this will also fetch if cache is empty)
            // Ensure roles are loaded before showing the modal if they aren't cached
            if (!allAvailableRolesCache) {
                try {
                    showLoading(userManagementStatusDiv, "Loading roles for bulk edit...");
                    allAvailableRolesCache = await apiCall('/api/admin/roles');
                    hideMessage(userManagementStatusDiv);
                } catch (error) {
                    showError(userManagementStatusDiv, `Failed to load roles: ${error.message}. Please try again.`);
                    return;
                }
            }
            populateRolesForBulkEditModal([], []); // Populate with no roles pre-selected

            if (bulkEditUserModal) bulkEditUserModal.style.display = 'block';
        });
    }

    if (closeBulkEditModalBtn) {
        closeBulkEditModalBtn.addEventListener('click', () => {
            if (bulkEditUserModal) bulkEditUserModal.style.display = 'none';
        });
    }

    if (bulkEditUserForm) {
        bulkEditUserForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(bulkEditUserModalStatusDiv, 'Applying bulk changes...');

            const selectedUserIds = Array.from(usersTableBody.querySelectorAll('.select-user-checkbox:checked'))
                                       .map(cb => parseInt(cb.dataset.userId, 10));

            if (selectedUserIds.length === 0) {
                showError(bulkEditUserModalStatusDiv, 'No users selected. Please select users from the table first.');
                return; // Should not happen if modal was opened correctly, but as a safeguard
            }

            const setAdminValue = bulkSetAdminSelect.value;
            let setAdmin = null;
            if (setAdminValue === "true") setAdmin = true;
            else if (setAdminValue === "false") setAdmin = false;

            const addRoleIds = Array.from(bulkEdit_addRolesContainer.querySelectorAll('input[name="bulk_edit_add_role_ids"]:checked')) // Use renamed variable and name
                                    .map(cb => parseInt(cb.value, 10));
            const removeRoleIds = Array.from(bulkRemoveRolesContainer.querySelectorAll('input[name="bulk_edit_remove_role_ids"]:checked')) // Use changed name
                                     .map(cb => parseInt(cb.value, 10));

            // Client-side validation for overlapping roles
            const commonRoles = addRoleIds.filter(id => removeRoleIds.includes(id));
            if (commonRoles.length > 0) {
                const commonRoleNames = allAvailableRolesCache
                    .filter(role => commonRoles.includes(role.id))
                    .map(role => role.name)
                    .join(', ');
                showError(bulkEditUserModalStatusDiv, `Cannot add and remove the same roles in one operation. Conflicting roles: ${commonRoleNames}.`);
                return;
            }

            // Ensure at least one action is selected
            if (setAdmin === null && addRoleIds.length === 0 && removeRoleIds.length === 0) {
                showError(bulkEditUserModalStatusDiv, 'No changes specified. Please select an admin status or roles to add/remove.');
                return;
            }


            const actions = {
                set_admin: setAdmin,
                add_role_ids: addRoleIds.length > 0 ? addRoleIds : null,
                remove_role_ids: removeRoleIds.length > 0 ? removeRoleIds : null
            };

            try {
                const response = await apiCall('/api/admin/users/bulk', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids: selectedUserIds, actions: actions })
                }, bulkEditUserModalStatusDiv); // Pass status div to apiCall

                // Check if apiCall handled the message display based on its logic.
                // If not, or if we want a more specific message for 207:
                if (response) { // apiCall returns response on success
                    let message = response.message || `Bulk update processed. ${response.updated_count || 0} users affected.`;
                    if (response.errors && response.errors.length > 0) {
                        message += ` Some operations had issues: ${response.errors.map(e => `User ${e.id || 'N/A'}: ${e.error}`).join(', ')}`;
                        showError(userManagementStatusDiv, message); // Show detailed errors on main page status
                    } else {
                        showSuccess(userManagementStatusDiv, message);
                    }
                }
                // If apiCall showed a message in bulkEditUserModalStatusDiv and it was an error,
                // we might not want to immediately hide the modal. But for now, let's assume success leads to hiding.

                if (bulkEditUserModal && (!bulkEditUserModalStatusDiv.textContent || bulkEditUserModalStatusDiv.style.color === 'green' || bulkEditUserModalStatusDiv.style.color === 'var(--success-color)')) {
                    bulkEditUserModal.style.display = 'none';
                }
                fetchAndDisplayUsers(currentFilters); // Refresh user list
                if (selectAllUsersCheckbox) selectAllUsersCheckbox.checked = false; // Uncheck select all

            } catch (error) {
                // apiCall should have displayed the error in bulkEditUserModalStatusDiv.
                // If for some reason it didn't, or for additional logging:
                console.error("Bulk edit submission failed:", error);
                if (!bulkEditUserModalStatusDiv.textContent || bulkEditUserModalStatusDiv.style.display === 'none') {
                    showError(bulkEditUserModalStatusDiv, `Operation failed: ${error.message}`);
                }
            }
        });
    }

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
            const permissionsArray = getSelectedPermissions();

            if (!name) {
                showError(roleFormModalStatusDiv, 'Role Name is required.');
                return;
            }

            const roleData = { name, description, permissions: permissionsArray };
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
    if (bulkEditUserModal) bulkEditUserModal.style.display = 'none'; // Ensure bulk modal hidden initially
    if (bulkAddUserModal) bulkAddUserModal.style.display = 'none'; // Ensure bulk add modal hidden initially


    // --- Bulk Add Users (Pattern) Functionality ---

    // Helper to populate roles in a generic container (used by bulk add)
    async function populateRolesInContainer(containerElement, checkboxNamePrefix, selectedRoleIds = []) {
        if (!containerElement) return;
        showLoading(containerElement, 'Loading roles...');

        try {
            if (!allAvailableRolesCache) { // Ensure cache is populated
                allAvailableRolesCache = await apiCall('/api/admin/roles');
            }
            containerElement.innerHTML = ''; // Clear previous

            if (!allAvailableRolesCache || allAvailableRolesCache.length === 0) {
                containerElement.innerHTML = '<small>No roles available.</small>';
                return;
            }

            allAvailableRolesCache.forEach(role => {
                const checkboxDiv = document.createElement('div');
                checkboxDiv.classList.add('checkbox-item');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `${checkboxNamePrefix}-role-${role.id}`;
                checkbox.value = role.id;
                checkbox.name = `${checkboxNamePrefix}_role_ids`;
                if (selectedRoleIds.includes(role.id)) {
                    checkbox.checked = true;
                }

                const label = document.createElement('label');
                label.htmlFor = `${checkboxNamePrefix}-role-${role.id}`;
                label.textContent = role.name;

                checkboxDiv.appendChild(checkbox);
                checkboxDiv.appendChild(label);
                containerElement.appendChild(checkboxDiv);
            });
        } catch (error) {
            showError(containerElement, 'Failed to load roles.');
            console.error(`Error populating roles for ${checkboxNamePrefix}:`, error);
        }
    }


    if (bulkAddUsersBtn) {
        bulkAddUsersBtn.addEventListener('click', async () => {
            if (bulkAddUserForm) bulkAddUserForm.reset(); // Reset form fields to default/empty
            if (bulkAddUserModalStatusDiv) hideMessage(bulkAddUserModalStatusDiv);

            // Set default values for pattern fields if needed (or ensure they are in HTML)
            if(bulkAddUsernamePatternInput) bulkAddUsernamePatternInput.value = 'user###';
            if(bulkAddStartIndexInput) bulkAddStartIndexInput.value = '1';
            if(bulkAddCountInput) bulkAddCountInput.value = '10';


            // Ensure roles are loaded and populate checkboxes
            // This reuses the logic from populateRolesForUserForm or a new generic one
            try {
                // If roles aren't cached, populateRolesInContainer will fetch them.
                await populateRolesInContainer(bulkAddPattern_rolesContainer, 'bulk-add-pattern', []); // Use renamed variable
            } catch (error) {
                showError(bulkAddUserModalStatusDiv, `Failed to load roles for selection: ${error.message}`);
                // Optionally, don't open modal if roles fail to load, or open with error.
                // For now, it will open with the error message in the roles container.
            }

            if (bulkAddUserModal) bulkAddUserModal.style.display = 'block';
        });
    }

    if (closeBulkAddModalBtn) {
        closeBulkAddModalBtn.addEventListener('click', () => {
            if (bulkAddUserModal) bulkAddUserModal.style.display = 'none';
        });
    }

    if (bulkAddUserForm) {
        bulkAddUserForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showLoading(bulkAddUserModalStatusDiv, 'Processing bulk user creation...');

            const usernamePattern = bulkAddUsernamePatternInput.value.trim();
            const startIndex = parseInt(bulkAddStartIndexInput.value, 10);
            const count = parseInt(bulkAddCountInput.value, 10);
            const defaultPassword = bulkAddDefaultPasswordInput.value; // No trim for password
            const emailPattern = bulkAddEmailPatternInput.value.trim(); // Optional
            const isAdmin = bulkAddIsAdminCheckbox.checked;
            const selectedRoleIds = Array.from(bulkAddPattern_rolesContainer.querySelectorAll('input[name="bulk-add-pattern_role_ids"]:checked')) // Use renamed variable and name
                                       .map(cb => parseInt(cb.value, 10));

            // --- Client-side Validation ---
            if (!usernamePattern || !usernamePattern.includes('###')) {
                showError(bulkAddUserModalStatusDiv, 'Username pattern is required and must include "###".');
                return;
            }
            if (isNaN(startIndex) || startIndex < 0) {
                showError(bulkAddUserModalStatusDiv, 'Start index must be a non-negative number.');
                return;
            }
            if (isNaN(count) || count <= 0) {
                showError(bulkAddUserModalStatusDiv, 'Number of users must be a positive number.');
                return;
            }
            if (count > 200) { // Safety limit
                showError(bulkAddUserModalStatusDiv, 'Cannot create more than 200 users at once.');
                return;
            }
            if (!defaultPassword || defaultPassword.length < 6) {
                showError(bulkAddUserModalStatusDiv, 'Default password is required and must be at least 6 characters long.');
                return;
            }
            if (emailPattern && !emailPattern.includes('###') && !emailPattern.includes('@')) { // Basic check if pattern looks like an email pattern or just a fixed email
                 showError(bulkAddUserModalStatusDiv, 'Email pattern, if provided, should ideally include "###" or be a valid email structure.');
                 // This is a soft warning, backend will do stricter validation if needed or derive email.
            }


            const payload = {
                username_pattern: usernamePattern,
                start_index: startIndex,
                count: count,
                default_password: defaultPassword,
                is_admin: isAdmin,
                role_ids: selectedRoleIds
            };
            if (emailPattern) {
                payload.email_pattern = emailPattern;
            }

            try {
                const response = await apiCall('/api/admin/users/bulk_add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, bulkAddUserModalStatusDiv); // Pass status div

                if (response) {
                    let message = response.message || `Bulk add operation processed.`;
                    let isError = false;

                    if (response.created_count > 0) {
                        message += ` Successfully created: ${response.created_count}.`;
                    }
                    if (response.failed_count && response.failed_count > 0) {
                        message += ` Failed: ${response.failed_count}.`;
                        isError = true; // Consider partial success an error for message styling
                        if (response.errors && response.errors.length > 0) {
                            message += " Errors: " + response.errors.map(err => `${err.username_attempt || 'N/A'}: ${err.error}`).join("; ");
                        }
                    }

                    if (isError || (response.failed_count && response.failed_count > 0)) {
                        showError(userManagementStatusDiv, message); // Show detailed errors on main page status
                    } else {
                        showSuccess(userManagementStatusDiv, message);
                    }

                    // Close modal only on full success (HTTP 201 from backend, or if no failures reported in 207)
                    if (response.created_count > 0 && (!response.failed_count || response.failed_count === 0)) {
                         if (bulkAddUserModal) bulkAddUserModal.style.display = 'none';
                    }
                    fetchAndDisplayUsers(currentFilters); // Refresh user list
                }
                // If apiCall itself threw an error, it would be caught below
                // and displayed in bulkAddUserModalStatusDiv

            } catch (error) {
                // This catch block is primarily for network errors or if apiCall itself throws
                console.error("Bulk add submission failed:", error);
                // apiCall should have already displayed the error in bulkAddUserModalStatusDiv
                if (!bulkAddUserModalStatusDiv.textContent || bulkAddUserModalStatusDiv.style.display === 'none') {
                     showError(bulkAddUserModalStatusDiv, `Operation failed: ${error.message}`);
                }
            }
        });
    }

    fetchAndDisplayRoles(); // This also populates allAvailableRolesCache for user forms
});

[end of static/js/user_management.js]
