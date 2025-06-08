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

    let currentFilters = {
        name: '',
        status: '',
        mapId: '',
        tags: ''
    };
    let currentPage = 1;
    let itemsPerPage = 10; // Default items per page

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

    async function fetchAndDisplayResources() { // Filter argument removed, uses global currentFilters
        showLoading(statusDiv, 'Fetching resources...');

        const params = new URLSearchParams();
        params.append('page', currentPage);
        params.append('per_page', itemsPerPage);

        if (currentFilters.name) params.append('name', currentFilters.name);
        if (currentFilters.status) params.append('status', currentFilters.status);
        if (currentFilters.tags) params.append('tags', currentFilters.tags);
        if (currentFilters.mapId) params.append('map_id', currentFilters.mapId);

        try {
            // Fetch maps only once or if not already populated
            if (filterMapSelect && filterMapSelect.options.length <= 1) { // Assuming default "-- Any --" option
                const maps = await apiCall('/api/admin/maps');
                if (maps) {
                    maps.forEach(m => {
                        const opt = document.createElement('option');
                        opt.value = m.id;
                        opt.textContent = m.name;
                        filterMapSelect.appendChild(opt);
                    });
                }
            }

            const data = await apiCall(`/api/admin/resources?${params.toString()}`);
            tableBody.innerHTML = ''; // Clear existing rows

            const resourcesToShow = data.resources;
            const paginationData = data.pagination;

            const mapsById = {}; // Populate this if needed for grouping, or fetch maps separately
            // If maps are needed for display and not fetched globally, fetch them here or pass from a global store.
            // For simplicity, assuming map name isn't displayed in the resource row directly or is part of resource_to_dict if needed.

            if (resourcesToShow && resourcesToShow.length > 0) {
                // Grouping logic can be simplified if the API returns resources sorted by map or if grouping is removed for pagination
                // For now, let's render without grouping by map to simplify pagination integration.
                // If grouping is required, the logic would need to handle pagination within groups or adjust UI significantly.
                resourcesToShow.forEach(r => {
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
                hideMessage(statusDiv);
            } else {
                tableBody.innerHTML = '<tr><td colspan="7">No resources found matching your criteria.</td></tr>'; // Colspan updated
                showSuccess(statusDiv, 'No resources to display for the current page/filters.');
            }

            renderResourcePagination(paginationData);
            if (selectAllCheckbox) selectAllCheckbox.checked = false;

        } catch (error) {
            showError(statusDiv, `Error fetching resources: ${error.message}`);
            renderResourcePagination(null); // Clear pagination on error
        }
    }

    function renderResourcePagination(paginationData) {
        const controlsContainer = document.getElementById('resource-pagination-controls');
        if (!controlsContainer) return;
        controlsContainer.innerHTML = '';

        if (!paginationData || paginationData.total_pages <= 0) {
            controlsContainer.style.display = 'none';
            return;
        }
        controlsContainer.style.display = 'block';

        const navElement = document.createElement('nav');
        navElement.className = 'mt-4';
        navElement.setAttribute('aria-label', 'Resources pagination');

        const ulElement = document.createElement('ul');
        ulElement.className = 'pagination justify-content-center';

        // Items Per Page Selector
        const itemsPerPageLi = document.createElement('li');
        itemsPerPageLi.className = 'page-item disabled';
        const form = document.createElement('form');
        form.className = 'd-flex align-items-center';
        const label = document.createElement('label');
        label.className = 'visually-hidden me-2';
        label.setAttribute('for', 'per_page_select_resource_pagination');
        label.textContent = 'Items per page:';
        form.appendChild(label);
        const select = document.createElement('select');
        select.className = 'form-select form-select-sm me-2';
        select.name = 'per_page';
        select.id = 'per_page_select_resource_pagination';
        select.style.width = 'auto';
        const perPageOptions = [10, 25, 50, 100];
        perPageOptions.forEach(num => {
            const option = document.createElement('option');
            option.value = num;
            option.textContent = num;
            if (num === itemsPerPage) option.selected = true;
            select.appendChild(option);
        });
        select.addEventListener('change', function() {
            itemsPerPage = parseInt(this.value, 10);
            currentPage = 1;
            fetchAndDisplayResources();
        });
        form.appendChild(select);
        itemsPerPageLi.appendChild(form);
        ulElement.appendChild(itemsPerPageLi);

        if (paginationData.total_pages <= 1 && paginationData.total_items > 0) {
            const p = document.createElement('p');
            p.className = 'text-center text-muted small mt-2';
            p.textContent = `Total items: ${paginationData.total_items}`;
            navElement.appendChild(ulElement);
            navElement.appendChild(p);
            controlsContainer.appendChild(navElement);
            return;
        }
        if (paginationData.total_pages <= 1) { // No items or only one page of items
             navElement.appendChild(ulElement); // Show selector only
             controlsContainer.appendChild(navElement);
             return;
        }


        // Blank Separator
        const liSep1 = document.createElement('li');
        liSep1.className = 'page-item disabled';
        const spanSep1 = document.createElement('span');
        spanSep1.className = 'page-link';
        spanSep1.style.paddingLeft = '1em';
        liSep1.appendChild(spanSep1);
        ulElement.appendChild(liSep1);

        // Previous Icon Link
        const liPrev = document.createElement('li');
        liPrev.className = 'page-item' + (paginationData.page === 1 ? ' disabled' : '');
        const aPrev = document.createElement('a');
        aPrev.className = 'page-link';
        aPrev.href = '#';
        aPrev.innerHTML = '&laquo;';
        if (paginationData.page > 1) {
            aPrev.addEventListener('click', (e) => { e.preventDefault(); handleResourcePageClick(paginationData.page - 1); });
        }
        liPrev.appendChild(aPrev);
        ulElement.appendChild(liPrev);

        // Opening Bracket
        const liOpenBracket = document.createElement('li');
        liOpenBracket.className = 'page-item disabled';
        const spanOpenBracket = document.createElement('span');
        spanOpenBracket.className = 'page-link';
        spanOpenBracket.textContent = '[';
        liOpenBracket.appendChild(spanOpenBracket);
        ulElement.appendChild(liOpenBracket);

        // Page Numbers and Commas
        function createCommaLi() {
            const li = document.createElement('li');
            li.className = 'page-item disabled';
            const span = document.createElement('span');
            span.className = 'page-link';
            span.textContent = ',';
            li.appendChild(span);
            return li;
        }

        let isFirstElementInSequence = true;
        const totalPages = paginationData.total_pages;
        const currentDisplayPage = paginationData.page;

        const pagesToShow = new Set();
        pagesToShow.add(1);
        pagesToShow.add(totalPages);
        if (currentDisplayPage > 1) pagesToShow.add(currentDisplayPage - 1);
        pagesToShow.add(currentDisplayPage);
        if (currentDisplayPage < totalPages) pagesToShow.add(currentDisplayPage + 1);

        const sortedPages = Array.from(pagesToShow).sort((a, b) => a - b);
        let lastPageShown = 0;

        sortedPages.forEach(p => {
            if (p < 1 || p > totalPages) return;

            if (p > lastPageShown + 1 && p !== 1 && lastPageShown !== 0) {
                 if (!isFirstElementInSequence) ulElement.appendChild(createCommaLi());
                 const liEllipsis = document.createElement('li');
                 liEllipsis.className = 'page-item disabled';
                 const spanEllipsis = document.createElement('span');
                 spanEllipsis.className = 'page-link';
                 spanEllipsis.textContent = '...';
                 liEllipsis.appendChild(spanEllipsis);
                 ulElement.appendChild(liEllipsis);
                 isFirstElementInSequence = false;
            }

            if (p > lastPageShown) {
                if (!isFirstElementInSequence) ulElement.appendChild(createCommaLi());
                const liPage = document.createElement('li');
                liPage.className = 'page-item' + (p === currentDisplayPage ? ' active' : '');
                const aPage = document.createElement('a');
                aPage.className = 'page-link';
                aPage.href = '#';
                aPage.textContent = p;
                aPage.addEventListener('click', (e) => { e.preventDefault(); handleResourcePageClick(p); });
                liPage.appendChild(aPage);
                ulElement.appendChild(liPage);
                isFirstElementInSequence = false;
                lastPageShown = p;
            }
        });

        // Closing Bracket
        const liCloseBracket = document.createElement('li');
        liCloseBracket.className = 'page-item disabled';
        const spanCloseBracket = document.createElement('span');
        spanCloseBracket.className = 'page-link';
        spanCloseBracket.textContent = ']';
        liCloseBracket.appendChild(spanCloseBracket);
        ulElement.appendChild(liCloseBracket);

        // Next Icon Link
        const liNext = document.createElement('li');
        liNext.className = 'page-item' + (paginationData.page === totalPages ? ' disabled' : '');
        const aNext = document.createElement('a');
        aNext.className = 'page-link';
        aNext.href = '#';
        aNext.innerHTML = '&raquo;';
        if (paginationData.page < totalPages) {
            aNext.addEventListener('click', (e) => { e.preventDefault(); handleResourcePageClick(paginationData.page + 1); });
        }
        liNext.appendChild(aNext);
        ulElement.appendChild(liNext);

        // Final Blank Separator
        const liSep2 = document.createElement('li');
        liSep2.className = 'page-item disabled';
        const spanSep2 = document.createElement('span');
        spanSep2.className = 'page-link';
        spanSep2.style.paddingLeft = '1em';
        liSep2.appendChild(spanSep2);
        ulElement.appendChild(liSep2);

        navElement.appendChild(ulElement);

        const pTotal = document.createElement('p');
        pTotal.className = 'text-center text-muted small mt-2';
        pTotal.textContent = `Page ${currentDisplayPage} of ${totalPages}. Total items: ${paginationData.total_items}`;
        navElement.appendChild(pTotal);

        controlsContainer.appendChild(navElement);
    }

    function handleResourcePageClick(newPageNum) {
        currentPage = newPageNum;
        fetchAndDisplayResources();
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
            currentPage = 1; // Reset to first page on filter change
            fetchAndDisplayResources();
        });
    }

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            if (filterNameInput) filterNameInput.value = '';
            if (filterStatusSelect) filterStatusSelect.value = '';
            if (filterMapSelect) filterMapSelect.value = '';
            if (filterTagsInput) filterTagsInput.value = '';
            currentFilters = { name: '', status: '', mapId: '', tags: '' }; // Reset to empty strings
            currentPage = 1; // Reset to first page
            fetchAndDisplayResources();
        });
    }

    fetchAndDisplayResources();

    // --- Bulk PIN Actions UI Elements ---
    const bulkPinActionsArea = document.getElementById('bulk-pin-actions-area');
    const bulkPinActionSelect = document.getElementById('bulk-pin-action-select');
    const btnExecuteBulkPinAction = document.getElementById('btn-execute-bulk-pin-action');
    const bulkPinActionStatus = document.getElementById('bulk-pin-action-status');

    function updateBulkPinActionsUI() {
        const selectedCheckboxes = document.querySelectorAll('.select-resource-checkbox:checked');
        const count = selectedCheckboxes.length;

        if (count > 0) {
            if (bulkPinActionsArea) bulkPinActionsArea.style.display = 'block';
            if (btnExecuteBulkPinAction) btnExecuteBulkPinAction.disabled = false;
        } else {
            if (bulkPinActionsArea) bulkPinActionsArea.style.display = 'none';
            if (btnExecuteBulkPinAction) btnExecuteBulkPinAction.disabled = true;
            if (bulkPinActionSelect) bulkPinActionSelect.value = ""; // Reset dropdown
            if (bulkPinActionStatus) hideMessage(bulkPinActionStatus);
        }

        // Update "Select All" checkbox state
        if (selectAllCheckbox) {
            const totalCheckboxes = document.querySelectorAll('.select-resource-checkbox').length;
            selectAllCheckbox.checked = (totalCheckboxes > 0 && count === totalCheckboxes);
        }
    }

    // Event listener for "Select All" checkbox
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            document.querySelectorAll('.select-resource-checkbox').forEach(checkbox => {
                checkbox.checked = this.checked;
            });
            updateBulkPinActionsUI();
        });
    }

    // Event delegation for individual resource checkboxes
    tableBody.addEventListener('change', function(event) {
        if (event.target.classList.contains('select-resource-checkbox')) {
            updateBulkPinActionsUI();
        }
    });

    // Event listener for "Execute Bulk PIN Action" button
    if (btnExecuteBulkPinAction) {
        btnExecuteBulkPinAction.addEventListener('click', async function() {
            const selectedActionValue = bulkPinActionSelect.value;
            const selectedResourceIds = Array.from(document.querySelectorAll('.select-resource-checkbox:checked'))
                                          .map(cb => parseInt(cb.dataset.id, 10));

            if (!selectedActionValue) {
                showError(bulkPinActionStatus, 'Please select a bulk PIN action.');
                return;
            }
            if (selectedResourceIds.length === 0) {
                showError(bulkPinActionStatus, 'Please select at least one resource.');
                return; // Should be prevented by button disabled state, but good check
            }

            const selectedActionText = bulkPinActionSelect.options[bulkPinActionSelect.selectedIndex].text;
            if (!confirm(`Are you sure you want to '${selectedActionText}' for ${selectedResourceIds.length} selected resources?`)) {
                return;
            }

            showLoading(bulkPinActionStatus, `Executing '${selectedActionText}'...`);
            try {
                const response = await apiCall('/api/resources/pins/bulk_action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        resource_ids: selectedResourceIds,
                        action: selectedActionValue
                    })
                }, bulkPinActionStatus); // Pass status element to apiCall

                // Display the message from the API response
                let message = response.message || `Bulk action '${selectedActionText}' completed.`;
                if (response.details && response.details.length > 0) {
                    const successes = response.details.filter(d => d.status === 'success').length;
                    const errors = response.details.filter(d => d.status === 'error' || d.status === 'skipped').length;
                    message += ` Successes: ${successes}, Failures/Skipped: ${errors}.`;
                    if (errors > 0) {
                         message += " Check console for detailed errors per resource.";
                         console.warn("Bulk PIN action errors/skipped details:", response.details.filter(d => d.status !== 'success'));
                    }
                }
                showSuccess(bulkPinActionStatus, message);

                fetchAndDisplayResources(currentFilters); // Refresh resource list to show updated current_pin etc.

                // Uncheck all and hide bulk actions UI
                if (selectAllCheckbox) selectAllCheckbox.checked = false;
                document.querySelectorAll('.select-resource-checkbox:checked').forEach(cb => cb.checked = false);
                updateBulkPinActionsUI();

            } catch (error) {
                // showError is typically handled by apiCall, but if not, or if we want to ensure it's shown here:
                showError(bulkPinActionStatus, error.message || `Failed to execute bulk action '${selectedActionText}'.`);
                console.error(`Error executing bulk PIN action '${selectedActionValue}':`, error);
            }
        });
    }

    // Initial UI setup
    updateBulkPinActionsUI();


    // --- PIN Management Functions ---
    async function loadResourcePins(resourceId, existingPins = null) {
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
            renderPinsTable(pinsToRender, resourceId);

            // Fetch global BookingSettings to control UI visibility
            const bookingSettings = await apiCall('/api/system/booking_settings');
            updateAddPinFormVisibility(bookingSettings);
            hideMessage(pinStatusEl);

        } catch (error) {
            showError(pinStatusEl, `Error loading PINs: ${error.message}`);
        }
    }

    function renderPinsTable(pins, resourceId) {
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
            actionsCell.style.whiteSpace = "nowrap"; // Keep buttons on one line

            // Action buttons for each PIN
            actionsCell.innerHTML = `
                <button class="button btn-pin-action btn-edit-pin" data-pin-id="${pin.id}" data-resource-id="${resourceId}" title="Edit PIN"><span aria-hidden="true">✏️</span></button>
                <button class="button btn-pin-action btn-delete-pin danger" data-pin-id="${pin.id}" data-resource-id="${resourceId}" title="Delete PIN"><span aria-hidden="true">🗑️</span></button>
                <button class="button btn-pin-action copy-pin-url-btn" data-pin-value="${pin.pin_value}" data-resource-id="${resourceId}" title="Copy Check-in URL" style="margin-left:5px;"><span aria-hidden="true">🔗</span></button>
                <button class="button btn-pin-action show-qr-code-btn" data-pin-value="${pin.pin_value}" data-resource-id="${resourceId}" title="Show PIN QR Code" style="margin-left:5px;"><span aria-hidden="true">📱</span></button>
            `;
        });

        // ATTACH EVENT LISTENER LOGIC HERE
        const currentPinsTableElement = document.getElementById('resource-pins-table');

        if (currentPinsTableElement) {
            if (!currentPinsTableElement._listenerAttached) {
                currentPinsTableElement.addEventListener('click', async function(event) {

                    const statusEl = document.getElementById('resource-pin-form-status'); // Ensure statusEl is defined for handlers

                    // Handle pin-active-toggle separately as it's an input
                    if (event.target.classList.contains('pin-active-toggle')) {
                        const pinId = event.target.dataset.pinId;
                        const resourceIdForToggle = event.target.dataset.resourceId; // Use specific resourceId from checkbox
                        const newStatus = event.target.checked;
                        showLoading(statusEl, `Updating PIN ${pinId} status...`);
                        try {
                            const updatedPinData = await apiCall(`/api/resources/${resourceIdForToggle}/pins/${pinId}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ is_active: newStatus })
                            }, statusEl);
                            const currentPinValueSpan = document.getElementById('current-pin-value');
                            if (currentPinValueSpan && updatedPinData.resource_current_pin) {
                                currentPinValueSpan.textContent = updatedPinData.resource_current_pin;
                            } else if (currentPinValueSpan) {
                                 currentPinValueSpan.textContent = 'N/A';
                            }
                            showSuccess(statusEl, `PIN ${pinId} status updated.`);
                            event.target.checked = updatedPinData.is_active;
                        } catch (error) {
                            event.target.checked = !newStatus;
                        }
                        return; // Processed, no need to check for button
                    }

                    const targetButton = event.target.closest('button.btn-pin-action');

                    if (!targetButton) {
                        return;
                    }

                    const target = targetButton; // Now target is definitely the button

                    if (target.classList.contains('copy-pin-url-btn')) {
                        const pinValue = target.dataset.pinValue;
                        const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`; // resourceId from renderPinsTable scope
                        try {
                            await navigator.clipboard.writeText(checkinUrl);
                            showSuccess(statusEl, 'Check-in URL copied to clipboard!');
                        } catch (err) {
                            showError(statusEl, 'Failed to copy URL. Please copy manually.');
                            console.error('Failed to copy URL: ', err);
                        }
                    } else if (target.classList.contains('show-qr-code-btn')) {
                        const pinValue = target.dataset.pinValue;
                        const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`; // resourceId from renderPinsTable scope
                        const qrCodeModal = document.getElementById('qr-code-modal');
                        const qrCodeDisplay = document.getElementById('qr-code-display');
                        const qrCodeUrlText = document.getElementById('qr-code-url-text');

                        if (qrCodeModal && qrCodeDisplay && qrCodeUrlText) {
                            qrCodeDisplay.innerHTML = '';
                            qrCodeUrlText.textContent = checkinUrl;
                            let attempts = 0;
                            const maxAttempts = 5;
                            const retryInterval = 200;
                            function tryGenerateQRCode() {
                                if (typeof QRCode !== 'undefined') {
                                    qrCodeDisplay.innerHTML = '';
                                    try {
                                        new QRCode(qrCodeDisplay, { text: checkinUrl, width: 200, height: 200, colorDark : "#000000", colorLight : "#ffffff", correctLevel : QRCode.CorrectLevel.H });
                                        if (statusEl) hideMessage(statusEl);
                                    } catch (e) {
                                        console.error('[QR Code] Error creating QRCode instance:', e); // Kept specific error for instantiation
                                        qrCodeDisplay.innerHTML = '<p style="color: red; font-weight: bold;">Error during QR Code generation.</p>' + '<p><small>Details: ' + e.message + '</small></p>';
                                        if (statusEl) showError(statusEl, 'Error generating QR Code.');
                                    }
                                    qrCodeModal.style.display = 'block';
                                } else {
                                    attempts++;
                                    if (attempts < maxAttempts) {
                                        setTimeout(tryGenerateQRCode, retryInterval);
                                    } else {
                                        console.error('[QR Code] QRCode library not loaded after multiple attempts.'); // Kept specific error for library load failure
                                        qrCodeDisplay.innerHTML = '<p style="color: red; font-weight: bold;">QR Code library could not load.</p>' + '<p>Check internet connection or browser extensions.</p>';
                                        if (statusEl) showError(statusEl, 'QR Code library failed to load.');
                                        qrCodeModal.style.display = 'block';
                                    }
                                }
                            }
                            tryGenerateQRCode();
                        } else {
                            console.error('[QR Code] Modal elements not found.'); // Kept specific error for missing UI
                            if (statusEl) showError(statusEl, 'QR Code modal elements missing.');
                        }
                    } else if (target.classList.contains('delete-pin-btn')) {
                        const pinId = target.dataset.pinId;
                        if (!confirm(`Are you sure you want to delete PIN ID ${pinId}?`)) return;
                        showLoading(statusEl, 'Deleting PIN...');
                        try {
                            // Use resourceId from renderPinsTable scope for the API call
                            const responseData = await apiCall(`/api/resources/${resourceId}/pins/${pinId}`, { method: 'DELETE' }, statusEl);
                            showSuccess(statusEl, responseData.message || 'PIN deleted successfully.');
                            // currentResourceIdForPins is a global; loadResourcePins might need it or the specific resourceId
                            if (typeof loadResourcePins === 'function') {
                                await loadResourcePins(currentResourceIdForPins); // Or resourceId, if loadResourcePins can take it
                            }
                        } catch (error) { /* Handled by apiCall */ }
                    } else if (target.classList.contains('btn-edit-pin')) {
                        alert('Edit PIN functionality not yet implemented. PIN ID: ' + target.dataset.pinId);
                    }
                });
                currentPinsTableElement._listenerAttached = true;
            }
        }
    }

    function updateAddPinFormVisibility(bookingSettings) {
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

    /*
    // Event delegation for "Toggle Active" and "Copy Check-in URL" on pins table
    const pinsTable = document.getElementById('resource-pins-table');
    console.log('[EVENT_LISTENER_DEBUG] pinsTable element:', pinsTable);

    if (pinsTable) {
        console.log('[EVENT_LISTENER_DEBUG] Attempting to add click listener to pinsTable.');
        pinsTable.addEventListener('click', async function(event) {
            console.log('[EVENT_LISTENER_DEBUG] A click occurred on pinsTable. Event target:', event.target);

            const target = event.target;
            const statusEl = document.getElementById('resource-pin-form-status');

            if (target.classList.contains('pin-active-toggle')) {
                const pinId = target.dataset.pinId;
                const resourceId = target.dataset.resourceId;
                const newStatus = target.checked;

                showLoading(statusEl, `Updating PIN ${pinId} status...`);
                try {
                    const updatedPinData = await apiCall(`/api/resources/${resourceId}/pins/${pinId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ is_active: newStatus })
                    }, statusEl);

                    const currentPinValueSpan = document.getElementById('current-pin-value');
                    if (currentPinValueSpan && updatedPinData.resource_current_pin) {
                        currentPinValueSpan.textContent = updatedPinData.resource_current_pin;
                    } else if (currentPinValueSpan) {
                         currentPinValueSpan.textContent = 'N/A';
                    }
                    showSuccess(statusEl, `PIN ${pinId} status updated.`);
                    target.checked = updatedPinData.is_active;

                } catch (error) {
                    target.checked = !newStatus;
                }
            } else if (target.classList.contains('copy-pin-url-btn')) {
                const pinValue = target.dataset.pinValue;
                const resourceId = target.dataset.resourceId;
                const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`;
                try {
                    await navigator.clipboard.writeText(checkinUrl);
                    showSuccess(statusEl, 'Check-in URL copied to clipboard!');
                } catch (err) {
                    showError(statusEl, 'Failed to copy URL. Please copy manually.');
                    console.error('Failed to copy URL: ', err);
                }
            } else if (target.classList.contains('show-qr-code-btn')) {
                console.log('!!! QR ICON CLICK HANDLER ENTERED !!!');
                const pinValue = target.dataset.pinValue;
                const resourceId = target.dataset.resourceId;
                const checkinUrl = `${window.location.origin}/api/r/${resourceId}/checkin?pin=${pinValue}`;

                const qrCodeModal = document.getElementById('qr-code-modal');
                const qrCodeDisplay = document.getElementById('qr-code-display');
                const qrCodeUrlText = document.getElementById('qr-code-url-text');
                const statusEl = document.getElementById('resource-pin-form-status');

                console.log('[QR DEBUG] Show QR button clicked. URL:', checkinUrl);
                console.log('[QR DEBUG] Modal elements: qrCodeModal:', !!qrCodeModal, 'qrCodeDisplay:', !!qrCodeDisplay, 'qrCodeUrlText:', !!qrCodeUrlText);

                if (qrCodeModal && qrCodeDisplay && qrCodeUrlText) {
                    console.log('[QR DEBUG] Initial qrCodeDisplay.innerHTML:', qrCodeDisplay.innerHTML);
                    qrCodeDisplay.innerHTML = '';
                    qrCodeUrlText.textContent = checkinUrl;
                    console.log('[QR DEBUG] Cleared qrCodeDisplay. Set qrCodeUrlText to:', checkinUrl);

                    let attempts = 0;
                    const maxAttempts = 5;
                    const retryInterval = 200;

                    function tryGenerateQRCode() {
                        console.log(`[QR DEBUG] tryGenerateQRCode attempt ${attempts + 1}/${maxAttempts}.`);
                        if (typeof QRCode !== 'undefined') {
                            console.log('[QR DEBUG] QRCode library IS defined.');
                            qrCodeDisplay.innerHTML = '';
                            try {
                                console.log('[QR DEBUG] Attempting to instantiate QRCode object...');
                                new QRCode(qrCodeDisplay, {
                                    text: checkinUrl,
                                    width: 200,
                                    height: 200,
                                    colorDark : "#000000",
                                    colorLight : "#ffffff",
                                    correctLevel : QRCode.CorrectLevel.H
                                });
                                console.log('[QR DEBUG] QRCode instance supposedly created.');
                                if (qrCodeDisplay.innerHTML.trim() === '') {
                                    console.warn('[QR DEBUG] QRCode object created, but qrCodeDisplay is empty. Forcing debug message.');
                                    qrCodeDisplay.innerHTML = '<p style="color: orange;">Debug: QRCode created but display is empty.</p>';
                                } else {
                                    console.log('[QR DEBUG] qrCodeDisplay content after new QRCode():', qrCodeDisplay.innerHTML.substring(0, 100) + '...');
                                }
                                if (statusEl) hideMessage(statusEl);
                            } catch (e) {
                                console.error('[QR DEBUG] Error during new QRCode() instantiation:', e);
                                qrCodeDisplay.innerHTML = '<p style="color: red; font-weight: bold;">Error during QR Code generation.</p>' +
                                                          '<p><small>Details: ' + e.message + '</small></p>';
                                if (statusEl) showError(statusEl, 'Error generating QR Code.');
                            }
                            console.log('[QR DEBUG] Setting qrCodeModal.style.display = "block". Current display state:', qrCodeModal.style.display);
                            qrCodeModal.style.display = 'block';
                            console.log('[QR DEBUG] qrCodeModal.style.display set to "block". New display state:', qrCodeModal.style.display);
                        } else {
                            attempts++;
                            console.log(`[QR DEBUG] QRCode library IS UNDEFINED (attempt ${attempts}).`);
                            if (attempts < maxAttempts) {
                                console.log(`[QR DEBUG] Retrying in ${retryInterval}ms...`);
                                setTimeout(tryGenerateQRCode, retryInterval);
                            } else {
                                console.error('[QR DEBUG] QRCode library still undefined after multiple attempts.');
                                qrCodeDisplay.innerHTML = '<p style="color: red; font-weight: bold;">QR Code library could not load.</p>' +
                                                          '<p>Check internet connection or browser extensions.</p>';
                                if (statusEl) showError(statusEl, 'QR Code library failed to load.');
                                console.log('[QR DEBUG] Setting qrCodeModal.style.display = "block" (library load failed). Current display state:', qrCodeModal.style.display);
                                qrCodeModal.style.display = 'block';
                                console.log('[QR DEBUG] qrCodeModal.style.display set to "block" (library load failed). New display state:', qrCodeModal.style.display);
                            }
                        }
                    }
                    tryGenerateQRCode();

                } else {
                    console.error('[QR DEBUG] Critical: Modal UI elements (qrCodeModal, qrCodeDisplay, or qrCodeUrlText) not found.');
                    if (statusEl) showError(statusEl, 'QR Code modal elements missing.');
                }
            } else if (target.classList.contains('delete-pin-btn')) {
                const pinId = target.dataset.pinId;
                const resourceId = target.dataset.resourceId;

                if (!confirm(`Are you sure you want to delete PIN ID ${pinId}?`)) return;

                const statusEl = document.getElementById('resource-pin-form-status');
                showLoading(statusEl, 'Deleting PIN...');

                try {
                    const responseData = await apiCall(`/api/resources/${resourceId}/pins/${pinId}`, {
                        method: 'DELETE'
                    }, statusEl);

                    showSuccess(statusEl, responseData.message || 'PIN deleted successfully.');

                    if (typeof loadResourcePins === 'function' && currentResourceIdForPins) {
                        await loadResourcePins(currentResourceIdForPins);
                    } else {
                        target.closest('tr').remove();
                        const pinsTableBody = document.querySelector('#resource-pins-table tbody');
                        if (pinsTableBody && pinsTableBody.children.length === 0) {
                            pinsTableBody.innerHTML = '<tr><td colspan="5">No PINs found for this resource.</td></tr>';
                        }
                        const currentPinValueSpan = document.getElementById('current-pin-value');
                        if (currentPinValueSpan) {
                             currentPinValueSpan.textContent = responseData.resource_current_pin || 'N/A';
                        }
                    }
                } catch (error) {
                }
            }
        });
        console.log('[EVENT_LISTENER_DEBUG] Click listener supposedly ADDED to pinsTable.');
    } else {
        console.error('[EVENT_LISTENER_DEBUG] pinsTable element NOT FOUND. Cannot add click listener.');
    }
    */
});
