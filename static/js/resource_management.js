document.addEventListener('DOMContentLoaded', function() {
    const statusDiv = document.getElementById('resource-management-status');
    const tableBody = document.querySelector('#resources-table tbody');
    const addBtn = document.getElementById('add-new-resource-btn');
    const addBulkBtn = document.getElementById('add-bulk-resource-btn');
    const bulkEditBtn = document.getElementById('bulk-edit-btn');
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    const selectAllCheckbox = document.getElementById('select-all-resources');
    const resourceFormModal = document.getElementById('resource-form-modal');
    const resourceForm = document.getElementById('resource-form');
    const resourceFormModalTitle = document.getElementById('resource-form-modal-title');
    const resourceFormStatus = document.getElementById('resource-form-modal-status');
    const resourceIdInput = document.getElementById('resource-id');
    const resourceNameInput = document.getElementById('resource-name');
    const resourceCapacityInput = document.getElementById('resource-capacity');
    const resourceEquipmentInput = document.getElementById('resource-equipment');
    const resourceStatusModalInput = document.getElementById('resource-status-modal'); // Added
    const resourceTagsInput = document.getElementById('resource-tags');

    const filterNameInput = document.getElementById('resource-filter-name');
    const filterStatusSelect = document.getElementById('resource-filter-status');
    const filterMapSelect = document.getElementById('resource-filter-map');
    const filterTagsInput = document.getElementById('resource-filter-tags');
    const applyFiltersBtn = document.getElementById('resource-apply-filters-btn');
    const clearFiltersBtn = document.getElementById('resource-clear-filters-btn');
    let currentFilters = {};

    let currentResourceIdForPins = null; // For PIN Management

    const bulkModal = document.getElementById('bulk-resource-modal');
    const bulkForm = document.getElementById('bulk-resource-form');
    const bulkFormStatus = document.getElementById('bulk-resource-form-status');
    const bulkPrefixInput = document.getElementById('bulk-prefix');
    const bulkSuffixInput = document.getElementById('bulk-suffix');
    const bulkStartInput = document.getElementById('bulk-start');
    const bulkCountInput = document.getElementById('bulk-count');
    const bulkPaddingInput = document.getElementById('bulk-padding');
    const bulkCapacityInput = document.getElementById('bulk-capacity');
    const bulkEquipmentInput = document.getElementById('bulk-equipment');
    const bulkTagsInput = document.getElementById('bulk-tags');
    const bulkStatusInput = document.getElementById('bulk-status');
    const bulkEditModal = document.getElementById('bulk-edit-modal');
    const bulkEditForm = document.getElementById('bulk-edit-form');
    const bulkEditFormStatus = document.getElementById('bulk-edit-form-status');
    const bulkEditStatusInput = document.getElementById('bulk-edit-status');
    const bulkEditCapacityInput = document.getElementById('bulk-edit-capacity');
    const bulkEditEquipmentInput = document.getElementById('bulk-edit-equipment');
    const bulkEditTagsInput = document.getElementById('bulk-edit-tags');
    const exportAllResourcesBtn = document.getElementById('export-all-resources-btn');
    const importResourcesFile = document.getElementById('import-resources-file');
    const importResourcesBtn = document.getElementById('import-resources-btn');

    async function fetchAndDisplayResources(filters = {}) {
        showLoading(statusDiv, 'Fetching resources...');
        try {
            const [resources, maps] = await Promise.all([
                apiCall('/api/admin/resources'),
                apiCall('/api/admin/maps')
            ]);
            tableBody.innerHTML = '';
            const mapsById = {};
            if (maps) maps.forEach(m => { mapsById[m.id] = m; });

            if (filterMapSelect && filterMapSelect.options.length === 1 && maps) {
                maps.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.id;
                    opt.textContent = m.name;
                    filterMapSelect.appendChild(opt);
                });
            }

            let filtered = resources || [];
            if (filters.name) {
                filtered = filtered.filter(r => r.name.toLowerCase().includes(filters.name.toLowerCase()));
            }
            if (filters.status) {
                filtered = filtered.filter(r => r.status === filters.status);
            }
            if (filters.mapId) {
                filtered = filtered.filter(r => String(r.floor_map_id || '') === String(filters.mapId));
            }
            if (filters.tags) {
                filtered = filtered.filter(r => r.tags && r.tags.toLowerCase().includes(filters.tags.toLowerCase()));
            }

            const grouped = {};
            filtered.forEach(r => {
                const key = r.floor_map_id ? String(r.floor_map_id) : 'none';
                if (!grouped[key]) grouped[key] = [];
                grouped[key].push(r);
            });

            const mapIdsInOrder = Object.keys(grouped);
            if (mapIdsInOrder.length > 0) {
                mapIdsInOrder.forEach(mid => {
                    const headingRow = tableBody.insertRow();
                    const headingCell = headingRow.insertCell();
                    headingCell.colSpan = 7;
                    const mapName = mid === 'none' ? 'Unassigned' : (mapsById[mid] ? mapsById[mid].name : 'Map ' + mid);
                    headingCell.textContent = `Map: ${mapName}`;

                    grouped[mid].forEach(r => {
                        const row = tableBody.insertRow();
                        const selectCell = row.insertCell();
                        selectCell.innerHTML = `<input type="checkbox" class="select-resource-checkbox" data-id="${r.id}">`;
                        row.insertCell().textContent = r.id;
                        row.insertCell().textContent = r.name;
                        row.insertCell().textContent = r.status || 'draft';
                        row.insertCell().textContent = r.capacity !== null && r.capacity !== undefined ? r.capacity : '';
                        row.insertCell().textContent = r.tags || '';
                        const actionsCell = row.insertCell();
                        actionsCell.innerHTML = `
                            <button class="button edit-resource-btn" data-id="${r.id}">Edit</button>
                            <button class="button danger delete-resource-btn" data-id="${r.id}" data-name="${r.name}">Delete</button>
                        `;
                    });
                });
                hideMessage(statusDiv);
            } else {
                tableBody.innerHTML = '<tr><td colspan="6">No resources found.</td></tr>';
                showSuccess(statusDiv, 'No resources to display.');
            }
            if (selectAllCheckbox) selectAllCheckbox.checked = false;
        } catch (error) {
            showError(statusDiv, `Error fetching resources: ${error.message}`);
        }
    }

    addBtn.addEventListener('click', function() {
        resourceForm.reset();
        resourceIdInput.value = '';
        resourceStatusModalInput.value = 'draft'; // Default for new resource
        resourceFormModalTitle.textContent = 'Add New Resource';
        hideMessage(resourceFormStatus);
        resourceFormModal.style.display = 'block';
    });

    if (addBulkBtn) {
        addBulkBtn.addEventListener('click', () => {
            if (bulkForm) bulkForm.reset();
            if (bulkStartInput) bulkStartInput.value = 1;
            if (bulkCountInput) bulkCountInput.value = 1;
            if (bulkPaddingInput) bulkPaddingInput.value = 0;
            if (bulkStatusInput) bulkStatusInput.value = 'draft';
            hideMessage(bulkFormStatus);
            if (bulkModal) bulkModal.style.display = 'block';
        });
    }

    if (importResourcesBtn && importResourcesFile) {
        importResourcesBtn.addEventListener('click', () => {
            importResourcesFile.click(); // Trigger file input when button is clicked
        });

        importResourcesFile.addEventListener('change', async (event) => {
            const file = event.target.files[0];
            if (!file) {
                showError(statusDiv, 'No file selected.');
                return;
            }
            if (file.type !== 'application/json') {
                showError(statusDiv, 'Please select a valid JSON file.');
                return;
            }

            showLoading(statusDiv, 'Importing resources...');
            const formData = new FormData();
            formData.append('file', file);

            try {
                const csrfTokenTag = document.querySelector('meta[name="csrf-token"]');
                const headers = {};
                if (csrfTokenTag) {
                    headers['X-CSRFToken'] = csrfTokenTag.content;
                }

                const response = await fetch('/api/admin/resources/import', {
                    method: 'POST',
                    body: formData,
                    headers: headers // Use the constructed headers object
                });
                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || `HTTP error! status: ${response.status}`);
                }

                let message = result.message || 'Import process completed.';
                if (result.created) message += ` Created: ${result.created}.`;
                if (result.updated) message += ` Updated: ${result.updated}.`;

                if (result.errors && result.errors.length > 0) {
                    showError(statusDiv, `${message} Some resources had errors: ${JSON.stringify(result.errors, null, 2)}`);
                } else {
                    showSuccess(statusDiv, message);
                }
                fetchAndDisplayResources(currentFilters); // Refresh the list
            } catch (error) {
                showError(statusDiv, `Error importing resources: ${error.message}`);
            } finally {
                // Reset file input to allow selecting the same file again if needed
                importResourcesFile.value = '';
            }
        });
    }

    if (exportAllResourcesBtn) {
        exportAllResourcesBtn.addEventListener('click', async () => {
            showLoading(statusDiv, 'Exporting resources...');
            try {
                const response = await fetch('/api/admin/resources/export');
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                // Extract filename from Content-Disposition header
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'resources_export.json'; // Default filename
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
                showSuccess(statusDiv, 'Resources exported successfully.');
            } catch (error) {
                showError(statusDiv, `Error exporting resources: ${error.message}`);
            }
        });
    }

    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', () => {
            const checked = selectAllCheckbox.checked;
            document.querySelectorAll('.select-resource-checkbox').forEach(cb => {
                cb.checked = checked;
            });
        });
    }

    function getSelectedResourceIds() {
        return Array.from(document.querySelectorAll('.select-resource-checkbox:checked')).map(cb => parseInt(cb.dataset.id, 10));
    }

    document.querySelectorAll('.close-modal-btn[data-modal-id]').forEach(btn => {

        btn.addEventListener('click', () => {
            const modal = document.getElementById(btn.dataset.modalId);
            if (modal) modal.style.display = 'none';
        });
    });

    document.querySelectorAll('.modal').forEach(modal => {
        window.addEventListener('click', e => {
            if (e.target === modal) modal.style.display = 'none';
        });
    });

    bulkEditBtn && bulkEditBtn.addEventListener('click', () => {
        const ids = getSelectedResourceIds();
        if (ids.length === 0) {
            alert('Please select at least one resource.');
            return;
        }
        if (bulkEditForm) bulkEditForm.reset();
        hideMessage(bulkEditFormStatus);
        if (bulkEditModal) bulkEditModal.style.display = 'block';
    });

    bulkDeleteBtn && bulkDeleteBtn.addEventListener('click', async () => {
        const ids = getSelectedResourceIds();
        if (ids.length === 0) {
            alert('Please select at least one resource.');
            return;
        }
        if (!confirm(`Delete ${ids.length} selected resources?`)) return;
        try {
            await apiCall('/api/admin/resources/bulk', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids })
            }, statusDiv);
            fetchAndDisplayResources();
        } catch (error) {
            /* handled by apiCall */
        }
    });

    tableBody.addEventListener('click', async function(event) {
        if (event.target.classList.contains('edit-resource-btn')) {
            const id = event.target.dataset.id;
            try {
                console.log('[DEBUG] Edit button clicked for resource ID:', id);
                const data = await apiCall(`/api/admin/resources/${id}`);
                console.log('[DEBUG] Resource data received:', data);
                resourceForm.reset();
                resourceIdInput.value = data.id;
                resourceNameInput.value = data.name || '';
                resourceCapacityInput.value = data.capacity !== null && data.capacity !== undefined ? data.capacity : '';
                resourceEquipmentInput.value = data.equipment || '';
                if (resourceTagsInput) resourceTagsInput.value = data.tags || '';
                resourceStatusModalInput.value = data.status || 'draft'; // Populate status for editing
                resourceFormModalTitle.textContent = 'Edit Resource';
                hideMessage(resourceFormStatus);

                // --- PIN Management UI ---
                const pinsManagementArea = document.getElementById('resource-pins-management-area');
                console.log('[DEBUG] Edit button clicked for resource ID:', id); // Duplicate, but as per request
                console.log('[DEBUG] Resource data received:', data); // Duplicate, but as per request
                if (pinsManagementArea) {
                    console.log('[DEBUG] pinsManagementArea found. Attempting to show. Current display:', pinsManagementArea.style.display);
                    pinsManagementArea.style.display = 'block'; // Show the PINs area
                    console.log('[DEBUG] pinsManagementArea display set to block. New display:', pinsManagementArea.style.display);
                    console.log('[DEBUG] Calling loadResourcePins with resourceId:', id, 'and data.pins:', data.pins);
                    loadResourcePins(id, data.pins); // Pass existing pins if available in 'data'
                }
                // --- End PIN Management UI ---

                resourceFormModal.style.display = 'block';
            } catch (error) {
                showError(statusDiv, `Failed to load resource: ${error.message}`);
            }
        } else if (event.target.classList.contains('delete-resource-btn')) {
            const id = event.target.dataset.id;
            const name = event.target.dataset.name;
            if (!confirm(`Delete resource '${name}' (ID: ${id})?`)) return;
            try {
                await apiCall(`/api/admin/resources/${id}`, { method: 'DELETE' }, statusDiv);
                fetchAndDisplayResources();
            } catch (error) {
                /* error handled by apiCall */
            }
        }
    });

    resourceForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const payload = {
            name: resourceNameInput.value,
            capacity: resourceCapacityInput.value !== '' ? parseInt(resourceCapacityInput.value, 10) : null,
            equipment: resourceEquipmentInput.value,
            status: resourceStatusModalInput.value, // Add status to payload
            tags: resourceTagsInput ? resourceTagsInput.value : ''
        };
        const id = resourceIdInput.value;
        try {
            if (id) {
                await apiCall(`/api/admin/resources/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, resourceFormStatus);
            } else {
                await apiCall('/api/admin/resources', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, resourceFormStatus);
            }
            await fetchAndDisplayResources();
            setTimeout(() => { resourceFormModal.style.display = 'none'; }, 500);
        } catch (error) {
            /* error shown by apiCall */
        }
    });

    if (bulkForm) {
        bulkForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const payload = {
                prefix: bulkPrefixInput.value,
                suffix: bulkSuffixInput.value,
                start: bulkStartInput.value !== '' ? parseInt(bulkStartInput.value, 10) : 1,
                count: bulkCountInput.value !== '' ? parseInt(bulkCountInput.value, 10) : 0,
                padding: bulkPaddingInput.value !== '' ? parseInt(bulkPaddingInput.value, 10) : 0,
                capacity: bulkCapacityInput.value !== '' ? parseInt(bulkCapacityInput.value, 10) : null,
                equipment: bulkEquipmentInput.value,
                status: bulkStatusInput.value,
                tags: bulkTagsInput ? bulkTagsInput.value : ''
            };
            try {
                const result = await apiCall('/api/admin/resources/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, bulkFormStatus);
                await fetchAndDisplayResources();
                if (result && result.created) {
                    showSuccess(bulkFormStatus, `Created ${result.created.length} resources.` + (result.skipped && result.skipped.length ? ` Skipped: ${result.skipped.join(', ')}` : ''));
                }
                setTimeout(() => { bulkModal.style.display = 'none'; }, 500);
            } catch (error) {
                /* error shown by apiCall */
            }
        });
    }

    if (bulkEditForm) {
        bulkEditForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const ids = getSelectedResourceIds();
            if (ids.length === 0) {
                showError(bulkEditFormStatus, 'No resources selected.');
                return;
            }
            const fields = {};
            if (bulkEditStatusInput.value) fields.status = bulkEditStatusInput.value;
            if (bulkEditCapacityInput.value !== '') fields.capacity = parseInt(bulkEditCapacityInput.value, 10);
            if (bulkEditEquipmentInput.value !== '') fields.equipment = bulkEditEquipmentInput.value;
            if (bulkEditTagsInput && bulkEditTagsInput.value !== '') fields.tags = bulkEditTagsInput.value;
            try {
                await apiCall('/api/admin/resources/bulk', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids, changes: fields })
                }, bulkEditFormStatus);
                await fetchAndDisplayResources();
                setTimeout(() => { bulkEditModal.style.display = 'none'; }, 500);
            } catch (error) {
                /* handled by apiCall */
            }
        });
    }

    if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener('click', () => {
            currentFilters = {
                name: filterNameInput.value.trim(),
                status: filterStatusSelect.value,
                mapId: filterMapSelect.value,
                tags: filterTagsInput.value.trim()
            };
            fetchAndDisplayResources(currentFilters);
        });
    }

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            if (filterNameInput) filterNameInput.value = '';
            if (filterStatusSelect) filterStatusSelect.value = '';
            if (filterMapSelect) filterMapSelect.value = '';
            if (filterTagsInput) filterTagsInput.value = '';
            currentFilters = {};
            fetchAndDisplayResources(currentFilters);
        });
    }

    fetchAndDisplayResources();

    // --- PIN Management Functions ---
    async function loadResourcePins(resourceId, existingPins = null) {
        console.log('[DEBUG] loadResourcePins called. resourceId:', resourceId, 'existingPins:', existingPins);
        const pinStatusEl = document.getElementById('resource-pin-form-status');
        currentResourceIdForPins = resourceId;
        const pinsTableBody = document.querySelector('#resource-pins-table tbody');
        const currentPinValueSpan = document.getElementById('current-pin-value');
        if (!pinsTableBody || !currentPinValueSpan) return;

        showLoading(pinStatusEl, 'Loading PINs...');

        try {
            // Fetch full resource details again OR rely on existingPins if comprehensive enough
            // For this implementation, we assume `existingPins` (passed from the main resource load) is sufficient for initial display.
            // If not, an additional fetch for pins specifically might be needed or ensure the main resource fetch is always up-to-date.
            // Let's assume `existingPins` is the `data.pins` from the resource details call.

            let pinsToRender = existingPins;
            let resourceCurrentPin = 'N/A';

            if (!pinsToRender) { // If pins were not passed, fetch them (e.g., after an update)
                const resourceData = await apiCall(`/api/admin/resources/${resourceId}`);
                pinsToRender = resourceData.pins || [];
                resourceCurrentPin = resourceData.current_pin || 'N/A';
            } else {
                // If existingPins were passed, we need the resource's current_pin value.
                // This implies the main resource data should also pass `current_pin`.
                // For simplicity, let's assume the main `data` object in `edit-resource-btn` handler has `current_pin`.
                // This needs adjustment if `resource_to_dict` doesn't include `current_pin`.
                // Let's do a targeted fetch for current_pin for now if not in existingPins structure
                const resDataForPin = await apiCall(`/api/admin/resources/${resourceId}`);
                resourceCurrentPin = resDataForPin.current_pin || 'N/A';
            }

            currentPinValueSpan.textContent = resourceCurrentPin;
            console.log('[DEBUG] About to render PINs table. pinsToRender:', pinsToRender, 'resourceId for table:', resourceId);
            console.log('[DEBUG] resourceCurrentPin for display:', resourceCurrentPin);
            renderPinsTable(pinsToRender, resourceId);

            // Fetch global BookingSettings to control UI visibility
            const bookingSettings = await apiCall('/api/system/booking_settings');
            console.log('[DEBUG] About to update Add PIN form visibility. bookingSettings:', bookingSettings);
            updateAddPinFormVisibility(bookingSettings);
            hideMessage(pinStatusEl);

        } catch (error) {
            showError(pinStatusEl, `Error loading PINs: ${error.message}`);
        }
    }

    function renderPinsTable(pins, resourceId) {
        console.log('[DEBUG] renderPinsTable called. pins:', pins, 'resourceId:', resourceId);
        const pinsTableBody = document.querySelector('#resource-pins-table tbody');
        pinsTableBody.innerHTML = ''; // Clear existing rows

        if (!pins || pins.length === 0) {
            pinsTableBody.innerHTML = '<tr><td colspan="5">No PINs found for this resource.</td></tr>';
            return;
        }

        pins.forEach(pin => {
            const row = pinsTableBody.insertRow();
            row.insertCell().textContent = pin.pin_value;

            const activeCell = row.insertCell();
            const activeCheckbox = document.createElement('input');
            activeCheckbox.type = 'checkbox';
            activeCheckbox.checked = pin.is_active;
            activeCheckbox.classList.add('pin-active-toggle');
            activeCheckbox.dataset.pinId = pin.id;
            activeCheckbox.dataset.resourceId = resourceId;
            activeCell.appendChild(activeCheckbox);

            row.insertCell().textContent = pin.notes || '';
            row.insertCell().textContent = pin.created_at ? new Date(pin.created_at).toLocaleString() : 'N/A';

            const actionsCell = row.insertCell();
            const copyUrlBtn = document.createElement('button');
            copyUrlBtn.textContent = 'Copy Check-in URL';
            copyUrlBtn.classList.add('button', 'button-small', 'copy-pin-url-btn');
            copyUrlBtn.dataset.pinValue = pin.pin_value;
            copyUrlBtn.dataset.resourceId = resourceId;
            actionsCell.appendChild(copyUrlBtn);

            const showQrBtn = document.createElement('button');
            showQrBtn.textContent = 'Show QR Code';
            showQrBtn.classList.add('button', 'button-small', 'show-qr-code-btn');
            showQrBtn.dataset.pinValue = pin.pin_value;
            showQrBtn.dataset.resourceId = resourceId;
            showQrBtn.style.marginLeft = '5px';
            actionsCell.appendChild(showQrBtn);
        });
    }

    function updateAddPinFormVisibility(bookingSettings) {
        console.log('[DEBUG] updateAddPinFormVisibility called. bookingSettings:', bookingSettings);
        const manualPinInput = document.getElementById('manual_pin_value');
        const addManualPinBtn = document.getElementById('btn-add-manual-pin');
        const autoGeneratePinBtn = document.getElementById('btn-auto-generate-pin');

        if (!bookingSettings) { // Default to restrictive if settings not loaded
            if (manualPinInput) manualPinInput.style.display = 'none';
            if (addManualPinBtn) addManualPinBtn.style.display = 'none';
            if (autoGeneratePinBtn) autoGeneratePinBtn.style.display = 'none';
            return;
        }

        if (manualPinInput && addManualPinBtn) {
            const showManual = bookingSettings.pin_allow_manual_override;
            manualPinInput.style.display = showManual ? 'inline-block' : 'none';
            addManualPinBtn.style.display = showManual ? 'inline-block' : 'none';
            if (manualPinInput.previousElementSibling && manualPinInput.previousElementSibling.tagName === 'LABEL') {
                 manualPinInput.previousElementSibling.style.display = showManual ? 'inline-block' : 'none';
            }
        }
        if (autoGeneratePinBtn) {
            autoGeneratePinBtn.style.display = bookingSettings.pin_auto_generation_enabled ? 'inline-block' : 'none';
        }
    }

    // Placeholder for event handlers to be added in the next chunk
    // Event handler for "Add Manual PIN"
    const addManualPinBtn = document.getElementById('btn-add-manual-pin');
    if (addManualPinBtn) {
        addManualPinBtn.addEventListener('click', async function() {
            const manualPinValue = document.getElementById('manual_pin_value').value.trim();
            const notes = document.getElementById('pin_notes').value.trim();
            const statusEl = document.getElementById('resource-pin-form-status');

            if (!currentResourceIdForPins) {
                showError(statusEl, 'No resource selected for PIN management.');
                return;
            }
            // Manual PIN value is optional if auto-generation is fallback, but this button implies manual intent.
            // Backend will validate if manual PIN is allowed and if value is provided when required.

            showLoading(statusEl, 'Adding manual PIN...');
            try {
                const payload = { notes: notes };
                if (manualPinValue) { // Only include pin_value if user actually entered one
                    payload.pin_value = manualPinValue;
                } else if (document.getElementById('btn-auto-generate-pin').style.display === 'none') {
                    // If auto-generate is hidden (disabled) and manual is empty, it's an error for "Add Manual"
                    showError(statusEl, 'Manual PIN value is required when auto-generation is disabled.');
                    return;
                }
                // If manualPinValue is empty, and auto-generation is enabled, the backend will auto-generate.
                // This button's click implies user wants to use the value in manual_pin_value field or trigger auto if empty & allowed.
                // The backend POST /pins handles empty pin_value by trying auto-generation if enabled.

                await apiCall(`/api/resources/${currentResourceIdForPins}/pins`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }, statusEl);
                document.getElementById('manual_pin_value').value = ''; // Clear input
                document.getElementById('pin_notes').value = ''; // Clear input
                loadResourcePins(currentResourceIdForPins); // Refresh PINs list
            } catch (error) {
                // showError is called by apiCall, but we can add specifics if needed
                // showError(statusEl, `Error adding manual PIN: ${error.message}`);
            }
        });
    }

    // Event handler for "Auto-generate PIN"
    const autoGeneratePinBtn = document.getElementById('btn-auto-generate-pin');
    if (autoGeneratePinBtn) {
        autoGeneratePinBtn.addEventListener('click', async function() {
            const notes = document.getElementById('pin_notes').value.trim();
            const statusEl = document.getElementById('resource-pin-form-status');

            if (!currentResourceIdForPins) {
                showError(statusEl, 'No resource selected for PIN management.');
                return;
            }
            showLoading(statusEl, 'Auto-generating PIN...');
            try {
                // Explicitly send empty pin_value to signify auto-generation preference if backend distinguishes.
                // Or rely on backend to auto-generate if pin_value is missing/empty and auto-gen is enabled.
                await apiCall(`/api/resources/${currentResourceIdForPins}/pins`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: notes, pin_value: '' }) // Sending empty pin_value
                }, statusEl);
                document.getElementById('manual_pin_value').value = ''; // Clear input
                document.getElementById('pin_notes').value = ''; // Clear input
                loadResourcePins(currentResourceIdForPins); // Refresh PINs list
            } catch (error) {
                // showError(statusEl, `Error auto-generating PIN: ${error.message}`);
            }
        });
    }

    // Event delegation for "Toggle Active" and "Copy Check-in URL" on pins table
    const pinsTable = document.getElementById('resource-pins-table');
    if (pinsTable) {
        pinsTable.addEventListener('click', async function(event) {
            const target = event.target;
            const statusEl = document.getElementById('resource-pin-form-status');

            if (target.classList.contains('pin-active-toggle')) {
                const pinId = target.dataset.pinId;
                const resourceId = target.dataset.resourceId; // Should be currentResourceIdForPins
                const newStatus = target.checked;

                showLoading(statusEl, `Updating PIN ${pinId} status...`);
                try {
                    const updatedPinData = await apiCall(`/api/resources/${resourceId}/pins/${pinId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ is_active: newStatus })
                    }, statusEl);

                    // Update the current PIN display if it changed
                    const currentPinValueSpan = document.getElementById('current-pin-value');
                    if (currentPinValueSpan && updatedPinData.resource_current_pin) {
                        currentPinValueSpan.textContent = updatedPinData.resource_current_pin;
                    } else if (currentPinValueSpan) {
                         currentPinValueSpan.textContent = 'N/A';
                    }
                    showSuccess(statusEl, `PIN ${pinId} status updated.`);
                    // Optionally, just update the specific row visually instead of full reload
                    // For now, a full reload ensures consistency:
                    // loadResourcePins(resourceId);
                    // Or, even better, update just the one pin in the table from response
                    target.checked = updatedPinData.is_active; // Reflect actual server state

                } catch (error) {
                    target.checked = !newStatus; // Revert checkbox on error
                    // showError is handled by apiCall
                }
            } else if (target.classList.contains('copy-pin-url-btn')) {
                const pinValue = target.dataset.pinValue;
                const resourceId = target.dataset.resourceId;
                const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`; // Fixed URL
                try {
                    await navigator.clipboard.writeText(checkinUrl);
                    showSuccess(statusEl, 'Check-in URL copied to clipboard!');
                } catch (err) {
                    showError(statusEl, 'Failed to copy URL. Please copy manually.');
                    console.error('Failed to copy URL: ', err);
                }
            } else if (target.classList.contains('show-qr-code-btn')) {
                const pinValue = target.dataset.pinValue;
                const resourceId = target.dataset.resourceId;
                const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`; // Correct URL

                const qrCodeModal = document.getElementById('qr-code-modal');
                const qrCodeDisplay = document.getElementById('qr-code-display');
                const qrCodeUrlText = document.getElementById('qr-code-url-text');
                console.log('[DEBUG QR MODAL ELEMENTS] qrCodeModal:', qrCodeModal, 'qrCodeDisplay:', qrCodeDisplay, 'qrCodeUrlText:', qrCodeUrlText);

                if (qrCodeModal && qrCodeDisplay && qrCodeUrlText) {
                    qrCodeDisplay.innerHTML = ''; // Clear previous QR code
                    qrCodeUrlText.textContent = checkinUrl;

                    if (typeof QRCode !== 'undefined') { // Check if QRCode library is loaded
                        new QRCode(qrCodeDisplay, {
                            text: checkinUrl,
                            width: 200,
                            height: 200,
                            colorDark : "#000000",
                            colorLight : "#ffffff",
                            correctLevel : QRCode.CorrectLevel.H
                        });
                    } else {
                        qrCodeDisplay.textContent = 'QR Code library not loaded. Please add it.';
                        console.error('QRCode library not found. Cannot generate QR code.');
                    }
                    qrCodeModal.style.display = 'block';
                } else {
                    console.error('QR Code modal elements not found.');
                    showError(statusEl, 'Could not display QR Code modal. Elements missing.');
                }
            }
        });
    }
});
