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
            showLoading(editResourceStatusMessage, 'Saving resource details...');

            const resourceId = document.getElementById('edit-resource-id').value;
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
                allowed_roles: allowed_roles.trim() === "" ? null : allowed_roles.trim(),
                is_under_maintenance: editResourceMaintenanceCheckbox ? editResourceMaintenanceCheckbox.checked : false,
                maintenance_until: editResourceMaintenanceUntil ? editResourceMaintenanceUntil.value : null
            };

            try {
                const responseData = await apiCall(`/api/admin/resources/${resourceId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, editResourceStatusMessage);

                let imgResponse = null;
                if (editResourceImageInput && editResourceImageInput.files.length > 0) {
                    const formData = new FormData();
                    formData.append('resource_image', editResourceImageInput.files[0]);
                    imgResponse = await apiCall(`/api/admin/resources/${resourceId}/image`, {
                        method: 'POST',
                        body: formData
                    }, editResourceStatusMessage);
                    if (editResourceImagePreview && imgResponse.image_url) {
                        editResourceImagePreview.src = imgResponse.image_url;
                        editResourceImagePreview.style.display = 'block';
                    }
                    editResourceImageInput.value = '';
                }

                showSuccess(editResourceStatusMessage, `Resource '${responseData.name}' updated successfully!`);
                
                if (resourceToMapSelect) {
                    const optionToUpdate = Array.from(resourceToMapSelect.options).find(opt => opt.value === resourceId);
                    if (optionToUpdate) {
                        optionToUpdate.textContent = `${responseData.name} (ID: ${resourceId}) - Status: ${responseData.status || 'N/A'}`;
                        // Update dataset attributes
                        optionToUpdate.dataset.resourceName = responseData.name;
                        optionToUpdate.dataset.resourceStatus = responseData.status;
                        optionToUpdate.dataset.capacity = responseData.capacity === null || responseData.capacity === undefined ? '' : String(responseData.capacity);
                        optionToUpdate.dataset.equipment = responseData.equipment || '';
                        optionToUpdate.dataset.bookingRestriction = responseData.booking_restriction || "";
                        optionToUpdate.dataset.allowedUserIds = responseData.allowed_user_ids || "";
                        optionToUpdate.dataset.allowedRoles = responseData.allowed_roles || "";
                        optionToUpdate.dataset.isUnderMaintenance = responseData.is_under_maintenance ? "true" : "false";
                        optionToUpdate.dataset.maintenanceUntil = responseData.maintenance_until || "";
                        if (imgResponse && imgResponse.image_url) {
                            optionToUpdate.dataset.imageUrl = imgResponse.image_url;
                        }
                         // Preserve map-specific dataset attributes if they exist
                        if (optionToUpdate.dataset.isMappedToCurrent === "true") {
                           optionToUpdate.textContent += ` (On this map)`;
                        }
                    }
                }
                
                if (typeof window.populateResourcesForMapping === 'function' && 
                    typeof window.fetchAndDrawExistingMapAreas === 'function') {
                    const currentMapId = document.getElementById('selected-floor-map-id') ? document.getElementById('selected-floor-map-id').value : null;
                    if (currentMapId) {
                        // await window.populateResourcesForMapping(currentMapId); // Might reset selection
                        await window.fetchAndDrawExistingMapAreas(currentMapId); 
                    }
                } else {
                    console.warn("Global map refresh functions not found. Canvas might not reflect all changes immediately.");
                }
                 // Dispatch change event to trigger UI updates in main script (e.g., resource actions container)
                if (resourceToMapSelect) {
                    resourceToMapSelect.dispatchEvent(new Event('change'));
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
});
