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

    const userIdInput = document.getElementById('user-id');
    const usernameInput = document.getElementById('username');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    const isAdminCheckbox = document.getElementById('is-admin');
    const userRolesCheckboxContainer = document.getElementById('user-roles-checkbox-container'); // For user edit modal

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

    async function fetchAndDisplayUsers() {
        if (!usersTableBody) return;
        showLoading(userManagementStatusDiv, 'Fetching users...');
        try {
            const users = await apiCall('/api/admin/users'); // Assumes apiCall is global
            localUsersCache = users; // Store for local use (e.g., populating edit form)
            
            usersTableBody.innerHTML = ''; // Clear existing rows
            if (users && users.length > 0) {
                users.forEach(user => {
                    const row = usersTableBody.insertRow();
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
                usersTableBody.innerHTML = '<tr><td colspan="6">No users found.</td></tr>';
                showSuccess(userManagementStatusDiv, 'No users to display.');
            }
        } catch (error) {
            showError(userManagementStatusDiv, `Error fetching users: ${error.message}`);
            localUsersCache = []; // Clear cache on error
        }
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
                            fetchAndDisplayUsers(); // Refresh the table
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
                        fetchAndDisplayUsers(); // Refresh table
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
                    fetchAndDisplayUsers(); // Refresh the table
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
    fetchAndDisplayUsers(); // Fetch and display users on page load

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
            const permissions = getSelectedPermissions().join(',');

            if (!name) {
                showError(roleFormModalStatusDiv, 'Role Name is required.');
                return;
            }

            const roleData = { name, description, permissions };
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
    fetchAndDisplayRoles();
});
