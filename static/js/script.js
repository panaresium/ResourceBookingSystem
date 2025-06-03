// JavaScript for Smart Resource Booking

// --- Global Helper Functions ---

/**
 * Shows a loading message.
 * @param {HTMLElement} element - The HTML element to display the loading message in.
 * @param {string} message - The loading message.
 */
function showLoading(element, message = "Loading...") {
    if (element) {
        element.textContent = message;
        element.style.color = 'inherit';
        element.classList.remove('success', 'error');
        element.style.display = 'block';
    }
}

/**
 * Shows a success message.
 * @param {HTMLElement} element - The HTML element to display the success message in.
 * @param {string} message - The success message.
 */
function showSuccess(element, message) {
    if (element) {
        element.innerHTML = message; // Use innerHTML to support <br> tags
        element.style.color = '';
        element.classList.add('success');
        element.classList.remove('error');
        element.style.display = 'block';
    }
}

/**
 * Shows an error message.
 * @param {HTMLElement} element - The HTML element to display the error message in.
 * @param {string} message - The error message.
 */
function showError(element, message) {
    if (element) {
        element.textContent = message;
        element.style.color = '';
        element.classList.add('error');
        element.classList.remove('success');
        element.style.display = 'block';
    }
}

/**
 * Hides a message element.
 * @param {HTMLElement} element - The HTML element to hide.
 */
function hideMessage(element) {
    if (element) {
        element.style.display = 'none';
        element.textContent = '';
    }
}

/**
 * Parses a comma-separated list of role IDs from a data attribute.
 * Returns an array of objects with numeric id properties.
 * @param {string} roleIdsStr - Comma separated role IDs.
 * @returns {Array<{id:number}>}
 */
function parseRolesFromDataset(roleIdsStr) {
    if (!roleIdsStr) return [];
    return roleIdsStr.split(',').filter(id => id.trim() !== '').map(id => ({ id: parseInt(id, 10) })).filter(r => !isNaN(r.id));
}

/**
 * Standardized API call helper function.
 * @param {string} url - The URL to fetch.
 * @param {object} options - Fetch options (method, headers, body, etc.).
 * @param {HTMLElement} [messageElement=null] - Element to display success/error messages.
 * @returns {Promise<object>} - The JSON response data.
 * @throws {Error} - Throws an error if the API call fails or returns a non-ok response.
 */
async function apiCall(url, options = {}, messageElement = null) {
    if (messageElement) showLoading(messageElement, 'Processing...');

    options.credentials = options.credentials || 'same-origin';
    const protectedMethods = ['POST', 'PUT', 'DELETE', 'PATCH'];
    const method = options.method ? options.method.toUpperCase() : 'GET';

    if (protectedMethods.includes(method)) {
        const csrfTokenTag = document.querySelector('meta[name="csrf-token"]');
        let csrfToken = csrfTokenTag ? csrfTokenTag.content : null;
        if (csrfToken) {
            if (!options.headers) options.headers = {};
            if (!options.headers['Content-Type'] && (method === 'POST' || method === 'PUT' || method === 'PATCH') && options.body) {
                options.headers['Content-Type'] = 'application/json';
            }
            options.headers['X-CSRFToken'] = csrfToken;
        } else {
            console.warn('CSRF token not found for a protected HTTP method.');
        }
    }

    try {
        const response = await fetch(url, options);
        let responseData;
        try {
            responseData = await response.json();
        } catch (e) {
            if (!response.ok) {
                const errorText = `API Error: ${response.status} - ${response.statusText || 'Server error, response not JSON.'}`;
                if (messageElement) showError(messageElement, errorText);
                throw new Error(errorText);
            }
            responseData = { success: true, message: response.statusText || "Operation successful (no content)." };
        }

        if (!response.ok) {
            const errorMsg = responseData.error || responseData.message || `HTTP error! status: ${response.status}`;
            if (messageElement) showError(messageElement, errorMsg);
            throw new Error(errorMsg);
        }
        
        if (messageElement && responseData.message && response.ok) {
             showSuccess(messageElement, responseData.message);
        } else if (messageElement && !responseData.error) {
            hideMessage(messageElement); 
        }
        return responseData;

    } catch (error) {
        console.error(`Error during API call to ${url}:`, error);
        if (messageElement) {
            showError(messageElement, error.message || "Request failed. Please check your connection.");
        }
        throw error;
    }
}

// --- Authentication Logic ---
async function updateAuthLink() {
    // ... (Keep existing updateAuthLink function as is) ...
    if (sessionStorage.getItem('explicitlyLoggedOut') === 'true') {
        setStateLoggedOut();
        return;
    }
    const userPerformedLoginActionBeforeApiCall = sessionStorage.getItem('userPerformedLoginAction');

    const authLinkContainer = document.getElementById('auth-link-container');
    const adminMapsNavLink = document.getElementById('admin-maps-nav-link');
    const resourceManagementNavLink = document.getElementById('resource-management-nav-link');
    const userManagementNavLink = document.getElementById('user-management-nav-link');
    const adminMenuItem = document.getElementById('admin-menu-item');
    const manualBackupNavLink = document.getElementById('manual-backup-nav-link');
    const welcomeMessageContainer = document.getElementById('welcome-message-container');
    const userDropdownContainer = document.getElementById('user-dropdown-container');
    const userDropdownButton = document.getElementById('user-dropdown-button');
    const userDropdownMenu = document.getElementById('user-dropdown-menu');
    const logoutLinkDropdown = document.getElementById('logout-link-dropdown');
    const myBookingsNavLink = document.getElementById('my-bookings-nav-link'); 
    const analyticsNavLink = document.getElementById('analytics-nav-link');
    const adminBookingsNavLink = document.getElementById('admin-bookings-nav-link');
    const backupRestoreNavLink = document.getElementById('backup-restore-nav-link'); // Added
    const troubleshootingNavLink = document.getElementById('troubleshooting-nav-link');
    const bookingSettingsNavLink = document.getElementById('booking-settings-nav-link'); // Added for Booking Settings
    const sidebar = document.getElementById('sidebar'); // Added for sidebar visibility
    const sidebarToggleBtn = document.getElementById('sidebar-toggle'); // Added for toggle button visibility

    const loginUrl = document.body.dataset.loginUrl || '/login';

    function setStateLoggedOut() {
        const localSidebar = document.getElementById('sidebar'); // Ensure access within function
        const localSidebarToggleBtn = document.getElementById('sidebar-toggle'); // Ensure access
        const localBackupRestoreNavLink = document.getElementById('backup-restore-nav-link'); // Added for this scope
        const localTroubleshootingNavLink = document.getElementById('troubleshooting-nav-link');
        const localBookingSettingsNavLink = document.getElementById('booking-settings-nav-link'); // Added for Booking Settings

        sessionStorage.removeItem('loggedInUserUsername');
        sessionStorage.removeItem('loggedInUserIsAdmin');
        sessionStorage.removeItem('loggedInUserId');

        if (welcomeMessageContainer) {
            welcomeMessageContainer.textContent = '';
            welcomeMessageContainer.style.display = 'none';
        }
        if (userDropdownContainer) userDropdownContainer.style.display = 'none';
        if (userDropdownMenu) userDropdownMenu.style.display = 'none';

        if (authLinkContainer) {
            authLinkContainer.innerHTML = `<a href="${loginUrl}">Login</a>`;
            authLinkContainer.style.display = 'list-item';
        }
        if (adminMapsNavLink) adminMapsNavLink.style.display = 'none';
        if (resourceManagementNavLink) resourceManagementNavLink.style.display = 'none';
        if (userManagementNavLink) userManagementNavLink.style.display = 'none';
        if (adminMenuItem) adminMenuItem.style.display = 'none';
        if (manualBackupNavLink) manualBackupNavLink.style.display = 'none';
        if (myBookingsNavLink) myBookingsNavLink.style.display = 'none'; 
        if (analyticsNavLink) analyticsNavLink.style.display = 'none';
        if (adminBookingsNavLink) adminBookingsNavLink.style.display = 'none';
        if (localBackupRestoreNavLink) localBackupRestoreNavLink.style.display = 'none'; // Added
        if (localTroubleshootingNavLink) localTroubleshootingNavLink.style.display = 'none';
        if (localBookingSettingsNavLink) localBookingSettingsNavLink.style.display = 'none'; // Added for Booking Settings

        if (localSidebar) localSidebar.style.display = 'none';
        if (localSidebarToggleBtn) localSidebarToggleBtn.style.display = 'none';
        document.body.classList.add('no-sidebar');
        document.body.classList.remove('sidebar-collapsed');
    }

    try {
        const data = await apiCall('/api/auth/status'); 

        if (data.logged_in && data.user) {
            if (userPerformedLoginActionBeforeApiCall !== 'true') {
                sessionStorage.setItem('userPerformedLoginAction', 'true');
            }

            sessionStorage.setItem('loggedInUserUsername', data.user.username);
            sessionStorage.setItem('loggedInUserIsAdmin', data.user.is_admin ? 'true' : 'false');
            sessionStorage.setItem('loggedInUserId', data.user.id);
            sessionStorage.removeItem('explicitlyLoggedOut'); 
            sessionStorage.removeItem('autoLoggedOutDueToStartupSession');

            if (welcomeMessageContainer) {
                welcomeMessageContainer.textContent = `Welcome, ${data.user.username}!`;
                welcomeMessageContainer.style.display = 'list-item';
            }

            if (userDropdownContainer) userDropdownContainer.style.display = 'list-item';
            if (userDropdownButton) {
                userDropdownButton.innerHTML = `<span class="user-icon">&#x1F464;</span><span class="dropdown-arrow"> &#9662;</span>`;
                userDropdownButton.setAttribute('aria-expanded', 'false');
                userDropdownButton.title = data.user.username;
            }
            if (userDropdownMenu) userDropdownMenu.style.display = 'none'; 
            if (authLinkContainer) authLinkContainer.style.display = 'none';
            if (adminMapsNavLink) {
                adminMapsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (resourceManagementNavLink) {
                resourceManagementNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (userManagementNavLink) {
                userManagementNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (adminMenuItem) {
                adminMenuItem.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (manualBackupNavLink) {
                manualBackupNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (myBookingsNavLink) { 
                myBookingsNavLink.style.display = 'flex'; // Changed from list-item to flex for header
            }
            if (analyticsNavLink) {
                analyticsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none'; // Stays list-item if it's inside admin ul
            }
            if (adminBookingsNavLink) {
                adminBookingsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none'; // Stays list-item
            }
            if (backupRestoreNavLink) { // Added
                backupRestoreNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (troubleshootingNavLink) {
                troubleshootingNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (bookingSettingsNavLink) { // Added for Booking Settings
                bookingSettingsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }

            // Sidebar and body class management based on admin status
            if (data.user.is_admin) {
                if (sidebar) {
                    sidebar.style.display = ''; // Show sidebar (revert to CSS default display)
                    sidebar.classList.remove('collapsed');
                }
                if (sidebarToggleBtn) sidebarToggleBtn.style.display = 'none'; // Hide toggle for admin
                document.body.classList.remove('no-sidebar');
                document.body.classList.remove('sidebar-collapsed');

                // Prevent admin menu details from collapsing
                const adminSectionDetails = document.getElementById('admin-section');
                if (adminSectionDetails) {
                    const adminSectionSummary = adminSectionDetails.querySelector('summary');
                    if (adminSectionSummary) {
                        // Ensure this listener is added only once
                        if (!adminSectionSummary.dataset.clickListenerAdded) {
                            adminSectionSummary.addEventListener('click', function(event) {
                                if (adminSectionDetails.hasAttribute('open')) {
                                    event.preventDefault();
                                }
                            });
                            adminSectionSummary.dataset.clickListenerAdded = 'true';
                        }
                    }
                }
            } else { // Non-admin user
                if (sidebar) sidebar.style.display = 'none';
                if (sidebarToggleBtn) sidebarToggleBtn.style.display = 'none';
                document.body.classList.add('no-sidebar');
                document.body.classList.remove('sidebar-collapsed'); // Ensure this is also removed for non-admins
            }

            if (logoutLinkDropdown) {
                logoutLinkDropdown.removeEventListener('click', handleLogout); 
                logoutLinkDropdown.addEventListener('click', handleLogout);
            }
        } else { 
            setStateLoggedOut();
            if (sessionStorage.getItem('autoLoggedOutDueToStartupSession') === 'true') {
                sessionStorage.removeItem('autoLoggedOutDueToStartupSession');
            }
        }
    } catch (error) {
        setStateLoggedOut();
    }
}

async function handleLogout(event) {
    // ... (Keep existing handleLogout function as is) ...
    try {
        sessionStorage.removeItem('userPerformedLoginAction');
        sessionStorage.removeItem('autoLoggedOutDueToStartupSession'); 

        const responseData = await apiCall('/api/auth/logout', { method: 'POST' });

        console.log("Logout successful from API:", responseData.message || "Logged out");
        sessionStorage.setItem('explicitlyLoggedOut', 'true');
        
        await updateAuthLink(); 

        window.location.href = '/logout';

    } catch (error) {
        sessionStorage.removeItem('userPerformedLoginAction'); 
        sessionStorage.removeItem('autoLoggedOutDueToStartupSession');
        sessionStorage.setItem('explicitlyLoggedOut', 'true');
        console.error('Logout error:', error);
        await updateAuthLink(); 
        window.location.href = '/logout';
    }
}

// --- Home Page: Display Available Resources Now ---
async function displayAvailableResourcesNow() {
    // ... (Keep existing displayAvailableResourcesNow function as is) ...
    const availableResourcesListDiv = document.getElementById('available-resources-now-list');
    if (!availableResourcesListDiv) return; 

    showLoading(availableResourcesListDiv, 'Loading available resources...');

    try {
        const now = new Date();
        const currentDateYMD = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        const currentHour = now.getHours();

        const params = new URLSearchParams();
        const capVal = document.getElementById('filter-capacity');
        const equipVal = document.getElementById('filter-equipment');
        const tagVal = document.getElementById('filter-tags');
        if (capVal && capVal.value) params.append('capacity', capVal.value);
        if (equipVal && equipVal.value) params.append('equipment', equipVal.value);
        if (tagVal && tagVal.value) params.append('tags', tagVal.value);

        const queryString = params.toString() ? `?${params.toString()}` : '';

        const resources = await apiCall(`/api/resources${queryString}`, {}, availableResourcesListDiv);

        if (!resources || resources.length === 0) {
            showSuccess(availableResourcesListDiv, 'No resources found.'); 
            return;
        }

        const availableNowResources = [];
        const availabilityResults = await Promise.allSettled(resources.map(resource => 
            apiCall(`/api/resources/${resource.id}/availability?date=${currentDateYMD}`)
        ));

        resources.forEach((resource, index) => {
            const availabilityResult = availabilityResults[index];
            if (availabilityResult.status === 'fulfilled') {
                const bookedSlots = availabilityResult.value;
                let isBookedThisHour = false;
                if (bookedSlots && bookedSlots.length > 0) {
                    for (const booking of bookedSlots) {
                        const startTimeHour = parseInt(booking.start_time.split(':')[0], 10);
                        const endTimeHour = parseInt(booking.end_time.split(':')[0], 10);
                        if (startTimeHour <= currentHour && currentHour < endTimeHour) {
                            isBookedThisHour = true;
                            break;
                        }
                    }
                }
                if (!isBookedThisHour) {
                    availableNowResources.push(resource.name);
                }
            }
        });

        if (availableNowResources.length === 0) {
            showSuccess(availableResourcesListDiv, 'No resources currently available.');
        } else {
            const ul = document.createElement('ul');
            availableNowResources.forEach(name => {
                const li = document.createElement('li');
                li.textContent = name;
                ul.appendChild(li);
            });
            availableResourcesListDiv.innerHTML = ''; 
            availableResourcesListDiv.appendChild(ul);
        }

    } catch (error) {
        if (!availableResourcesListDiv.classList.contains('error')) {
             showError(availableResourcesListDiv, 'Error fetching available resources. Please try refreshing.');
        }
    }
}

function getTodayDateString() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0'); // Months are 0-indexed
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

// --- Permission Helper Function ---
function checkUserPermissionForResource(resource, currentUserId, currentUserIsAdmin) {
    // ... (Keep existing checkUserPermissionForResource function as is) ...
    if (!resource) return false;
    if (currentUserIsAdmin) return true; 
    if (resource.booking_restriction === 'admin_only') return false;

    let userInAllowedList = false;
    let hasUserIdRestriction = resource.allowed_user_ids && resource.allowed_user_ids.trim() !== "";

    if (hasUserIdRestriction) {
        const allowedIds = resource.allowed_user_ids.split(',').map(idStr => parseInt(idStr.trim(), 10));
        if (allowedIds.includes(currentUserId)) {
            userInAllowedList = true;
            return true; 
        }
    }

    let hasRoleRestriction = resource.roles && Array.isArray(resource.roles) && resource.roles.length > 0;
    
    if (hasRoleRestriction) return true; 
    if (!hasUserIdRestriction && !hasRoleRestriction) return true;
    if (hasUserIdRestriction && !userInAllowedList && !hasRoleRestriction) return false;
    return true; 
}


document.addEventListener('DOMContentLoaded', function() {
    document.body.dataset.loginUrl = document.getElementById('login-form') ? "#" : "/login";
    updateAuthLink();

    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle'); // Already declared as sidebarToggleBtn in updateAuthLink scope
    if (sidebar && sidebarToggle) { // sidebar is already declared in DOMContentLoaded scope
        sidebarToggle.addEventListener('click', function() {
            // Only toggle if the sidebar is supposed to be visible (i.e., for admins)
            if (sidebar.style.display !== 'none') {
                sidebar.classList.toggle('collapsed');
                document.body.classList.toggle('sidebar-collapsed');
            }
        });
    }

    const bookingForm = document.getElementById('booking-form');
    const bookingResultsDiv = document.getElementById('booking-results');
    const loginForm = document.getElementById('login-form');
    const loginMessageDiv = document.getElementById('login-message');
    const manualBackupBtn = document.getElementById('manual-backup-btn');

    // --- New Booking Page Specific Logic ---
    if (bookingForm) {
        // ... (Keep existing bookingForm related logic as is) ...
        const resourceSelectBooking = document.getElementById('resource-select-booking');
        const newBookingMessageDiv = document.getElementById('new-booking-message'); 

        if (resourceSelectBooking) {
            apiCall('/api/resources', {}, newBookingMessageDiv)
                .then(data => {
                    resourceSelectBooking.innerHTML = '<option value="">-- Select a Resource --</option>';
                    if (!data || data.length === 0) {
                        const option = new Option('No resources available', '');
                        option.disabled = true;
                        resourceSelectBooking.add(option);
                        if (newBookingMessageDiv) showSuccess(newBookingMessageDiv, 'No resources available to book.');
                        return;
                    }
                    data.forEach(resource => {
                        const option = new Option(
                           `${resource.name} (Capacity: ${resource.capacity || 'N/A'})`, 
                           resource.id
                        );
                        option.dataset.resourceName = resource.name; 
                        resourceSelectBooking.add(option);
                    });
                    if (newBookingMessageDiv) hideMessage(newBookingMessageDiv);
                })
                .catch(error => {
                    resourceSelectBooking.innerHTML = '<option value="">Error loading resources</option>';
                    if (newBookingMessageDiv && !newBookingMessageDiv.classList.contains('error')) {
                        showError(newBookingMessageDiv, 'Failed to load resources for booking.');
                    }
                });
        }

        const quickTimeOptions = document.querySelectorAll('input[name="quick_time_option"]');
        const manualTimeInputsDiv = document.getElementById('manual-time-inputs');
        const startTimeInput = document.getElementById('start-time');
        const endTimeInput = document.getElementById('end-time');
        const recurrenceToggle = document.getElementById('enable-recurrence');
        const recurrenceSelect = document.getElementById('recurrence-rule');

        if (recurrenceToggle && recurrenceSelect) {
            recurrenceSelect.disabled = !recurrenceToggle.checked;
            recurrenceToggle.addEventListener('change', function() {
                recurrenceSelect.disabled = !this.checked;
                if (!this.checked) {
                    recurrenceSelect.value = '';
                }
            });
        }

        quickTimeOptions.forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.checked) {
                    // The values "09:00-13:00", "13:00-17:00", "09:00-17:00" are now directly set
                    // from the HTML. This JS logic might only be needed if "manual" is an option.
                    // For now, assuming the new HTML values directly drive the form.
                    // If manual time entry needs to be re-enabled, this switch would need adjustment.
                    if (manualTimeInputsDiv) {
                         manualTimeInputsDiv.style.display = (this.value === 'manual') ? 'block' : 'none';
                    }
                    // If specific start/end times need to be set from these values:
                    if (this.value !== 'manual' && startTimeInput && endTimeInput) {
                        const parts = this.value.split('-');
                        if (parts.length === 2) {
                            startTimeInput.value = parts[0];
                            endTimeInput.value = parts[1];
                        }
                    }
                }
            });
        });
        
        // Trigger change for the initially checked quick time option
        const initiallyCheckedQuickTime = document.querySelector('input[name="quick_time_option"]:checked');
        if (initiallyCheckedQuickTime) {
            initiallyCheckedQuickTime.dispatchEvent(new Event('change'));
        }


        bookingForm.addEventListener('submit', async function(event) {
            event.preventDefault(); 
            if (bookingResultsDiv) {
                bookingResultsDiv.innerHTML = ''; 
                bookingResultsDiv.className = ''; 
            }
            const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
            if (!loggedInUsername) {
                if (bookingResultsDiv) {
                    bookingResultsDiv.innerHTML = `<p>Please <a href="${document.body.dataset.loginUrl || '/login'}">login</a> to book a resource.</p>`;
                    bookingResultsDiv.classList.add('error');
                }
                return; 
            }

            const resourceId = resourceSelectBooking ? resourceSelectBooking.value : '';
            const dateValue = document.getElementById('booking-date') ? document.getElementById('booking-date').value : '';
            
            // Determine start and end times from the selected quick time option
            const checkedQuickTimeOption = document.querySelector('input[name="quick_time_option"]:checked');
            let startTimeValue = '';
            let endTimeValue = '';

            if (checkedQuickTimeOption && checkedQuickTimeOption.value !== 'manual') {
                const timeParts = checkedQuickTimeOption.value.split('-');
                if (timeParts.length === 2) {
                    startTimeValue = timeParts[0];
                    endTimeValue = timeParts[1];
                }
            } else if (checkedQuickTimeOption && checkedQuickTimeOption.value === 'manual') {
                // This case is currently removed from HTML, but if re-added:
                startTimeValue = startTimeInput ? startTimeInput.value : '';
                endTimeValue = endTimeInput ? endTimeInput.value : '';
            }


            const recurrenceValue = recurrenceSelect ? recurrenceSelect.value : '';
            let titleValue = 'User Booking'; 
            if (resourceSelectBooking && resourceSelectBooking.selectedIndex >= 0 && resourceSelectBooking.value) {
                const selectedOption = resourceSelectBooking.options[resourceSelectBooking.selectedIndex];
                titleValue = `Booking for ${selectedOption.dataset.resourceName || selectedOption.text.split(' (Capacity:')[0]}`;
            }

            if (!resourceId) {
                showError(bookingResultsDiv, 'Please select a resource.');
                return;
            }
            if (!dateValue || !startTimeValue || !endTimeValue) {
                showError(bookingResultsDiv, 'Please fill in date and select a valid time option.');
                return;
            }
            
            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateValue,
                start_time_str: startTimeValue,
                end_time_str: endTimeValue,
                title: titleValue,
                user_name: loggedInUsername, 
                recurrence_rule: recurrenceValue
            };

            try {
                const responseData = await apiCall('/api/bookings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                }, bookingResultsDiv); 

                const created = responseData.bookings || [responseData];
                let resourceName = 'N/A';
                if (resourceSelectBooking && resourceSelectBooking.selectedIndex !== -1) {
                    const selectedOption = resourceSelectBooking.options[resourceSelectBooking.selectedIndex];
                    resourceName = selectedOption.dataset.resourceName || selectedOption.text.split(' (Capacity:')[0];
                }

                const first = created[0];
                const displayDate = first.start_time ? first.start_time.split(' ')[0] : 'N/A';
                const displayStartTime = first.start_time ? first.start_time.split(' ')[1].substring(0,5) : 'N/A';
                const displayEndTime = first.end_time ? first.end_time.split(' ')[1].substring(0,5) : 'N/A';
                const displayTitle = first.title || 'N/A';
                const displayBookingId = first.id || 'N/A';

                const successHtml = `
                    <p><strong>Booking Confirmed!</strong><br>
                    Resource: ${resourceName}<br>
                    Date: ${displayDate}<br>
                    Time: ${displayStartTime} - ${displayEndTime}<br>
                    Title: ${displayTitle}<br>
                    Booking ID: ${displayBookingId}<br>
                    Created: ${created.length} booking(s)</p>
                `;
                if (bookingResultsDiv) { 
                    bookingResultsDiv.innerHTML = successHtml; 
                    bookingResultsDiv.className = 'success'; 
                    bookingResultsDiv.style.display = 'block'; 
                }

                bookingForm.reset(); 
                const defaultQuickTime = document.querySelector('input[name="quick_time_option"][value="09:00-13:00"]');
                if(defaultQuickTime) {
                    defaultQuickTime.checked = true;
                    defaultQuickTime.dispatchEvent(new Event('change'));
                }
                if (recurrenceToggle && recurrenceSelect) {
                    recurrenceToggle.checked = false;
                    recurrenceSelect.disabled = true;
                    recurrenceSelect.value = '';
                }
            } catch (error) {
                console.error('Booking submission failed:', error.message);
            }
        });
    }

    if (loginForm) {
        // ... (Keep existing loginForm related logic as is) ...
        loginForm.addEventListener('submit', async function(event) {
            event.preventDefault();
    
            const usernameInput = document.getElementById('username'); 
            const passwordInput = document.getElementById('password'); 
            const username = usernameInput.value.trim();
            const password = passwordInput.value; 
    
            if (!username || !password) {
                showError(loginMessageDiv, 'Username and password are required.');
                return;
            }
    
            try {
                const responseData = await apiCall('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                }, loginMessageDiv);

                showSuccess(loginMessageDiv, responseData.message || 'Login successful!');
    
                if (responseData.user) {
                    sessionStorage.setItem('loggedInUserUsername', responseData.user.username);
                    sessionStorage.setItem('loggedInUserIsAdmin', responseData.user.is_admin ? 'true' : 'false');
                    sessionStorage.setItem('loggedInUserId', responseData.user.id);
                } else {
                    sessionStorage.setItem('loggedInUserUsername', username);
                    sessionStorage.removeItem('loggedInUserIsAdmin');
                    sessionStorage.removeItem('loggedInUserId');
                }
                sessionStorage.setItem('userPerformedLoginAction', 'true');
                sessionStorage.removeItem('explicitlyLoggedOut');
                sessionStorage.removeItem('autoLoggedOutDueToStartupSession');
                
                await updateAuthLink(); 
                
                setTimeout(() => {
                    window.location.href = '/'; 
                }, 500); 
    
            } catch (error) {
                sessionStorage.removeItem('loggedInUserUsername');
                sessionStorage.removeItem('loggedInUserIsAdmin');
                sessionStorage.removeItem('loggedInUserId');
                console.error('Login attempt failed:', error.message);
            }
        });
    }

    const googleLoginBtn = document.getElementById('google-login-btn');
    if (googleLoginBtn) {
        // ... (Keep existing googleLoginBtn related logic as is) ...
        googleLoginBtn.addEventListener('click', function() {
            sessionStorage.setItem('userPerformedLoginAction', 'true');
            sessionStorage.removeItem('explicitlyLoggedOut');
            sessionStorage.removeItem('autoLoggedOutDueToStartupSession');
            window.location.href = '/login/google'; 
        });
    }

    // For resources.html page - Calendar View Logic (existing)
    const roomSelectDropdown = document.getElementById('room-select');
    const availabilityDateInputCalendar = document.getElementById('availability-date'); // Renamed to avoid conflict
    const calendarTable = document.getElementById('calendar-table');
    const resourceImageDisplay = document.getElementById('resource-image-display');

    if (availabilityDateInputCalendar && roomSelectDropdown && calendarTable) {
        // ... (Keep existing calendar view logic for resources.html as is) ...
        availabilityDateInputCalendar.value = getTodayDateString(); 

        async function fetchAndDisplayAvailability(resourceId, dateString, currentResourceDetails) {
            const calendarStatusMessageDiv = document.getElementById('calendar-status-message'); 
            if (!resourceId) {
                clearCalendar();
                if(calendarStatusMessageDiv) hideMessage(calendarStatusMessageDiv);
                return;
            }
            
            try {
                const bookedSlots = await apiCall(
                    `/api/resources/${resourceId}/availability?date=${dateString}`, 
                    {}, 
                    calendarStatusMessageDiv 
                );

                let currentUserDailyBookings = [];
                const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
                if (loggedInUsername) {
                    try {
                        // Fetch current user's bookings for the given date to check for overlaps on other resources
                        currentUserDailyBookings = await apiCall(
                            `/api/bookings/my_bookings_for_date?date=${dateString}`,
                            {},
                            null // Or calendarStatusMessageDiv if messages are desired for this secondary call
                        );
                    } catch (userBookingError) {
                        console.warn(`Could not fetch current user's bookings for ${dateString}:`, userBookingError.message);
                        // Non-critical, proceed with empty currentUserDailyBookings
                    }
                }
                // Pass currentResourceDetails as the third argument and currentUserDailyBookings as the fourth
                updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails, currentUserDailyBookings);
            } catch (error) {
                console.error(`Error fetching availability for resource ${resourceId} on ${dateString}:`, error.message);
                clearCalendar(true); 
            }
        }

        function handleAvailableSlotClick(event, resourceId, dateString) {
            const cell = event.target;
            const timeSlot = cell.dataset.timeSlot; 

            if (!timeSlot) return;

            const loggedInUsername = sessionStorage.getItem('loggedInUserUsername'); // Corrected key
            if (!loggedInUsername) {
                alert("Please login to book a resource.");
                return;
            }

            const bookingTitle = prompt(`Book slot ${timeSlot} on ${dateString} for resource ID ${resourceId}?\nEnter a title for your booking (optional):`);

            if (bookingTitle === null) return;

            const [startTimeStr, endTimeStr] = timeSlot.split('-');
            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateString,
                start_time_str: startTimeStr,
                end_time_str: endTimeStr,
                title: bookingTitle,
                user_name: loggedInUsername // Corrected key
            };
            makeBookingApiCall(bookingData); 
        }

        async function makeBookingApiCall(bookingData) { 
            const calendarStatusMessageDiv = document.getElementById('calendar-status-message');
            try {
                const responseData = await apiCall('/api/bookings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                }, calendarStatusMessageDiv);

                alert(`Booking successful! Title: ${responseData.title || 'Untitled'} (ID: ${responseData.id})`);
                
                if (roomSelectDropdown.value && availabilityDateInputCalendar.value) {
                     const selectedOption = roomSelectDropdown.selectedOptions[0];
                    const currentResourceDetails = {
                        id: roomSelectDropdown.value,
                        name: selectedOption.dataset.resourceName || selectedOption.textContent.split(' (ID:')[0],
                        booking_restriction: selectedOption.dataset.bookingRestriction,
                        allowed_user_ids: selectedOption.dataset.allowedUserIds,
                        roles: parseRolesFromDataset(selectedOption.dataset.roleIds)
                     };
                    fetchAndDisplayAvailability(
                        roomSelectDropdown.value,
                        availabilityDateInputCalendar.value,
                        currentResourceDetails 
                    );
                }
                if(calendarStatusMessageDiv) showSuccess(calendarStatusMessageDiv, `Booking for '${responseData.title || 'Untitled'}' (ID: ${responseData.id}) confirmed.`);

            } catch (error) {
                alert(`Booking failed: ${error.message}. Check messages above calendar.`);
            }
        }

        function updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails, currentUserDailyBookings = []) {
            const calendarCells = calendarTable.querySelectorAll('tbody td[data-time-slot]');
            const currentUserId = parseInt(sessionStorage.getItem('loggedInUserId'), 10);
            const currentUserIsAdmin = sessionStorage.getItem('loggedInUserIsAdmin') === 'true';

            calendarCells.forEach(currentCell => {
                let cell = currentCell;
                let isBooked = false;
                let cellIsClickable = true;
                let cellText = 'Available';
                let cellClass = 'available';

                const cellTimeSlot = cell.dataset.timeSlot;
                if (!cellTimeSlot) return;

                const [cellStartTimeStr, cellEndTimeStr] = cellTimeSlot.split('-');
                const [sH, sM] = cellStartTimeStr.split(':').map(Number);
                const [eH, eM] = cellEndTimeStr.split(':').map(Number);

                const cellStartDateTime = new Date(`${dateString}T${String(sH).padStart(2, '0')}:${String(sM).padStart(2, '0')}:00`);
                const cellEndDateTime = new Date(`${dateString}T${String(eH).padStart(2, '0')}:${String(eM).padStart(2, '0')}:00`);

                for (const bookedSlot of bookedSlots) {
                    const [bSH, bSM, bSS] = bookedSlot.start_time.split(':').map(Number);
                    const [bEH, bEM, bESS] = bookedSlot.end_time.split(':').map(Number);
                    const bookedStartDateTime = new Date(`${dateString}T${String(bSH).padStart(2, '0')}:${String(bSM).padStart(2, '0')}:${String(bSS).padStart(2, '0')}`);
                    const bookedEndDateTime = new Date(`${dateString}T${String(bEH).padStart(2, '0')}:${String(bEM).padStart(2, '0')}:${String(bESS).padStart(2, '0')}`);
                    if (bookedStartDateTime < cellEndDateTime && bookedEndDateTime > cellStartDateTime) {
                        isBooked = true;
                        cellText = `Booked (${bookedSlot.title || 'Event'})`;
                        cellClass = 'booked';
                        cellIsClickable = false;
                        break;
                    }
                }

                if (!isBooked && currentResourceDetails) {
                    if (!checkUserPermissionForResource(currentResourceDetails, currentUserId, currentUserIsAdmin)) {
                        cellClass = 'unavailable-permission'; 
                        cellText = 'Restricted'; 
                        cellIsClickable = false;
                    }
                }

                // New check: If the slot is still available for the current resource,
                // check if the user has another booking elsewhere at this time.
                if (cellIsClickable && currentUserDailyBookings && currentUserDailyBookings.length > 0) {
                    for (const userBooking of currentUserDailyBookings) {
                        // userBooking times are 'HH:MM:SS'
                        const [u_sH, u_sM] = userBooking.start_time.split(':').map(Number);
                        const [u_eH, u_eM] = userBooking.end_time.split(':').map(Number);

                        // Create Date objects for comparison, using the cell's date part
                        const userBookingStartDateTime = new Date(cellStartDateTime);
                        userBookingStartDateTime.setHours(u_sH, u_sM, 0, 0); // Set hours, minutes, seconds, ms
                        const userBookingEndDateTime = new Date(cellStartDateTime);
                        userBookingEndDateTime.setHours(u_eH, u_eM, 0, 0);

                        // Check for overlap
                        if (userBookingStartDateTime < cellEndDateTime && userBookingEndDateTime > cellStartDateTime) {
                            // User has an overlapping booking on another resource
                            cellClass = 'booked'; // Mark as booked (or a new class like 'user-booked-elsewhere')
                            cellText = `Booked (${userBooking.resource_name})`; // Indicate the conflict
                            cellIsClickable = false;
                            break; // Found a conflict for this cell, no need to check further user bookings
                        }
                    }
                }
                
                let new_cell = cell.cloneNode(false); 
                new_cell.textContent = cellText; 
                new_cell.className = cellClass;  
                new_cell.dataset.timeSlot = cellTimeSlot; 
                cell.parentNode.replaceChild(new_cell, cell);
                cell = new_cell; // Re-assign cell to the new cloned node

                if (cellIsClickable) { 
                    cell.addEventListener('click', (event) => {
                        // Ensure currentResourceDetails is correctly passed or retrieved for handleAvailableSlotClick
                        const currentResourceIdFromDropdown = currentResourceDetails ? currentResourceDetails.id : roomSelectDropdown.value;
                        const currentDateStringFromPicker = availabilityDateInputCalendar.value;
                        handleAvailableSlotClick(event, currentResourceIdFromDropdown, currentDateStringFromPicker);
                    });
                }
            });
        }

        function clearCalendar(isError = false) {
             const calendarCells = calendarTable.querySelectorAll('tbody td[data-time-slot]');
             calendarCells.forEach(cell => {
                cell.textContent = isError ? 'Error' : '-';
                cell.className = isError ? 'error-slot' : 'unavailable'; 
             });
        }

        roomSelectDropdown.addEventListener('change', () => {
            const selectedOption = roomSelectDropdown.selectedOptions[0];
            if (!selectedOption) return; 
            if (resourceImageDisplay) {
                const url = selectedOption.dataset.imageUrl;
                if (url) {
                    resourceImageDisplay.src = url;
                    resourceImageDisplay.style.display = 'block';
                } else {
                    resourceImageDisplay.style.display = 'none';
                }
            }
            const currentResourceDetails = {
                id: roomSelectDropdown.value,
                booking_restriction: selectedOption.dataset.bookingRestriction,
                allowed_user_ids: selectedOption.dataset.allowedUserIds,
                roles: parseRolesFromDataset(selectedOption.dataset.roleIds)
            };
            fetchAndDisplayAvailability(currentResourceDetails.id, availabilityDateInputCalendar.value, currentResourceDetails);
        });

        availabilityDateInputCalendar.addEventListener('change', () => {
            const selectedOption = roomSelectDropdown.selectedOptions[0];
            if (!selectedOption) return; 
            const currentResourceDetails = {
                id: roomSelectDropdown.value,
                booking_restriction: selectedOption.dataset.bookingRestriction,
                allowed_user_ids: selectedOption.dataset.allowedUserIds,
                roles: parseRolesFromDataset(selectedOption.dataset.roleIds)
            };
            fetchAndDisplayAvailability(currentResourceDetails.id, availabilityDateInputCalendar.value, currentResourceDetails);
        });

        const calendarStatusMessageDiv = document.getElementById('calendar-status-message');
        if (roomSelectDropdown && availabilityDateInputCalendar && calendarTable && calendarStatusMessageDiv) { 
            apiCall('/api/resources', {}, calendarStatusMessageDiv)
                .then(data => {
                    roomSelectDropdown.innerHTML = ''; 
                    if (!data || data.length === 0) {
                        roomSelectDropdown.add(new Option('No rooms available', ''));
                        clearCalendar();
                        showSuccess(calendarStatusMessageDiv, 'No resources available to display.');
                        return;
                    }
                    data.forEach(resource => {
                        const option = new Option(resource.name, resource.id);
                        option.dataset.bookingRestriction = resource.booking_restriction || "";
                        option.dataset.allowedUserIds = resource.allowed_user_ids || "";
                        option.dataset.roleIds = (resource.roles || []).map(r => r.id).join(',');
                        option.dataset.imageUrl = resource.image_url || "";
                        option.dataset.resourceName = resource.name;
                        roomSelectDropdown.add(option);
                    });
                    
                    if (roomSelectDropdown.options.length > 0) {
                        roomSelectDropdown.value = roomSelectDropdown.options[0].value;
                        const selectedOption = roomSelectDropdown.options[0];
                        if (resourceImageDisplay) {
                            const url = selectedOption.dataset.imageUrl;
                            if (url) {
                                resourceImageDisplay.src = url;
                                resourceImageDisplay.style.display = 'block';
                            } else {
                                resourceImageDisplay.style.display = 'none';
                            }
                        }
                        const initialResourceDetails = {
                            id: selectedOption.value,
                            name: selectedOption.dataset.resourceName,
                            booking_restriction: selectedOption.dataset.bookingRestriction,
                            allowed_user_ids: selectedOption.dataset.allowedUserIds,
                            roles: parseRolesFromDataset(selectedOption.dataset.roleIds)
                        };
                        fetchAndDisplayAvailability(initialResourceDetails.id, availabilityDateInputCalendar.value, initialResourceDetails);
                    } else {
                         clearCalendar(); 
                         showSuccess(calendarStatusMessageDiv, 'No resources to display in calendar.');
                    }
                })
                .catch(error => {
                    roomSelectDropdown.innerHTML = '<option value="">Error loading rooms</option>';
                    clearCalendar(true);
                });
        }
        // Removed the floorMapsListUl, floorMapsLoadingStatusDiv, locationFilter, floorFilter related block
    } 


    // --- START: Resources Page - Resource Buttons Grid & Modal ---
    const resourceButtonsContainer = document.getElementById('resource-buttons-container');
    if (resourceButtonsContainer) {
        console.log("Resource buttons page script initializing...");

        // 1. Initial Setup: DOM Elements & Variables
        const availabilityDateInput = document.getElementById('availability-date'); // Date picker for this view
        const resourceLoadingStatusDiv = document.getElementById('resource-loading-status');
        const filterCapacityInput = document.getElementById('resource-filter-capacity');
        const filterEquipmentInput = document.getElementById('resource-filter-equipment');
        const filterTagsInput = document.getElementById('resource-filter-tags');
        const applyFiltersBtn = document.getElementById('resource-apply-filters-btn');
        const clearFiltersBtn = document.getElementById('resource-clear-filters-btn');
        let currentFilters = {};

        // Modal elements (rpbm- prefix)
        const bookingModal = document.getElementById('resource-page-booking-modal');
        const closeModalBtn = document.getElementById('rpbm-close-modal-btn'); // Main (X) close button
        const modalResourceName = document.getElementById('rpbm-resource-name');
        const modalSelectedDate = document.getElementById('rpbm-selected-date');
        const modalResourceImage = document.getElementById('rpbm-resource-image');
        const modalSlotOptionsContainer = document.getElementById('rpbm-slot-options');
        const modalBookingTitle = document.getElementById('rpbm-booking-title');
        const modalConfirmBtn = document.getElementById('rpbm-confirm-booking-btn');
        const modalStatusMsg = document.getElementById('rpbm-status-message');
        const modalAckCloseBtn = document.getElementById('rpbm-ack-close-btn'); // "Close" button after confirmation

        let allFetchedResources = [];
        let currentResourceBookingsCache = {}; // Cache for bookings: { resourceId: [bookings] }
        let countdownInterval = null;
        let selectedSlotDetails = null; // { startTimeStr, endTimeStr }

        if (availabilityDateInput) {
            availabilityDateInput.value = getTodayDateString();
            console.log("Availability date input set to today:", availabilityDateInput.value);
        } else {
            console.error("Resource availability date input not found!");
        }
        
        // Helper function to reset the Resource Page Booking Modal (rpbm)
        function resetRpbmModal() {
            console.log("Resetting RPBM modal state.");
            if (modalConfirmBtn) modalConfirmBtn.style.display = 'inline-block';
            if (modalSlotOptionsContainer) modalSlotOptionsContainer.style.display = 'block'; // Or 'flex' if styled that way
            if (modalBookingTitle && modalBookingTitle.parentElement) modalBookingTitle.parentElement.style.display = 'block';
            if (modalAckCloseBtn) modalAckCloseBtn.style.display = 'none';
            
            if (modalStatusMsg) {
                modalStatusMsg.innerHTML = '';
                modalStatusMsg.className = 'status-message'; // Reset any success/error classes
                hideMessage(modalStatusMsg); // Ensure it's hidden initially
            }
            
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
                console.log("Countdown interval cleared.");
            }
            
            if (modalBookingTitle) modalBookingTitle.value = '';
            selectedSlotDetails = null;

            // Deselect any selected slot buttons
            if (modalSlotOptionsContainer) {
                modalSlotOptionsContainer.querySelectorAll('.time-slot-btn.selected').forEach(btn => {
                    btn.classList.remove('selected');
                });
            }
            console.log("RPBM modal reset complete.");
        }

        function updateGroupVisibility() {
            console.log("Updating group visibility...");
            const allHeadings = document.querySelectorAll('#resource-buttons-container .map-group-heading');
    
            allHeadings.forEach(heading => {
                // A bit fragile if structure changes, but common pattern for heading + content div
                const gridContainer = heading.nextElementSibling; 
    
                if (gridContainer && gridContainer.classList.contains('resource-buttons-grid')) {
                    // More robust check for visibility:
                    // Iterate through buttons and check computed style or explicit style.display !== 'none'
                    let hasVisibleButton = false;
                    const buttonsInGroup = gridContainer.querySelectorAll('.resource-availability-button');
                    for (let i = 0; i < buttonsInGroup.length; i++) {
                        if (buttonsInGroup[i].style.display !== 'none') {
                            hasVisibleButton = true;
                            break;
                        }
                    }
    
                    if (hasVisibleButton) {
                        heading.style.display = ''; // Reset to default (visible)
                        gridContainer.style.display = ''; // Reset to default (visible)
                        console.log(`Group for heading "${heading.textContent}" has visible resources, showing group.`);
                    } else {
                        heading.style.display = 'none';
                        gridContainer.style.display = 'none';
                        console.log(`Group for heading "${heading.textContent}" has NO visible resources, hiding group.`);
                    }
                } else {
                    // console.warn("Could not find grid container for heading:", heading.textContent);
                }
            });
        }

        // 2. fetchAndRenderResources() function
        async function fetchAndRenderResources(filters = {}) {
            // Ensure resourceLoadingStatusDiv is defined in this scope or passed.
            // const resourceLoadingStatusDiv = document.getElementById('resource-loading-status'); 
            if (resourceLoadingStatusDiv) showLoading(resourceLoadingStatusDiv, "Loading resources and maps...");
            else console.warn("resourceLoadingStatusDiv not found for fetchAndRenderResources initial loading message.");

            try {
                const params = new URLSearchParams();
                if (filters.capacity) params.append('capacity', filters.capacity);
                if (filters.equipment) params.append('equipment', filters.equipment);
                if (filters.tags) params.append('tags', filters.tags);
                const query = params.toString() ? `?${params.toString()}` : '';

                const [resourcesResponse, mapsResponse] = await Promise.all([
                    apiCall(`/api/resources${query}`, {}, resourceLoadingStatusDiv),
                    apiCall('/api/maps', {}, resourceLoadingStatusDiv)
                ]);

                allFetchedResources = resourcesResponse || []; 
                const allMaps = mapsResponse || [];

                if (resourceButtonsContainer) resourceButtonsContainer.innerHTML = ''; // Clear previous content

                if (!allFetchedResources || allFetchedResources.length === 0) {
                    if (resourceLoadingStatusDiv) showSuccess(resourceLoadingStatusDiv, "No resources found.");
                    if (resourceButtonsContainer) resourceButtonsContainer.innerHTML = '<p>No resources found.</p>';
                    return;
                }

                const mapsById = {};
                allMaps.forEach(map => { mapsById[map.id] = map; });

                const groupedResources = { unassigned: [] }; 

                allFetchedResources.forEach(resource => {
                    const mapId = resource.floor_map_id;
                    if (mapId && mapsById[mapId]) {
                        if (!groupedResources[mapId]) {
                            groupedResources[mapId] = [];
                        }
                        groupedResources[mapId].push(resource);
                    } else {
                        groupedResources.unassigned.push(resource);
                    }
                });

                let resourcesRenderedInAnyGroup = false;

                allMaps.forEach(map => {
                    if (groupedResources[map.id] && groupedResources[map.id].length > 0) {
                        resourcesRenderedInAnyGroup = true;
                        const mapHeading = document.createElement('h3');
                        let headingText = `Map: ${map.name}`;
                        if (map.location && map.floor) {
                            headingText += ` (${map.location} - Floor ${map.floor})`;
                        } else if (map.location) {
                            headingText += ` (${map.location})`;
                        } else if (map.floor) {
                            headingText += ` (Floor ${map.floor})`;
                        }
                        mapHeading.textContent = headingText;
                        mapHeading.className = 'map-group-heading';
                        if (resourceButtonsContainer) resourceButtonsContainer.appendChild(mapHeading);

                        const mapGroupGrid = document.createElement('div');
                        mapGroupGrid.className = 'resource-buttons-grid map-specific-grid';
                        if (resourceButtonsContainer) resourceButtonsContainer.appendChild(mapGroupGrid);

                        groupedResources[map.id].forEach(resource => {
                            const button = document.createElement('button');
                            button.textContent = resource.name;
                            button.classList.add('button', 'resource-availability-button');
                            button.dataset.resourceId = resource.id;
                            button.dataset.resourceName = resource.name;
                            button.dataset.imageUrl = resource.image_url || '';
                            button.dataset.bookingRestriction = resource.booking_restriction || "";
                            button.dataset.allowedUserIds = resource.allowed_user_ids || "";
                            button.dataset.roleIds = (resource.roles || []).map(r => r.id).join(',');
                            
                            button.addEventListener('click', async function() {
                                console.log(`Resource button clicked: ${this.dataset.resourceName} (ID: ${this.dataset.resourceId})`);
                                const clickedButton = this; // Keep reference to the button
        
                                if (clickedButton.classList.contains('unavailable') && !clickedButton.classList.contains('partial')) {
                                    console.log("Resource button is completely unavailable, click ignored.");
                                    return;
                                }
                                
                                const resourceId = clickedButton.dataset.resourceId;
                                const resourceName = clickedButton.dataset.resourceName;
                                const selectedDate = availabilityDateInput ? availabilityDateInput.value : getTodayDateString();
                                const imageUrl = clickedButton.dataset.imageUrl;
        
                                console.log(`Modal to be opened for: ID=${resourceId}, Name=${resourceName}, Date=${selectedDate}`);
        
                                resetRpbmModal(); 
        
                                if (modalResourceName) modalResourceName.textContent = resourceName;
                                if (modalSelectedDate) modalSelectedDate.textContent = selectedDate;
                                if (modalResourceImage) {
                                    if (imageUrl) {
                                        modalResourceImage.src = imageUrl;
                                        modalResourceImage.style.display = 'block';
                                    } else {
                                        modalResourceImage.style.display = 'none';
                                    }
                                }
                                if (modalConfirmBtn) modalConfirmBtn.dataset.resourceId = resourceId;
        
                                const cacheKey = resourceId + '_' + selectedDate;
                                let resourceBookings = currentResourceBookingsCache[cacheKey];
                                if (!resourceBookings) {
                                    try {
                                        resourceBookings = await apiCall(`/api/resources/${resourceId}/availability?date=${selectedDate}`, {}, modalStatusMsg);
                                        currentResourceBookingsCache[cacheKey] = resourceBookings;
                                    } catch (error) {
                                        showError(modalStatusMsg, `Could not load availability for ${resourceName}.`);
                                        if (bookingModal) bookingModal.style.display = 'block';
                                        return;
                                    }
                                }

                                let userBookings = [];
                                const loggedInUserId = sessionStorage.getItem('loggedInUserId'); // Check if user is logged in
                                if (loggedInUserId) {
                                    try {
                                        userBookings = await apiCall(`/api/bookings/my_bookings_for_date?date=${selectedDate}`, {}, null); // No specific message div for this background fetch
                                    } catch (error) {
                                        console.warn(`Could not fetch user's other bookings for ${selectedDate}:`, error.message);
                                        // Proceed even if this fails, userBookings will be empty.
                                    }
                                }
                                
                                const slotButtons = [
                                    modalSlotOptionsContainer.querySelector('[data-slot-type="first_half"]'),
                                    modalSlotOptionsContainer.querySelector('[data-slot-type="second_half"]'),
                                    modalSlotOptionsContainer.querySelector('[data-slot-type="full_day"]')
                                ].filter(btn => btn); // Filter out nulls if any button not found

                                const definedSlots = {
                                    first_half: { name: 'First Half-Day', start: 8 * 60, end: 12 * 60, startTimeStr: "08:00:00", endTimeStr: "12:00:00" },
                                    second_half: { name: 'Second Half-Day', start: 13 * 60, end: 17 * 60, startTimeStr: "13:00:00", endTimeStr: "17:00:00" },
                                    full_day: { name: 'Full Day', start: 8 * 60, end: 17 * 60, startTimeStr: "08:00:00", endTimeStr: "17:00:00" }
                                };

                                function parseTimeHHMMSS(timeStr) { // e.g., "08:00:00"
                                    const parts = timeStr.split(':');
                                    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
                                }
        
                                slotButtons.forEach(btn => {
                                    const slotType = btn.dataset.slotType;
                                    const definedSlot = definedSlots[slotType];
                                    if (!definedSlot) return;

                                    btn.disabled = false;
                                    btn.classList.remove('slot-available', 'slot-booked-resource', 'slot-user-busy', 'selected', 'unavailable', 'booked', 'partial'); // Clear all relevant classes
                                    const baseText = btn.textContent.split(" (")[0]; // Get original button text like "First Half-Day"

                                    let isResourceBookedForSlot = false;
                                    if (resourceBookings && resourceBookings.length > 0) {
                                        for (const booking of resourceBookings) {
                                            const bookingStartMinutes = parseTimeHHMMSS(booking.start_time);
                                            const bookingEndMinutes = parseTimeHHMMSS(booking.end_time);
                                            if (Math.max(definedSlot.start, bookingStartMinutes) < Math.min(definedSlot.end, bookingEndMinutes)) {
                                                isResourceBookedForSlot = true;
                                                break;
                                            }
                                        }
                                    }

                                    if (isResourceBookedForSlot) {
                                        btn.disabled = true;
                                        btn.classList.add('slot-booked-resource');
                                        btn.textContent = baseText + " (Booked)";
                                    } else {
                                        let isUserBusyElsewhere = false;
                                        if (userBookings && userBookings.length > 0) {
                                            for (const userBooking of userBookings) {
                                                // Ensure it's a booking on a DIFFERENT resource
                                                if (String(userBooking.resource_id) !== String(resourceId)) {
                                                    const userBookingStartMinutes = parseTimeHHMMSS(userBooking.start_time);
                                                    const userBookingEndMinutes = parseTimeHHMMSS(userBooking.end_time);
                                                    if (Math.max(definedSlot.start, userBookingStartMinutes) < Math.min(definedSlot.end, userBookingEndMinutes)) {
                                                        isUserBusyElsewhere = true;
                                                        break;
                                                    }
                                                }
                                            }
                                        }

                                        if (isUserBusyElsewhere) {
                                            btn.classList.add('slot-user-busy');
                                            btn.textContent = baseText + " (User Busy)";
                                            // Button remains enabled
                                        } else {
                                            btn.classList.add('slot-available');
                                            btn.textContent = baseText; // Or baseText + " (Available)"
                                        }
                                    }
                                });

                                // Special handling for full_day if half-days are affected
                                const firstHalfBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="first_half"]');
                                const secondHalfBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="second_half"]');
                                const fullDayBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="full_day"]');

                                if (fullDayBtn && !fullDayBtn.classList.contains('slot-booked-resource')) { // Only if not already booked on this resource
                                    const firstHalfBookedOnResource = firstHalfBtn && firstHalfBtn.classList.contains('slot-booked-resource');
                                    const secondHalfBookedOnResource = secondHalfBtn && secondHalfBtn.classList.contains('slot-booked-resource');

                                    if (firstHalfBookedOnResource || secondHalfBookedOnResource) {
                                        fullDayBtn.disabled = true;
                                        fullDayBtn.classList.remove('slot-available', 'slot-user-busy');
                                        fullDayBtn.classList.add('slot-booked-resource'); // Treat as resource booked for simplicity
                                        fullDayBtn.textContent = fullDayBtn.textContent.split(" (")[0] + " (Unavailable)";
                                    }
                                    // If user is busy in one half, full day might still be "User Busy" or "Available" depending on exact overlap logic desired.
                                    // Current logic marks slot by slot. Full day being "User Busy" if one half is "User Busy" is an enhancement.
                                    // For now, if any part of full day makes it "User Busy", it will be marked as such if not resource-booked.
                                }
        
                                if (bookingModal) bookingModal.style.display = 'block';
                                console.log("Booking modal displayed.");
                            });
                            mapGroupGrid.appendChild(button); // This was for the first loop example, ensure it's in the correct place
                        });
                    }
                }); // End of allMaps.forEach

                if (groupedResources.unassigned.length > 0) { // Repeat for unassigned resources
                    resourcesRenderedInAnyGroup = true;
                    const unassignedHeading = document.createElement('h3');
                    unassignedHeading.textContent = 'Other Resources';
                    unassignedHeading.className = 'map-group-heading';
                    if (resourceButtonsContainer) resourceButtonsContainer.appendChild(unassignedHeading);

                    const unassignedGroupGrid = document.createElement('div');
                    unassignedGroupGrid.className = 'resource-buttons-grid unassigned-grid';
                    if (resourceButtonsContainer) resourceButtonsContainer.appendChild(unassignedGroupGrid);

                    groupedResources.unassigned.forEach(resource => {
                        const button = document.createElement('button');
                        button.textContent = resource.name;
                        button.classList.add('button', 'resource-availability-button');
                        button.dataset.resourceId = resource.id;
                        button.dataset.resourceName = resource.name;
                        button.dataset.imageUrl = resource.image_url || '';
                        button.dataset.bookingRestriction = resource.booking_restriction || "";
                        button.dataset.allowedUserIds = resource.allowed_user_ids || "";
                        button.dataset.roleIds = (resource.roles || []).map(r => r.id).join(',');

                        button.addEventListener('click', async function() { // Duplicated logic - consider refactoring to a common function
                            console.log(`Resource button clicked: ${this.dataset.resourceName} (ID: ${this.dataset.resourceId})`);
                            const clickedButton = this; 
                            const resourceId = clickedButton.dataset.resourceId;
                            const resourceName = clickedButton.dataset.resourceName;
                            const selectedDate = availabilityDateInput ? availabilityDateInput.value : getTodayDateString();
                            const imageUrl = clickedButton.dataset.imageUrl;
                            resetRpbmModal(); 
                            if (modalResourceName) modalResourceName.textContent = resourceName;
                            if (modalSelectedDate) modalSelectedDate.textContent = selectedDate;
                            if (modalResourceImage) {
                                if (imageUrl) {
                                    modalResourceImage.src = imageUrl; modalResourceImage.style.display = 'block';
                                } else {
                                    modalResourceImage.style.display = 'none';
                                }
                            }
                            if (modalConfirmBtn) modalConfirmBtn.dataset.resourceId = resourceId;

                            // START of new availability logic for unassigned resources
                            const cacheKey = resourceId + '_' + selectedDate;
                            let resourceBookings = currentResourceBookingsCache[cacheKey];
                            if (!resourceBookings) {
                                try {
                                    resourceBookings = await apiCall(`/api/resources/${resourceId}/availability?date=${selectedDate}`, {}, modalStatusMsg);
                                    currentResourceBookingsCache[cacheKey] = resourceBookings;
                                } catch (error) {
                                    showError(modalStatusMsg, `Could not load availability for ${resourceName}.`);
                                    if (bookingModal) bookingModal.style.display = 'block'; return;
                                }
                            }

                            let userBookings = [];
                            const loggedInUserId = sessionStorage.getItem('loggedInUserId');
                            if (loggedInUserId) {
                                try {
                                    userBookings = await apiCall(`/api/bookings/my_bookings_for_date?date=${selectedDate}`, {}, null);
                                } catch (error) {
                                    console.warn(`Could not fetch user's other bookings for ${selectedDate}:`, error.message);
                                }
                            }

                            const slotButtons = [
                                modalSlotOptionsContainer.querySelector('[data-slot-type="first_half"]'),
                                modalSlotOptionsContainer.querySelector('[data-slot-type="second_half"]'),
                                modalSlotOptionsContainer.querySelector('[data-slot-type="full_day"]')
                            ].filter(btn => btn);

                            const definedSlots = {
                                first_half: { name: 'First Half-Day', start: 8 * 60, end: 12 * 60, startTimeStr: "08:00:00", endTimeStr: "12:00:00" },
                                second_half: { name: 'Second Half-Day', start: 13 * 60, end: 17 * 60, startTimeStr: "13:00:00", endTimeStr: "17:00:00" },
                                full_day: { name: 'Full Day', start: 8 * 60, end: 17 * 60, startTimeStr: "08:00:00", endTimeStr: "17:00:00" }
                            };

                            function parseTimeHHMMSS(timeStr) {
                                const parts = timeStr.split(':');
                                return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
                            }

                            slotButtons.forEach(btn => {
                                const slotType = btn.dataset.slotType;
                                const definedSlot = definedSlots[slotType];
                                if (!definedSlot) return;

                                btn.disabled = false;
                                btn.classList.remove('slot-available', 'slot-booked-resource', 'slot-user-busy', 'selected', 'unavailable', 'booked', 'partial');
                                const baseText = btn.textContent.split(" (")[0];

                                let isResourceBookedForSlot = false;
                                if (resourceBookings && resourceBookings.length > 0) {
                                    for (const booking of resourceBookings) {
                                        const bookingStartMinutes = parseTimeHHMMSS(booking.start_time);
                                        const bookingEndMinutes = parseTimeHHMMSS(booking.end_time);
                                        if (Math.max(definedSlot.start, bookingStartMinutes) < Math.min(definedSlot.end, bookingEndMinutes)) {
                                            isResourceBookedForSlot = true;
                                            break;
                                        }
                                    }
                                }

                                if (isResourceBookedForSlot) {
                                    btn.disabled = true;
                                    btn.classList.add('slot-booked-resource');
                                    btn.textContent = baseText + " (Booked)";
                                } else {
                                    let isUserBusyElsewhere = false;
                                    if (userBookings && userBookings.length > 0) {
                                        for (const userBooking of userBookings) {
                                            if (String(userBooking.resource_id) !== String(resourceId)) {
                                                const userBookingStartMinutes = parseTimeHHMMSS(userBooking.start_time);
                                                const userBookingEndMinutes = parseTimeHHMMSS(userBooking.end_time);
                                                if (Math.max(definedSlot.start, userBookingStartMinutes) < Math.min(definedSlot.end, userBookingEndMinutes)) {
                                                    isUserBusyElsewhere = true;
                                                    break;
                                                }
                                            }
                                        }
                                    }

                                    if (isUserBusyElsewhere) {
                                        btn.classList.add('slot-user-busy');
                                        btn.textContent = baseText + " (User Busy)";
                                    } else {
                                        btn.classList.add('slot-available');
                                        btn.textContent = baseText;
                                    }
                                }
                            });

                            const firstHalfBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="first_half"]');
                            const secondHalfBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="second_half"]');
                            const fullDayBtn = modalSlotOptionsContainer.querySelector('[data-slot-type="full_day"]');

                            if (fullDayBtn && !fullDayBtn.classList.contains('slot-booked-resource')) {
                                const firstHalfBookedOnResource = firstHalfBtn && firstHalfBtn.classList.contains('slot-booked-resource');
                                const secondHalfBookedOnResource = secondHalfBtn && secondHalfBtn.classList.contains('slot-booked-resource');

                                if (firstHalfBookedOnResource || secondHalfBookedOnResource) {
                                    fullDayBtn.disabled = true;
                                    fullDayBtn.classList.remove('slot-available', 'slot-user-busy');
                                    fullDayBtn.classList.add('slot-booked-resource');
                                    fullDayBtn.textContent = fullDayBtn.textContent.split(" (")[0] + " (Unavailable)";
                                }
                            }
                            // END of new availability logic for unassigned resources
                            if (bookingModal) bookingModal.style.display = 'block';
                        });
                        unassignedGroupGrid.appendChild(button);
                    });
                }

                if (!resourcesRenderedInAnyGroup && resourceButtonsContainer) {
                     resourceButtonsContainer.innerHTML = '<p>No resources found matching current criteria or groups.</p>';
                }

                await updateAllButtonColors(); 
                if (resourceLoadingStatusDiv && !resourceLoadingStatusDiv.classList.contains('error')) {
                    hideMessage(resourceLoadingStatusDiv);
                }

            } catch (error) {
                console.error("Failed to fetch and render grouped resources:", error);
                if (resourceLoadingStatusDiv) showError(resourceLoadingStatusDiv, error.message || "Could not load grouped resources. Check console for details.");
                if (resourceButtonsContainer) resourceButtonsContainer.innerHTML = '<p class="error">Error loading resources. Please try refreshing.</p>';
            }
        }

        // 3. updateButtonColor(button, dateStr) function
        async function updateButtonColor(button, dateStr) {
            const resourceId = button.dataset.resourceId;
            console.log(`Updating button color for resource ${resourceId} on date ${dateStr}`);

            // Use a temporary, non-visible element for apiCall's messages for this specific update,
            // or null if errors should only be logged for this background update.
            // For now, let's use resourceLoadingStatusDiv but it might flash "Processing..." often.
            // A dedicated silent message div or null might be better.
            let bookings;
            const cacheKey = resourceId + '_' + dateStr;

            // Check cache first
            if (currentResourceBookingsCache[cacheKey]) {
                bookings = currentResourceBookingsCache[cacheKey];
                console.log(`Using cached availability for ${resourceId} on ${dateStr} for button color.`);
            } else {
                try {
                    bookings = await apiCall(`/api/resources/${resourceId}/availability?date=${dateStr}`, {}, null /* No message element for background updates */);
                    currentResourceBookingsCache[cacheKey] = bookings; // Cache the result
                    console.log(`Fetched availability for ${resourceId} on ${dateStr}:`, bookings);
                } catch (error) {
                    console.error(`Failed to fetch availability for ${resourceId} on ${dateStr}:`, error);
                    button.classList.remove('available', 'partial', 'unavailable');
                    button.classList.add('error'); // Special class for API error state
                    button.title = `${button.dataset.resourceName} - Error loading availability`;
                    return; // Stop further processing for this button
                }
            }

            // Define slots (using 08:00-12:00 and 13:00-17:00 as per modal)
            const slots = [
                { name: "First Half", startHour: 8, endHour: 12, isAvailable: true },
                { name: "Second Half", startHour: 13, endHour: 17, isAvailable: true }
            ];

            if (bookings && bookings.length > 0) {
                bookings.forEach(booking => {
                    const bookingStartHour = parseInt(booking.start_time.split(':')[0], 10);
                    const bookingEndHour = parseInt(booking.end_time.split(':')[0], 10);

                    slots.forEach(slot => {
                        if (bookingStartHour < slot.endHour && bookingEndHour > slot.startHour) {
                            slot.isAvailable = false; // This slot is booked
                        }
                    });
                });
            }
            
            const isFirstHalfAvailable = slots[0].isAvailable;
            const isSecondHalfAvailable = slots[1].isAvailable;
            
            console.log(`Availability for ${resourceId}: First Half: ${isFirstHalfAvailable}, Second Half: ${isSecondHalfAvailable}`);

            button.classList.remove('available', 'partial', 'unavailable', 'error'); // Clear previous states

            let currentUserId = null;
            const currentUserIdStr = sessionStorage.getItem('loggedInUserId');
            if (currentUserIdStr) currentUserId = parseInt(currentUserIdStr, 10);
            const currentUserIsAdmin = sessionStorage.getItem('loggedInUserIsAdmin') === 'true';
            
            const resourceDataForPermission = { // Construct a resource-like object for the permission check
                id: resourceId,
                name: button.dataset.resourceName,
                booking_restriction: button.dataset.bookingRestriction,
                allowed_user_ids: button.dataset.allowedUserIds,
                roles: parseRolesFromDataset(button.dataset.roleIds) // Assuming role_ids are stored on button dataset
            };

            if (!checkUserPermissionForResource(resourceDataForPermission, currentUserId, currentUserIsAdmin)) {
                 button.classList.add('unavailable'); // Or a new 'restricted' class
                 button.title = `${button.dataset.resourceName} - Restricted Access`;
                 console.log(`Resource ${resourceId} is restricted. Class: unavailable (or restricted)`);
            } else if (isFirstHalfAvailable && isSecondHalfAvailable) {
                button.classList.add('available');
                button.title = `${button.dataset.resourceName} - Available`;
                console.log(`Resource ${resourceId} is available. Class: available`);
            } else if (isFirstHalfAvailable || isSecondHalfAvailable) {
                button.classList.add('partial');
                button.title = `${button.dataset.resourceName} - Partially Available`;
                console.log(`Resource ${resourceId} is partially available. Class: partial`);
            } else {
                button.classList.add('unavailable');
                button.title = `${button.dataset.resourceName} - Unavailable`;
                console.log(`Resource ${resourceId} is unavailable. Class: unavailable`);
            }

            // Existing class adding logic should be right above this
            if (button.classList.contains('unavailable') && !button.title.includes('Restricted Access')) {
                // If the button is 'unavailable' AND it's not due to a permission restriction (title check)
                button.style.display = 'none';
                console.log(`Resource ${resourceId} is unavailable and not restricted, hiding button.`);
            } else {
                // For 'available', 'partial', or 'unavailable' due to restriction, or 'error' state
                button.style.display = ''; // Reset to default display (usually 'block' or 'inline-block' based on CSS)
                console.log(`Resource ${resourceId} is available, partial, restricted, or in error state, showing button. Classes: ${button.className}`);
            }
        }

        // 4. updateAllButtonColors() function
        async function updateAllButtonColors() {
            const dateStr = availabilityDateInput ? availabilityDateInput.value : getTodayDateString();
            console.log(`Updating all button colors for date: ${dateStr}`);
            currentResourceBookingsCache = {}; // Clear cache when date changes or full refresh

            const buttons = resourceButtonsContainer.querySelectorAll('.resource-availability-button');
            if (buttons.length === 0) {
                console.log("No resource buttons found to update.");
                return;
            }
            
            // Show a general loading message while updating all buttons
            if (resourceLoadingStatusDiv) showLoading(resourceLoadingStatusDiv, "Updating availability status...");

            // Sequentially or with Promise.all. Promise.all is faster but might hit rate limits if many resources.
            // For a moderate number of resources, Promise.all is fine.
            const updatePromises = [];
            buttons.forEach(button => {
                updatePromises.push(updateButtonColor(button, dateStr));
            });

            try {
                await Promise.all(updatePromises);
                console.log("All button colors updated.");
                if (resourceLoadingStatusDiv && !resourceLoadingStatusDiv.classList.contains('error')) { // Check if an error occurred during any update
                    hideMessage(resourceLoadingStatusDiv); // Hide general loading message
                }
                updateGroupVisibility(); // Call here after successful updates
            } catch (error) {
                console.error("Error during Promise.all for updateAllButtonColors:", error);
                // Individual errors are handled in updateButtonColor. 
                // This catch is for Promise.all itself if it rejects for some reason not caught by individual calls.
                if (resourceLoadingStatusDiv) showError(resourceLoadingStatusDiv, "An error occurred while updating resource statuses.");
                // Consider if updateGroupVisibility() should also be called in case of error, 
                // if partially updated button states are possible and groups might need hiding.
                // For now, calling only on full success of all button updates.
            }
        }
        
        if (availabilityDateInput) {
            availabilityDateInput.addEventListener('change', updateAllButtonColors);
        }

        // 5. Modal Slot Button Click Listeners
        if (modalSlotOptionsContainer) {
            modalSlotOptionsContainer.querySelectorAll('.time-slot-btn').forEach(slotBtn => {
                slotBtn.addEventListener('click', function() {
                    if (this.classList.contains('unavailable') || this.classList.contains('booked')) {
                        console.log("Clicked on a disabled/booked slot button. No action.");
                        return;
                    }
                    // Remove 'selected' from all slot buttons within the same container
                    modalSlotOptionsContainer.querySelectorAll('.time-slot-btn').forEach(btn => {
                        btn.classList.remove('selected');
                    });
                    // Add 'selected' to the clicked button
                    this.classList.add('selected');
                    selectedSlotDetails = {
                        startTimeStr: this.dataset.startTime,
                        endTimeStr: this.dataset.endTime,
                        slotName: this.dataset.slotName // e.g. "First Half", "Full Day"
                    };
                    console.log("Slot selected:", selectedSlotDetails);
                    if (modalStatusMsg) modalStatusMsg.textContent = ''; // Clear any previous status messages
                });
            });
        } else {
            console.error("Modal slot options container (rpbm-slot-options) not found!");
        }

        // 7. Modal Booking Confirmation (modalConfirmBtn click listener)
        if (modalConfirmBtn) {
            modalConfirmBtn.addEventListener('click', async function() {
                console.log("Confirm booking button clicked.");
                if (!selectedSlotDetails) {
                    showError(modalStatusMsg, 'Please select a time slot first.');
                    console.warn("No slot selected for booking.");
                    return;
                }

                const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
                if (!loggedInUsername) {
                    showError(modalStatusMsg, 'You must be logged in to book. Please log in and try again.');
                    console.warn("User not logged in for booking.");
                    // Optionally, redirect to login page or show login modal
                    return;
                }

                const resourceId = this.dataset.resourceId; // Retained from when modal was opened
                const dateStr = modalSelectedDate ? modalSelectedDate.textContent : null;
                const title = modalBookingTitle ? modalBookingTitle.value.trim() : `Booking for ${modalResourceName.textContent}`;

                if (!resourceId || !dateStr) {
                    showError(modalStatusMsg, 'Error: Missing resource ID or date for booking.');
                    console.error("Missing resourceId or dateStr for booking confirmation.");
                    return;
                }

                const payload = {
                    resource_id: parseInt(resourceId, 10),
                    date_str: dateStr,
                    start_time_str: selectedSlotDetails.startTimeStr,
                    end_time_str: selectedSlotDetails.endTimeStr,
                    title: title || `Booking for ${modalResourceName.textContent}`, // Ensure title is not empty
                    user_name: loggedInUsername // Backend will use authenticated user, but good to send for logging/confirmation
                };
                console.log("Booking payload:", payload);

                try {
                    const responseData = await apiCall('/api/bookings', {
                        method: 'POST',
                        body: JSON.stringify(payload)
                    }, modalStatusMsg); // modalStatusMsg will show "Processing..." then success/error

                    console.log("Booking API call successful, response:", responseData);
                    
                    // On Success:
                    await updateAllButtonColors(); // Refresh main page button colors

                    // Hide form elements, show acknowledgement
                    if (modalConfirmBtn) modalConfirmBtn.style.display = 'none';
                    if (modalSlotOptionsContainer) modalSlotOptionsContainer.style.display = 'none';
                    if (modalBookingTitle && modalBookingTitle.parentElement) modalBookingTitle.parentElement.style.display = 'none';
                    if (modalAckCloseBtn) modalAckCloseBtn.style.display = 'inline-block';

                    const resourceNameForMsg = modalResourceName ? modalResourceName.textContent : 'N/A';
                    const dateStrForMsg = dateStr;
                    const startTimeForMsg = selectedSlotDetails.startTimeStr;
                    const endTimeForMsg = selectedSlotDetails.endTimeStr;
                    const bookingTitleValue = title;

                    let countdown = 5;
                    const detailedMessage = `Booking Confirmed!<br>Resource: ${resourceNameForMsg}<br>Date: ${dateStrForMsg}<br>Time: ${startTimeForMsg} - ${endTimeForMsg}${bookingTitleValue ? '<br>Title: ' + bookingTitleValue : ''}<br><br>Closing in <span id="rpbm-countdown-timer">${countdown}</span>s...`;
                    
                    // apiCall might have already shown a simple success message. Overwrite with detailed one.
                    showSuccess(modalStatusMsg, detailedMessage); // showSuccess uses innerHTML

                    const timerSpan = document.getElementById('rpbm-countdown-timer');
                    if (countdownInterval) clearInterval(countdownInterval); // Clear any existing interval
                    countdownInterval = setInterval(() => {
                        countdown--;
                        if (timerSpan) timerSpan.textContent = countdown;
                        if (countdown <= 0) {
                            clearInterval(countdownInterval);
                            countdownInterval = null;
                            if (bookingModal) bookingModal.style.display = 'none';
                            console.log("Modal closed by countdown.");
                            // resetRpbmModal(); // Modal will be reset when next opened
                        }
                    }, 1000);

                } catch (error) {
                    console.error("Booking failed:", error);
                    // apiCall already showed the error in modalStatusMsg.
                    // Optionally, add more specific error handling here if needed.
                }
            });
        } else {
            console.error("Modal confirm button (rpbm-confirm-booking-btn) not found!");
        }

        // 8. modalAckCloseBtn Click Listener
        if (modalAckCloseBtn) {
            modalAckCloseBtn.addEventListener('click', function() {
                console.log("Modal acknowledgement close button clicked.");
                if (countdownInterval) {
                    clearInterval(countdownInterval);
                    countdownInterval = null;
                    console.log("Countdown interval cleared by AckClose button.");
                }
                if (bookingModal) bookingModal.style.display = 'none';
                // resetRpbmModal(); // Modal will be reset when next opened
            });
        } else {
             console.error("Modal acknowledgement close button (rpbm-ack-close-btn) not found!");
        }

        // 9. Window Click Outside Modal for resource-page-booking-modal
        // AND main (X) close button
        if (closeModalBtn) { // The 'X' span
            closeModalBtn.addEventListener('click', function() {
                console.log("Modal (X) close button clicked.");
                if (countdownInterval) {
                    clearInterval(countdownInterval);
                    countdownInterval = null;
                    console.log("Countdown interval cleared by (X) close button.");
                }
                if (bookingModal) bookingModal.style.display = 'none';
                // resetRpbmModal(); // Modal will be reset when next opened
            });
        } else {
            console.error("Modal main close button (rpbm-close-modal-btn) not found!");
        }

        window.addEventListener('click', function(event) {
            if (bookingModal && event.target == bookingModal) { // Clicked on the modal backdrop
                console.log("Clicked outside modal content area.");
                if (countdownInterval) {
                    clearInterval(countdownInterval);
                    countdownInterval = null;
                    console.log("Countdown interval cleared by clicking outside modal.");
                }
                bookingModal.style.display = 'none';
                // resetRpbmModal(); // Modal will be reset when next opened
            }
        });

        if (applyFiltersBtn) {
            applyFiltersBtn.addEventListener('click', () => {
                currentFilters = {
                    capacity: filterCapacityInput.value,
                    equipment: filterEquipmentInput.value.trim(),
                    tags: filterTagsInput.value.trim()
                };
                fetchAndRenderResources(currentFilters);
            });
        }

        if (clearFiltersBtn) {
            clearFiltersBtn.addEventListener('click', () => {
                if (filterCapacityInput) filterCapacityInput.value = '';
                if (filterEquipmentInput) filterEquipmentInput.value = '';
                if (filterTagsInput) filterTagsInput.value = '';
                currentFilters = {};
                fetchAndRenderResources(currentFilters);
            });
        }

        // Initial call to fetch and render resources and their button states
        fetchAndRenderResources();
        console.log("Initial fetchAndRenderResources called.");

    } // --- END: Resources Page - Resource Buttons Grid & Modal ---


    // Admin Maps Page Specific Logic
    const adminMapsPageIdentifier = document.getElementById('upload-map-form');
    if (adminMapsPageIdentifier) { 
        const uploadMapForm = document.getElementById('upload-map-form');
        const mapsListUl = document.getElementById('maps-list'); // This might be legacy if table is used in admin_maps.html
        const uploadStatusDiv = document.getElementById('upload-status'); 
        const adminMapsListStatusDiv = document.getElementById('admin-maps-list-status'); 

        const defineAreasSection = document.getElementById('define-areas-section');
        const selectedMapNameH3 = document.getElementById('selected-map-name');
        const selectedMapImageImg = document.getElementById('selected-map-image');
        const resourceToMapSelect = document.getElementById('resource-to-map');
        const defineAreaForm = document.getElementById('define-area-form');
        const hiddenFloorMapIdInput = document.getElementById('selected-floor-map-id');
        const areaDefinitionStatusDiv = document.getElementById('area-definition-status');
        const bookingPermissionDropdown = document.getElementById('booking-permission');
        const resourceActionsContainer = document.getElementById('resource-actions-container');
        const authorizedUsersCheckboxContainer = document.getElementById('define-area-authorized-users-checkbox-container');
        const authorizedRolesCheckboxContainer = document.getElementById('define-area-authorized-roles-checkbox-container');

        const drawingCanvas = document.getElementById('drawing-canvas');
        let canvasCtx = null;
        let isDrawing = false;
        let startX, startY;
        let currentDrawnRect = null;
        let existingMapAreas = [];
        let selectedAreaForEditing = null;

        let isMovingArea = false;
        let isResizingArea = false;
        let resizeHandle = null;
        let dragStartX, dragStartY;
        let initialAreaX, initialAreaY;
        let initialAreaWidth, initialAreaHeight;

        const HANDLE_SIZE = 8;
        const HANDLE_COLOR = 'rgba(0, 0, 255, 0.7)';
        const SELECTED_BORDER_COLOR = 'rgba(0, 0, 255, 0.9)';
        const SELECTED_LINE_WIDTH = 2;


        // Function to fetch and display maps (original simple list, might need adaptation for new table)
        async function fetchAndDisplayMaps() {
            // This function is now largely superseded by the inline script in admin_maps.html
            // which populates a table. Keeping it here for now, but it might be removed
            // or adapted if parts of its logic are still needed by other functions in this file.
            // For now, the new table rendering in admin_maps.html handles the display.
            console.log("Legacy fetchAndDisplayMaps in script.js called. Consider removing if new table in admin_maps.html is sufficient.");
            if (!mapsListUl || !adminMapsListStatusDiv) { // mapsListUl is the old <ul>
                // If mapsListUl doesn't exist (because it's a table now), this function might not be needed.
                return;
            }
            try {
                const maps = await apiCall('/api/admin/maps', {}, adminMapsListStatusDiv);
                mapsListUl.innerHTML = ''; 
                if (!maps || maps.length === 0) {
                    mapsListUl.innerHTML = '<li>No maps uploaded yet.</li>';
                    showSuccess(adminMapsListStatusDiv, 'No maps uploaded. Use the form to add one.');
                    return;
                }
                maps.forEach(map => {
                    const listItem = document.createElement('li');
                    listItem.innerHTML = `
                        <strong>${map.name}</strong> (ID: ${map.id})<br>
                        ${map.location ? 'Location: ' + map.location + '<br>' : ''}
                        ${map.floor ? 'Floor: ' + map.floor + '<br>' : ''}
                        Filename: ${map.image_filename}<br>
                        <img src="${map.image_url}" alt="${map.name}" style="max-width: 200px; max-height: 150px; border: 1px solid #eee;">
                        <br>
                        <button class="select-map-for-areas-btn button" data-map-id="${map.id}" data-map-name="${map.name}" data-map-image-url="${map.image_url}">Define Areas</button>
                        <button class="delete-map-btn button btn-danger btn-sm" data-map-id="${map.id}" data-map-name="${map.name}" style="margin-left: 5px;">Delete Map</button>
                    `; // Added "button" class and Delete Map button
                    mapsListUl.appendChild(listItem);
                });
            } catch (error) {
                mapsListUl.innerHTML = '<li>Error loading maps.</li>';
            }
        }

        if (uploadMapForm && uploadStatusDiv) {
            uploadMapForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                showLoading(uploadStatusDiv, 'Uploading...');
                const formData = new FormData(uploadMapForm);
                try {
                    const csrfTokenTag = document.querySelector('meta[name="csrf-token"]');
                    const csrfToken = csrfTokenTag ? csrfTokenTag.content : null;

                    const response = await fetch('/api/admin/maps', {
                        method: 'POST',
                        body: formData,
                        credentials: 'same-origin',
                        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {}
                    });
                    const responseData = await response.json();
                    if (response.ok) { 
                        showSuccess(uploadStatusDiv, `Map '${responseData.name}' uploaded successfully! (ID: ${responseData.id})`);
                        uploadMapForm.reset();
                        fetchAndDisplayMaps(); 
                    } else {
                        showError(uploadStatusDiv, `Upload failed: ${responseData.error || responseData.message || 'Unknown server error'}`);
                    }
                } catch (error) {
                    showError(uploadStatusDiv, `Upload failed: ${error.message || 'Network error or server is down.'}`);
                }
            });
        }

        fetchAndDisplayMaps();
        
        // Populate Roles for Checkbox List in Define Area Form
        async function populateDefineAreaRolesCheckboxes() {
            const authorizedRolesCheckboxContainer = document.getElementById('define-area-authorized-roles-checkbox-container');

            if (!authorizedRolesCheckboxContainer) {
                console.error("#define-area-authorized-roles-checkbox-container not found in DOM.");
                return;
            }

            // apiCall will now handle initial "Loading..." message and subsequent error/success messages.
            try {
                const roles = await apiCall('/api/admin/roles', {}, authorizedRolesCheckboxContainer);

                // If apiCall was successful, it might have shown a generic success message or hidden the loading one.
                // We must clear the container before adding checkboxes.
                authorizedRolesCheckboxContainer.innerHTML = '';

                if (roles && roles.length > 0) {
                    roles.forEach(role => {
                        const div = document.createElement('div');
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.id = `define-area-role-${role.id}`;
                        checkbox.value = role.id;
                        checkbox.name = 'define_area_authorized_role_ids';
                        const label = document.createElement('label');
                        label.htmlFor = `define-area-role-${role.id}`;
                        label.textContent = role.name + (role.description ? ` (${role.description})` : '');
                        div.appendChild(checkbox);
                        div.appendChild(label);
                        authorizedRolesCheckboxContainer.appendChild(div);
                    });
                } else {
                    // If roles array is empty or undefined after a successful API call (no error thrown by apiCall)
                    showSuccess(authorizedRolesCheckboxContainer, 'No roles found. You can create roles in User Management.');
                }
            } catch (error) {
                // This catch block is for errors not handled by apiCall (e.g., if apiCall itself fails or network issues not caught by it)
                // or if an error occurs in the processing logic above (after apiCall returns successfully but before this catch).
                // apiCall should have already displayed an error in authorizedRolesCheckboxContainer if the API call failed.
                console.error("Error in populateDefineAreaRolesCheckboxes after apiCall:", error);
                // Check if an error message is already displayed by apiCall
                const hasExistingErrorMessage = authorizedRolesCheckboxContainer.classList.contains('error') && authorizedRolesCheckboxContainer.textContent.trim() !== '';
                if (!hasExistingErrorMessage) {
                     // Show a generic error only if apiCall hasn't already set one.
                     showError(authorizedRolesCheckboxContainer, 'Could not display roles due to an unexpected error.');
                }
            }
        }
        // populateDefineAreaRolesCheckboxes(); // This is likely called on DOMContentLoaded or when Define Areas is shown.

        // Expose fetchAndDrawExistingMapAreas
        window.fetchAndDrawExistingMapAreas = async function(mapId) {
            existingMapAreas = [];
            const defineAreasStatusDiv = document.getElementById('define-areas-status');
            if (!defineAreasStatusDiv) {
                console.warn("define-areas-status element not found for fetchAndDrawExistingMapAreas messages.");
            }

            try {
                const data = await apiCall(`/api/map_details/${mapId}`, {}, defineAreasStatusDiv);
                if (data.mapped_resources && data.mapped_resources.length > 0) {
                    data.mapped_resources.forEach(resource => {
                        if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                            existingMapAreas.push({
                                id: resource.id, resource_id: resource.id, name: resource.name,
                                map_coordinates: resource.map_coordinates,
                                booking_restriction: resource.booking_restriction,
                                allowed_user_ids: resource.allowed_user_ids,
                                roles: resource.roles, // Assuming roles is an array of objects [{id, name}, ...]
                                status: resource.status, floor_map_id: resource.floor_map_id
                            });
                        }
                    });
                    if (defineAreasStatusDiv) {
                        if (existingMapAreas.length > 0) showSuccess(defineAreasStatusDiv, `Loaded ${existingMapAreas.length} area(s). Click to edit or draw new.`);
                        else showSuccess(defineAreasStatusDiv, "No areas defined. Draw on map to begin.");
                    }
                } else {
                     if (defineAreasStatusDiv) showSuccess(defineAreasStatusDiv, "No mapped resources found. Draw to define areas.");
                }
            } catch (error) {
                console.error('Error fetching existing map areas:', error.message);
            }
            if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
        }
        window.fetchAndDrawExistingMapAreas = fetchAndDrawExistingMapAreas; // Expose it

        // Expose redrawCanvas
        window.redrawCanvas = function() {
            if (!canvasCtx) {
                console.warn("Canvas context not initialized for redrawCanvas.");
                return;
            }
            canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);

            // Apply global map offsets before drawing each area
            const globalOffsetX = window.currentMapContext ? (window.currentMapContext.offsetX || 0) : 0;
            const globalOffsetY = window.currentMapContext ? (window.currentMapContext.offsetY || 0) : 0;

            canvasCtx.font = "10px Arial";
            existingMapAreas.forEach(area => {
                if (selectedAreaForEditing && selectedAreaForEditing.id === area.id) {
                    return; // Skip drawing here, will be drawn as selected
                }
                if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                    const coords = area.map_coordinates;
                    const drawX = coords.x + globalOffsetX;
                    const drawY = coords.y + globalOffsetY;

                    canvasCtx.fillStyle = 'rgba(255, 0, 0, 0.1)';
                    canvasCtx.strokeStyle = 'rgba(255, 0, 0, 0.7)';
                    canvasCtx.lineWidth = 1;

                    canvasCtx.fillRect(drawX, drawY, coords.width, coords.height);
                    canvasCtx.strokeRect(drawX, drawY, coords.width, coords.height);

                    canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                    canvasCtx.textAlign = "center";
                    canvasCtx.textBaseline = "middle";
                    if (coords.width > 30 && coords.height > 10) {
                         canvasCtx.fillText(area.name || `ID:${area.id}`, drawX + coords.width / 2, drawY + coords.height / 2, coords.width - 4);
                    }
                }
            });

            if (selectedAreaForEditing && selectedAreaForEditing.map_coordinates && selectedAreaForEditing.map_coordinates.type === 'rect') {
                const coords = selectedAreaForEditing.map_coordinates;
                const drawX = coords.x + globalOffsetX;
                const drawY = coords.y + globalOffsetY;

                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.2)';
                canvasCtx.strokeStyle = SELECTED_BORDER_COLOR;
                canvasCtx.lineWidth = SELECTED_LINE_WIDTH;

                canvasCtx.fillRect(drawX, drawY, coords.width, coords.height);
                canvasCtx.strokeRect(drawX, drawY, coords.width, coords.height);

                canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.9)';
                canvasCtx.textAlign = "center";
                canvasCtx.textBaseline = "middle";
                if (coords.width > 30 && coords.height > 10) {
                     canvasCtx.fillText(selectedAreaForEditing.name || `ID:${selectedAreaForEditing.id}`, drawX + coords.width / 2, drawY + coords.height / 2, coords.width - 4);
                }

                canvasCtx.fillStyle = HANDLE_COLOR;
                const halfHandle = HANDLE_SIZE / 2;
                canvasCtx.fillRect(drawX - halfHandle, drawY - halfHandle, HANDLE_SIZE, HANDLE_SIZE);
                canvasCtx.fillRect(drawX + coords.width - halfHandle, drawY - halfHandle, HANDLE_SIZE, HANDLE_SIZE);
                canvasCtx.fillRect(drawX - halfHandle, drawY + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE);
                canvasCtx.fillRect(drawX + coords.width - halfHandle, drawY + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE);
            }

            if (currentDrawnRect && currentDrawnRect.width !== undefined) {
                canvasCtx.strokeStyle = 'rgba(0, 0, 255, 0.7)';
                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.1)';
                canvasCtx.lineWidth = 2;

                // Do NOT apply global offsets to currentDrawnRect as it's drawn relative to mouse which is already on canvas
                let x = currentDrawnRect.x;
                let y = currentDrawnRect.y;
                let w = currentDrawnRect.width;
                let h = currentDrawnRect.height;

                if (w < 0) { x = currentDrawnRect.x + w; w = -w; }
                if (h < 0) { y = currentDrawnRect.y + h; h = -h; }

                canvasCtx.fillRect(x,y,w,h);
                canvasCtx.strokeRect(x, y, w, h);
            }
        }

        function updateCoordinateInputs(coords) { // This function remains local as it directly manipulates DOM elements in this scope
            document.getElementById('coord-x').value = Math.round(coords.x);
            document.getElementById('coord-y').value = Math.round(coords.y);
            document.getElementById('coord-width').value = Math.round(coords.width);
            document.getElementById('coord-height').value = Math.round(coords.height);
        }

        async function saveSelectedAreaDimensions(coords) { // Only saves dimensions, not other properties
            if (!selectedAreaForEditing) return;
            const areaDefStatusDiv = document.getElementById('area-definition-status'); // Corrected ID
            const payload = {
                floor_map_id: selectedAreaForEditing.floor_map_id, // Should be correct from selectedAreaForEditing
                coordinates: { type: 'rect', x: coords.x, y: coords.y, width: coords.width, height: coords.height }
                // No need to send booking_restriction, allowed_user_ids, role_ids here
                // as this function is only for updating geometry after drag/resize.
                // Those are handled by the main form submission.
            };
            try {
                await apiCall(
                    `/api/admin/resources/${selectedAreaForEditing.id}/map_info`, // Uses resource ID
                    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
                    areaDefStatusDiv
                );
                if (areaDefStatusDiv) showSuccess(areaDefStatusDiv, 'Area dimensions updated.');
            } catch (error) {
                console.error('Error saving resized/moved area:', error.message);
                 if (areaDefStatusDiv) showError(areaDefStatusDiv, 'Failed to update area dimensions: ' + error.message);
            }
        }


        async function populateResourcesForMapping(currentMapId) {
            const defineAreasStatusDiv = document.getElementById('define-areas-status');
            if (!resourceToMapSelect) return;

            try {
                const resources = await apiCall('/api/admin/resources', {}, defineAreasStatusDiv); // Changed to admin resources endpoint
                resourceToMapSelect.innerHTML = '<option value="">-- Select a Resource to Map --</option>';
                let count = 0;
                if (resources && resources.length > 0) {
                    resources.forEach(r => {
                        // Only show resources that are not mapped OR are mapped to the CURRENT map
                        if (!r.floor_map_id || !r.map_coordinates || r.floor_map_id === parseInt(currentMapId)) {
                            count++;
                            const opt = new Option(`${r.name} (ID: ${r.id}) - Status: ${r.status || 'N/A'}`, r.id);
                            Object.assign(opt.dataset, {
                                resourceId: r.id, resourceName: r.name, resourceStatus: r.status || 'draft',
                                bookingRestriction: r.booking_restriction || "",
                                allowedUserIds: r.allowed_user_ids || "",
                                roleIds: (r.roles || []).map(role => role.id).join(','), // Store role IDs
                                imageUrl: r.image_url || "",
                                isUnderMaintenance: r.is_under_maintenance ? "true" : "false",
                                maintenanceUntil: r.maintenance_until || "",
                                isMappedToCurrent: (r.floor_map_id === parseInt(currentMapId) && r.map_coordinates) ? "true" : "false"
                            });
                            if (opt.dataset.isMappedToCurrent === "true") opt.textContent += ` (On this map)`;
                            resourceToMapSelect.add(opt);
                        }
                    });
                }
                if (defineAreasStatusDiv) {
                    if (count === 0) showSuccess(defineAreasStatusDiv, "No new resources available for mapping to this map.");
                    else if (!defineAreasStatusDiv.classList.contains('error')) hideMessage(defineAreasStatusDiv);
                }
            } catch (error) {
                resourceToMapSelect.innerHTML = '<option value="">Error loading resources</option>';
            }
        }
        window.populateResourcesForMapping = populateResourcesForMapping; // Expose it

        // New function to encapsulate canvas setup and event listener attachment
        function initializeDefineAreasCanvasLogic() {
            if (!drawingCanvas || !selectedMapImageImg) {
                console.error("Canvas or map image element not found for initialization.");
                return;
            }

            // This function should be called after selectedMapImageImg.src is set and it's loaded.
            // The new 'Define Areas' button in admin_maps.html inline script should handle this.
            // Ensure selectedMapImageImg has loaded before setting canvas dimensions.
            if (!selectedMapImageImg.complete || selectedMapImageImg.naturalWidth === 0) {
                console.warn("Selected map image not loaded yet. Canvas initialization might be inaccurate or deferred.");
                // It's better if the caller ensures image is loaded.
                // For now, we proceed, but this could lead to 0x0 canvas if image isn't ready.
            }

            drawingCanvas.width = selectedMapImageImg.clientWidth;
            drawingCanvas.height = selectedMapImageImg.clientHeight;
            canvasCtx = drawingCanvas.getContext('2d'); // Ensure canvasCtx is accessible by handlers

            // Attach mouse event handlers (these are the existing functions, they will be updated for offsets later)
            drawingCanvas.onmousedown = function(event) { // Start of onmousedown
                const globalOffsetX = window.currentMapContext ? (window.currentMapContext.offsetX || 0) : 0;
                const globalOffsetY = window.currentMapContext ? (window.currentMapContext.offsetY || 0) : 0;

                const clickX = event.offsetX - globalOffsetX; // Adjust click by global offset
                const clickY = event.offsetY - globalOffsetY; // Adjust click by global offset
                const rawClickX = event.offsetX; // Keep raw for handle checks if handles are drawn without offset
                const rawClickY = event.offsetY;

                const editDeleteButtonsDiv = document.getElementById('edit-delete-buttons');

                const getHandleUnderCursor = (x, y, rect) => { // x,y are raw canvas click coordinates
                    const rectDrawX = rect.x + globalOffsetX;
                    const rectDrawY = rect.y + globalOffsetY;
                    const half = HANDLE_SIZE / 2;
                    if (x >= rectDrawX - half && x <= rectDrawX + half && y >= rectDrawY - half && y <= rectDrawY + half) return 'nw';
                    if (x >= rectDrawX + rect.width - half && x <= rectDrawX + rect.width + half && y >= rectDrawY - half && y <= rectDrawY + half) return 'ne';
                    if (x >= rectDrawX - half && x <= rectDrawX + half && y >= rectDrawY + rect.height - half && y <= rectDrawY + rect.height + half) return 'sw';
                    if (x >= rectDrawX + rect.width - half && x <= rectDrawX + rect.width + half && y >= rectDrawY + rect.height - half && y <= rectDrawY + rect.height + half) return 'se';
                    return null;
                };

                if (selectedAreaForEditing && selectedAreaForEditing.map_coordinates && selectedAreaForEditing.map_coordinates.type === 'rect') {
                    const coords = selectedAreaForEditing.map_coordinates;
                    const handle = getHandleUnderCursor(rawClickX, rawClickY, coords);
                    if (handle) {
                        isResizingArea = true; resizeHandle = handle; isDrawing = false; isMovingArea = false; currentDrawnRect = null;
                        dragStartX = rawClickX; dragStartY = rawClickY; // Use raw canvas coords for drag calculation start
                        initialAreaX = coords.x; initialAreaY = coords.y; initialAreaWidth = coords.width; initialAreaHeight = coords.height;
                        if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window"); return;
                    }
                    // Check click within the drawn area (using adjusted clickX/Y for logical coords)
                    if (clickX >= coords.x && clickX <= coords.x + coords.width && clickY >= coords.y && clickY <= coords.y + coords.height) {
                        isMovingArea = true; isDrawing = false; currentDrawnRect = null;
                        dragStartX = rawClickX; dragStartY = rawClickY; // Use raw canvas coords
                        initialAreaX = coords.x; initialAreaY = coords.y;
                        if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window"); return;
                    }
                }

                let clickedOnExistingArea = false;
                for (const area of existingMapAreas) {
                    if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                        const coords = area.map_coordinates;
                        // Check click within the logical area (using adjusted clickX/Y)
                        if (clickX >= coords.x && clickX <= coords.x + coords.width && clickY >= coords.y && clickY <= coords.y + coords.height) {
                            selectedAreaForEditing = area;
                            console.log('Area selected:', JSON.parse(JSON.stringify(selectedAreaForEditing)));
                            isDrawing = false; currentDrawnRect = null; clickedOnExistingArea = true;
                            if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'block';
                            updateCoordinateInputs(coords);
                            if (resourceToMapSelect) resourceToMapSelect.value = area.resource_id;
                            if (bookingPermissionDropdown) bookingPermissionDropdown.value = area.booking_restriction || "";
                            if (authorizedRolesCheckboxContainer) {
                                const selectedRoleIds = (area.roles || []).map(r => String(r.id));
                                authorizedRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                                    cb.checked = selectedRoleIds.includes(cb.value);
                                });
                            }
                            resourceToMapSelect.dispatchEvent(new Event('change'));
                            break;
                        }
                    }
                }

                if (!clickedOnExistingArea) {
                    selectedAreaForEditing = null;
                    if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'none';
                    isDrawing = true;
                    startX = clickX; // Use adjusted click coordinates for drawing start
                    startY = clickY;
                    currentDrawnRect = { x: startX, y: startY, width: 0, height: 0 };
                    const defineAreaFormElement = document.getElementById('define-area-form');
                    if(defineAreaFormElement) {
                        defineAreaFormElement.reset();
                        const submitButton = defineAreaFormElement.querySelector('button[type="submit"]');
                        if (submitButton) submitButton.textContent = 'Save New Area Mapping';
                        if(authorizedRolesCheckboxContainer) authorizedRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
                    }
                    if (resourceToMapSelect) resourceToMapSelect.value = '';
                    if (bookingPermissionDropdown) bookingPermissionDropdown.value = "";
                    resourceToMapSelect.dispatchEvent(new Event('change'));
                }
                if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
            }; // End of onmousedown

            drawingCanvas.onmousemove = function(event) { // Start of onmousemove
                const globalOffsetX = window.currentMapContext ? (window.currentMapContext.offsetX || 0) : 0;
                const globalOffsetY = window.currentMapContext ? (window.currentMapContext.offsetY || 0) : 0;
                const currentX = event.offsetX - globalOffsetX; // Adjust by global offset
                const currentY = event.offsetY - globalOffsetY; // Adjust by global offset
                const rawCurrentX = event.offsetX;
                const rawCurrentY = event.offsetY;

                if (isDrawing) {
                    currentDrawnRect.width = currentX - startX; currentDrawnRect.height = currentY - startY;
                    if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
                } else if (isMovingArea && selectedAreaForEditing) {
                    const deltaX = rawCurrentX - dragStartX; const deltaY = rawCurrentY - dragStartY;
                    const coords = selectedAreaForEditing.map_coordinates;
                    coords.x = initialAreaX + deltaX; coords.y = initialAreaY + deltaY;
                    updateCoordinateInputs(coords); currentDrawnRect = { ...coords }; // Store logical, un-offsetted coords
                    if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
                } else if (isResizingArea && selectedAreaForEditing) {
                    const deltaX = rawCurrentX - dragStartX; const deltaY = rawCurrentY - dragStartY;
                    const coords = selectedAreaForEditing.map_coordinates;
                    let newX = initialAreaX, newY = initialAreaY, newW = initialAreaWidth, newH = initialAreaHeight;
                    switch(resizeHandle) {
                        case 'nw': newX += deltaX; newY += deltaY; newW -= deltaX; newH -= deltaY; break;
                        case 'ne': newY += deltaY; newW += deltaX; newH -= deltaY; break;
                        case 'sw': newX += deltaX; newW -= deltaX; newH += deltaY; break;
                        case 'se': newW += deltaX; newH += deltaY; break;
                    }
                    if (newW < 1) newW = 1; if (newH < 1) newH = 1;
                    coords.x = newX; coords.y = newY; coords.width = newW; coords.height = newH;
                    updateCoordinateInputs(coords); currentDrawnRect = { ...coords }; // Store logical, un-offsetted coords
                    if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
                }
            }; // End of onmousemove

            drawingCanvas.onmouseup = async function(event) { // Start of onmouseup
                if (isDrawing) {
                    isDrawing = false;
                    let {x,y,width,height} = currentDrawnRect;
                    if (width < 0) { x += width; width = -width; }
                    if (height < 0) { y += height; height = -height; }
                    currentDrawnRect = { x, y, width, height }; // These are logical, un-offsetted coords
                    updateCoordinateInputs(currentDrawnRect);
                    if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
                } else if ((isMovingArea || isResizingArea) && selectedAreaForEditing) {
                    isMovingArea = false; isResizingArea = false;
                    const coords = selectedAreaForEditing.map_coordinates;
                    updateCoordinateInputs(coords);
                    await saveSelectedAreaDimensions(coords);
                    if (typeof window.redrawCanvas === 'function') window.redrawCanvas(); else console.warn("redrawCanvas not on window");
                }
            }; // End of onmouseup

            console.log("Define Areas canvas logic initialized/re-initialized.");
        }
        window.initializeDefineAreasCanvasLogic = initializeDefineAreasCanvasLogic; // Expose it


        // The old mapsListUl event listener for 'select-map-for-areas-btn' needs to be removed or adapted.
        // Since the new 'Define Areas' button is in admin_maps.html (handled by its inline script),
        // the old listener on mapsListUl (if it still exists and has such buttons) might conflict or be redundant.
        // For now, we are focusing on exposing functions. The actual call to initializeDefineAreasCanvasLogic
        // will be from the inline script in admin_maps.html after the image is loaded.
        // The original selectedMapImageImg.onload within the old mapsListUl click listener
        // has its core logic now encapsulated or to be called by initializeDefineAreasCanvasLogic.

        /*
        // This entire block for mapsListUl is commented out as its functionality is replaced
        // by the inline script in templates/admin_maps.html which uses a table and global functions.
        if (mapsListUl) { // This targets the old UL. The new table has its own delete logic.
            mapsListUl.addEventListener('click', async function(event) {
                if (event.target.classList.contains('delete-map-btn')) { // This is for the old list
                    const button = event.target;
                    const mapId = button.dataset.mapId;
                    const mapName = button.dataset.mapName;

                    if (confirm(`Are you sure you want to delete the map "${mapName}" (ID: ${mapId})? This will also unmap any resources on it.`)) {
                        showLoading(adminMapsListStatusDiv, `Deleting map ${mapName}...`);
                        try {
                            await apiCall(`/api/admin/maps/${mapId}`, { method: 'DELETE' }, adminMapsListStatusDiv);
                            showSuccess(adminMapsListStatusDiv, `Map "${mapName}" deleted successfully.`);
                            fetchAndDisplayMaps(); // Refresh the list

                            // If the deleted map was being edited, hide the define areas section
                            if (defineAreasSection.style.display !== 'none' && hiddenFloorMapIdInput.value === mapId) {
                                defineAreasSection.style.display = 'none';
                                if (selectedMapNameH3) selectedMapNameH3.textContent = '';
                                if (selectedMapImageImg) { selectedMapImageImg.src = '#'; selectedMapImageImg.alt = 'No map selected'; }
                                if (canvasCtx) canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
                                if (hiddenFloorMapIdInput) hiddenFloorMapIdInput.value = '';
                                if (resourceToMapSelect) resourceToMapSelect.innerHTML = '<option value="">-- Select a Resource to Map --</option>';
                                if (defineAreaForm) defineAreaForm.reset();
                                if (areaDefinitionStatusDiv) areaDefinitionStatusDiv.innerHTML = '';
                                existingMapAreas = [];
                                currentDrawnRect = null;
                                selectedAreaForEditing = null;
                                const editDelBtns = document.getElementById('edit-delete-buttons');
                                if (editDelBtns) editDelBtns.style.display = 'none';
                                if (resourceActionsContainer) resourceActionsContainer.innerHTML = '<p><em>Select a resource to see its status or actions.</em></p>';
                            }
                        } catch (error) {
                            // apiCall already shows the error in adminMapsListStatusDiv
                            console.error(`Error deleting map ${mapName}:`, error);
                        }
                    }
                }
            });
        }
        */

        if (defineAreaForm) {
            defineAreaForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                showLoading(areaDefinitionStatusDiv, 'Saving area...');

                const selectedResourceId = resourceToMapSelect.value;
                const floorMapId = parseInt(hiddenFloorMapIdInput.value, 10);
                
                if (!selectedResourceId) {
                    showError(areaDefinitionStatusDiv, 'Please select a resource to map.'); return;
                }
                if (isNaN(floorMapId)) {
                    showError(areaDefinitionStatusDiv, 'No floor map selected or invalid map ID.'); return;
                }

                const coordinates = {
                    type: document.getElementById('coordinates-type').value,
                    x: parseInt(document.getElementById('coord-x').value, 10),
                    y: parseInt(document.getElementById('coord-y').value, 10),
                    width: parseInt(document.getElementById('coord-width').value, 10),
                    height: parseInt(document.getElementById('coord-height').value, 10)
                };
                for (const key of ['x', 'y', 'width', 'height']) {
                    if (isNaN(coordinates[key])) {
                        showError(areaDefinitionStatusDiv, `Invalid input for coordinate: ${key}.`); return;
                    }
                }
                
                const selectedUserIds = [];
                if (authorizedUsersCheckboxContainer) {
                    authorizedUsersCheckboxContainer.querySelectorAll('input[name="authorized_user_ids"]:checked').forEach(cb => {
                        selectedUserIds.push(parseInt(cb.value));
                    });
                }
                // const roleIdsStr = authorizedRolesInput ? authorizedRolesInput.value : ""; // This was causing ReferenceError

                let selectedRoleIds = [];
                const rolesContainer = document.getElementById('define-area-authorized-roles-checkbox-container');
                if (rolesContainer) {
                    const checkedRoles = rolesContainer.querySelectorAll('input[type="checkbox"]:checked');
                    checkedRoles.forEach(checkbox => {
                        selectedRoleIds.push(parseInt(checkbox.value));
                    });
                }

                const payload = { 
                    floor_map_id: floorMapId, 
                    coordinates: coordinates,
                    // Send other properties if the form is extended to manage them directly
                    // For now, assuming these are managed on the main Resource Management page,
                    // and map_info PUT only updates map-specific data.
                    // If you want to update these here, add them to payload:
                    booking_restriction: bookingPermissionDropdown.value, // Example: if you want to update this
                    allowed_user_ids: selectedUserIds.join(','), // Example: if you want to update this
                    role_ids: selectedRoleIds // Send as array of ints
                };

                try {
                    // This endpoint is for mapping an existing resource.
                    // If the resource itself (name, capacity etc) needs update, use /api/admin/resources/{id}
                    const responseData = await apiCall(
                        `/api/admin/resources/${selectedResourceId}/map_info`, 
                        { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 
                        areaDefinitionStatusDiv 
                    );
                    showSuccess(areaDefinitionStatusDiv, `Area mapping saved for resource '${responseData.name || selectedResourceId}'!`);
                    const mapIdRefresh = hiddenFloorMapIdInput.value;
                    if (mapIdRefresh) {
                        await populateResourcesForMapping(mapIdRefresh); // Refresh dropdown
                        await fetchAndDrawExistingMapAreas(mapIdRefresh); // Redraw map areas
                    }
                    currentDrawnRect = null; 
                    if (selectedAreaForEditing && selectedAreaForEditing.resource_id === parseInt(selectedResourceId)) { // Use resource_id
                        selectedAreaForEditing.map_coordinates = coordinates; 
                        // Update other fields if they were part of payload and response
                    }
                    redrawCanvas(); 
                } catch (error) {
                    console.error('Error saving area on map:', error.message);
                }
            });
        }

        const deleteSelectedAreaBtn = document.getElementById('delete-selected-area-btn');
        const editSelectedAreaBtn = document.getElementById('edit-selected-area-btn'); 

        if (deleteSelectedAreaBtn) {
            deleteSelectedAreaBtn.addEventListener('click', async function() {
                console.log('Attempting to delete area. Current selectedAreaForEditing:', JSON.parse(JSON.stringify(selectedAreaForEditing || {}))); // DEBUG
                if (!selectedAreaForEditing || !selectedAreaForEditing.id) {
                    alert("No area selected for deletion, or selected area has no valid resource ID."); return;
                }
                const resourceName = selectedAreaForEditing.name || `ID: ${selectedAreaForEditing.id}`;
                if (!confirm(`Are you sure you want to remove the map mapping for resource: ${resourceName}?`)) return;
    
                showLoading(areaDefinitionStatusDiv, `Deleting mapping for ${resourceName}...`);
                try {
                    const resourceIdForDeletion = selectedAreaForEditing.id; // This should be the resource_id
                    const responseData = await apiCall(
                        `/api/admin/resources/${resourceIdForDeletion}/map_info`,
                        { method: 'DELETE' },
                        areaDefinitionStatusDiv
                    );
                    showSuccess(areaDefinitionStatusDiv, responseData.message || `Mapping for '${resourceName}' deleted.`);
                    selectedAreaForEditing = null;
                    const btnsDiv = document.getElementById('edit-delete-buttons');
                    if(btnsDiv) btnsDiv.style.display = 'none';
                    if(defineAreaForm) defineAreaForm.reset();
                    if(resourceToMapSelect) resourceToMapSelect.value = '';
                    if(bookingPermissionDropdown) bookingPermissionDropdown.value = "";
                    if (authorizedRolesCheckboxContainer) authorizedRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
                    // Also clear authorizedUsersCheckboxContainer if it's being used in this form
                    if (authorizedUsersCheckboxContainer) authorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
                    currentDrawnRect = null;
                    const mapIdRefresh = hiddenFloorMapIdInput.value;
                    if (mapIdRefresh) {
                        await fetchAndDrawExistingMapAreas(mapIdRefresh);
                        await populateResourcesForMapping(mapIdRefresh);
                    }
                    redrawCanvas();
                } catch (error) {
                    console.error('Error deleting map mapping:', error.message);
                     // apiCall should handle displaying the error in areaDefinitionStatusDiv
                }
            });
        }

        if (editSelectedAreaBtn) { // This button just populates the form for editing
            editSelectedAreaBtn.addEventListener('click', function() {
                if (!selectedAreaForEditing || !selectedAreaForEditing.id || !selectedAreaForEditing.map_coordinates) {
                    alert("No area selected for editing, or selected area is missing data."); return;
                }
                if (resourceToMapSelect) resourceToMapSelect.value = selectedAreaForEditing.id;
                const coords = selectedAreaForEditing.map_coordinates;
                if (coords.type === 'rect') {
                    updateCoordinateInputs(coords);
                    if (bookingPermissionDropdown) bookingPermissionDropdown.value = selectedAreaForEditing.booking_restriction || "";
                    
                    const allowedUserIdsArr = (selectedAreaForEditing.allowed_user_ids || "").split(',').filter(id => id.trim() !== '');
                    if(authorizedUsersCheckboxContainer) {
                        authorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                            cb.checked = allowedUserIdsArr.includes(cb.value);
                        });
                    }
                    if (authorizedRolesCheckboxContainer) {
                        const selectedRoleIds = (selectedAreaForEditing.roles || []).map(r => String(r.id));
                        authorizedRolesCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                            cb.checked = selectedRoleIds.includes(cb.value);
                        });
                    }

                    currentDrawnRect = { ...coords };
                    redrawCanvas();
                } else {
                    alert("Cannot edit non-rectangular areas with this form.");
                    if(defineAreaForm) defineAreaForm.reset(); currentDrawnRect = null; redrawCanvas(); return;
                }
                const defineAreaFormElement = document.getElementById('define-area-form');
                if (defineAreaFormElement) defineAreaFormElement.scrollIntoView({ behavior: 'smooth' });
                const submitButton = defineAreaFormElement ? defineAreaFormElement.querySelector('button[type="submit"]') : null;
                if (submitButton) submitButton.textContent = 'Update Area Mapping';
                resourceToMapSelect.dispatchEvent(new Event('change'));
            });
        }

        if (resourceToMapSelect && resourceActionsContainer) {
            resourceToMapSelect.addEventListener('change', function() {
                const selectedOption = this.options[this.selectedIndex];
                resourceActionsContainer.innerHTML = ''; 
    
                if (selectedOption && selectedOption.value) { 
                    const resourceId = selectedOption.dataset.resourceId;
                    const resourceStatus = selectedOption.dataset.resourceStatus;
    
                    if (existingMapAreas && typeof redrawCanvas === 'function') { 
                        const area = existingMapAreas.find(a => a.id === parseInt(resourceId));
                        const currentMapDisplayingId = hiddenFloorMapIdInput ? parseInt(hiddenFloorMapIdInput.value) : null;
                        if (area && area.map_coordinates && area.floor_map_id === currentMapDisplayingId) { 
                            selectedAreaForEditing = area;
                        } else {
                            selectedAreaForEditing = null; 
                        }
                        redrawCanvas(); 
                    }
    
                    if (resourceStatus === 'draft') {
                        const publishBtn = document.createElement('button');
                        publishBtn.id = 'publish-resource-btn'; publishBtn.textContent = 'Publish This Resource';
                        publishBtn.type = 'button'; publishBtn.className = 'button'; 
                        publishBtn.dataset.resourceId = resourceId;
                        publishBtn.addEventListener('click', handlePublishResource); 
                        resourceActionsContainer.appendChild(publishBtn);
                    } else { // Covers 'published', 'archived', etc.
                        const statusText = document.createElement('p');
                        statusText.textContent = `Status: ${resourceStatus.charAt(0).toUpperCase() + resourceStatus.slice(1)}`;
                        resourceActionsContainer.appendChild(statusText);
                    }
                } else {
                    selectedAreaForEditing = null;
                    if (typeof redrawCanvas === 'function') redrawCanvas();
                    resourceActionsContainer.innerHTML = '<p><em>Select a resource to see its status or actions.</em></p>';
                }
            });
        }
        async function handlePublishResource(event) {
            const resourceId = event.target.dataset.resourceId;
            if (!resourceId || !confirm(`Publish resource ID ${resourceId}?`)) return;
            
            const actionsContainer = document.getElementById('resource-actions-container'); 
            try {
                const responseData = await apiCall(
                    `/api/admin/resources/${resourceId}/publish`, { method: 'POST' }, actionsContainer
                );
                showSuccess(actionsContainer, responseData.message || `Resource ${resourceId} published!`);
                alert(responseData.message || `Resource ${resourceId} published!`);
                const currentMapId = hiddenFloorMapIdInput.value; 
                if (currentMapId) await populateResourcesForMapping(currentMapId); 
                const resSelect = document.getElementById('resource-to-map');
                if (resSelect) { 
                    const opt = Array.from(resSelect.options).find(o => o.dataset.resourceId === resourceId);
                    if (opt) opt.dataset.resourceStatus = 'published';
                    resSelect.dispatchEvent(new Event('change'));
                }
                if (currentMapId) await fetchAndDrawExistingMapAreas(currentMapId);
            } catch (error) {
                alert(`Failed to publish: ${error.message}.`);
                const resSelect = document.getElementById('resource-to-map'); 
                if (resSelect && resSelect.value === resourceId) resSelect.dispatchEvent(new Event('change'));
            }
        }
    } 

    // Map View Page Specific Logic
    const mapContainer = document.getElementById('map-container');
    if (mapContainer) { 
        // ... (Keep existing map view page logic as is) ...
        const mapId = mapContainer.dataset.mapId;
        const mapLoadingStatusDiv = document.getElementById('map-loading-status');
        const mapViewTitleH1 = document.getElementById('map-view-title');
        const mapAvailabilityDateInput = document.getElementById('map-availability-date'); // This is for map_view.html
        const mapLocationSelect = document.getElementById('map-location-select');
        const mapFloorSelect = document.getElementById('map-floor-select');
        let allMapInfo = [];
        
        if(mapAvailabilityDateInput) { 
            mapAvailabilityDateInput.value = getTodayDateString(); // Use global getTodayDateString
        }

        function updateFloorSelectOptions() {
            if (!mapFloorSelect) return;
            const loc = mapLocationSelect ? mapLocationSelect.value : '';
            const floors = [...new Set(allMapInfo.filter(m => !loc || m.location === loc).map(m => m.floor).filter(f => f))];
            mapFloorSelect.innerHTML = '<option value="">All</option>';
            floors.forEach(fl => mapFloorSelect.add(new Option(fl, fl)));
        }

        function setSelectorsFromCurrentMap() {
            const current = allMapInfo.find(m => m.id == mapId);
            if (!current) return;
            if (mapLocationSelect) mapLocationSelect.value = current.location || '';
            updateFloorSelectOptions();
            if (mapFloorSelect) mapFloorSelect.value = current.floor || '';
        }

        function handleSelectorChange() {
            const loc = mapLocationSelect ? mapLocationSelect.value : '';
            const fl = mapFloorSelect ? mapFloorSelect.value : '';
            const found = allMapInfo.find(m => (!loc || m.location === loc) && (!fl || m.floor === fl));
            if (found && found.id != mapId) {
                window.location.href = `/map_view/${found.id}${window.location.search}`; // Preserve query params like date
            }
        }

        async function loadMapSelectors() {
            try {
                const maps = await apiCall('/api/admin/maps', {}, mapLoadingStatusDiv);
                allMapInfo = maps || [];
                if (mapLocationSelect) {
                    const locations = [...new Set(allMapInfo.map(m => m.location).filter(l => l))];
                    mapLocationSelect.innerHTML = '<option value="">All</option>';
                    locations.forEach(loc => mapLocationSelect.add(new Option(loc, loc)));
                }
                updateFloorSelectOptions();
                setSelectorsFromCurrentMap();
            } catch (e) { console.error('Error loading map selector data', e); }
        }

        if (mapLocationSelect) mapLocationSelect.addEventListener('change', () => { updateFloorSelectOptions(); handleSelectorChange(); });
        if (mapFloorSelect) mapFloorSelect.addEventListener('change', handleSelectorChange);

        loadMapSelectors();

        async function fetchAndRenderMap(currentMapId, dateString) {
            showLoading(mapLoadingStatusDiv, 'Loading map details...');
            mapContainer.innerHTML = ''; 

            try {
                const apiUrl = dateString ? `/api/map_details/${currentMapId}?date=${dateString}` : `/api/map_details/${currentMapId}`;
                const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv); 

                mapContainer.style.backgroundImage = `url(${data.map_details.image_url})`;
                if (mapViewTitleH1) mapViewTitleH1.textContent = `Map View: ${data.map_details.name}`;
                
                if (data.mapped_resources && data.mapped_resources.length > 0) {
                    data.mapped_resources.forEach(resource => {
                        if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                            const coords = resource.map_coordinates;
                            const areaDiv = document.createElement('div');
                            areaDiv.className = 'resource-area';
                            areaDiv.style.left = `${coords.x}px`; areaDiv.style.top = `${coords.y}px`;
                            areaDiv.style.width = `${coords.width}px`; areaDiv.style.height = `${coords.height}px`;
                            areaDiv.textContent = resource.name;
                            areaDiv.dataset.resourceId = resource.id;
                            if (resource.image_url) areaDiv.dataset.imageUrl = resource.image_url;

                            let availabilityClass = 'resource-area-unknown'; 
                            const bookings = resource.bookings_on_date;

                            if (bookings) { 
                                if (bookings.length === 0) {
                                    availabilityClass = 'resource-area-available';
                                } else {
                                    let totalBookedMinutes = 0;
                                    const workDayStartHour = 8; 
                                    const workDayEndHour = 17; 

                                    bookings.forEach(booking => {
                                        const [sH, sM, sS] = booking.start_time.split(':').map(Number);
                                        const [eH, eM, eSS] = booking.end_time.split(':').map(Number);
                                        const bookingStart = new Date(2000, 0, 1, sH, sM, sS);
                                        const bookingEnd = new Date(2000, 0, 1, eH, eM, eSS);
                                        const slotStartInWorkHours = new Date(2000, 0, 1, Math.max(workDayStartHour, sH), sM, sS);
                                        const slotEndInWorkHours = new Date(2000, 0, 1, Math.min(workDayEndHour, eH), eM, eSS);
                                        if (slotEndInWorkHours > slotStartInWorkHours) {
                                            totalBookedMinutes += (slotEndInWorkHours - slotStartInWorkHours) / (1000 * 60);
                                        }
                                    });
                                    const workDayDurationMinutes = (workDayEndHour - workDayStartHour) * 60;
                                    if (totalBookedMinutes >= workDayDurationMinutes * 0.75) { 
                                        availabilityClass = 'resource-area-fully-booked';
                                    } else if (totalBookedMinutes > 0) {
                                        availabilityClass = 'resource-area-partially-booked';
                                    } else { 
                                        availabilityClass = 'resource-area-available';
                                    }
                                }
                            }
                            
                            let mapAreaAvailabilityClass = availabilityClass; 
                            let isMapAreaClickable = true; 
                            const currentUserId = parseInt(sessionStorage.getItem('loggedInUserId'), 10);
                            const currentUserIsAdmin = sessionStorage.getItem('loggedInUserIsAdmin') === 'true';

                            if (!checkUserPermissionForResource(resource, currentUserId, currentUserIsAdmin)) {
                                mapAreaAvailabilityClass = 'resource-area-restricted'; 
                                isMapAreaClickable = false;
                                areaDiv.title = `${resource.name} (Access Restricted)`;
                            } else {
                                areaDiv.title = resource.name; 
                            }
                            
                            areaDiv.classList.remove('resource-area-available', 'resource-area-partially-booked', 'resource-area-fully-booked', 'resource-area-unknown', 'resource-area-restricted', 'map-area-clickable');
                            areaDiv.classList.add(mapAreaAvailabilityClass);

                            if (isMapAreaClickable && mapAreaAvailabilityClass !== 'resource-area-fully-booked' && mapAreaAvailabilityClass !== 'resource-area-unknown') { 
                                areaDiv.classList.add('map-area-clickable');
                                const newAreaDiv = areaDiv.cloneNode(true);
                                areaDiv.parentNode?.replaceChild(newAreaDiv, areaDiv); // Check parentNode
                                areaDiv = newAreaDiv; 

                                areaDiv.addEventListener('click', function() {
                                    handleMapAreaClick(resource.id, resource.name, mapAvailabilityDateInput.value, areaDiv.dataset.imageUrl);
                                });
                            } else {
                                areaDiv.classList.remove('map-area-clickable');
                                const newAreaDiv = areaDiv.cloneNode(true); 
                                areaDiv.parentNode?.replaceChild(newAreaDiv, areaDiv);
                                areaDiv = newAreaDiv; 
                            }
                            mapContainer.appendChild(areaDiv);
                        }
                    });
                    hideMessage(mapLoadingStatusDiv); 
                } else {
                    showSuccess(mapLoadingStatusDiv, 'No resources are mapped to this floor plan yet.');
                }
            } catch (error) {
                showError(mapLoadingStatusDiv, `Error loading map: ${error.message}`);
                mapContainer.style.backgroundImage = 'none'; 
            }
        }

        const timeSlotModal = document.getElementById('time-slot-modal');
        const modalCloseBtn = timeSlotModal ? timeSlotModal.querySelector('.close-modal-btn') : null;
        const modalResourceNameSpan = document.getElementById('modal-resource-name');
        const modalResourceImage = document.getElementById('modal-resource-image');
        const modalDateSpan = document.getElementById('modal-date');
        const modalTimeSlotsListDiv = document.getElementById('modal-time-slots-list');
        const modalBookingTitleInput = document.getElementById('modal-booking-title');
        const modalConfirmBookingBtn = document.getElementById('modal-confirm-booking-btn');
        const modalStatusMessage = document.getElementById('modal-status-message');
        let selectedTimeSlotForBooking = null; 

        async function handleMapAreaClick(resourceId, resourceName, dateString, imageUrl) {
            showLoading(mapLoadingStatusDiv, `Fetching slots for ${resourceName}...`);
            try {
                const detailedBookedSlots = await apiCall(`/api/resources/${resourceId}/availability?date=${dateString}`, {}, modalStatusMessage);
                openTimeSlotSelectionModal(resourceId, resourceName, dateString, detailedBookedSlots, imageUrl);
                hideMessage(mapLoadingStatusDiv); 
                if (modalStatusMessage && !modalStatusMessage.classList.contains('error')) hideMessage(modalStatusMessage);
            } catch (error) {
                let errorMsgDisplayed = modalStatusMessage && modalStatusMessage.classList.contains('error');
                if (!errorMsgDisplayed && mapLoadingStatusDiv) showError(mapLoadingStatusDiv, `Error fetching slots for ${resourceName}.`);
                if (!errorMsgDisplayed && modalStatusMessage) showError(modalStatusMessage, `Error fetching slots: ${error.message}`);
                alert(`Could not load time slots for ${resourceName}. Details: ${error.message}`);
            }
        }

        function openTimeSlotSelectionModal(resourceId, resourceName, dateString, detailedBookedSlots, imageUrl) {
            if (!timeSlotModal) return;
            modalResourceNameSpan.textContent = resourceName;
            modalDateSpan.textContent = dateString;
            if (modalResourceImage) {
                if (imageUrl) { modalResourceImage.src = imageUrl; modalResourceImage.style.display = 'block'; } 
                else { modalResourceImage.style.display = 'none'; }
            }
            modalBookingTitleInput.value = ''; 
            modalTimeSlotsListDiv.innerHTML = ''; 
            modalStatusMessage.textContent = ''; 
            selectedTimeSlotForBooking = null; 
            if(modalConfirmBookingBtn) {
                modalConfirmBookingBtn.dataset.resourceId = resourceId;
                modalConfirmBookingBtn.dataset.dateString = dateString;
            }

            const workDayStartHour = 8; 
            const workDayEndHour = 17; 
            const slotDurationHours = 1;

            for (let hour = workDayStartHour; hour < workDayEndHour; hour += slotDurationHours) {
                const slotStart = new Date(`${dateString}T${String(hour).padStart(2, '0')}:00:00`);
                const slotEnd = new Date(slotStart.getTime() + slotDurationHours * 60 * 60 * 1000);
                const startTimeStr = `${String(slotStart.getHours()).padStart(2, '0')}:00`;
                const endTimeStr = `${String(slotEnd.getHours()).padStart(2, '0')}:00`;
                const slotLabel = `${startTimeStr} - ${endTimeStr}`;

                let isBooked = false; let myBookingInfo = null;
                for (const booked of detailedBookedSlots) {
                    const bookedStart = new Date(`${dateString}T${booked.start_time}`);
                    const bookedEnd = new Date(`${dateString}T${booked.end_time}`);
                    if (bookedStart < slotEnd && bookedEnd > slotStart) {
                        isBooked = true;
                        if (booked.user_name === sessionStorage.getItem('loggedInUserUsername')) myBookingInfo = booked; // Corrected key
                        break;
                    }
                }

                const slotDiv = document.createElement('div');
                slotDiv.classList.add('time-slot-item'); slotDiv.textContent = slotLabel;
                if (isBooked) {
                    slotDiv.classList.add('time-slot-booked');
                    if (myBookingInfo) {
                        slotDiv.textContent += ' (Your Booking)';
                        if (myBookingInfo.can_check_in) { // Assuming can_check_in is a boolean field
                            const btn = document.createElement('button');
                            btn.textContent = 'Check In'; btn.className = 'button button-sm button-success ms-2'; // Standardized classes
                            btn.addEventListener('click', async (e)=>{
                                e.stopPropagation();
                                try {
                                    await apiCall(`/api/bookings/${myBookingInfo.booking_id}/check_in`, {method: 'POST'}, modalStatusMessage); // Ensure POST
                                    btn.remove(); slotDiv.textContent = slotLabel + ' (Checked In)';
                                } catch (err) { console.error('Check in failed', err); }
                            });
                            slotDiv.appendChild(btn);
                        }
                    } else slotDiv.textContent += ' (Booked)';
                } else {
                    slotDiv.classList.add('time-slot-available');
                    slotDiv.dataset.startTime = startTimeStr; slotDiv.dataset.endTime = endTimeStr;
                    slotDiv.addEventListener('click', function() {
                        const previouslySelected = modalTimeSlotsListDiv.querySelector('.time-slot-selected');
                        if (previouslySelected) previouslySelected.classList.remove('time-slot-selected');
                        this.classList.add('time-slot-selected');
                        selectedTimeSlotForBooking = { startTimeStr: this.dataset.startTime, endTimeStr: this.dataset.endTime };
                        if(modalStatusMessage) modalStatusMessage.textContent = ''; 
                    });
                }
                modalTimeSlotsListDiv.appendChild(slotDiv);
            }
            timeSlotModal.style.display = 'block';
        }

        if (modalCloseBtn) modalCloseBtn.onclick = function() { timeSlotModal.style.display = "none"; selectedTimeSlotForBooking = null; }
        window.onclick = function(event) {
            if (event.target == timeSlotModal) { timeSlotModal.style.display = "none"; selectedTimeSlotForBooking = null; }
        }

        if (modalConfirmBookingBtn) {
            modalConfirmBookingBtn.addEventListener('click', async function() {
                modalStatusMessage.textContent = ''; 
                if (!selectedTimeSlotForBooking) { showError(modalStatusMessage, 'Please select an available time slot.'); return; }
                const loggedInUsername = sessionStorage.getItem('loggedInUserUsername'); // Corrected key
                if (!loggedInUsername) { showError(modalStatusMessage, 'Please login to make a booking.'); return; }

                const resourceId = this.dataset.resourceId; 
                const dateString = this.dataset.dateString; 
                const title = modalBookingTitleInput.value.trim();
                const bookingData = {
                    resource_id: parseInt(resourceId, 10), date_str: dateString,
                    start_time_str: selectedTimeSlotForBooking.startTimeStr, end_time_str: selectedTimeSlotForBooking.endTimeStr,
                    title: title, user_name: loggedInUsername // Corrected key
                };
                showLoading(modalStatusMessage, 'Submitting booking...');
                try {
                    const responseData = await apiCall('/api/bookings', { method: 'POST', body: JSON.stringify(bookingData) }, modalStatusMessage);
                    showSuccess(modalStatusMessage, `Booking for '${responseData.title || 'Untitled'}' (ID: ${responseData.id}) confirmed!`);
                    setTimeout(() => { if(timeSlotModal) timeSlotModal.style.display = "none"; selectedTimeSlotForBooking = null; }, 1500);
                    const mapIdRefresh = mapContainer ? mapContainer.dataset.mapId : null;
                    const dateRefresh = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : null;
                    if (mapIdRefresh && dateRefresh) fetchAndRenderMap(mapIdRefresh, dateRefresh);
                } catch (error) { console.error('Booking from map view modal failed:', error.message); }
            });
        }
        if (mapId) {
            const initialDate = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : getTodayDateString();
            fetchAndRenderMap(mapId, initialDate);
            mapAvailabilityDateInput.addEventListener('change', function() { fetchAndRenderMap(mapId, this.value); });
        } else { showError(mapLoadingStatusDiv, 'Map ID not found.'); }
    }

    const availableResourcesListDiv = document.getElementById('available-resources-now-list');
    if (availableResourcesListDiv) {
        // ... (Keep existing home page filter logic as is) ...
        const filterContainer = document.createElement('div');
        filterContainer.id = 'resource-filter-controls';
        filterContainer.innerHTML = `
            <label>Min Capacity: <input type="number" id="filter-capacity" min="1" class="form-control-sm"></label>
            <label>Equipment: <input type="text" id="filter-equipment" placeholder="Projector" class="form-control-sm"></label>
            <label>Tags: <input type="text" id="filter-tags" placeholder="tag1,tag2" class="form-control-sm"></label>
            <button id="apply-resource-filters" class="button button-primary">Apply Filters</button>
        `; // Added some classes for styling
        availableResourcesListDiv.parentElement.insertBefore(filterContainer, availableResourcesListDiv);
        document.getElementById('apply-resource-filters').addEventListener('click', displayAvailableResourcesNow);
        displayAvailableResourcesNow();
    }

    // --- Accessibility Controls ---
    // ... (Keep existing accessibility controls logic as is) ...
    // Theme Toggle (now in footer)
    const themeToggleBtn = document.getElementById('theme-toggle');
    if (themeToggleBtn) themeToggleBtn.addEventListener('click', toggleTheme);

    // High Contrast Toggle (new button in footer)
    const toggleHighContrastBtnNew = document.getElementById('toggle-high-contrast');
    if (toggleHighContrastBtnNew) {
        toggleHighContrastBtnNew.addEventListener('click', toggleHighContrast);
    }

    // Font Size Buttons (new buttons in footer)
    const increaseFontSizeBtnNew = document.getElementById('increase-font-size');
    if (increaseFontSizeBtnNew) {
        increaseFontSizeBtnNew.addEventListener('click', increaseFontSize);
    }

    const decreaseFontSizeBtnNew = document.getElementById('decrease-font-size');
    if (decreaseFontSizeBtnNew) {
        decreaseFontSizeBtnNew.addEventListener('click', decreaseFontSize);
    }

    const resetFontSizeBtnNew = document.getElementById('reset-font-size');
    if (resetFontSizeBtnNew) {
        resetFontSizeBtnNew.addEventListener('click', resetFontSize);
    }

    // Keep existing functions for these controls
    function toggleHighContrast() {
        document.body.classList.toggle('high-contrast');
        localStorage.setItem('highContrastEnabled', document.body.classList.contains('high-contrast'));
    }
    function loadHighContrastPreference() {
        if (localStorage.getItem('highContrastEnabled') === 'true') document.body.classList.add('high-contrast');
    }

    function applyTheme(theme) {
        if (theme === 'dark') document.body.classList.add('dark-theme');
        else document.body.classList.remove('dark-theme');
    }
    function toggleTheme() {
        const newTheme = document.body.classList.toggle('dark-theme') ? 'dark' : 'light';
        localStorage.setItem('theme', newTheme);
    }
    function loadThemePreference() {
        if (localStorage.getItem('theme') === 'dark') applyTheme('dark');
    }
    
    const BASE_FONT_SIZE_REM = 1.0, FONT_SIZE_STEP_REM = 0.1, MAX_FONT_SIZE_REM = 2.0, MIN_FONT_SIZE_REM = 0.7;
    function getCurrentRootFontSizeRem() {
        const currentSizeStyle = document.documentElement.style.fontSize;
        if (currentSizeStyle && currentSizeStyle.endsWith('rem')) return parseFloat(currentSizeStyle);
        const computedRootFontSize = getComputedStyle(document.documentElement).fontSize;
        if (computedRootFontSize && computedRootFontSize.endsWith('px')) {
            const rootBasePxFromCSS = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-size').trim().replace('px','')) || 16; // Ensure :root --font-size is read if set in px
            return parseFloat(computedRootFontSize) / rootBasePxFromCSS;
        }
        return BASE_FONT_SIZE_REM;
    }
    function changeFontSize(amountInRem) {
        let newSizeRem = Math.max(MIN_FONT_SIZE_REM, Math.min(getCurrentRootFontSizeRem() + amountInRem, MAX_FONT_SIZE_REM));
        document.documentElement.style.fontSize = `${newSizeRem}rem`;
        localStorage.setItem('rootFontSize', `${newSizeRem}rem`);
    }
    function increaseFontSize() { changeFontSize(FONT_SIZE_STEP_REM); }
    function decreaseFontSize() { changeFontSize(-FONT_SIZE_STEP_REM); }
    function resetFontSize() { document.documentElement.style.removeProperty('font-size'); localStorage.removeItem('rootFontSize'); }
    function loadFontSizePreference() {
        const savedFontSize = localStorage.getItem('rootFontSize');
        if (savedFontSize && savedFontSize.endsWith('rem') && !isNaN(parseFloat(savedFontSize))) {
            document.documentElement.style.fontSize = savedFontSize;
        } else localStorage.removeItem('rootFontSize');
    }
    // Event listeners for new font size buttons are already added above.

    if (manualBackupBtn) {
        const manualBackupStatusDiv = document.getElementById('manual-backup-status');
        manualBackupBtn.addEventListener('click', async () => {
            manualBackupBtn.disabled = true;
            showLoading(manualBackupStatusDiv, 'Manual sync in progress...');
            try {
                await apiCall('/api/admin/manual_backup', { method: 'POST' });
                showSuccess(manualBackupStatusDiv, 'Manual sync completed.');
                console.log('Manual sync completed');
            } catch (e) {
                showError(manualBackupStatusDiv, 'Manual sync failed.');
                console.error('Manual sync failed', e);
            } finally {
                manualBackupBtn.disabled = false;
            }
        });
    }

    loadHighContrastPreference(); loadFontSizePreference(); loadThemePreference();

    // --- Language Selection ---
    // ... (Keep existing language selection logic as is) ...
    const languageSelector = document.getElementById('language-selector');
    function handleLanguageChange() {
        const selectedLang = languageSelector.value;
        localStorage.setItem('selectedLanguage', selectedLang);
        const currentParams = new URLSearchParams(window.location.search);
        currentParams.set('lang', selectedLang);
        window.location.search = currentParams.toString();
    }
    function loadLanguagePreference() {
        const storedLang = localStorage.getItem('selectedLanguage');
        const currentParams = new URLSearchParams(window.location.search);
        const queryLang = currentParams.get('lang');
        if (storedLang) {
            if (languageSelector) languageSelector.value = storedLang;
            if (queryLang !== storedLang) {
                currentParams.set('lang', storedLang);
                window.location.search = currentParams.toString(); return;
            }
        } else if (queryLang && languageSelector) {
            languageSelector.value = queryLang;
            localStorage.setItem('selectedLanguage', queryLang);
        }
    }
    if (languageSelector) languageSelector.addEventListener('change', handleLanguageChange);
    loadLanguagePreference();

    // --- Real-time Updates via Socket.IO ---
    // ... (Keep existing Socket.IO logic as is) ...
    if (typeof io !== 'undefined') {
        const socket = io();
        socket.on('booking_updated', (data) => { // Added data argument
            console.log('Socket.IO: booking_updated received', data);
            // Calendar view on resources.html
            if (calendarTable && roomSelectDropdown && availabilityDateInputCalendar && roomSelectDropdown.value == data.resource_id) { // Check if update affects current view
                const selectedOption = roomSelectDropdown.selectedOptions[0];
                if (selectedOption) {
                    const resourceDetails = {
                        id: roomSelectDropdown.value,
                        booking_restriction: selectedOption.dataset.bookingRestriction,
                        allowed_user_ids: selectedOption.dataset.allowedUserIds,
                        roles: parseRolesFromDataset(selectedOption.dataset.roleIds)
                    };
                    fetchAndDisplayAvailability(resourceDetails.id, availabilityDateInputCalendar.value, resourceDetails);
                }
            }

            // Map view page
            if (typeof fetchAndRenderMap === 'function' && mapContainer && mapContainer.dataset.mapId) {
                // Check if the update is relevant to any resource on the current map
                // This might require fetching map details again or checking against currently displayed resources.
                // For simplicity, just refetch/render if any booking changes.
                // A more optimized approach would be to check if data.resource_id is on the current map.
                console.log('Socket.IO: Refreshing map view due to booking update.');
                const mapId = mapContainer.dataset.mapId;
                const dateInputMap = document.getElementById('map-availability-date'); // Date picker on map_view.html
                const dateStr = dateInputMap ? dateInputMap.value : getTodayDateString();
                fetchAndRenderMap(mapId, dateStr);
            }

            // Resource buttons grid on resources.html
            if (typeof updateAllButtonColors === 'function' && resourceButtonsContainer) {
                 console.log('Socket.IO: Refreshing resource button colors due to booking update for resource_id:', data.resource_id);
                 // More targeted update: only update the specific button if possible
                 const buttonToUpdate = resourceButtonsContainer.querySelector(`.resource-availability-button[data-resource-id="${data.resource_id}"]`);
                 if (buttonToUpdate && availabilityDateInput) { // availabilityDateInput is for resource buttons page
                     updateButtonColor(buttonToUpdate, availabilityDateInput.value);
                 } else if (buttonToUpdate) { // Fallback if date input not found (should not happen)
                     updateButtonColor(buttonToUpdate, getTodayDateString());
                 } else { // Fallback to full update if specific button not found (e.g. new resource added)
                    updateAllButtonColors();
                 }
            }
        });
        socket.on('connect', () => console.log('Socket.IO connected'));
        socket.on('disconnect', () => console.log('Socket.IO disconnected'));
        socket.on('connect_error', (err) => console.error('Socket.IO connection error:', err));
    }


    // --- User Dropdown Menu Logic (Global) ---
    // ... (Keep existing user dropdown logic as is) ...
    const userDropdownButtonGlobal = document.getElementById('user-dropdown-button');
    const userDropdownMenuGlobal = document.getElementById('user-dropdown-menu');
    if (userDropdownButtonGlobal && userDropdownMenuGlobal) {
        userDropdownButtonGlobal.addEventListener('click', function(event) {
            const isExpanded = userDropdownButtonGlobal.getAttribute('aria-expanded') === 'true' || false;
            userDropdownButtonGlobal.setAttribute('aria-expanded', !isExpanded);
            userDropdownMenuGlobal.style.display = isExpanded ? 'none' : 'block';
            event.stopPropagation(); 
        });
        window.addEventListener('click', function(event) {
            if (userDropdownMenuGlobal.style.display === 'block') {
                if (!userDropdownButtonGlobal.contains(event.target) && !userDropdownMenuGlobal.contains(event.target)) {
                    userDropdownMenuGlobal.style.display = 'none';
                    userDropdownButtonGlobal.setAttribute('aria-expanded', 'false');
                }
            }
        });
    }
    const logoutLinkDropdownGlobal = document.getElementById('logout-link-dropdown');
    if (logoutLinkDropdownGlobal && typeof handleLogout === 'function') { // Ensure handleLogout is defined
        logoutLinkDropdownGlobal.removeEventListener('click', handleLogout); // Prevent duplicates if script runs multiple times or parts are reloaded
        logoutLinkDropdownGlobal.addEventListener('click', handleLogout);
    }

    // --- Mobile Menu Toggle Logic ---
    const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
    const sidebarNav = document.getElementById('sidebar'); // nav#sidebar

    if (mobileMenuToggle && sidebarNav) {
        mobileMenuToggle.addEventListener('click', function() {
            sidebarNav.classList.toggle('sidebar-open');
            const isExpanded = sidebarNav.classList.contains('sidebar-open');
            this.setAttribute('aria-expanded', isExpanded);
            // Optional: Change hamburger to X icon
            if (isExpanded) {
                this.innerHTML = '<span>&times;</span>'; // Simple X
                this.style.fontSize = '2rem'; // Adjust X size if needed
            } else {
                this.innerHTML = '<span></span><span></span><span></span>'; // Hamburger bars
                this.style.fontSize = '1.5rem'; // Reset to original hamburger size
            }
        });
    }
});

[end of static/js/script.js]
