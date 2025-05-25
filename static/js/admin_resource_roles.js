// Make functions global for now, assuming script.js and admin_resource_edit.js can call them.
window.allAvailableRolesCache = null;

async function fetchAllRolesForResourceForms() {
    if (window.allAvailableRolesCache) {
        return window.allAvailableRolesCache;
    }
    try {
        // Assumes apiCall is globally available from script.js
        const roles = await apiCall('/api/admin/roles');
        window.allAvailableRolesCache = roles || []; // Ensure it's an array
        return window.allAvailableRolesCache;
    } catch (error) {
        console.error('Failed to load roles for resource forms:', error);
        // Optionally display an error in a shared status element if one exists and is known
        window.allAvailableRolesCache = []; // Prevent repeated attempts on error
        return [];
    }
}

async function populateRolesCheckboxes(containerElementId, assignedRoleIds = []) {
    const containerElement = document.getElementById(containerElementId);
    if (!containerElement) {
        console.error('Role checkbox container not found:', containerElementId);
        return;
    }
    // Assumes showLoading is global or we add a simple text message
    containerElement.innerHTML = '<small>Loading roles...</small>'; 
    
    const roles = await fetchAllRolesForResourceForms();
    containerElement.innerHTML = ''; // Clear previous content

    if (!roles || roles.length === 0) {
        containerElement.innerHTML = '<small>No roles found or failed to load roles.</small>';
        return;
    }

    roles.forEach(role => {
        const checkboxDiv = document.createElement('div');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `role-${containerElementId}-${role.id}`; // Unique ID for checkbox
        checkbox.value = role.id;
        checkbox.dataset.roleName = role.name; // Store name for easier access if needed
        
        // Ensure assignedRoleIds are numbers for comparison
        const numericAssignedRoleIds = assignedRoleIds.map(id => parseInt(id, 10));
        if (numericAssignedRoleIds.includes(role.id)) {
            checkbox.checked = true;
        }
        
        const label = document.createElement('label');
        label.htmlFor = `role-${containerElementId}-${role.id}`;
        label.textContent = `${role.name} (ID: ${role.id})`;
        
        checkboxDiv.appendChild(checkbox);
        checkboxDiv.appendChild(label);
        containerElement.appendChild(checkboxDiv);
    });
}

function getSelectedRoleIds(containerElementId) {
    const containerElement = document.getElementById(containerElementId);
    if (!containerElement) return [];
    
    const selectedIds = [];
    containerElement.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        selectedIds.push(parseInt(cb.value, 10));
    });
    return selectedIds;
}

// Expose functions to be called from other scripts
window.populateRolesCheckboxesForResource = populateRolesCheckboxes;
window.getSelectedRoleIdsForResource = getSelectedRoleIds;

// Initialize roles cache on load, if desired, or let it be lazy-loaded
document.addEventListener('DOMContentLoaded', function() {
    fetchAllRolesForResourceForms(); // Pre-fetch roles
});
