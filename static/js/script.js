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
        element.style.color = 'green';
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
        element.style.color = 'red';
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
    const welcomeMessageContainer = document.getElementById('welcome-message-container');
    const userDropdownContainer = document.getElementById('user-dropdown-container');
    const userDropdownButton = document.getElementById('user-dropdown-button');
    const userDropdownMenu = document.getElementById('user-dropdown-menu');
    const logoutLinkDropdown = document.getElementById('logout-link-dropdown');
    const myBookingsNavLink = document.getElementById('my-bookings-nav-link'); 
    const analyticsNavLink = document.getElementById('analytics-nav-link');

    const loginUrl = document.body.dataset.loginUrl || '/login';

    function setStateLoggedOut() {
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
        if (myBookingsNavLink) myBookingsNavLink.style.display = 'none'; 
        if (analyticsNavLink) analyticsNavLink.style.display = 'none';
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
                userDropdownButton.innerHTML = `<span class="user-icon">&#x1F464;</span> &#9662;`;
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
            if (myBookingsNavLink) { 
                myBookingsNavLink.style.display = 'list-item'; 
            }
            if (analyticsNavLink) {
                analyticsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
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

    const bookingForm = document.getElementById('booking-form');
    const bookingResultsDiv = document.getElementById('booking-results');
    const loginForm = document.getElementById('login-form');
    const loginMessageDiv = document.getElementById('login-message');

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
                updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails);
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

        function updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails) {
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
                
                let new_cell = cell.cloneNode(false); 
                new_cell.textContent = cellText; 
                new_cell.className = cellClass;  
                new_cell.dataset.timeSlot = cellTimeSlot; 
                cell.parentNode.replaceChild(new_cell, cell);
                cell = new_cell; 

                if (cellIsClickable) { 
                    cell.addEventListener('click', (event) => {
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
        
        const floorMapsListUl = document.getElementById('floor-maps-list');
        const floorMapsLoadingStatusDiv = document.getElementById('floor-maps-loading-status');
        const locationFilter = document.getElementById('location-filter');
        const floorFilter = document.getElementById('floor-filter');
        if (floorMapsListUl && floorMapsLoadingStatusDiv) {
            // ... (Keep existing floor map list logic as is) ...
            let allMaps = [];

            function renderMapLinks() {
                floorMapsListUl.innerHTML = '';
                const loc = locationFilter ? locationFilter.value : '';
                const fl = floorFilter ? floorFilter.value : '';
                const filtered = allMaps.filter(m => (!loc || m.location === loc) && (!fl || m.floor === fl));
                if (filtered.length === 0) {
                    floorMapsListUl.innerHTML = '<li>No floor maps match selection.</li>';
                    return;
                }
                filtered.forEach(map => {
                    const li = document.createElement('li');
                    const link = document.createElement('a');
                    link.href = `/map_view/${map.id}`;
                    link.textContent = map.name;
                    li.appendChild(link);
                    floorMapsListUl.appendChild(li);
                });
            }

            function updateFloorOptions() {
                if (!floorFilter) return;
                const loc = locationFilter ? locationFilter.value : '';
                const floors = [...new Set(allMaps.filter(m => !loc || m.location === loc).map(m => m.floor).filter(f => f))];
                floorFilter.innerHTML = '<option value="">All</option>';
                floors.forEach(f => {
                    const opt = new Option(f, f);
                    floorFilter.add(opt);
                });
            }

            async function fetchAndDisplayFloorMapLinks() {
                try {
                    const maps = await apiCall('/api/admin/maps', {}, floorMapsLoadingStatusDiv);
                    allMaps = maps || [];
                    if (locationFilter) {
                        const locations = [...new Set(allMaps.map(m => m.location).filter(l => l))];
                        locationFilter.innerHTML = '<option value="">All</option>';
                        locations.forEach(loc => locationFilter.add(new Option(loc, loc)));
                    }
                    updateFloorOptions();
                    renderMapLinks();
                } catch (error) {
                    if (floorMapsListUl) floorMapsListUl.innerHTML = '<li>Error loading floor maps.</li>';
                }
            }

            if (locationFilter) locationFilter.addEventListener('change', () => { updateFloorOptions(); renderMapLinks(); });
            if (floorFilter) floorFilter.addEventListener('change', renderMapLinks);

            fetchAndDisplayFloorMapLinks();
        }
    } 


    // --- START: Resources Page - Resource Buttons Grid & Modal ---
    const resourceButtonsContainer = document.getElementById('resource-buttons-container');
    if (resourceButtonsContainer) {
        console.log("Resource buttons page script initializing...");

        // 1. Initial Setup: DOM Elements & Variables
        const availabilityDateInput = document.getElementById('resource-availability-date'); // Date picker for this view
        const resourceLoadingStatusDiv = document.getElementById('resource-loading-status');

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

        // 2. fetchAndRenderResources() function
        async function fetchAndRenderResources() {
            console.log("Fetching all resources...");
            if (resourceLoadingStatusDiv) showLoading(resourceLoadingStatusDiv, "Loading resources...");
            else console.warn("resourceLoadingStatusDiv not found for fetchAndRenderResources");

            try {
                const resources = await apiCall('/api/resources', {}, resourceLoadingStatusDiv);
                allFetchedResources = resources || [];
                console.log("Raw resources fetched:", allFetchedResources);

                if (resourceButtonsContainer) resourceButtonsContainer.innerHTML = ''; // Clear previous buttons

                if (!allFetchedResources || allFetchedResources.length === 0) {
                    if (resourceLoadingStatusDiv) showSuccess(resourceLoadingStatusDiv, "No resources found.");
                    return;
                }

                allFetchedResources.forEach(resource => {
                    console.log("Creating button for resource:", resource.name, resource.id);
                    const button = document.createElement('button');
                    button.textContent = resource.name;
                    button.classList.add('button', 'resource-availability-button'); // General button styling + specific
                    button.dataset.resourceId = resource.id;
                    button.dataset.resourceName = resource.name;
                    button.dataset.imageUrl = resource.image_url || '';
                    // Add other necessary data attributes from resource if needed for checkUserPermissionForResource
                    button.dataset.bookingRestriction = resource.booking_restriction || "";
                    button.dataset.allowedUserIds = resource.allowed_user_ids || "";
                    button.dataset.roleIds = (resource.roles || []).map(r => r.id).join(',');


                    // Resource Button Click Listener
                    button.addEventListener('click', async function() {
                        console.log(`Resource button clicked: ${this.dataset.resourceName} (ID: ${this.dataset.resourceId})`);
                        const clickedButton = this; // Keep reference to the button

                        if (clickedButton.classList.contains('unavailable') && !clickedButton.classList.contains('partial')) {
                            console.log("Resource button is completely unavailable, click ignored.");
                            // Optionally show a small message or just do nothing
                            return;
                        }
                        
                        const resourceId = clickedButton.dataset.resourceId;
                        const resourceName = clickedButton.dataset.resourceName;
                        const selectedDate = availabilityDateInput ? availabilityDateInput.value : getTodayDateString();
                        const imageUrl = clickedButton.dataset.imageUrl;

                        console.log(`Modal to be opened for: ID=${resourceId}, Name=${resourceName}, Date=${selectedDate}`);

                        resetRpbmModal(); // Reset modal to initial state

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
                        // Store resourceId on the confirm button for later use during booking submission
                        if (modalConfirmBtn) modalConfirmBtn.dataset.resourceId = resourceId;


                        let bookings = currentResourceBookingsCache[resourceId + '_' + selectedDate];
                        if (!bookings) {
                            console.log(`No cached bookings for ${resourceId} on ${selectedDate}. Fetching...`);
                            try {
                                bookings = await apiCall(`/api/resources/${resourceId}/availability?date=${selectedDate}`, {}, modalStatusMsg);
                                currentResourceBookingsCache[resourceId + '_' + selectedDate] = bookings;
                                console.log("Bookings fetched and cached:", bookings);
                            } catch (error) {
                                console.error("Failed to fetch bookings for modal:", error);
                                // Error already shown by apiCall in modalStatusMsg.
                                // Optionally, prevent modal from opening or show error within modal more explicitly.
                                showError(modalStatusMsg, `Could not load availability for ${resourceName}.`);
                                if (bookingModal) bookingModal.style.display = 'block'; // Show modal to display error
                                return;
                            }
                        } else {
                            console.log(`Using cached bookings for ${resourceId} on ${selectedDate}:`, bookings);
                        }

                        // Slot Button Logic
                        const firstHalfBtn = document.getElementById('rpbm-slot-first-half');
                        const secondHalfBtn = document.getElementById('rpbm-slot-second-half');
                        const fullDayBtn = document.getElementById('rpbm-slot-full-day');

                        if (!firstHalfBtn || !secondHalfBtn || !fullDayBtn) {
                            console.error("One or more slot buttons not found in the modal!");
                            if (modalStatusMsg) showError(modalStatusMsg, "Modal slot buttons are missing. Cannot proceed.");
                            if (bookingModal) bookingModal.style.display = 'block';
                            return;
                        }
                        
                        // Reset slot buttons
                        [firstHalfBtn, secondHalfBtn, fullDayBtn].forEach(btn => {
                            btn.disabled = false;
                            btn.classList.remove('unavailable', 'booked', 'selected', 'partial'); // Ensure 'partial' is also reset
                            btn.classList.add('available');
                            // Reset text content (remove " (Booked)", " (Partial)")
                            const baseText = btn.textContent.split(" (")[0];
                            btn.textContent = baseText;
                        });

                        let isFirstHalfBooked = false;
                        let isSecondHalfBooked = false;

                        // Slot times are 08:00-12:00 and 13:00-17:00 as per earlier subtasks for this modal
                        const firstHalfSlot = { start: 8, end: 12 };
                        const secondHalfSlot = { start: 13, end: 17 };

                        if (bookings && bookings.length > 0) {
                            for (const booking of bookings) {
                                const bookingStartTime = parseInt(booking.start_time.split(':')[0], 10);
                                const bookingEndTime = parseInt(booking.end_time.split(':')[0], 10);

                                // Check for first half conflict
                                if (bookingStartTime < firstHalfSlot.end && bookingEndTime > firstHalfSlot.start) {
                                    isFirstHalfBooked = true;
                                    console.log("Conflict found for first half:", booking);
                                }
                                // Check for second half conflict
                                if (bookingStartTime < secondHalfSlot.end && bookingEndTime > secondHalfSlot.start) {
                                    isSecondHalfBooked = true;
                                    console.log("Conflict found for second half:", booking);
                                }
                            }
                        }
                        console.log(`Slot availability: First Half Booked: ${isFirstHalfBooked}, Second Half Booked: ${isSecondHalfBooked}`);

                        if (isFirstHalfBooked) {
                            firstHalfBtn.disabled = true;
                            firstHalfBtn.classList.add('unavailable', 'booked');
                            firstHalfBtn.classList.remove('available');
                            firstHalfBtn.textContent += " (Booked)";
                        }
                        if (isSecondHalfBooked) {
                            secondHalfBtn.disabled = true;
                            secondHalfBtn.classList.add('unavailable', 'booked');
                            secondHalfBtn.classList.remove('available');
                            secondHalfBtn.textContent += " (Booked)";
                        }
                        if (isFirstHalfBooked || isSecondHalfBooked) {
                            fullDayBtn.disabled = true;
                            fullDayBtn.classList.add('unavailable', 'booked'); // Or 'partial' if one half is available but full day isn't an option
                            fullDayBtn.classList.remove('available');
                            fullDayBtn.textContent += " (Unavailable)"; // Or more specific like " (Partially Booked)"
                        }
                        
                        if (bookingModal) bookingModal.style.display = 'block';
                        console.log("Booking modal displayed.");
                    });
                    if (resourceButtonsContainer) resourceButtonsContainer.appendChild(button);
                });
                
                await updateAllButtonColors(); // Update colors after rendering all buttons
                if (resourceLoadingStatusDiv && !resourceLoadingStatusDiv.classList.contains('error')) {
                     hideMessage(resourceLoadingStatusDiv); // Hide "Loading resources..." if no error occurred
                }

            } catch (error) {
                console.error("Failed to fetch and render resources:", error);
                // Error message already shown by apiCall in resourceLoadingStatusDiv
                if (resourceButtonsContainer) resourceButtonsContainer.innerHTML = '<p class="error">Could not load resources. Please try again later.</p>';
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
            } catch (error) {
                console.error("Error during Promise.all for updateAllButtonColors:", error);
                // Individual errors are handled in updateButtonColor. 
                // This catch is for Promise.all itself if it rejects for some reason not caught by individual calls.
                if (resourceLoadingStatusDiv) showError(resourceLoadingStatusDiv, "An error occurred while updating resource statuses.");
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
        
        // Initial call to fetch and render resources and their button states
        fetchAndRenderResources();
        console.log("Initial fetchAndRenderResources called.");

    } // --- END: Resources Page - Resource Buttons Grid & Modal ---


    // Admin Maps Page Specific Logic
    const adminMapsPageIdentifier = document.getElementById('upload-map-form');
    if (adminMapsPageIdentifier) { 
        // ... (Keep existing admin maps page logic as is) ...
        const uploadMapForm = document.getElementById('upload-map-form');
        const mapsListUl = document.getElementById('maps-list');
        const uploadStatusDiv = document.getElementById('upload-status'); 
        const adminMapsListStatusDiv = document.getElementById('admin-maps-list-status'); 

        async function fetchAndDisplayMaps() {
            if (!mapsListUl || !adminMapsListStatusDiv) return;
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
                    `; // Added "button" class
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
        
        const defineAreasSection = document.getElementById('define-areas-section');
        const selectedMapNameH3 = document.getElementById('selected-map-name');
        const selectedMapImageImg = document.getElementById('selected-map-image');
        const resourceToMapSelect = document.getElementById('resource-to-map');
        const defineAreaForm = document.getElementById('define-area-form'); 
        const hiddenFloorMapIdInput = document.getElementById('selected-floor-map-id');
        const areaDefinitionStatusDiv = document.getElementById('area-definition-status');
        const bookingPermissionDropdown = document.getElementById('booking-permission'); 
        const resourceActionsContainer = document.getElementById('resource-actions-container');
        const authorizedUsersCheckboxContainer = document.getElementById('authorized-users-checkbox-container'); // Added
        const authorizedRolesInput = document.getElementById('authorized-roles'); // Added


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

        // Populate Users for Checkbox List (if container exists)
        async function populateUserCheckboxes() {
            if (!authorizedUsersCheckboxContainer) return;
            authorizedUsersCheckboxContainer.innerHTML = '<em>Loading users...</em>';
            try {
                const users = await apiCall('/api/users'); // Assuming this endpoint exists
                authorizedUsersCheckboxContainer.innerHTML = ''; // Clear loading message
                if (users && users.length > 0) {
                    users.forEach(user => {
                        const div = document.createElement('div');
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.id = `user-${user.id}`;
                        checkbox.value = user.id;
                        checkbox.name = 'authorized_user_ids';
                        const label = document.createElement('label');
                        label.htmlFor = `user-${user.id}`;
                        label.textContent = user.username;
                        div.appendChild(checkbox);
                        div.appendChild(label);
                        authorizedUsersCheckboxContainer.appendChild(div);
                    });
                } else {
                    authorizedUsersCheckboxContainer.innerHTML = '<em>No users found.</em>';
                }
            } catch (error) {
                console.error("Failed to load users for checkboxes:", error);
                authorizedUsersCheckboxContainer.innerHTML = '<em class="error">Could not load users.</em>';
            }
        }
        populateUserCheckboxes(); // Call when admin map section is initialized


        async function fetchAndDrawExistingMapAreas(mapId) {
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
            redrawCanvas(); 
        }

        function redrawCanvas() {
            if (!canvasCtx) return;
            canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
    
            canvasCtx.font = "10px Arial";
            existingMapAreas.forEach(area => {
                if (selectedAreaForEditing && selectedAreaForEditing.id === area.id) {
                    return; 
                }
                if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                    const coords = area.map_coordinates;
                    canvasCtx.fillStyle = 'rgba(255, 0, 0, 0.1)';   
                    canvasCtx.strokeStyle = 'rgba(255, 0, 0, 0.7)'; 
                    canvasCtx.lineWidth = 1;

                    canvasCtx.fillRect(coords.x, coords.y, coords.width, coords.height);
                    canvasCtx.strokeRect(coords.x, coords.y, coords.width, coords.height);
                    
                    canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.7)'; 
                    canvasCtx.textAlign = "center";
                    canvasCtx.textBaseline = "middle";
                    if (coords.width > 30 && coords.height > 10) {
                         canvasCtx.fillText(area.name || `ID:${area.id}`, coords.x + coords.width / 2, coords.y + coords.height / 2, coords.width - 4);
                    }
                }
            });

            if (selectedAreaForEditing && selectedAreaForEditing.map_coordinates && selectedAreaForEditing.map_coordinates.type === 'rect') {
                const coords = selectedAreaForEditing.map_coordinates;
                
                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.2)'; 
                canvasCtx.strokeStyle = SELECTED_BORDER_COLOR;
                canvasCtx.lineWidth = SELECTED_LINE_WIDTH;
                
                canvasCtx.fillRect(coords.x, coords.y, coords.width, coords.height);
                canvasCtx.strokeRect(coords.x, coords.y, coords.width, coords.height);

                canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.9)'; 
                canvasCtx.textAlign = "center";
                canvasCtx.textBaseline = "middle";
                if (coords.width > 30 && coords.height > 10) {
                     canvasCtx.fillText(selectedAreaForEditing.name || `ID:${selectedAreaForEditing.id}`, coords.x + coords.width / 2, coords.y + coords.height / 2, coords.width - 4);
                }

                canvasCtx.fillStyle = HANDLE_COLOR;
                const halfHandle = HANDLE_SIZE / 2;
                canvasCtx.fillRect(coords.x - halfHandle, coords.y - halfHandle, HANDLE_SIZE, HANDLE_SIZE); 
                canvasCtx.fillRect(coords.x + coords.width - halfHandle, coords.y - halfHandle, HANDLE_SIZE, HANDLE_SIZE); 
                canvasCtx.fillRect(coords.x - halfHandle, coords.y + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE); 
                canvasCtx.fillRect(coords.x + coords.width - halfHandle, coords.y + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE); 
            }
    
            if (currentDrawnRect && currentDrawnRect.width !== undefined) {
                canvasCtx.strokeStyle = 'rgba(0, 0, 255, 0.7)'; 
                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.1)';   
                canvasCtx.lineWidth = 2;
                
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

        function updateCoordinateInputs(coords) {
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
                const resources = await apiCall('/api/resources', {}, defineAreasStatusDiv); 
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

        if (mapsListUl) {
            mapsListUl.addEventListener('click', async function(event) {
                if (event.target.classList.contains('select-map-for-areas-btn')) {
                    const button = event.target;
                    const mapId = button.dataset.mapId;
                    const mapName = button.dataset.mapName;
                    const mapImageUrl = button.dataset.mapImageUrl;

                    if (defineAreasSection) defineAreasSection.style.display = 'block';
                    if (selectedMapNameH3) selectedMapNameH3.textContent = `Defining Areas for: ${mapName}`;
                    if (selectedMapImageImg) {
                        selectedMapImageImg.src = mapImageUrl;
                        selectedMapImageImg.alt = mapName;
                    }
                    if (hiddenFloorMapIdInput) hiddenFloorMapIdInput.value = mapId; 

                    if (resourceToMapSelect) await populateResourcesForMapping(mapId);
                    if (defineAreasSection) defineAreasSection.scrollIntoView({ behavior: 'smooth' });

                    selectedMapImageImg.onload = () => {
                        if (drawingCanvas) {
                            drawingCanvas.width = selectedMapImageImg.clientWidth;
                            drawingCanvas.height = selectedMapImageImg.clientHeight;
                            canvasCtx = drawingCanvas.getContext('2d');
                            canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
                            isDrawing = false;
                            currentDrawnRect = null; 
                            
                            const currentMapIdForAreas = hiddenFloorMapIdInput.value; 
                            if (currentMapIdForAreas) {
                                fetchAndDrawExistingMapAreas(currentMapIdForAreas); 
                            } else {
                                existingMapAreas = []; 
                                redrawCanvas(); 
                            }

                            drawingCanvas.onmousedown = function(event) {
                                const clickX = event.offsetX;
                                const clickY = event.offsetY;
                                const editDeleteButtonsDiv = document.getElementById('edit-delete-buttons');

                                const getHandleUnderCursor = (x, y, rect) => {
                                    const half = HANDLE_SIZE / 2;
                                    if (x >= rect.x - half && x <= rect.x + half && y >= rect.y - half && y <= rect.y + half) return 'nw';
                                    if (x >= rect.x + rect.width - half && x <= rect.x + rect.width + half && y >= rect.y - half && y <= rect.y + half) return 'ne';
                                    if (x >= rect.x - half && x <= rect.x + half && y >= rect.y + rect.height - half && y <= rect.y + rect.height + half) return 'sw';
                                    if (x >= rect.x + rect.width - half && x <= rect.x + rect.width + half && y >= rect.y + rect.height - half && y <= rect.y + rect.height + half) return 'se';
                                    return null;
                                };

                                if (selectedAreaForEditing && selectedAreaForEditing.map_coordinates && selectedAreaForEditing.map_coordinates.type === 'rect') {
                                    const coords = selectedAreaForEditing.map_coordinates;
                                    const handle = getHandleUnderCursor(clickX, clickY, coords);
                                    if (handle) {
                                        isResizingArea = true; resizeHandle = handle; isDrawing = false; isMovingArea = false; currentDrawnRect = null;
                                        dragStartX = clickX; dragStartY = clickY;
                                        initialAreaX = coords.x; initialAreaY = coords.y; initialAreaWidth = coords.width; initialAreaHeight = coords.height;
                                        redrawCanvas(); return;
                                    }
                                    if (clickX >= coords.x && clickX <= coords.x + coords.width && clickY >= coords.y && clickY <= coords.y + coords.height) {
                                        isMovingArea = true; isDrawing = false; currentDrawnRect = null;
                                        dragStartX = clickX; dragStartY = clickY; initialAreaX = coords.x; initialAreaY = coords.y;
                                        redrawCanvas(); return;
                                    }
                                }
                        
                                let clickedOnExistingArea = false;
                                for (const area of existingMapAreas) {
                                    if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                                        const coords = area.map_coordinates;
                                        if (clickX >= coords.x && clickX <= coords.x + coords.width && clickY >= coords.y && clickY <= coords.y + coords.height) {
                                            selectedAreaForEditing = area; isDrawing = false; currentDrawnRect = null; clickedOnExistingArea = true;
                                            if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'block';
                                            
                                            updateCoordinateInputs(coords); // Update X,Y,W,H inputs
                                            if (resourceToMapSelect) resourceToMapSelect.value = area.resource_id; // Select resource in dropdown
                                            if (bookingPermissionDropdown) bookingPermissionDropdown.value = area.booking_restriction || "";
                                            
                                            const allowedUserIdsArr = (area.allowed_user_ids || "").split(',').filter(id => id.trim() !== '');
                                            if(authorizedUsersCheckboxContainer) {
                                                authorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                                                    cb.checked = allowedUserIdsArr.includes(cb.value);
                                                });
                                            }
                                            if(authorizedRolesInput) { // Assuming roles is array of {id, name}
                                                 authorizedRolesInput.value = (area.roles || []).map(r => r.id).join(',');
                                            }

                                            resourceToMapSelect.dispatchEvent(new Event('change')); 
                                            break; 
                                        }
                                    }
                                }
                        
                                if (!clickedOnExistingArea) { 
                                    selectedAreaForEditing = null; 
                                    if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'none';
                                    isDrawing = true; startX = clickX; startY = clickY;
                                    currentDrawnRect = { x: startX, y: startY, width: 0, height: 0 };
                                    
                                    const defineAreaFormElement = document.getElementById('define-area-form');
                                    if(defineAreaFormElement) {
                                        defineAreaFormElement.reset(); 
                                        const submitButton = defineAreaFormElement.querySelector('button[type="submit"]');
                                        if (submitButton) submitButton.textContent = 'Save New Area Mapping';
                                        // Clear user/role selections manually if reset() doesn't
                                        if(authorizedUsersCheckboxContainer) authorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
                                        if(authorizedRolesInput) authorizedRolesInput.value = '';
                                    }
                                    if (resourceToMapSelect) resourceToMapSelect.value = ''; 
                                    if (bookingPermissionDropdown) bookingPermissionDropdown.value = "";
                                    resourceToMapSelect.dispatchEvent(new Event('change')); // Update resource actions UI
                                }
                                redrawCanvas(); 
                            };

                            drawingCanvas.onmousemove = function(event) {
                                const currentX = event.offsetX; const currentY = event.offsetY;
                                if (isDrawing) {
                                    currentDrawnRect.width = currentX - startX; currentDrawnRect.height = currentY - startY;
                                    redrawCanvas();
                                } else if (isMovingArea && selectedAreaForEditing) {
                                    const deltaX = currentX - dragStartX; const deltaY = currentY - dragStartY;
                                    const coords = selectedAreaForEditing.map_coordinates;
                                    coords.x = initialAreaX + deltaX; coords.y = initialAreaY + deltaY;
                                    updateCoordinateInputs(coords); currentDrawnRect = { ...coords }; 
                                    redrawCanvas();
                                } else if (isResizingArea && selectedAreaForEditing) {
                                    const deltaX = currentX - dragStartX; const deltaY = currentY - dragStartY;
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
                                    updateCoordinateInputs(coords); currentDrawnRect = { ...coords };
                                    redrawCanvas();
                                }
                            };

                            drawingCanvas.onmouseup = async function(event) {
                                if (isDrawing) {
                                    isDrawing = false;
                                    let {x,y,width,height} = currentDrawnRect;
                                    if (width < 0) { x += width; width = -width; }
                                    if (height < 0) { y += height; height = -height; }
                                    currentDrawnRect = { x, y, width, height };
                                    updateCoordinateInputs(currentDrawnRect);
                                    redrawCanvas();
                                } else if ((isMovingArea || isResizingArea) && selectedAreaForEditing) {
                                    isMovingArea = false; isResizingArea = false;
                                    const coords = selectedAreaForEditing.map_coordinates; // Already updated by onmousemove
                                    updateCoordinateInputs(coords); // Ensure form reflects final state
                                    await saveSelectedAreaDimensions(coords); // API call to save new dimensions
                                    redrawCanvas();
                                }
                            };
                        }
                    };
                    if (selectedMapImageImg.complete && selectedMapImageImg.src && selectedMapImageImg.src !== 'data:,') {
                        selectedMapImageImg.onload(); 
                    }
                }
            });
        }

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
                const roleIdsStr = authorizedRolesInput ? authorizedRolesInput.value : "";


                const payload = { 
                    floor_map_id: floorMapId, 
                    coordinates: coordinates,
                    // Send other properties if the form is extended to manage them directly
                    // For now, assuming these are managed on the main Resource Management page,
                    // and map_info PUT only updates map-specific data.
                    // If you want to update these here, add them to payload:
                    // booking_restriction: bookingPermissionDropdown.value,
                    // allowed_user_ids: selectedUserIds.join(','), // Send as comma-separated string
                    // role_ids: roleIdsStr.split(',').filter(id => id.trim() !== '').map(id => parseInt(id)) // Send as array of ints
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
                if (!selectedAreaForEditing || !selectedAreaForEditing.id) { // Check against resource_id
                    alert("No area selected for deletion, or selected area has no resource ID."); return;
                }
                const resourceName = selectedAreaForEditing.name || `ID: ${selectedAreaForEditing.id}`;
                if (!confirm(`Are you sure you want to remove the map mapping for resource: ${resourceName}?`)) return;
    
                showLoading(areaDefinitionStatusDiv, `Deleting mapping for ${resourceName}...`);
                try {
                    // Using selectedAreaForEditing.id which should be the resource_id
                    const responseData = await apiCall(
                        `/api/admin/resources/${selectedAreaForEditing.id}/map_info`, 
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
                    currentDrawnRect = null; 
                    const mapIdRefresh = hiddenFloorMapIdInput.value;
                    if (mapIdRefresh) {
                        await fetchAndDrawExistingMapAreas(mapIdRefresh); 
                        await populateResourcesForMapping(mapIdRefresh);   
                    }
                    redrawCanvas(); 
                } catch (error) {
                    console.error('Error deleting map mapping:', error.message);
                }
            });
        }

        if (editSelectedAreaBtn) { // This button just populates the form for editing
            editSelectedAreaBtn.addEventListener('click', function() {
                if (!selectedAreaForEditing || !selectedAreaForEditing.id || !selectedAreaForEditing.map_coordinates) {
                    alert("No area selected for editing, or selected area is missing data."); return;
                }
                if (resourceToMapSelect) resourceToMapSelect.value = selectedAreaForEditing.id; // resource_id
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
                    if(authorizedRolesInput) {
                        authorizedRolesInput.value = (selectedAreaForEditing.roles || []).map(r => r.id).join(',');
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
    const toggleHighContrastBtn = document.getElementById('toggle-high-contrast');
    const themeToggleBtn = document.getElementById('theme-toggle');
    const increaseFontSizeBtn = document.getElementById('increase-font-size');
    const decreaseFontSizeBtn = document.getElementById('decrease-font-size');
    const resetFontSizeBtn = document.getElementById('reset-font-size');

    function toggleHighContrast() {
        document.body.classList.toggle('high-contrast');
        localStorage.setItem('highContrastEnabled', document.body.classList.contains('high-contrast'));
    }
    function loadHighContrastPreference() {
        if (localStorage.getItem('highContrastEnabled') === 'true') document.body.classList.add('high-contrast');
    }
    if (toggleHighContrastBtn) toggleHighContrastBtn.addEventListener('click', toggleHighContrast);

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
    if (themeToggleBtn) themeToggleBtn.addEventListener('click', toggleTheme);
    
    const BASE_FONT_SIZE_REM = 1.0, FONT_SIZE_STEP_REM = 0.1, MAX_FONT_SIZE_REM = 2.0, MIN_FONT_SIZE_REM = 0.7;
    function getCurrentRootFontSizeRem() {
        const currentSizeStyle = document.documentElement.style.fontSize;
        if (currentSizeStyle && currentSizeStyle.endsWith('rem')) return parseFloat(currentSizeStyle);
        const computedRootFontSize = getComputedStyle(document.documentElement).fontSize;
        if (computedRootFontSize && computedRootFontSize.endsWith('px')) {
            const rootBasePxFromCSS = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-size').trim().replace('px','')) || 16;
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
    if (increaseFontSizeBtn) increaseFontSizeBtn.addEventListener('click', increaseFontSize);
    if (decreaseFontSizeBtn) decreaseFontSizeBtn.addEventListener('click', decreaseFontSize);
    if (resetFontSizeBtn) resetFontSizeBtn.addEventListener('click', resetFontSize);

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

});
