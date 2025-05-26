document.addEventListener('DOMContentLoaded', function() {
    const statusDiv = document.getElementById('resource-management-status');
    const tableBody = document.querySelector('#resources-table tbody');
    const addBtn = document.getElementById('add-new-resource-btn');
    const resourceFormModal = document.getElementById('resource-form-modal');
    const closeModalBtn = resourceFormModal ? resourceFormModal.querySelector('.close-modal-btn') : null;
    const resourceForm = document.getElementById('resource-form');
    const resourceFormModalTitle = document.getElementById('resource-form-modal-title');
    const resourceFormStatus = document.getElementById('resource-form-modal-status');
    const resourceIdInput = document.getElementById('resource-id');
    const resourceNameInput = document.getElementById('resource-name');
    const resourceCapacityInput = document.getElementById('resource-capacity');
    const resourceEquipmentInput = document.getElementById('resource-equipment');

    async function fetchAndDisplayResources() {
        showLoading(statusDiv, 'Fetching resources...');
        try {
            const resources = await apiCall('/api/admin/resources');
            tableBody.innerHTML = '';
            if (resources && resources.length > 0) {
                resources.forEach(r => {
                    const row = tableBody.insertRow();
                    row.insertCell().textContent = r.id;
                    row.insertCell().textContent = r.name;
                    row.insertCell().textContent = r.status || 'draft';
                    row.insertCell().textContent = r.capacity !== null && r.capacity !== undefined ? r.capacity : '';
                    const actionsCell = row.insertCell();
                    actionsCell.innerHTML = `
                        <button class="button edit-resource-btn" data-id="${r.id}">Edit</button>
                        <button class="button danger delete-resource-btn" data-id="${r.id}" data-name="${r.name}">Delete</button>
                    `;
                });
                hideMessage(statusDiv);
            } else {
                tableBody.innerHTML = '<tr><td colspan="5">No resources found.</td></tr>';
                showSuccess(statusDiv, 'No resources to display.');
            }
        } catch (error) {
            showError(statusDiv, `Error fetching resources: ${error.message}`);
        }
    }

    addBtn.addEventListener('click', function() {
        resourceForm.reset();
        resourceIdInput.value = '';
        resourceFormModalTitle.textContent = 'Add New Resource';
        hideMessage(resourceFormStatus);
        resourceFormModal.style.display = 'block';
    });

    closeModalBtn && closeModalBtn.addEventListener('click', () => resourceFormModal.style.display = 'none');
    window.addEventListener('click', e => { if (e.target === resourceFormModal) resourceFormModal.style.display = 'none'; });

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
            equipment: resourceEquipmentInput.value
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

    fetchAndDisplayResources();
});
