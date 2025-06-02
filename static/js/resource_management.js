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
                const data = await apiCall(`/api/admin/resources/${id}`);
                resourceForm.reset();
                resourceIdInput.value = data.id;
                resourceNameInput.value = data.name || '';
                resourceCapacityInput.value = data.capacity !== null && data.capacity !== undefined ? data.capacity : '';
                resourceEquipmentInput.value = data.equipment || '';
                if (resourceTagsInput) resourceTagsInput.value = data.tags || '';
                resourceStatusModalInput.value = data.status || 'draft'; // Populate status for editing
                resourceFormModalTitle.textContent = 'Edit Resource';
                hideMessage(resourceFormStatus);
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
});
