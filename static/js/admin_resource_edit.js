document.addEventListener('DOMContentLoaded', function() {
    // Ensure this runs after the main script.js has initialized elements if needed
    // However, for self-contained modal logic, direct element access should be fine.

    const openEditModalBtn = document.getElementById('open-edit-resource-modal-btn');
    const deleteResourceBtn = document.getElementById('delete-resource-btn'); // New button
    const editResourceModal = document.getElementById('edit-resource-modal');
    const editResourceForm = document.getElementById('edit-resource-form');
    const editResourceImageInput = document.getElementById('edit-resource-image-file');
    const editResourceImagePreview = document.getElementById('edit-resource-image-preview');
    const closeEditModalBtn = editResourceModal ? editResourceModal.querySelector('.close-modal-btn') : null;
    const editResourceStatusMessage = document.getElementById('edit-resource-status-message');
    const resourceToMapSelect = document.getElementById('resource-to-map'); // From main script
    // const authorizedUsersCheckboxContainer = document.getElementById('authorized-users-checkbox-container'); // Main form - Not directly used by this script for population
    const editAuthorizedUsersCheckboxContainer = document.getElementById('edit-authorized-users-checkbox-container'); // Modal form
    const editResourceMaintenanceCheckbox = document.getElementById('edit-resource-maintenance');
    const editResourceMaintenanceUntil = document.getElementById('edit-resource-maintenance-until');
    const editResourceRecurrenceLimit = document.getElementById('edit-resource-recurrence-limit');
    
    let allUsersCache = null; // Cache for user list

    // Helper function to ensure global functions from script.js are available
    // This is a placeholder; actual availability depends on how script.js exposes them.
    function getGlobalHelper(functionName) {
        if (typeof window[functionName] === 'function') {
            return window[functionName];
        }
        console.warn(`${functionName} is not available globally. Ensure it's exposed from script.js.`);
        // Return a dummy function to prevent immediate crashes, though functionality will be impaired.
        return (...args) => { 
            console.error(`Dummy ${functionName} called with:`, args);
            if (functionName.startsWith("show") && args.length > 0 && args[0] instanceof HTMLElement) {
                 args[0].textContent = `${functionName} not loaded. ${args[1] || ''}`;
            }
        };
    }

    const apiCall = getGlobalHelper('apiCall');
    const showLoading = getGlobalHelper('showLoading');
    const showSuccess = getGlobalHelper('showSuccess');
    const showError = getGlobalHelper('showError');
    const hideMessage = getGlobalHelper('hideMessage');


    async function fetchAllUsers() {
        if (allUsersCache) {
            return allUsersCache;
        }
        try {
            const users = await apiCall('/api/admin/users', {}, editResourceStatusMessage);
            allUsersCache = users;
            return users;
        } catch (error) {
            showError(editResourceStatusMessage, 'Failed to load users for permissions.');
            allUsersCache = []; 
            return [];
        }
    }

    async function populateUsersCheckboxes(containerElement, selectedUserIdsStr = "") {
        if (!containerElement) return;
        showLoading(containerElement, 'Loading users...');
        
        const users = await fetchAllUsers();
        containerElement.innerHTML = ''; 

        if (!users || users.length === 0) {
            containerElement.innerHTML = '<small>No users found.</small>';
            return;
        }

        const selectedUserIds = selectedUserIdsStr ? selectedUserIdsStr.split(',').map(id => parseInt(id.trim(), 10)) : [];

        users.forEach(user => {
            const checkboxDiv = document.createElement('div');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `edit-modal-user-${user.id}`; 
            checkbox.value = user.id;
            checkbox.checked = selectedUserIds.includes(user.id);
            
            const label = document.createElement('label');
            label.htmlFor = `edit-modal-user-${user.id}`;
            label.textContent = `${user.username} (ID: ${user.id})${user.is_admin ? ' - Admin' : ''}`;
            
            checkboxDiv.appendChild(checkbox);
            checkboxDiv.appendChild(label);
            containerElement.appendChild(checkboxDiv);
        });
    }
    
    if (openEditModalBtn && editResourceModal && resourceToMapSelect) {
        openEditModalBtn.addEventListener('click', async function() {
            const selectedOption = resourceToMapSelect.options[resourceToMapSelect.selectedIndex];
            if (!selectedOption || !selectedOption.value) {
                alert('Please select a resource first.');
                return;
            }

            const resourceId = selectedOption.value;
            
            try {
                showLoading(editResourceStatusMessage);
                // Assuming the main /api/resources endpoint can fetch a single resource by ID for admins
                // Or a more specific admin endpoint like /api/admin/resources/${resourceId} (GET) might be needed.
                // For now, using the dataset from the option as a primary source, then falling back or requiring full fetch.
                // The task implies fetching `/api/resources/${resourceId}`. Let's assume it returns full details.
                const resourceData = await apiCall(`/api/resources/${resourceId}`); 
                hideMessage(editResourceStatusMessage);

                if (!resourceData) {
                    showError(editResourceStatusMessage, 'Could not load resource details.');
                    return;
                }

                document.getElementById('edit-resource-id').value = resourceId;
                document.getElementById('edit-resource-name').value = resourceData.name || selectedOption.dataset.resourceName || '';
                document.getElementById('edit-resource-capacity').value = resourceData.capacity || selectedOption.dataset.capacity || '';
                document.getElementById('edit-resource-equipment').value = resourceData.equipment || selectedOption.dataset.equipment || '';
                document.getElementById('edit-resource-status').value = resourceData.status || selectedOption.dataset.resourceStatus || 'draft';
                document.getElementById('edit-resource-booking-permission').value = resourceData.booking_restriction || selectedOption.dataset.bookingRestriction || "";
                if (editResourceMaintenanceCheckbox) {
                    editResourceMaintenanceCheckbox.checked = resourceData.is_under_maintenance || selectedOption.dataset.isUnderMaintenance === "true";
                }
                if (editResourceMaintenanceUntil) {
                    const maintUntil = resourceData.maintenance_until || selectedOption.dataset.maintenanceUntil || "";
                    editResourceMaintenanceUntil.value = maintUntil ? maintUntil.slice(0,16) : "";
                }
                if (editResourceRecurrenceLimit) {
                    const recLim = resourceData.max_recurrence_count || selectedOption.dataset.maxRecurrenceCount || "";
                    editResourceRecurrenceLimit.value = recLim;
                }

                // Populate scheduled status fields
                document.getElementById('edit-resource-scheduled-status').value = resourceData.scheduled_status || "";
                const scheduledAtInput = document.getElementById('edit-resource-scheduled-at');
                if (resourceData.scheduled_status_at) {
                    // Format to YYYY-MM-DDTHH:MM, assuming resourceData.scheduled_status_at is a full ISO string
                    scheduledAtInput.value = resourceData.scheduled_status_at.slice(0, 16);
                } else {
                    scheduledAtInput.value = "";
                }

                // document.getElementById('edit-authorized-roles').value = resourceData.allowed_roles || selectedOption.dataset.allowedRoles || ""; // Old text field

                await populateUsersCheckboxes(editAuthorizedUsersCheckboxContainer, resourceData.allowed_user_ids || selectedOption.dataset.allowedUserIds);

                if (editResourceImagePreview) {
                    if (resourceData.image_url) {
                        editResourceImagePreview.src = resourceData.image_url;
                        editResourceImagePreview.style.display = 'block';
                    } else {
                        editResourceImagePreview.style.display = 'none';
                    }
                }

                // Populate roles checkboxes
                const assignedRoleIds = resourceData.roles && Array.isArray(resourceData.roles) ? resourceData.roles.map(r => r.id) : [];
                if (typeof window.populateRolesCheckboxesForResource === 'function') {
                    await window.populateRolesCheckboxesForResource('edit-resource-authorized-roles-checkbox-container', assignedRoleIds, editResourceStatusMessage);
                } else {
                    console.error("populateRolesCheckboxesForResource is not defined globally for edit modal.");
                    if(editResourceStatusMessage) showError(editResourceStatusMessage, "Role loading function not found.");
                }
                
                // Ensure modal title and button text are set for "Edit" mode
                const modalTitle = editResourceModal.querySelector('h3');
                const submitButton = editResourceForm.querySelector('button[type="submit"]');
                if (modalTitle) modalTitle.textContent = 'Edit Resource Details';
                if (submitButton) submitButton.textContent = 'Save Changes';

                editResourceModal.style.display = 'block';

            } catch (error) {
                 showError(editResourceStatusMessage, `Error loading resource details: ${error.message}`);
            }
        });
    }

    if (closeEditModalBtn) {
        closeEditModalBtn.addEventListener('click', function() {
            if (editResourceModal) editResourceModal.style.display = 'none';
        });
    }

    window.addEventListener('click', function(event) {
        if (event.target === editResourceModal) {
            if (editResourceModal) editResourceModal.style.display = 'none';
        }
    });

    if (editResourceForm) {
        editResourceForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            
            const resourceId = document.getElementById('edit-resource-id').value;
            const isCreatingNew = !resourceId; // If resourceId is empty, we are creating
            
            const actionVerb = isCreatingNew ? 'Creating' : 'Saving';
            showLoading(editResourceStatusMessage, `${actionVerb} resource details...`);

            const name = document.getElementById('edit-resource-name').value;
            const capacityStr = document.getElementById('edit-resource-capacity').value;
            const equipment = document.getElementById('edit-resource-equipment').value;
            const status = document.getElementById('edit-resource-status').value;
            const booking_restriction = document.getElementById('edit-resource-booking-permission').value;
            // const allowed_roles = document.getElementById('edit-authorized-roles').value; // Old text field

            let capacity = null;
            if (capacityStr.trim() !== '') {
                capacity = parseInt(capacityStr, 10);
                if (isNaN(capacity)) {
                    showError(editResourceStatusMessage, 'Capacity must be a valid number.');
                    return;
                }
            }
            
            const selectedUserIds = [];
            if (editAuthorizedUsersCheckboxContainer) {
                editAuthorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                    selectedUserIds.push(cb.value);
                });
            }
            const allowed_user_ids = selectedUserIds.join(',');

            const selectedRoleIds = typeof window.getSelectedRoleIdsForResource === 'function'
                                    ? window.getSelectedRoleIdsForResource('edit-resource-authorized-roles-checkbox-container')
                                    : [];

            const payload = {
                name,
                capacity,
                equipment,
                status,
                booking_restriction: booking_restriction === "" ? null : booking_restriction,
                allowed_user_ids: allowed_user_ids === "" ? null : allowed_user_ids,
                // allowed_roles: allowed_roles.trim() === "" ? null : allowed_roles.trim(), // Ensure this line is removed or updated if roles are fully checkbox based
                role_ids: selectedRoleIds, // Use selectedRoleIds from checkbox logic
                is_under_maintenance: editResourceMaintenanceCheckbox ? editResourceMaintenanceCheckbox.checked : false,
                maintenance_until: editResourceMaintenanceUntil && editResourceMaintenanceUntil.value ? editResourceMaintenanceUntil.value : null,
                max_recurrence_count: editResourceRecurrenceLimit && editResourceRecurrenceLimit.value !== '' ? parseInt(editResourceRecurrenceLimit.value, 10) : null,
                scheduled_status: document.getElementById('edit-resource-scheduled-status').value,
                scheduled_status_at: document.getElementById('edit-resource-scheduled-at').value || null // Send null if empty
            };
            // Remove allowed_roles if it's definitely replaced by role_ids
            if (payload.hasOwnProperty('allowed_roles')) { // Check if the old field is still there and remove
                delete payload.allowed_roles;
            }


            try {
                const method = isCreatingNew ? 'POST' : 'PUT';
                const apiUrl = isCreatingNew ? '/api/admin/resources' : `/api/admin/resources/${resourceId}`;

                const responseData = await apiCall(apiUrl, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, editResourceStatusMessage);

                let imgResponse = null;
                const newResourceId = isCreatingNew ? responseData.id : resourceId; // Use new ID for image upload if creating

                if (editResourceImageInput && editResourceImageInput.files.length > 0) {
                    const formData = new FormData();
                    formData.append('resource_image', editResourceImageInput.files[0]);
                    // Use newResourceId for the image upload URL, important for creation case
                    imgResponse = await apiCall(`/api/admin/resources/${newResourceId}/image`, {
                        method: 'POST',
                        body: formData
                    }, editResourceStatusMessage);
                    if (editResourceImagePreview && imgResponse.image_url) {
                        editResourceImagePreview.src = imgResponse.image_url;
                        editResourceImagePreview.style.display = 'block';
                    }
                    editResourceImageInput.value = '';
                }
                
                const successMessage = isCreatingNew ? 
                    `Resource '${responseData.name}' created successfully!` : 
                    `Resource '${responseData.name}' updated successfully!`;
                showSuccess(editResourceStatusMessage, successMessage);
                
                // Update the resourceToMapSelect dropdown in the main document (admin_maps.html)
                const mainDocResourceToMapSelect = window.document.getElementById('resource-to-map');
                if (mainDocResourceToMapSelect) {
                    if (isCreatingNew) {
                        const newOption = new Option(
                            `${responseData.name} (ID: ${responseData.id}) - Status: ${responseData.status || 'N/A'}`,
                            responseData.id
                        );
                        // Populate dataset for the new option
                        newOption.dataset.resourceId = responseData.id;
                        newOption.dataset.resourceName = responseData.name;
                        newOption.dataset.resourceStatus = responseData.status || 'draft';
                        newOption.dataset.capacity = responseData.capacity === null || responseData.capacity === undefined ? '' : String(responseData.capacity);
                        newOption.dataset.equipment = responseData.equipment || '';
                        newOption.dataset.bookingRestriction = responseData.booking_restriction || "";
                        newOption.dataset.allowedUserIds = responseData.allowed_user_ids || "";
                        newOption.dataset.roleIds = (responseData.roles || []).map(role => role.id).join(',');
                        newOption.dataset.isUnderMaintenance = responseData.is_under_maintenance ? "true" : "false";
                        newOption.dataset.maintenanceUntil = responseData.maintenance_until || "";
                        newOption.dataset.maxRecurrenceCount = responseData.max_recurrence_count || "";
                        newOption.dataset.scheduledStatus = responseData.scheduled_status || "";
                        newOption.dataset.scheduledStatusAt = responseData.scheduled_status_at || "";
                        if (imgResponse && imgResponse.image_url) {
                            newOption.dataset.imageUrl = imgResponse.image_url;
                        }
                        // Add to dropdown and select it
                        mainDocResourceToMapSelect.add(newOption);
                        mainDocResourceToMapSelect.value = responseData.id;
                        // Trigger change to update define-area-form and other UI
                        mainDocResourceToMapSelect.dispatchEvent(new Event('change')); 

                    } else { // Existing logic for updating an option
                        const optionToUpdate = Array.from(mainDocResourceToMapSelect.options).find(opt => opt.value === resourceId);
                        if (optionToUpdate) {
                            optionToUpdate.textContent = `${responseData.name} (ID: ${resourceId}) - Status: ${responseData.status || 'N/A'}`;
                            // Update dataset attributes
                            optionToUpdate.dataset.resourceName = responseData.name;
                            optionToUpdate.dataset.resourceStatus = responseData.status;
                            optionToUpdate.dataset.capacity = responseData.capacity === null || responseData.capacity === undefined ? '' : String(responseData.capacity);
                            optionToUpdate.dataset.equipment = responseData.equipment || '';
                            optionToUpdate.dataset.bookingRestriction = responseData.booking_restriction || "";
                            optionToUpdate.dataset.allowedUserIds = responseData.allowed_user_ids || "";
                            // optionToUpdate.dataset.allowedRoles = responseData.allowed_roles || ""; // Keep if still used, or rely on role_ids
                            optionToUpdate.dataset.roleIds = (responseData.roles || []).map(role => role.id).join(',');
                            optionToUpdate.dataset.isUnderMaintenance = responseData.is_under_maintenance ? "true" : "false";
                            optionToUpdate.dataset.maintenanceUntil = responseData.maintenance_until || "";
                            optionToUpdate.dataset.maxRecurrenceCount = responseData.max_recurrence_count || "";
                            optionToUpdate.dataset.scheduledStatus = responseData.scheduled_status || "";
                            optionToUpdate.dataset.scheduledStatusAt = responseData.scheduled_status_at || "";
                            if (imgResponse && imgResponse.image_url) {
                                optionToUpdate.dataset.imageUrl = imgResponse.image_url;
                            }
                             // Preserve map-specific dataset attributes if they exist
                            if (optionToUpdate.dataset.isMappedToCurrent === "true") {
                               optionToUpdate.textContent += ` (On this map)`;
                            }
                             // Dispatch change event after updating existing option
                            mainDocResourceToMapSelect.dispatchEvent(new Event('change'));
                        }
                    }
                }
                
                // Refresh map areas on the main page, especially if a resource name changed
                if (typeof window.fetchAndDrawExistingMapAreas === 'function') {
                    const currentMapId = window.document.getElementById('selected-floor-map-id') ? window.document.getElementById('selected-floor-map-id').value : null;
                    if (currentMapId) {
                        await window.fetchAndDrawExistingMapAreas(currentMapId); 
                    }
                } else {
                    console.warn("Global map refresh functions not found. Canvas might not reflect all changes immediately.");
                }

                setTimeout(() => {
                    if (editResourceModal) editResourceModal.style.display = 'none';
                }, 1500);

            } catch (error) {
                console.error('Failed to update resource:', error.message);
            }
        });
    }
    
    if (resourceToMapSelect && openEditModalBtn && deleteResourceBtn) { // Added deleteResourceBtn
        resourceToMapSelect.addEventListener('change', function() {
            const selectedOption = this.options[this.selectedIndex];
            if (this.value && selectedOption && selectedOption.dataset.resourceId) { 
                openEditModalBtn.style.display = 'inline-block'; 
                deleteResourceBtn.style.display = 'inline-block';
            } else {
                openEditModalBtn.style.display = 'none';
                deleteResourceBtn.style.display = 'none';
            }
        });
        // Initial state
        const initialSelectedOption = resourceToMapSelect.options[resourceToMapSelect.selectedIndex];
        if (!resourceToMapSelect.value || !initialSelectedOption || !initialSelectedOption.dataset.resourceId) {
            openEditModalBtn.style.display = 'none';
            deleteResourceBtn.style.display = 'none';
        }
    }

    if (deleteResourceBtn && resourceToMapSelect) {
        deleteResourceBtn.addEventListener('click', async function() {
            const selectedOption = resourceToMapSelect.options[resourceToMapSelect.selectedIndex];
            if (!selectedOption || !selectedOption.value) {
                alert('Please select a resource to delete.');
                return;
            }

            const resourceId = selectedOption.value;
            const resourceName = selectedOption.dataset.resourceName || selectedOption.text.split(' (ID:')[0];
            const statusMessageDiv = document.getElementById('area-definition-status'); // Use a general status div for this action

            if (!confirm(`Are you sure you want to permanently delete the resource '${resourceName}' (ID: ${resourceId})? This action cannot be undone and will also delete all its bookings.`)) {
                return;
            }

            showLoading(statusMessageDiv, `Deleting resource '${resourceName}'...`);

            try {
                await apiCall(`/api/admin/resources/${resourceId}`, {
                    method: 'DELETE'
                }, statusMessageDiv);

                showSuccess(statusMessageDiv, `Resource '${resourceName}' and its bookings were successfully deleted.`);
                
                // Remove from dropdown
                selectedOption.remove();
                resourceToMapSelect.value = ''; // Reset selection

                // Clear selectedAreaForEditing if it was the deleted resource
                // This relies on selectedAreaForEditing being accessible, assuming it's in the global scope or accessible via a getter from script.js
                if (window.selectedAreaForEditing && String(window.selectedAreaForEditing.id) === String(resourceId)) {
                    window.selectedAreaForEditing = null;
                }

                // Reset forms (optional, but good practice)
                if (document.getElementById('define-area-form')) {
                    document.getElementById('define-area-form').reset();
                }
                if (editResourceForm) { // editResourceForm is already defined in this script
                    editResourceForm.reset();
                }
                if (editAuthorizedUsersCheckboxContainer) editAuthorizedUsersCheckboxContainer.innerHTML = '';


                // Refresh map and resource lists
                const currentMapId = document.getElementById('selected-floor-map-id') ? document.getElementById('selected-floor-map-id').value : null;
                if (currentMapId) {
                    if (typeof window.populateResourcesForMapping === 'function') {
                        await window.populateResourcesForMapping(currentMapId);
                    }
                    if (typeof window.fetchAndDrawExistingMapAreas === 'function') {
                        await window.fetchAndDrawExistingMapAreas(currentMapId); // This calls redrawCanvas
                    } else if (typeof window.redrawCanvas === 'function') {
                        window.redrawCanvas(); // Fallback if fetchAndDraw is not global
                    }
                } else if (typeof window.redrawCanvas === 'function') {
                     window.redrawCanvas(); // Fallback if no currentMapId
                }
                
                // Hide action buttons as no resource is selected
                if (openEditModalBtn) openEditModalBtn.style.display = 'none';
                deleteResourceBtn.style.display = 'none';
                const publishBtn = document.getElementById('publish-resource-btn'); // From main script
                if (publishBtn) publishBtn.style.display = 'none';
                const resourceActionsContainer = document.getElementById('resource-actions-container');
                if (resourceActionsContainer) { // Clear any specific action buttons and show default message
                    resourceActionsContainer.innerHTML = '<p><em>Select a resource from the dropdown above to see its status or publish actions.</em></p>';
                    // Re-append the general action buttons (Edit/Delete) but keep them hidden initially
                    if (openEditModalBtn) resourceActionsContainer.appendChild(openEditModalBtn);
                    if (deleteResourceBtn) resourceActionsContainer.appendChild(deleteResourceBtn);
                    openEditModalBtn.style.display = 'none';
                    deleteResourceBtn.style.display = 'none';
                }


                setTimeout(() => {
                    hideMessage(statusMessageDiv);
                }, 3000);

            } catch (error) {
                // apiCall should have already shown the error in statusMessageDiv
                console.error(`Failed to delete resource '${resourceName}':`, error);
            }
        });
    }

    const exportMapConfigBtn = document.getElementById('export-map-config-btn');
    if (exportMapConfigBtn) {
        exportMapConfigBtn.addEventListener('click', async () => {
            const statusDiv = document.getElementById('admin-maps-list-status'); // Or any other relevant status div on admin_maps.html
            if (statusDiv) showLoading(statusDiv, 'Exporting map configuration...');
            try {
                // Assuming apiCall is globally available and handles CSRF
                const response = await fetch('/api/admin/maps/export_configuration');

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;

                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'map_configuration_export.json'; // Default filename
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
                    if (filenameMatch && filenameMatch.length > 1) {
                        filename = filenameMatch[1];
                    }
                }
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                if (statusDiv) showSuccess(statusDiv, 'Map configuration exported successfully.');

            } catch (error) {
                if (statusDiv) showError(statusDiv, `Error exporting map configuration: ${error.message}`);
                console.error('Error exporting map configuration:', error);
            }
        });
    }

    const exportMapConfigBtn = document.getElementById('export-map-config-btn');
    if (exportMapConfigBtn) {
        exportMapConfigBtn.addEventListener('click', async () => {
            const statusDiv = document.getElementById('admin-maps-list-status'); // Use a relevant status div
            if (statusDiv) showLoading(statusDiv, 'Exporting map configuration...');
            try {
                const response = await fetch('/api/admin/maps/export_configuration');
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;

                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'map_configuration_export.json'; // Default filename
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
                    if (filenameMatch && filenameMatch.length > 1) {
                        filename = filenameMatch[1];
                    }
                }
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                if (statusDiv) showSuccess(statusDiv, 'Map configuration exported successfully.');
            } catch (error) {
                if (statusDiv) showError(statusDiv, `Error exporting map configuration: ${error.message}`);
                console.error('Error exporting map configuration:', error);
            }
        });
    }

    const importMapConfigFile = document.getElementById('import-map-config-file');
    const importMapConfigBtn = document.getElementById('import-map-config-btn');

    if (importMapConfigBtn && importMapConfigFile) {
        importMapConfigBtn.addEventListener('click', () => {
            importMapConfigFile.click(); // Trigger file input
        });

        importMapConfigFile.addEventListener('change', async (event) => {
            const file = event.target.files[0];
            if (!file) {
                showError(document.getElementById('admin-maps-list-status'), 'No file selected for map configuration import.');
                return;
            }
            if (file.type !== 'application/json') {
                showError(document.getElementById('admin-maps-list-status'), 'Please select a valid JSON file for map configuration.');
                return;
            }

            const statusDiv = document.getElementById('admin-maps-list-status');
            showLoading(statusDiv, 'Importing map configuration...');
            const formData = new FormData();
            formData.append('file', file);

            try {
                // apiCall should handle CSRF if set up globally (e.g., in script.js)
                const result = await apiCall('/api/admin/maps/import_configuration', {
                    method: 'POST',
                    body: formData,
                    // 'Content-Type': 'multipart/form-data' is automatically set by browser with FormData
                }, statusDiv); // Pass statusDiv for messages

                // The apiCall function itself should handle showing success/error from result.message
                // But we might want to format a more detailed summary here.
                let summaryMessage = result.message || "Import process completed.";
                if (result.maps_created) summaryMessage += ` Maps Created: ${result.maps_created}.`;
                if (result.maps_updated) summaryMessage += ` Maps Updated: ${result.maps_updated}.`;
                if (result.resource_mappings_updated) summaryMessage += ` Resource Mappings Updated: ${result.resource_mappings_updated}.`;

                if (result.image_reminders && result.image_reminders.length > 0) {
                    summaryMessage += "<br><strong>Important Reminders:</strong><ul>";
                    result.image_reminders.forEach(reminder => {
                        summaryMessage += `<li>${reminder}</li>`;
                    });
                    summaryMessage += "</ul>";
                }

                if ((result.maps_errors && result.maps_errors.length > 0) || (result.resource_mapping_errors && result.resource_mapping_errors.length > 0)) {
                    summaryMessage += "<br><strong>Errors Encountered:</strong><ul>";
                    if (result.maps_errors) {
                        result.maps_errors.forEach(err => {
                            summaryMessage += `<li>Map Error: ${err.error} (Data: ${JSON.stringify(err.data)})</li>`;
                        });
                    }
                    if (result.resource_mapping_errors) {
                        result.resource_mapping_errors.forEach(err => {
                            summaryMessage += `<li>Resource Mapping Error: ${err.error} (Data: ${JSON.stringify(err.data)})</li>`;
                        });
                    }
                    summaryMessage += "</ul>";
                    showError(statusDiv, summaryMessage); // Use showError for multi-status like display with errors
                } else {
                    showSuccess(statusDiv, summaryMessage);
                }

                // Refresh map list and potentially resource mapping UI if it's visible
                if (typeof window.fetchAndDisplayMaps === 'function') { // Assuming fetchAndDisplayMaps is global from admin_maps.html's own script part
                    window.fetchAndDisplayMaps();
                }
                // If the "Define Areas" section is visible and a map is selected, refresh its data too
                const defineAreasSection = document.getElementById('define-areas-section');
                if (defineAreasSection && defineAreasSection.style.display !== 'none') {
                    const currentMapId = document.getElementById('selected-floor-map-id') ? document.getElementById('selected-floor-map-id').value : null;
                    if (currentMapId && typeof window.populateResourcesForMapping === 'function' && typeof window.fetchAndDrawExistingMapAreas === 'function') {
                        await window.populateResourcesForMapping(currentMapId);
                        await window.fetchAndDrawExistingMapAreas(currentMapId);
                    }
                }

            } catch (error) {
                // apiCall should have shown the error in statusDiv, but catch any other JS errors
                showError(statusDiv, `Error during map configuration import: ${error.message}`);
                console.error('Map configuration import error:', error);
            } finally {
                importMapConfigFile.value = ''; // Reset file input
            }
        });
    }

    const importMapConfigFile = document.getElementById('import-map-config-file');
    const importMapConfigBtn = document.getElementById('import-map-config-btn');

    if (importMapConfigBtn && importMapConfigFile) {
        importMapConfigBtn.addEventListener('click', () => {
            importMapConfigFile.click(); // Trigger file input
        });

        importMapConfigFile.addEventListener('change', async (event) => {
            const file = event.target.files[0];
            const statusDiv = document.getElementById('admin-maps-list-status'); // Status div for this section

            if (!file) {
                if (statusDiv) showError(statusDiv, 'No file selected for map configuration import.');
                return;
            }
            if (file.type !== 'application/json') {
                if (statusDiv) showError(statusDiv, 'Please select a valid JSON file for map configuration.');
                return;
            }

            if (statusDiv) showLoading(statusDiv, 'Importing map configuration...');
            const formData = new FormData();
            formData.append('file', file);

            try {
                // apiCall is assumed to be globally available from script.js and handles CSRF
                const result = await apiCall('/api/admin/maps/import_configuration', {
                    method: 'POST',
                    body: formData,
                }, statusDiv); // Pass statusDiv for unified messaging by apiCall

                // Construct a more detailed summary message based on the response
                let summaryHtml = result.message || "Map configuration import processed.";
                summaryHtml += `<br>Maps Created: ${result.maps_created || 0}, Maps Updated: ${result.maps_updated || 0}.`;
                summaryHtml += `<br>Resource Mappings Updated: ${result.resource_mappings_updated || 0}.`;

                if (result.image_reminders && result.image_reminders.length > 0) {
                    summaryHtml += "<br><strong>Important Reminders:</strong><ul>";
                    result.image_reminders.forEach(reminder => {
                        summaryHtml += `<li>${reminder}</li>`;
                    });
                    summaryHtml += "</ul>";
                }

                let hasErrors = false;
                if (result.maps_errors && result.maps_errors.length > 0) {
                    hasErrors = true;
                    summaryHtml += "<br><strong>Map Errors:</strong><ul>";
                    result.maps_errors.forEach(err => {
                        summaryHtml += `<li>${err.error} (Data: ${JSON.stringify(err.data)})</li>`;
                    });
                    summaryHtml += "</ul>";
                }
                if (result.resource_mapping_errors && result.resource_mapping_errors.length > 0) {
                    hasErrors = true;
                    summaryHtml += "<br><strong>Resource Mapping Errors:</strong><ul>";
                    result.resource_mapping_errors.forEach(err => {
                        summaryHtml += `<li>${err.error} (Data: ${JSON.stringify(err.data)})</li>`;
                    });
                    summaryHtml += "</ul>";
                }

                if (hasErrors) {
                    if (statusDiv) showError(statusDiv, summaryHtml); // Show detailed summary with errors
                } else {
                    if (statusDiv) showSuccess(statusDiv, summaryHtml); // Show detailed success summary
                }

                // Refresh map list and potentially resource mapping UI if it's visible
                // These functions are expected to be defined in the global scope or within admin_maps.html script tag
                if (typeof fetchAndDisplayMaps === 'function') {
                    fetchAndDisplayMaps();
                }
                const defineAreasSection = document.getElementById('define-areas-section');
                if (defineAreasSection && defineAreasSection.style.display !== 'none') {
                    const currentMapId = document.getElementById('selected-floor-map-id') ? document.getElementById('selected-floor-map-id').value : null;
                    if (currentMapId) {
                        if (typeof populateResourcesForMapping === 'function') await populateResourcesForMapping(currentMapId);
                        if (typeof fetchAndDrawExistingMapAreas === 'function') await fetchAndDrawExistingMapAreas(currentMapId);
                    }
                }

            } catch (error) {
                // If apiCall itself throws an error not caught by its internal messaging (e.g. network error)
                if (statusDiv && !statusDiv.classList.contains('error')) { // Check if apiCall already set an error
                    showError(statusDiv, `Error during map configuration import: ${error.message}`);
                }
                console.error('Map configuration import error:', error);
            } finally {
                importMapConfigFile.value = ''; // Reset file input
            }
        });
    }
});
