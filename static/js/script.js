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
        element.textContent = message;
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
 * Standardized API call helper function.
 * @param {string} url - The URL to fetch.
 * @param {object} options - Fetch options (method, headers, body, etc.).
 * @param {HTMLElement} [messageElement=null] - Element to display success/error messages.
 * @returns {Promise<object>} - The JSON response data.
 * @throws {Error} - Throws an error if the API call fails or returns a non-ok response.
 */
async function apiCall(url, options = {}, messageElement = null) {
    if (messageElement) showLoading(messageElement, 'Processing...');

    try {
        const response = await fetch(url, options);
        let responseData;
        try {
            responseData = await response.json();
        } catch (e) {
            // Handle cases where response is not JSON (e.g., server error page)
            if (!response.ok) {
                console.error(`API call to ${url} failed with status ${response.status}. Response not JSON.`, response);
                const errorText = `API Error: ${response.status} - ${response.statusText || 'Server error, response not JSON.'}`;
                if (messageElement) showError(messageElement, errorText);
                throw new Error(errorText);
            }
            // If response.ok but not JSON, this is unusual but could be a 204 No Content
            console.warn(`API call to ${url} was OK but response not JSON.`, response);
            responseData = { success: true, message: response.statusText || "Operation successful (no content)." }; 
        }

        if (!response.ok) {
            const errorMsg = responseData.error || responseData.message || `HTTP error! status: ${response.status}`;
            console.error(`API call to ${url} failed:`, errorMsg, responseData);
            if (messageElement) showError(messageElement, errorMsg);
            throw new Error(errorMsg);
        }
        
        // If there's a success message in responseData, show it
        if (messageElement && responseData.message && response.ok) { // Only show explicit success messages if provided
             showSuccess(messageElement, responseData.message);
        } else if (messageElement && !responseData.error) { // If no error and no specific message, hide loading.
            hideMessage(messageElement); 
        }
        return responseData;

    } catch (error) {
        // This catch handles network errors (fetch itself fails) or errors thrown from above
        console.error(`Network or other error during API call to ${url}:`, error);
        if (messageElement) {
            showError(messageElement, error.message || "Request failed. Please check your connection.");
        }
        throw error; // Re-throw the error so calling function can also handle if needed
    }
}


// --- Authentication Logic ---
async function updateAuthLink() {
    const authLinkContainer = document.getElementById('auth-link-container');
    const adminMapsNavLink = document.getElementById('admin-maps-nav-link');
    const welcomeMessageContainer = document.getElementById('welcome-message-container');
    const userDropdownContainer = document.getElementById('user-dropdown-container');
    const userDropdownButton = document.getElementById('user-dropdown-button');
    const userDropdownMenu = document.getElementById('user-dropdown-menu');
    const logoutLinkDropdown = document.getElementById('logout-link-dropdown');
    const myBookingsNavLink = document.getElementById('my-bookings-nav-link'); // Added

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
        if (myBookingsNavLink) myBookingsNavLink.style.display = 'none'; // Added
    }

    try {
        // Using apiCall helper. No specific messageElement for this, errors are handled by resetting UI.
        const data = await apiCall('/api/auth/status'); 

        if (data.logged_in && data.user) {
            sessionStorage.setItem('loggedInUserUsername', data.user.username);
            sessionStorage.setItem('loggedInUserIsAdmin', data.user.is_admin ? 'true' : 'false');
            sessionStorage.setItem('loggedInUserId', data.user.id);

            if (welcomeMessageContainer) {
                welcomeMessageContainer.textContent = `Welcome, ${data.user.username}!`;
                welcomeMessageContainer.style.display = 'list-item';
            }

            if (userDropdownContainer) userDropdownContainer.style.display = 'list-item';
            if (userDropdownButton) {
                userDropdownButton.innerHTML = `${data.user.username} &#9662;`;
                userDropdownButton.setAttribute('aria-expanded', 'false');
            }
            if (userDropdownMenu) userDropdownMenu.style.display = 'none'; 
            if (authLinkContainer) authLinkContainer.style.display = 'none';
            if (adminMapsNavLink) {
                adminMapsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
            if (myBookingsNavLink) { // Added
                myBookingsNavLink.style.display = 'list-item'; // Show if logged in
            }

            if (logoutLinkDropdown) {
                logoutLinkDropdown.removeEventListener('click', handleLogout); // Prevent duplicates
                logoutLinkDropdown.addEventListener('click', handleLogout);
            }
        } else {
            setStateLoggedOut();
        }
    } catch (error) {
        // apiCall already logged the error. Reset UI to logged-out state.
        setStateLoggedOut();
    }
}

async function handleLogout(event) {
    if (event) event.preventDefault();
    
    // No specific message element for logout link, errors will be alerted or handled in catch.
    try {
        // apiCall will throw an error if not response.ok
        const responseData = await apiCall('/api/auth/logout', { method: 'POST' });

        console.log("Logout successful from API:", responseData.message || "Logged out");
        // Clear all session storage related to user
        sessionStorage.removeItem('loggedInUserUsername');
        sessionStorage.removeItem('loggedInUserIsAdmin');
        sessionStorage.removeItem('loggedInUserId');
        
        await updateAuthLink(); // Refresh navigation and UI

        const loginUrl = document.body.dataset.loginUrl || '/login';
        if (window.location.pathname.startsWith('/admin')) {
            window.location.href = '/'; // Redirect from admin to home
        } else if (window.location.pathname !== loginUrl) {
            window.location.href = loginUrl; // Redirect to login if not already there
        }
        // If on login page, updateAuthLink handles UI, no redirect needed.

    } catch (error) {
        // apiCall helper would have logged the error. Alert a generic message.
        alert("Logout failed. Please try again or check the console for details.");
        // Ensure UI is in a logged-out state even if API call had issues
        await updateAuthLink();
    }
}


// --- Home Page: Display Available Resources Now ---
async function displayAvailableResourcesNow() {
    const availableResourcesListDiv = document.getElementById('available-resources-now-list');
    if (!availableResourcesListDiv) return; 

    showLoading(availableResourcesListDiv, 'Loading available resources...');

    try {
        const now = new Date();
        const currentDateYMD = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        const currentHour = now.getHours();

        // Fetch all published resources using apiCall
        // The API /api/resources should ideally only return published resources.
        // The subtask mentions: "In displayAvailableResourcesNow, the check resource.status !== 'published' is redundant 
        // if the API /api/resources already filters by published status. Verify API behavior and remove client-side check if appropriate."
        // Assuming API filters, so no client-side status check here for now.
        const resources = await apiCall('/api/resources', {}, availableResourcesListDiv);

        if (!resources || resources.length === 0) {
            showSuccess(availableResourcesListDiv, 'No resources found.'); // Use showSuccess for neutral info
            return;
        }

        const availableNowResources = [];
        // Use Promise.allSettled to handle individual availability fetch errors gracefully
        const availabilityResults = await Promise.allSettled(resources.map(resource => 
            apiCall(`/api/resources/${resource.id}/availability?date=${currentDateYMD}`)
            // No specific message element for these individual calls to avoid UI clutter. Errors are logged by apiCall.
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
            } else {
                // apiCall already logged the error for this specific resource's availability check.
                // console.warn(`Could not fetch availability for resource ${resource.id}, skipping. Reason: ${availabilityResult.reason.message}`);
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
            // Clear "Loading..." or any previous message and show the list
            availableResourcesListDiv.innerHTML = ''; 
            availableResourcesListDiv.appendChild(ul);
        }

    } catch (error) {
        // This catch handles failure of the primary '/api/resources' call or other unexpected errors.
        // apiCall for '/api/resources' would have already shown an error in availableResourcesListDiv.
        console.error('Critical Error in displayAvailableResourcesNow:', error.message);
        // Ensure an error message is shown if not already by a nested apiCall.
        if (!availableResourcesListDiv.classList.contains('error')) {
             showError(availableResourcesListDiv, 'Error fetching available resources. Please try refreshing.');
        }
    }
}


document.addEventListener('DOMContentLoaded', function() {
    // Set login URL on body for dynamic link creation
    // Simplified login URL setup (as per subtask)
    document.body.dataset.loginUrl = document.getElementById('login-form') ? "#" : "/login";
    
    updateAuthLink(); // Call on every page load

    const bookingForm = document.getElementById('booking-form');
    const bookingResultsDiv = document.getElementById('booking-results');
    const loginForm = document.getElementById('login-form');

    // --- New Booking Page Specific Logic ---
    if (bookingForm) {
        const resourceSelectBooking = document.getElementById('resource-select-booking');
        // Assuming a message div for the new booking form, e.g., <div id="new-booking-message"></div>
        const newBookingMessageDiv = document.getElementById('new-booking-message'); 

        // Populate Resource Selector for New Booking Page
        if (resourceSelectBooking) {
            apiCall('/api/resources', {}, newBookingMessageDiv) // Pass message div
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
                        // Per subtask, API /api/resources should return published.
                        // If not, a filter "if (resource.status === 'published')" might be needed.
                        const option = new Option(
                           `${resource.name} (Capacity: ${resource.capacity || 'N/A'})`, 
                           resource.id
                        );
                        // Robust resource name retrieval (as per subtask)
                        option.dataset.resourceName = resource.name; 
                        resourceSelectBooking.add(option);
                    });
                    if (newBookingMessageDiv) hideMessage(newBookingMessageDiv); // Clear "Loading..."
                })
                .catch(error => {
                    // apiCall already showed error in newBookingMessageDiv (if provided)
                    resourceSelectBooking.innerHTML = '<option value="">Error loading resources</option>';
                    // If newBookingMessageDiv wasn't used by apiCall or error is different:
                    if (newBookingMessageDiv && !newBookingMessageDiv.classList.contains('error')) {
                        showError(newBookingMessageDiv, 'Failed to load resources for booking.');
                    }
                });
        }

        // Handle Predefined Time Slot Options
        const quickTimeOptions = document.querySelectorAll('input[name="quick_time_option"]');
        const manualTimeInputsDiv = document.getElementById('manual-time-inputs');
        const startTimeInput = document.getElementById('start-time');
        const endTimeInput = document.getElementById('end-time');

        quickTimeOptions.forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.checked) {
                    switch (this.value) {
                        case 'morning':
                            if (startTimeInput) startTimeInput.value = '08:00';
                            if (endTimeInput) endTimeInput.value = '12:00';
                            if (manualTimeInputsDiv) manualTimeInputsDiv.style.display = 'none';
                            break;
                        case 'afternoon':
                            if (startTimeInput) startTimeInput.value = '13:00';
                            if (endTimeInput) endTimeInput.value = '17:00';
                            if (manualTimeInputsDiv) manualTimeInputsDiv.style.display = 'none';
                            break;
                        case 'full_day':
                            if (startTimeInput) startTimeInput.value = '08:00';
                            if (endTimeInput) endTimeInput.value = '17:00';
                            if (manualTimeInputsDiv) manualTimeInputsDiv.style.display = 'none';
                            break;
                        case 'manual':
                            // Optionally clear times or leave them for user to edit
                            // if (startTimeInput) startTimeInput.value = '';
                            // if (endTimeInput) endTimeInput.value = '';
                            if (manualTimeInputsDiv) manualTimeInputsDiv.style.display = 'block'; // Or 'flex' or '' depending on original
                            break;
                    }
                }
            });
        });

        // Initial state for manual time (ensure it's visible if manual is checked by default)
        const manualRadio = document.querySelector('input[name="quick_time_option"][value="manual"]');
        if (manualRadio && manualRadio.checked && manualTimeInputsDiv) {
            manualTimeInputsDiv.style.display = 'block'; // Or 'flex' or ''
        } else if (manualTimeInputsDiv && (!manualRadio || !manualRadio.checked)) {
            // If manual is not checked by default, and another option is, hide manual inputs
            // This case should be covered by the radio button's 'checked' attribute in HTML triggering the change listener.
            // However, as a fallback:
            const anyCheckedRadio = document.querySelector('input[name="quick_time_option"]:checked');
            if (anyCheckedRadio && anyCheckedRadio.value !== 'manual' && manualTimeInputsDiv) {
                 manualTimeInputsDiv.style.display = 'none';
            }
        }
    } // This closes the outer if(bookingForm)

    // The rest of the file continues from here...
    // const loginMessageDiv = document.getElementById('login-message'); // This was duplicated, remove one

    // Re-locating the bookingForm submit listener logic to be AFTER the time slot logic,
    // but still within the main DOMContentLoaded.
    // The original placement of the bookingForm event listener was outside the if(bookingForm) block
    // which is fine, but for clarity, I will ensure all bookingForm related setup is grouped.
    // The code below will be adjusted in the next step.

    // This is the original location of the loginMessageDiv, keep it here.
    const loginMessageDiv = document.getElementById('login-message'); 

    if (bookingForm) { // This is the original bookingForm event listener block, now with updated logic
        bookingForm.addEventListener('submit', async function(event) {
            event.preventDefault(); // Prevent default form submission

            if (bookingResultsDiv) {
                bookingResultsDiv.innerHTML = ''; // Clear previous messages
                bookingResultsDiv.className = ''; // Clear existing classes
            }

            // Check if user is logged in
            const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
            if (!loggedInUsername) {
                if (bookingResultsDiv) {
                    bookingResultsDiv.innerHTML = `<p>Please <a href="${document.body.dataset.loginUrl || '/login'}">login</a> to book a resource.</p>`;
                    bookingResultsDiv.classList.add('error');
                }
                return; // Stop further processing
            }

            // Get form values
            const resourceSelectBooking = document.getElementById('resource-select-booking');
            const dateInput = document.getElementById('booking-date');
            const startTimeInput = document.getElementById('start-time');
            const endTimeInput = document.getElementById('end-time');

            const resourceId = resourceSelectBooking ? resourceSelectBooking.value : '';
            const dateValue = dateInput ? dateInput.value : '';
            const startTimeValue = startTimeInput ? startTimeInput.value : '';
            const endTimeValue = endTimeInput ? endTimeInput.value : '';
            
            let titleValue = 'User Booking'; // Default title
            if (resourceSelectBooking && resourceSelectBooking.selectedIndex >= 0 && resourceSelectBooking.value) {
                const selectedOption = resourceSelectBooking.options[resourceSelectBooking.selectedIndex];
                // Use data-resource-name for robust name retrieval
                titleValue = `Booking for ${selectedOption.dataset.resourceName || selectedOption.text.split(' (Capacity:')[0]}`;
            }


            if (!resourceId) {
                showError(bookingResultsDiv, 'Please select a resource.');
                return;
            }
            if (!dateValue || !startTimeValue || !endTimeValue) {
                showError(bookingResultsDiv, 'Please fill in date, start time, and end time.');
                return;
            }
            
            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateValue,
                start_time_str: startTimeValue,
                end_time_str: endTimeValue,
                title: titleValue, 
                user_name: loggedInUsername // Already fetched and checked
            };

            try {
                const responseData = await apiCall('/api/bookings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                }, bookingResultsDiv); // Pass bookingResultsDiv for messages

                // apiCall throws on error, so if we're here, it's a success
                let resourceName = 'N/A';
                if (resourceSelectBooking && resourceSelectBooking.selectedIndex !== -1) {
                    const selectedOption = resourceSelectBooking.options[resourceSelectBooking.selectedIndex];
                    resourceName = selectedOption.dataset.resourceName || selectedOption.text.split(' (Capacity:')[0];
                }

                const displayDate = responseData.start_time ? responseData.start_time.split(' ')[0] : 'N/A';
                const displayStartTime = responseData.start_time ? responseData.start_time.split(' ')[1].substring(0,5) : 'N/A';
                const displayEndTime = responseData.end_time ? responseData.end_time.split(' ')[1].substring(0,5) : 'N/A';
                const displayTitle = responseData.title || 'N/A';
                const displayBookingId = responseData.id || 'N/A';

                // Construct HTML string for success message
                const successHtml = `
                    <p><strong>Booking Confirmed!</strong><br>
                    Resource: ${resourceName}<br>
                    Date: ${displayDate}<br>
                    Time: ${displayStartTime} - ${displayEndTime}<br>
                    Title: ${displayTitle}<br>
                    Booking ID: ${displayBookingId}</p>
                `;
                // Use showSuccess with HTML content
                if (bookingResultsDiv) { // Ensure div exists
                    bookingResultsDiv.innerHTML = successHtml; // Set HTML directly
                    bookingResultsDiv.className = 'success'; // Apply class for styling
                    bookingResultsDiv.style.display = 'block'; // Make sure it's visible
                }
                
                bookingForm.reset(); // Reset form fields
                // Reset quick time options to manual and ensure UI updates
                const manualRadio = document.querySelector('input[name="quick_time_option"][value="manual"]');
                if(manualRadio) {
                    manualRadio.checked = true;
                    // Trigger change to ensure manual time inputs are shown if hidden
                    manualRadio.dispatchEvent(new Event('change')); 
                }
            } catch (error) {
                // apiCall already displayed the error in bookingResultsDiv.
                console.error('Booking submission failed:', error.message);
            }
        });
    }

    if (loginForm) {
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
                // apiCall will show "Logging in..." via its messageElement parameter.
                const responseData = await apiCall('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                }, loginMessageDiv);

                // If apiCall is successful, responseData.message might contain a success message.
                // If not, use a generic one. apiCall's showSuccess will handle display.
                showSuccess(loginMessageDiv, responseData.message || 'Login successful!');
    
                if (responseData.user) {
                    sessionStorage.setItem('loggedInUserUsername', responseData.user.username);
                    sessionStorage.setItem('loggedInUserIsAdmin', responseData.user.is_admin ? 'true' : 'false');
                    sessionStorage.setItem('loggedInUserId', responseData.user.id);
                } else {
                    // This case should ideally not happen if API is consistent
                    sessionStorage.setItem('loggedInUserUsername', username); 
                    sessionStorage.removeItem('loggedInUserIsAdmin'); 
                    sessionStorage.removeItem('loggedInUserId');
                    console.warn("User object missing from successful login response. Storing username only.");
                }
                
                await updateAuthLink(); // Refresh nav/UI elements
                
                setTimeout(() => {
                    window.location.href = '/'; // Redirect to home page
                }, 500); // Delay for user to see success message
    
            } catch (error) {
                // apiCall already displayed the error in loginMessageDiv.
                // Clear any potentially partially set session data on login failure
                sessionStorage.removeItem('loggedInUserUsername');
                sessionStorage.removeItem('loggedInUserIsAdmin');
                sessionStorage.removeItem('loggedInUserId');
                // updateAuthLink(); // Optionally, re-update auth links to explicitly show logged-out state
                console.error('Login attempt failed:', error.message);
            }
        });
    }

// --- Permission Helper Function ---
function checkUserPermissionForResource(resource, currentUserId, currentUserIsAdmin) {
    if (!resource) return false;

    if (currentUserIsAdmin) return true; // Admins can generally book/override

    if (resource.booking_restriction === 'admin_only') {
        return currentUserIsAdmin; // This will be false here since admin case handled above
    }

    // Check allowed user IDs (assuming resource.allowed_user_ids is a string "id1,id2")
    let userInAllowedList = false;
    let hasUserIdRestriction = resource.allowed_user_ids && resource.allowed_user_ids.trim() !== "";

    if (hasUserIdRestriction) {
        const allowedIds = resource.allowed_user_ids.split(',').map(idStr => parseInt(idStr.trim(), 10));
        if (allowedIds.includes(currentUserId)) {
            userInAllowedList = true;
            return true; // User specifically allowed
        }
    }

    // If there are specific roles defined for the resource, and user is not in allowed_user_ids (if any were specified),
    // we can't confirm client-side without knowing user's roles. For simplicity, allow click.
    // The backend will make the final decision.
    // This also covers the case where allowed_user_ids is empty but roles are present.
    // resource.roles is expected to be an array of objects e.g. [{id: 1, name: 'RoleName'}]
    let hasRoleRestriction = resource.roles && Array.isArray(resource.roles) && resource.roles.length > 0;
    
    if (hasRoleRestriction) {
        // If user IDs were specified but user didn't match, we still allow click because roles might grant access.
        // If user IDs were NOT specified, but roles are, allow click.
        return true; // Allow click, let backend verify role
    }
    
    // If not admin_only, no specific user IDs defined, and no specific roles defined, then it's bookable by any authenticated user.
    if (!hasUserIdRestriction && !hasRoleRestriction) {
        return true;
    }

    // If user IDs were specified, user is NOT in the list, AND no roles are specified for the resource.
    // In this specific case, the user definitely cannot book.
    if (hasUserIdRestriction && !userInAllowedList && !hasRoleRestriction) {
         return false;
    }
    
    // Default to allowing the click if logic is ambiguous without user roles info,
    // or if user IDs were not specified but roles were (covered by hasRoleRestriction returning true above).
    // This path is mostly for cases where user IDs were specified, user not in list, but roles *were* specified
    // (which returned true above). If somehow it reaches here with hasUserIdRestriction && !userInAllowedList && hasRoleRestriction,
    // it means the role check should have returned true.
    // This acts as a fallback.
    return true; 
}


    // For resources.html page - Populate room selector and handle availability
    const roomSelectDropdown = document.getElementById('room-select');
    const availabilityDateInput = document.getElementById('availability-date');
    const calendarTable = document.getElementById('calendar-table');

    function getTodayDateString() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0'); // Months are 0-indexed
        const dd = String(today.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    if (availabilityDateInput && roomSelectDropdown && calendarTable) {
        availabilityDateInput.value = getTodayDateString(); // Set to today by default

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
                    calendarStatusMessageDiv // This div will show loading/errors for this call
                );
                updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails);
                // If apiCall was successful and no specific success message was in response, 
                // it would hide the calendarStatusMessageDiv. This is usually desired.
            } catch (error) {
                // apiCall has already shown the error in calendarStatusMessageDiv.
                // Log for debugging and ensure calendar UI reflects error state.
                console.error(`Error fetching availability for resource ${resourceId} on ${dateString}:`, error.message);
                clearCalendar(true); 
            }
        }

        function handleAvailableSlotClick(event, resourceId, dateString) {
            const cell = event.target;
            const timeSlot = cell.dataset.timeSlot; // e.g., "09:00-10:00"

            if (!timeSlot) {
                console.error("Clicked cell is missing data-time-slot attribute.");
                return;
            }

            const loggedInUser = sessionStorage.getItem('loggedInUser');
            if (!loggedInUser) {
                alert("Please login to book a resource.");
                // window.location.href = '/login'; // Optionally redirect
                return;
            }

            const bookingTitle = prompt(`Book slot ${timeSlot} on ${dateString} for resource ID ${resourceId}?
Enter a title for your booking (optional):`);

            if (bookingTitle === null) { // User clicked cancel
                console.log("Booking cancelled by user.");
                return;
            }

            const [startTimeStr, endTimeStr] = timeSlot.split('-');
            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateString,
                start_time_str: startTimeStr,
                end_time_str: endTimeStr,
                title: bookingTitle,
                user_name: loggedInUser
            };

            console.log("Booking data prepared:", bookingData);
            // alert(`Booking prepared for ${bookingData.title || 'Untitled Booking'} at ${timeSlot}. API call to be implemented next.`);
            makeBookingApiCall(bookingData); 
        }

        async function makeBookingApiCall(bookingData) { // For calendar table's direct booking
            const calendarStatusMessageDiv = document.getElementById('calendar-status-message');
            try {
                const responseData = await apiCall('/api/bookings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                }, calendarStatusMessageDiv);

                alert(`Booking successful! Title: ${responseData.title || 'Untitled'} (ID: ${responseData.id})`);
                
                if (roomSelectDropdown.value && availabilityDateInput.value) {
                     const selectedOption = roomSelectDropdown.selectedOptions[0];
                     const currentResourceDetails = { 
                        id: roomSelectDropdown.value, 
                        name: selectedOption.dataset.resourceName || selectedOption.textContent.split(' (ID:')[0],
                        booking_restriction: selectedOption.dataset.bookingRestriction,
                        allowed_user_ids: selectedOption.dataset.allowedUserIds,
                        allowed_roles: selectedOption.dataset.allowedRoles
                     };
                    fetchAndDisplayAvailability(
                        roomSelectDropdown.value,
                        availabilityDateInput.value,
                        currentResourceDetails 
                    );
                }
                if(calendarStatusMessageDiv) showSuccess(calendarStatusMessageDiv, `Booking for '${responseData.title || 'Untitled'}' (ID: ${responseData.id}) confirmed.`);

            } catch (error) {
                // apiCall showed error in calendarStatusMessageDiv. Alert for additional feedback.
                alert(`Booking failed: ${error.message}. Check messages above calendar.`);
                console.error('Calendar table direct booking failed:', error.message);
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

                // Apply general booking restriction first, then granular if applicable
                if (!isBooked && currentResourceDetails) {
                    if (!checkUserPermissionForResource(currentResourceDetails, currentUserId, currentUserIsAdmin)) {
                        cellClass = 'unavailable-permission'; // New CSS class for permission denied
                        cellText = 'Restricted'; // More generic term
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
                        const currentDateStringFromPicker = availabilityDateInput.value;
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
            if (!selectedOption) return; // Should not happen if list is populated
            const currentResourceDetails = { 
                id: roomSelectDropdown.value, 
                booking_restriction: selectedOption.dataset.bookingRestriction,
                allowed_user_ids: selectedOption.dataset.allowedUserIds,
                allowed_roles: selectedOption.dataset.allowedRoles
            };
            fetchAndDisplayAvailability(currentResourceDetails.id, availabilityDateInput.value, currentResourceDetails);
        });

        availabilityDateInput.addEventListener('change', () => {
            const selectedOption = roomSelectDropdown.selectedOptions[0];
            if (!selectedOption) return; // Should not happen if list is populated
            const currentResourceDetails = { 
                id: roomSelectDropdown.value, 
                booking_restriction: selectedOption.dataset.bookingRestriction,
                allowed_user_ids: selectedOption.dataset.allowedUserIds,
                allowed_roles: selectedOption.dataset.allowedRoles
            };
            fetchAndDisplayAvailability(currentResourceDetails.id, availabilityDateInput.value, currentResourceDetails);
        });

        // Initial population of room selector for the calendar view on resources.html
        const calendarStatusMessageDiv = document.getElementById('calendar-status-message');
        if (roomSelectDropdown && availabilityDateInput && calendarTable && calendarStatusMessageDiv) { // Ensure all elements exist
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
                        option.dataset.allowedRoles = resource.allowed_roles || "";
                        option.dataset.resourceName = resource.name;
                        roomSelectDropdown.add(option);
                    });
                    
                    if (roomSelectDropdown.options.length > 0) {
                        roomSelectDropdown.value = roomSelectDropdown.options[0].value;
                        const selectedOption = roomSelectDropdown.options[0];
                        const initialResourceDetails = { 
                            id: selectedOption.value, 
                            name: selectedOption.dataset.resourceName,
                            booking_restriction: selectedOption.dataset.bookingRestriction,
                            allowed_user_ids: selectedOption.dataset.allowedUserIds,
                            allowed_roles: selectedOption.dataset.allowedRoles
                        };
                        fetchAndDisplayAvailability(initialResourceDetails.id, availabilityDateInput.value, initialResourceDetails);
                    } else {
                         clearCalendar(); 
                         showSuccess(calendarStatusMessageDiv, 'No resources to display in calendar.');
                    }
                })
                .catch(error => {
                    roomSelectDropdown.innerHTML = '<option value="">Error loading rooms</option>';
                    clearCalendar(true);
                    // Error message already shown by apiCall in calendarStatusMessageDiv
                });
        }
        
        // Logic for displaying floor map links on resources.html
        const floorMapsListUl = document.getElementById('floor-maps-list');
        const floorMapsLoadingStatusDiv = document.getElementById('floor-maps-loading-status'); 
        if (floorMapsListUl && floorMapsLoadingStatusDiv) { 
            async function fetchAndDisplayFloorMapLinks() {
                try {
                    const maps = await apiCall('/api/admin/maps', {}, floorMapsLoadingStatusDiv); 
                    floorMapsListUl.innerHTML = ''; 
                    if (!maps || maps.length === 0) {
                        showSuccess(floorMapsLoadingStatusDiv, 'No floor maps available.');
                        return;
                    }
                    maps.forEach(map => {
                        const listItem = document.createElement('li');
                        const link = document.createElement('a');
                        link.href = `/map_view/${map.id}`; 
                        link.textContent = map.name;
                        listItem.appendChild(link);
                        floorMapsListUl.appendChild(listItem);
                    });
                     // apiCall success default behavior is to hide messageElement if no specific success message from API.
                     // If a message was shown, and it wasn't an error, it's fine for it to be hidden.
                } catch (error) {
                    // apiCall already showed error in floorMapsLoadingStatusDiv
                    if (floorMapsListUl) floorMapsListUl.innerHTML = '<li>Error loading floor maps.</li>'; // Fallback
                }
            }
            fetchAndDisplayFloorMapLinks();
        }
    } // End of `if (availabilityDateInput && roomSelectDropdown && calendarTable)`

    // Admin Maps Page Specific Logic
    const adminMapsPageIdentifier = document.getElementById('upload-map-form');
    if (adminMapsPageIdentifier) { 
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
                        Filename: ${map.image_filename}<br>
                        <img src="${map.image_url}" alt="${map.name}" style="max-width: 200px; max-height: 150px; border: 1px solid #eee;">
                        <br>
                        <button class="select-map-for-areas-btn" data-map-id="${map.id}" data-map-name="${map.name}" data-map-image-url="${map.image_url}">Define Areas</button>
                    `;
                    mapsListUl.appendChild(listItem);
                });
            } catch (error) {
                mapsListUl.innerHTML = '<li>Error loading maps.</li>';
                // Error already shown by apiCall in adminMapsListStatusDiv
            }
        }

        if (uploadMapForm && uploadStatusDiv) {
            uploadMapForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                showLoading(uploadStatusDiv, 'Uploading...');
                const formData = new FormData(uploadMapForm);
                try {
                    // Direct fetch for FormData, manual error/success handling for this specific case.
                    const response = await fetch('/api/admin/maps', { method: 'POST', body: formData });
                    const responseData = await response.json();
                    if (response.ok) { 
                        showSuccess(uploadStatusDiv, `Map '${responseData.name}' uploaded successfully! (ID: ${responseData.id})`);
                        uploadMapForm.reset();
                        fetchAndDisplayMaps(); 
                    } else {
                        showError(uploadStatusDiv, `Upload failed: ${responseData.error || responseData.message || 'Unknown server error'}`);
                    }
                } catch (error) {
                    console.error('Error uploading map:', error);
                    showError(uploadStatusDiv, `Upload failed: ${error.message || 'Network error or server is down.'}`);
                }
            });
        }

        // Initial fetch of maps when the page loads
        fetchAndDisplayMaps();
        
        // --- Define Areas Section Logic ---
        const defineAreasSection = document.getElementById('define-areas-section');
        const selectedMapNameH3 = document.getElementById('selected-map-name');
        const selectedMapImageImg = document.getElementById('selected-map-image');
        const resourceToMapSelect = document.getElementById('resource-to-map');
        const defineAreaForm = document.getElementById('define-area-form'); // Define it here
        const hiddenFloorMapIdInput = document.getElementById('selected-floor-map-id');
        const areaDefinitionStatusDiv = document.getElementById('area-definition-status');
        const bookingPermissionDropdown = document.getElementById('booking-permission'); 
        const resourceActionsContainer = document.getElementById('resource-actions-container'); // **NEW**


        const drawingCanvas = document.getElementById('drawing-canvas');
        let canvasCtx = null; // To be initialized later
        let isDrawing = false;
        let startX, startY;
        let currentDrawnRect = null; // To store {x, y, width, height}
        let existingMapAreas = []; // Array to store fetched existing areas
        let selectedAreaForEditing = null; // To store the selected area object

        // Move Mode State Variables
        let isMovingArea = false;
        let dragStartX, dragStartY; // Mouse start position for dragging
        let initialAreaX, initialAreaY; // Initial top-left corner of the area being moved

        // Resize Handle Properties
        const HANDLE_SIZE = 8; 
        const HANDLE_COLOR = 'rgba(0, 0, 255, 0.7)'; 
        const SELECTED_BORDER_COLOR = 'rgba(0, 0, 255, 0.9)'; 
        const SELECTED_LINE_WIDTH = 2;


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
                            existingMapAreas.push({ /* ... (all properties) ... */ 
                                id: resource.id, resource_id: resource.id, name: resource.name,
                                map_coordinates: resource.map_coordinates,
                                booking_restriction: resource.booking_restriction,
                                allowed_user_ids: resource.allowed_user_ids, 
                                allowed_roles: resource.allowed_roles,
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
                // Error shown by apiCall in defineAreasStatusDiv
                console.error('Error fetching existing map areas:', error.message);
            }
            redrawCanvas(); 
        }

        function redrawCanvas() {
            if (!canvasCtx) return;
            canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
    
            // Draw all existing (saved) map areas (non-selected first)
            canvasCtx.font = "10px Arial";
            existingMapAreas.forEach(area => {
                if (selectedAreaForEditing && selectedAreaForEditing.id === area.id) {
                    return; // Skip drawing here, it's handled by the dedicated "selected" drawing block
                }
                if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                    const coords = area.map_coordinates;
                    canvasCtx.fillStyle = 'rgba(255, 0, 0, 0.1)';   // Light red fill for non-selected
                    canvasCtx.strokeStyle = 'rgba(255, 0, 0, 0.7)'; // Red border for non-selected
                    canvasCtx.lineWidth = 1;

                    canvasCtx.fillRect(coords.x, coords.y, coords.width, coords.height);
                    canvasCtx.strokeRect(coords.x, coords.y, coords.width, coords.height);
                    
                    canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.7)'; // Text color
                    canvasCtx.textAlign = "center";
                    canvasCtx.textBaseline = "middle";
                    if (coords.width > 30 && coords.height > 10) {
                         canvasCtx.fillText(area.name || `ID:${area.id}`, coords.x + coords.width / 2, coords.y + coords.height / 2, coords.width - 4);
                    }
                }
            });

            // Highlight and draw handles for selectedAreaForEditing
            if (selectedAreaForEditing && selectedAreaForEditing.map_coordinates && selectedAreaForEditing.map_coordinates.type === 'rect') {
                const coords = selectedAreaForEditing.map_coordinates;
                
                // Draw main rectangle for selected area
                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.2)'; // Light blue fill for selected
                canvasCtx.strokeStyle = SELECTED_BORDER_COLOR;
                canvasCtx.lineWidth = SELECTED_LINE_WIDTH;
                
                canvasCtx.fillRect(coords.x, coords.y, coords.width, coords.height);
                canvasCtx.strokeRect(coords.x, coords.y, coords.width, coords.height);

                // Draw resource name for selected
                canvasCtx.fillStyle = 'rgba(0, 0, 0, 0.9)'; // Darker text for selected
                canvasCtx.textAlign = "center";
                canvasCtx.textBaseline = "middle";
                if (coords.width > 30 && coords.height > 10) {
                     canvasCtx.fillText(selectedAreaForEditing.name || `ID:${selectedAreaForEditing.id}`, coords.x + coords.width / 2, coords.y + coords.height / 2, coords.width - 4);
                }

                // Draw resize handles (4 corners)
                canvasCtx.fillStyle = HANDLE_COLOR;
                const halfHandle = HANDLE_SIZE / 2;
                canvasCtx.fillRect(coords.x - halfHandle, coords.y - halfHandle, HANDLE_SIZE, HANDLE_SIZE); // Top-left
                canvasCtx.fillRect(coords.x + coords.width - halfHandle, coords.y - halfHandle, HANDLE_SIZE, HANDLE_SIZE); // Top-right
                canvasCtx.fillRect(coords.x - halfHandle, coords.y + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE); // Bottom-left
                canvasCtx.fillRect(coords.x + coords.width - halfHandle, coords.y + coords.height - halfHandle, HANDLE_SIZE, HANDLE_SIZE); // Bottom-right
            }
    
            // Draw the current rectangle being drawn by mouse (currentDrawnRect)
            if (currentDrawnRect && currentDrawnRect.width !== undefined) {
                canvasCtx.strokeStyle = 'rgba(0, 0, 255, 0.7)'; // Blue for the new rectangle being drawn
                canvasCtx.fillStyle = 'rgba(0, 0, 255, 0.1)';   // Light blue fill
                canvasCtx.lineWidth = 2;
                
                let x = currentDrawnRect.x;
                let y = currentDrawnRect.y;
                let w = currentDrawnRect.width;
                let h = currentDrawnRect.height;
    
                if (w < 0) { x = currentDrawnRect.x + w; w = -w; }
                if (h < 0) { y = currentDrawnRect.y + h; h = -h; }
                
                canvasCtx.fillRect(x,y,w,h); // Also fill the temporary drawing
                canvasCtx.strokeRect(x, y, w, h);
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
                        if ((!r.floor_map_id || !r.map_coordinates) || (r.floor_map_id === parseInt(currentMapId))) {
                            count++;
                            const opt = new Option(`${r.name} (ID: ${r.id}) - Status: ${r.status || 'N/A'}`, r.id);
                            Object.assign(opt.dataset, { // Assign all relevant data
                                resourceId: r.id, resourceName: r.name, resourceStatus: r.status || 'draft',
                                bookingRestriction: r.booking_restriction || "",
                                allowedUserIds: r.allowed_user_ids || "", allowedRoles: r.allowed_roles || "",
                                isMappedToCurrent: (r.floor_map_id === parseInt(currentMapId) && r.map_coordinates) ? "true" : "false"
                            });
                            if (opt.dataset.isMappedToCurrent === "true") opt.textContent += ` (On this map)`;
                            resourceToMapSelect.add(opt);
                        }
                    });
                }
                if (defineAreasStatusDiv) {
                    if (count === 0) showSuccess(defineAreasStatusDiv, "No resources available for mapping or all mapped.");
                    else if (!defineAreasStatusDiv.classList.contains('error')) hideMessage(defineAreasStatusDiv);
                }
            } catch (error) {
                resourceToMapSelect.innerHTML = '<option value="">Error loading resources</option>';
                // Error shown by apiCall in defineAreasStatusDiv
            }
        }

        if (mapsListUl) {
            mapsListUl.addEventListener('click', async function(event) {
                if (event.target.classList.contains('select-map-for-areas-btn')) {
                    const button = event.target;
                    const mapId = button.dataset.mapId;
                    const mapName = button.dataset.mapName;
                    const mapImageUrl = button.dataset.mapImageUrl;

                    // Display the define areas section
                    if (defineAreasSection) defineAreasSection.style.display = 'block';
                    
                    // Populate selected map details
                    if (selectedMapNameH3) selectedMapNameH3.textContent = `Defining Areas for: ${mapName}`;
                    if (selectedMapImageImg) {
                        selectedMapImageImg.src = mapImageUrl;
                        selectedMapImageImg.alt = mapName;
                    }
                    if (hiddenFloorMapIdInput) hiddenFloorMapIdInput.value = mapId; // Store map ID in the hidden form input

                    // Fetch and populate resources for the dropdown
                    if (resourceToMapSelect) { // Ensure element exists
                         await populateResourcesForMapping(mapId);
                    }
                    
                    // Scroll to the define areas section for better UX
                    if (defineAreasSection) defineAreasSection.scrollIntoView({ behavior: 'smooth' });

                    // Initialize canvas AFTER image is loaded to get correct dimensions
                    selectedMapImageImg.onload = () => {
                        if (drawingCanvas) {
                            // Set canvas dimensions to match the *displayed* size of the image
                            drawingCanvas.width = selectedMapImageImg.clientWidth;
                            drawingCanvas.height = selectedMapImageImg.clientHeight;
                            canvasCtx = drawingCanvas.getContext('2d');
                            
                            // Clear any previous drawings and reset state
                            canvasCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
                            isDrawing = false;
                            currentDrawnRect = null; // Reset current drawing
                            // existingMapAreas = []; // Clear previously loaded areas for other maps -- MOVED to fetchAndDrawExistingMapAreas
                            
                            console.log(`Canvas initialized for map ${mapName}. Dimensions: ${drawingCanvas.width}x${drawingCanvas.height}`);
                            
                            // Fetch and draw existing areas for the current map
                            const currentMapIdForAreas = hiddenFloorMapIdInput.value; 
                            if (currentMapIdForAreas) {
                                fetchAndDrawExistingMapAreas(currentMapIdForAreas); // This will call redrawCanvas itself
                            } else {
                                console.error("Map ID not available for fetching existing areas.");
                                existingMapAreas = []; // Ensure it's empty
                                redrawCanvas(); // Call redraw even if no mapId, to clear canvas.
                            }

                            // Attach mouse event listeners for drawing
                            drawingCanvas.onmousedown = function(event) {
                                const clickX = event.offsetX;
                                const clickY = event.offsetY;
                                const editDeleteButtonsDiv = document.getElementById('edit-delete-buttons');
                                
                                // TODO: Future: Check if click is on a resize handle of selectedAreaForEditing first

                                if (selectedAreaForEditing && 
                                    selectedAreaForEditing.map_coordinates && 
                                    selectedAreaForEditing.map_coordinates.type === 'rect') {
                                    
                                    const coords = selectedAreaForEditing.map_coordinates;
                                    // Check if click is within the main body of the selectedAreaForEditing
                                    if (clickX >= coords.x && clickX <= coords.x + coords.width &&
                                        clickY >= coords.y && clickY <= coords.y + coords.height) {
                                        
                                        isMovingArea = true;
                                        isDrawing = false; 
                                        currentDrawnRect = null; 
                                        dragStartX = clickX;
                                        dragStartY = clickY;
                                        initialAreaX = coords.x;
                                        initialAreaY = coords.y;
                                        
                                        console.log("Move started for area:", selectedAreaForEditing.name);
                                        redrawCanvas(); 
                                        return; 
                                    }
                                }
                        
                                // If not moving, proceed with existing selection/new drawing logic
                                let clickedOnExistingArea = false;
                                for (const area of existingMapAreas) {
                                    if (area.map_coordinates && area.map_coordinates.type === 'rect') {
                                        const coords = area.map_coordinates;
                                        if (clickX >= coords.x && clickX <= coords.x + coords.width &&
                                            clickY >= coords.y && clickY <= coords.y + coords.height) {
                                            
                                            selectedAreaForEditing = area;
                                            isDrawing = false; 
                                            currentDrawnRect = null; 
                                            clickedOnExistingArea = true;
                                            console.log("Selected existing area:", selectedAreaForEditing);
                                            if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'block';
                                            
                                            // Populate form fields (existing logic)
                                            document.getElementById('coord-x').value = Math.round(coords.x);
                                            document.getElementById('coord-y').value = Math.round(coords.y);
                                            document.getElementById('coord-width').value = Math.round(coords.width);
                                            document.getElementById('coord-height').value = Math.round(coords.height);
                                            if (resourceToMapSelect) resourceToMapSelect.value = area.id;
                                            if (bookingPermissionDropdown) bookingPermissionDropdown.value = area.booking_restriction || "";
                                            const allowedUserIdsStr = area.allowed_user_ids || "";
                                            const allowedUserIds = allowedUserIdsStr.split(',').filter(id => id.trim() !== '');
                                            if(authorizedUsersCheckboxContainer) {
                                                authorizedUsersCheckboxContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                                                    cb.checked = allowedUserIds.includes(cb.value);
                                                });
                                            }
                                            if(authorizedRolesInput) authorizedRolesInput.value = area.allowed_roles || "";
                                            resourceToMapSelect.dispatchEvent(new Event('change')); // Trigger change for resource actions
                                            break; 
                                        }
                                    }
                                }
                        
                                if (!clickedOnExistingArea) { // Click was not on any existing area
                                    selectedAreaForEditing = null; 
                                    if (editDeleteButtonsDiv) editDeleteButtonsDiv.style.display = 'none';
                                    
                                    isDrawing = true;
                                    startX = clickX; 
                                    startY = clickY;
                                    currentDrawnRect = { x: startX, y: startY, width: 0, height: 0 };
                                    
                                    // Clear form fields when starting a new drawing
                                    const defineAreaFormElement = document.getElementById('define-area-form');
                                    if(defineAreaFormElement) {
                                        defineAreaFormElement.reset(); // Resets all form fields
                                        const submitButton = defineAreaFormElement.querySelector('button[type="submit"]');
                                        if (submitButton) {
                                            submitButton.textContent = 'Save Area for Resource';
                                        }
                                    }
                                    // Explicitly set dropdowns to default if reset() doesn't guarantee it or for clarity
                                    if (resourceToMapSelect) resourceToMapSelect.value = ''; 
                                    if (bookingPermissionDropdown) bookingPermissionDropdown.value = "";
                                }
                                redrawCanvas(); 
                            };

                            drawingCanvas.onmousemove = function(event) {
                                if (!isDrawing) return;
                                
                                const currentX = event.offsetX;
                                const currentY = event.offsetY;
                                
                                currentDrawnRect.width = currentX - startX;
                                currentDrawnRect.height = currentY - startY;
                                
                                redrawCanvas(); // Redraw with the current rectangle
                            };

                            drawingCanvas.onmouseup = function(event) {
                                if (!isDrawing) return;
                                isDrawing = false;
                                
                                // Normalize the rectangle coordinates (if width/height are negative)
                                let finalX = currentDrawnRect.x;
                                let finalY = currentDrawnRect.y;
                                let finalWidth = currentDrawnRect.width;
                                let finalHeight = currentDrawnRect.height;

                                if (finalWidth < 0) {
                                    finalX = currentDrawnRect.x + finalWidth;
                                    finalWidth = Math.abs(finalWidth);
                                }
                                if (finalHeight < 0) {
                                    finalY = currentDrawnRect.y + finalHeight;
                                    finalHeight = Math.abs(finalHeight);
                                }
                                
                                currentDrawnRect = { x: finalX, y: finalY, width: finalWidth, height: finalHeight };

                                // Populate the form fields
                                document.getElementById('coord-x').value = Math.round(finalX);
                                document.getElementById('coord-y').value = Math.round(finalY);
                                document.getElementById('coord-width').value = Math.round(finalWidth);
                                document.getElementById('coord-height').value = Math.round(finalHeight);
                                
                                redrawCanvas(); // Draw the final version of the new rect
                                console.log("Rectangle drawn:", currentDrawnRect);
                            };

                            drawingCanvas.onmouseleave = function(event) {
                                // Optional: if you want to cancel drawing when mouse leaves canvas
                                // if (isDrawing) {
                                //     isDrawing = false;
                                //     currentDrawnRect = null; // Or finalize if desired
                                //     redrawCanvas(); // Clear temporary drawing
                                //     console.log("Drawing cancelled due to mouse leave.");
                                // }
                            };
                            
                            // Note: fetchAndDrawExistingMapAreas already calls redrawCanvas, so no need for an extra one here unless that fails.
                        }
                    };
                    // If the image is already cached and fires 'load' before this handler is set,
                    // or if src is set to the same value, 'onload' might not fire.
                    // Check if image is already complete.
                    if (selectedMapImageImg.complete && selectedMapImageImg.src && selectedMapImageImg.src !== 'data:,') { // Check src is not empty/default
                        selectedMapImageImg.onload(); // Call it manually
                    }
                }
            });
        }

        // Handle "Define Area" Form Submission
        if (defineAreaForm) {
            defineAreaForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                areaDefinitionStatusDiv.textContent = 'Saving area...';
                areaDefinitionStatusDiv.style.color = 'inherit';

                const selectedResourceId = resourceToMapSelect.value;
                const floorMapId = parseInt(hiddenFloorMapIdInput.value, 10);
                
                if (!selectedResourceId) {
                    areaDefinitionStatusDiv.textContent = 'Please select a resource to map.';
                    areaDefinitionStatusDiv.style.color = 'red';
                    return;
                }
                if (isNaN(floorMapId)) {
                    areaDefinitionStatusDiv.textContent = 'No floor map selected or invalid map ID.';
                    areaDefinitionStatusDiv.style.color = 'red';
                    return;
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
                        areaDefinitionStatusDiv.textContent = `Invalid input for coordinate: ${key}. Must be a number.`;
                        areaDefinitionStatusDiv.style.color = 'red';
                        return;
                    }
                }
                
                // Payload includes coordinates and potentially other resource-specific settings if form is extended
                const payload = { floor_map_id: floorMapId, coordinates: coordinates };
                // Add other properties like booking_restriction from form if they are part of this update
                // payload.booking_restriction = bookingPermissionDropdown.value; 
                // payload.allowed_user_ids = ... ; payload.allowed_roles = ...;

                try {
                    const responseData = await apiCall(
                        `/api/admin/resources/${selectedResourceId}/map_info`, 
                        { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 
                        areaDefinitionStatusDiv 
                    );
                    showSuccess(areaDefinitionStatusDiv, `Area saved for '${responseData.name || selectedResourceId}'!`);
                    const mapIdRefresh = hiddenFloorMapIdInput.value;
                    if (mapIdRefresh) {
                        await populateResourcesForMapping(mapIdRefresh); 
                        await fetchAndDrawExistingMapAreas(mapIdRefresh); 
                    }
                    currentDrawnRect = null; 
                    if (selectedAreaForEditing && selectedAreaForEditing.id === parseInt(selectedResourceId)) {
                        selectedAreaForEditing.map_coordinates = coordinates; // Update local cache
                        // Also update other relevant fields if they were part of payload
                    }
                    redrawCanvas(); 
                } catch (error) {
                    // Error shown by apiCall
                    console.error('Error saving area on map:', error.message);
                }
            });
        }

        // --- Edit/Delete Button Logic ---
        const deleteSelectedAreaBtn = document.getElementById('delete-selected-area-btn');
        const editSelectedAreaBtn = document.getElementById('edit-selected-area-btn'); 

        if (deleteSelectedAreaBtn) {
            deleteSelectedAreaBtn.addEventListener('click', async function() {
                if (!selectedAreaForEditing || !selectedAreaForEditing.id) {
                    alert("No area selected for deletion, or selected area has no ID.");
                    return;
                }
    
                const resourceName = selectedAreaForEditing.name || `ID: ${selectedAreaForEditing.id}`;
                if (!confirm(`Are you sure you want to delete the map mapping for resource: ${resourceName}? This will remove its position from the map.`)) {
                    return;
                }
    
                // const areaDefinitionStatusDiv = document.getElementById('area-definition-status'); // Already defined above
                areaDefinitionStatusDiv.textContent = `Deleting mapping for ${resourceName}...`;
                areaDefinitionStatusDiv.style.color = 'inherit';
    
                try {
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
                    // Error shown by apiCall
                    console.error('Error deleting map mapping:', error.message);
                }
            });
        }

        if (editSelectedAreaBtn) {
            editSelectedAreaBtn.addEventListener('click', function() {
                if (!selectedAreaForEditing || !selectedAreaForEditing.id || !selectedAreaForEditing.map_coordinates) {
                    alert("No area selected for editing, or selected area is missing coordinate data.");
                    return;
                }
    
                console.log("Editing area:", selectedAreaForEditing);
    
                // 1. Populate the resource dropdown and select the correct resource
                if (resourceToMapSelect) { // Ensure the select element exists
                    resourceToMapSelect.value = selectedAreaForEditing.id;
                }
    
                // 2. Populate the coordinate input fields
                const coords = selectedAreaForEditing.map_coordinates;
                if (coords.type === 'rect') {
                    document.getElementById('coord-x').value = Math.round(coords.x);
                    document.getElementById('coord-y').value = Math.round(coords.y);
                    document.getElementById('coord-width').value = Math.round(coords.width);
                    document.getElementById('coord-height').value = Math.round(coords.height);
                    
                    // Populate the booking permission dropdown
                    if (bookingPermissionDropdown) {
                        bookingPermissionDropdown.value = selectedAreaForEditing.booking_restriction || ""; 
                    }

                    // Update currentDrawnRect to visually represent the area being edited
                    currentDrawnRect = { 
                        x: coords.x, 
                        y: coords.y, 
                        width: coords.width, 
                        height: coords.height 
                    };
                    redrawCanvas(); // Show this currentDrawnRect
    
                } else {
                    alert("Cannot edit non-rectangular areas with this form.");
                    // Clear form or handle appropriately if other types were supported
                    document.getElementById('define-area-form').reset();
                    currentDrawnRect = null; // Clear any temporary drawing
                    redrawCanvas();
                    return;
                }
    
                // 3. Scroll to the form for editing
                const defineAreaFormElement = document.getElementById('define-area-form'); // Renamed to avoid conflict with defineAreaForm const
                if (defineAreaFormElement) {
                    defineAreaFormElement.scrollIntoView({ behavior: 'smooth' });
                }
                
                // Optional: Change submit button text
                const submitButton = defineAreaFormElement ? defineAreaFormElement.querySelector('button[type="submit"]') : null;
                if (submitButton) {
                    submitButton.textContent = 'Update Area for Resource';
                }
                // Note: Need to reset this text when selection is cleared or a new drawing starts.
                // This reset is added to the 'else' block of drawingCanvas.onmousedown
                
                // Dispatch change event to update resource actions UI
                resourceToMapSelect.dispatchEvent(new Event('change'));
            });
        }

        if (resourceToMapSelect && resourceActionsContainer) {
            resourceToMapSelect.addEventListener('change', function() {
                const selectedOption = this.options[this.selectedIndex];
                resourceActionsContainer.innerHTML = ''; // Clear previous buttons/text
    
                if (selectedOption && selectedOption.value) { // If a resource is selected
                    const resourceId = selectedOption.dataset.resourceId;
                    const resourceStatus = selectedOption.dataset.resourceStatus;
    
                    // Logic to also update selectedAreaForEditing and redraw canvas if a mapped resource is chosen
                    if (existingMapAreas && typeof redrawCanvas === 'function') { 
                        const area = existingMapAreas.find(a => a.id === parseInt(resourceId));
                        // Ensure hiddenFloorMapIdInput is defined and has a value
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
                        publishBtn.id = 'publish-resource-btn';
                        publishBtn.textContent = 'Publish This Resource';
                        publishBtn.type = 'button'; 
                        publishBtn.className = 'button'; 
                        publishBtn.dataset.resourceId = resourceId;
                        publishBtn.addEventListener('click', handlePublishResource); 
                        resourceActionsContainer.appendChild(publishBtn);
                    } else if (resourceStatus === 'published') {
                        const statusText = document.createElement('p');
                        statusText.textContent = 'Status: Published';
                        resourceActionsContainer.appendChild(statusText);
                    } else if (resourceStatus === 'archived') {
                         const statusText = document.createElement('p');
                        statusText.textContent = 'Status: Archived';
                        resourceActionsContainer.appendChild(statusText);
                    } else {
                        const statusText = document.createElement('p');
                        statusText.textContent = `Status: ${resourceStatus || 'N/A'}`;
                        resourceActionsContainer.appendChild(statusText);
                    }
                } else {
                    // No resource selected, clear actions and map selection
                    selectedAreaForEditing = null;
                    if (typeof redrawCanvas === 'function') redrawCanvas();
                    resourceActionsContainer.innerHTML = '<p><em>Select a resource from the dropdown above to see its status or publish actions.</em></p>';
                }
            });
        }
        async function handlePublishResource(event) {
            const resourceId = event.target.dataset.resourceId;
            if (!resourceId) { alert("Error: Resource ID not found."); return; }
            if (!confirm(`Publish resource ID ${resourceId}? It will become visible and bookable.`)) return;
            
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
                if (resSelect) { // Update dataset and trigger change to refresh UI for actions
                    const opt = Array.from(resSelect.options).find(o => o.dataset.resourceId === resourceId);
                    if (opt) opt.dataset.resourceStatus = 'published';
                    resSelect.dispatchEvent(new Event('change'));
                }
                if (currentMapId) await fetchAndDrawExistingMapAreas(currentMapId);
            } catch (error) {
                alert(`Failed to publish: ${error.message}. See messages in actions area.`);
                // Error shown by apiCall in actionsContainer
                const resSelect = document.getElementById('resource-to-map'); // Refresh current state
                if (resSelect && resSelect.value === resourceId) resSelect.dispatchEvent(new Event('change'));
            }
        }
    } 

    // Map View Page Specific Logic
    const mapContainer = document.getElementById('map-container');

    // --- User Dropdown Menu Logic (Global) ---
    const userDropdownButtonGlobal = document.getElementById('user-dropdown-button');
    const userDropdownMenuGlobal = document.getElementById('user-dropdown-menu');

    if (userDropdownButtonGlobal && userDropdownMenuGlobal) {
        userDropdownButtonGlobal.addEventListener('click', function(event) {
            const isExpanded = userDropdownButtonGlobal.getAttribute('aria-expanded') === 'true' || false;
            userDropdownButtonGlobal.setAttribute('aria-expanded', !isExpanded);
            userDropdownMenuGlobal.style.display = isExpanded ? 'none' : 'block';
            event.stopPropagation(); // Prevent window click listener from closing it immediately
        });

        // Close dropdown if clicked outside
        window.addEventListener('click', function(event) {
            // Check if the dropdown is visible before trying to close
            if (userDropdownMenuGlobal.style.display === 'block') {
                if (!userDropdownButtonGlobal.contains(event.target) && !userDropdownMenuGlobal.contains(event.target)) {
                    userDropdownMenuGlobal.style.display = 'none';
                    userDropdownButtonGlobal.setAttribute('aria-expanded', 'false');
                }
            }
        });
    }
    // Ensure this event listener for logout in dropdown is correctly handled.
    // It's also being handled within updateAuthLink to ensure it's added after login.
    // If this causes issues, one location should be chosen (updateAuthLink is likely better).
    // For now, this adds a safety net if updateAuthLink was not called after DOM is ready but before user action.
    const logoutLinkDropdownGlobal = document.getElementById('logout-link-dropdown');
    if (logoutLinkDropdownGlobal) {
        logoutLinkDropdownGlobal.addEventListener('click', handleLogout);
    }


    if (mapContainer) { // Check if we are on the map_view.html page
        const mapId = mapContainer.dataset.mapId;
        const mapLoadingStatusDiv = document.getElementById('map-loading-status');
        const mapViewTitleH1 = document.getElementById('map-view-title');
        const mapAvailabilityDateInput = document.getElementById('map-availability-date');

        // Function to get today's date in YYYY-MM-DD for API calls
        function getTodayDateStringForMap() {
            const today = new Date();
            const yyyy = today.getFullYear();
            const mm = String(today.getMonth() + 1).padStart(2, '0');
            const dd = String(today.getDate()).padStart(2, '0');
            return `${yyyy}-${mm}-${dd}`;
        }
        
        if(mapAvailabilityDateInput) { // Initialize date picker
            mapAvailabilityDateInput.value = getTodayDateStringForMap();
        }

        async function fetchAndRenderMap(currentMapId, dateString) {
            mapLoadingStatusDiv.textContent = 'Loading map details...';
            mapContainer.innerHTML = ''; // Clear previous resource areas

            try {
                const apiUrl = dateString ? `/api/map_details/${currentMapId}?date=${dateString}` : `/api/map_details/${currentMapId}`;
                const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv); // mapLoadingStatusDiv for messages

                // Display map image
                mapContainer.style.backgroundImage = `url(${data.map_details.image_url})`;
                if (mapViewTitleH1) mapViewTitleH1.textContent = `Map View: ${data.map_details.name}`;
                
                // Render resource areas
                if (data.mapped_resources && data.mapped_resources.length > 0) {
                    data.mapped_resources.forEach(resource => {
                        if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                            const coords = resource.map_coordinates;
                            const areaDiv = document.createElement('div');
                            areaDiv.className = 'resource-area'; 
                            areaDiv.style.left = `${coords.x}px`;
                            areaDiv.style.top = `${coords.y}px`;
                            areaDiv.style.width = `${coords.width}px`;
                            areaDiv.style.height = `${coords.height}px`;
                            areaDiv.textContent = resource.name; 
                            areaDiv.dataset.resourceId = resource.id; 

                            // Determine availability and set class
                            let availabilityClass = 'resource-area-unknown'; // Default or if no booking info
                            const bookings = resource.bookings_on_date;

                            if (bookings) { // Ensure bookings_on_date array exists
                                if (bookings.length === 0) {
                                    availabilityClass = 'resource-area-available';
                                } else {
                                    let totalBookedMinutes = 0;
                                    const workDayStartHour = 8; // Changed from 9 to 8
                                    const workDayEndHour = 17; // 5 PM

                                    bookings.forEach(booking => {
                                        const [sH, sM, sS] = booking.start_time.split(':').map(Number);
                                        const [eH, eM, eSS] = booking.end_time.split(':').map(Number);
                                        
                                        const bookingStart = new Date(2000, 0, 1, sH, sM, sS);
                                        const bookingEnd = new Date(2000, 0, 1, eH, eM, eSS);
                                        
                                        // Consider only time within typical work hours for "fully booked" heuristic
                                        const slotStartInWorkHours = new Date(2000, 0, 1, Math.max(workDayStartHour, sH), sM, sS);
                                        const slotEndInWorkHours = new Date(2000, 0, 1, Math.min(workDayEndHour, eH), eM, eSS);

                                        if (slotEndInWorkHours > slotStartInWorkHours) {
                                            totalBookedMinutes += (slotEndInWorkHours - slotStartInWorkHours) / (1000 * 60);
                                        }
                                    });

                                    const workDayDurationMinutes = (workDayEndHour - workDayStartHour) * 60;

                                    if (totalBookedMinutes >= workDayDurationMinutes * 0.75) { // Example: 75% of workday booked
                                        availabilityClass = 'resource-area-fully-booked';
                                    } else if (totalBookedMinutes > 0) {
                                        availabilityClass = 'resource-area-partially-booked';
                                    } else { 
                                        availabilityClass = 'resource-area-available';
                                    }
                                }
                            }
                            
                            // Remove previous availability classes before adding the new one
                            let mapAreaAvailabilityClass = availabilityClass; 
                            let isMapAreaClickable = true; // Assume clickable initially
                            const currentUserId = parseInt(sessionStorage.getItem('loggedInUserId'), 10);
                            const currentUserIsAdmin = sessionStorage.getItem('loggedInUserIsAdmin') === 'true';

                            // Use the helper function for complex permission check
                            if (!checkUserPermissionForResource(resource, currentUserId, currentUserIsAdmin)) {
                                mapAreaAvailabilityClass = 'resource-area-restricted'; // New class for permission denied
                                isMapAreaClickable = false;
                                areaDiv.title = `${resource.name} (Access Restricted)`;
                            } else {
                                areaDiv.title = resource.name; // Default title if accessible
                            }
                            
                            // Remove previous availability/restriction classes before adding the new one(s)
                            areaDiv.classList.remove(
                                'resource-area-available', 'resource-area-partially-booked', 
                                'resource-area-fully-booked', 'resource-area-unknown', 
                                'resource-area-admin-only', 'resource-area-restricted', // Make sure to remove old admin-only if it's no longer the case
                                'map-area-clickable'
                            );
                            areaDiv.classList.add(mapAreaAvailabilityClass);

                            if (isMapAreaClickable && 
                                mapAreaAvailabilityClass !== 'resource-area-fully-booked' && 
                                mapAreaAvailabilityClass !== 'resource-area-unknown') { // Removed admin-only check here as it's covered by checkUserPermissionForResource
                                
                                areaDiv.classList.add('map-area-clickable');
                                const newAreaDiv = areaDiv.cloneNode(true);
                                areaDiv.parentNode.replaceChild(newAreaDiv, areaDiv);
                                areaDiv = newAreaDiv; 

                                areaDiv.addEventListener('click', function() {
                                    handleMapAreaClick(resource.id, resource.name, mapAvailabilityDateInput.value);
                                });
                            } else {
                                areaDiv.classList.remove('map-area-clickable');
                                const newAreaDiv = areaDiv.cloneNode(true); 
                                areaDiv.parentNode.replaceChild(newAreaDiv, areaDiv);
                                areaDiv = newAreaDiv; 
                            }
                            
                            mapContainer.appendChild(areaDiv);
                        }
                    });
                    mapLoadingStatusDiv.textContent = ''; 
                } else {
                    mapLoadingStatusDiv.textContent = 'No resources are mapped to this floor plan yet.';
                }

            } catch (error) {
                console.error('Error fetching or rendering map:', error);
                mapLoadingStatusDiv.textContent = `Error loading map: ${error.message}`;
                mapContainer.style.backgroundImage = 'none'; 
            }
        }

        const timeSlotModal = document.getElementById('time-slot-modal');
        const modalCloseBtn = timeSlotModal ? timeSlotModal.querySelector('.close-modal-btn') : null;
        const modalResourceNameSpan = document.getElementById('modal-resource-name');
        const modalDateSpan = document.getElementById('modal-date');
        const modalTimeSlotsListDiv = document.getElementById('modal-time-slots-list');
        const modalBookingTitleInput = document.getElementById('modal-booking-title');
        const modalConfirmBookingBtn = document.getElementById('modal-confirm-booking-btn');
        const modalStatusMessage = document.getElementById('modal-status-message');
        let selectedTimeSlotForBooking = null; // Variable to store selected slot

        async function handleMapAreaClick(resourceId, resourceName, dateString) {
            console.log(`Map area clicked: Resource ID ${resourceId}, Name: ${resourceName}, Date: ${dateString}`);
            if (mapLoadingStatusDiv) {
                mapLoadingStatusDiv.textContent = `Fetching available slots for ${resourceName} on ${dateString}...`;
                mapLoadingStatusDiv.style.color = 'inherit';
            }

            try {
                const detailedBookedSlots = await apiCall(
                    `/api/resources/${resourceId}/availability?date=${dateString}`, {}, modalStatusMessage 
                );
                openTimeSlotSelectionModal(resourceId, resourceName, dateString, detailedBookedSlots);
                if (mapLoadingStatusDiv) hideMessage(mapLoadingStatusDiv); 
                if (modalStatusMessage && !modalStatusMessage.classList.contains('error')) hideMessage(modalStatusMessage);
            } catch (error) {
                // Error handling primarily by apiCall. Alert for additional feedback.
                let errorMsgDisplayed = modalStatusMessage && modalStatusMessage.classList.contains('error');
                if (!errorMsgDisplayed && mapLoadingStatusDiv) {
                     showError(mapLoadingStatusDiv, `Error fetching slots for ${resourceName}.`);
                     errorMsgDisplayed = true;
                }
                if (!errorMsgDisplayed && modalStatusMessage) { // If modal status is visible but not yet showing an error
                    showError(modalStatusMessage, `Error fetching slots: ${error.message}`);
                }
                alert(`Could not load time slots for ${resourceName}. Details: ${error.message}`);
            }
        }

        function openTimeSlotSelectionModal(resourceId, resourceName, dateString, detailedBookedSlots) {
            if (!timeSlotModal) return;

            modalResourceNameSpan.textContent = resourceName;
            modalDateSpan.textContent = dateString;
            modalBookingTitleInput.value = ''; // Clear previous title
            modalTimeSlotsListDiv.innerHTML = ''; // Clear previous slots
            modalStatusMessage.textContent = ''; // Clear status message
            selectedTimeSlotForBooking = null; // Reset selected slot
            
            // Store resourceId and dateString for the confirm booking button
            if(modalConfirmBookingBtn) {
                modalConfirmBookingBtn.dataset.resourceId = resourceId;
                modalConfirmBookingBtn.dataset.dateString = dateString;
            }


            // Define working hours (e.g., 8 AM to 5 PM) and slot duration (e.g., 1 hour)
            const workDayStartHour = 8; // Changed from 9 to 8
            const workDayEndHour = 17; // Ends at 17:00, so last slot is 16:00-17:00
            const slotDurationHours = 1;

            for (let hour = workDayStartHour; hour < workDayEndHour; hour += slotDurationHours) {
                const slotStart = new Date(`${dateString}T${String(hour).padStart(2, '0')}:00:00`);
                const slotEnd = new Date(slotStart.getTime() + slotDurationHours * 60 * 60 * 1000);
                
                const startTimeStr = `${String(slotStart.getHours()).padStart(2, '0')}:00`;
                const endTimeStr = `${String(slotEnd.getHours()).padStart(2, '0')}:00`;
                const slotLabel = `${startTimeStr} - ${endTimeStr}`;

                let isBooked = false;
                for (const booked of detailedBookedSlots) {
                    const bookedStart = new Date(`${dateString}T${booked.start_time}`);
                    const bookedEnd = new Date(`${dateString}T${booked.end_time}`);
                    // Check for overlap: (BookedStart < SlotEnd) and (BookedEnd > SlotStart)
                    if (bookedStart < slotEnd && bookedEnd > slotStart) {
                        isBooked = true;
                        break;
                    }
                }

                const slotDiv = document.createElement('div');
                slotDiv.classList.add('time-slot-item');
                slotDiv.textContent = slotLabel;

                if (isBooked) {
                    slotDiv.classList.add('time-slot-booked');
                    slotDiv.textContent += ' (Booked)';
                } else {
                    slotDiv.classList.add('time-slot-available');
                    slotDiv.dataset.startTime = startTimeStr;
                    slotDiv.dataset.endTime = endTimeStr;
                    slotDiv.addEventListener('click', function() {
                        // Remove 'selected' from previously selected slot
                        const previouslySelected = modalTimeSlotsListDiv.querySelector('.time-slot-selected');
                        if (previouslySelected) {
                            previouslySelected.classList.remove('time-slot-selected');
                        }
                        // Add 'selected' to current slot
                        this.classList.add('time-slot-selected');
                        selectedTimeSlotForBooking = { 
                            startTimeStr: this.dataset.startTime, 
                            endTimeStr: this.dataset.endTime 
                        };
                        if(modalStatusMessage) modalStatusMessage.textContent = ''; // Clear previous messages
                    });
                }
                modalTimeSlotsListDiv.appendChild(slotDiv);
            }
            timeSlotModal.style.display = 'block';
        }

        if (modalCloseBtn) {
            modalCloseBtn.onclick = function() {
                timeSlotModal.style.display = "none";
                selectedTimeSlotForBooking = null; // Reset
            }
        }
        // Also close if user clicks outside the modal content (optional)
        window.onclick = function(event) {
            if (event.target == timeSlotModal) {
                timeSlotModal.style.display = "none";
                selectedTimeSlotForBooking = null; // Reset
            }
        }

        if (modalConfirmBookingBtn) {
            modalConfirmBookingBtn.addEventListener('click', async function() {
                modalStatusMessage.textContent = ''; // Clear previous messages

                if (!selectedTimeSlotForBooking) {
                    modalStatusMessage.textContent = 'Please select an available time slot.';
                    modalStatusMessage.style.color = 'red';
                    return;
                }

                const loggedInUser = sessionStorage.getItem('loggedInUser');
                if (!loggedInUser) {
                    modalStatusMessage.textContent = 'Please login to make a booking.';
                    modalStatusMessage.style.color = 'red';
                    return;
                }

                const resourceId = this.dataset.resourceId; // From button's dataset, set when modal opened
                const dateString = this.dataset.dateString; // From button's dataset
                const title = modalBookingTitleInput.value.trim();

                const bookingData = {
                    resource_id: parseInt(resourceId, 10),
                    date_str: dateString,
                    start_time_str: selectedTimeSlotForBooking.startTimeStr,
                    end_time_str: selectedTimeSlotForBooking.endTimeStr,
                    title: title,
                    user_name: loggedInUser
                };

                console.log("Submitting booking from map view:", bookingData);
                modalStatusMessage.textContent = 'Submitting booking...';
                modalStatusMessage.style.color = 'inherit';

                try {
                    const responseData = await apiCall(
                        '/api/bookings', 
                        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bookingData) }, 
                        modalStatusMessage
                    );
                    showSuccess(modalStatusMessage, `Booking for '${responseData.title || 'Untitled'}' (ID: ${responseData.id}) confirmed!`);
                    setTimeout(() => { 
                        if(timeSlotModal) timeSlotModal.style.display = "none"; 
                        selectedTimeSlotForBooking = null; 
                    }, 1500);
                    const mapIdRefresh = mapContainer ? mapContainer.dataset.mapId : null;
                    const dateRefresh = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : null;
                    if (mapIdRefresh && dateRefresh) fetchAndRenderMap(mapIdRefresh, dateRefresh);
                } catch (error) {
                    // Error shown by apiCall in modalStatusMessage
                    console.error('Booking from map view modal failed:', error.message);
                }
            });
        }
        // Initial fetch and render
        if (mapId) {
            const initialDate = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : getTodayDateStringForMap();
            fetchAndRenderMap(mapId, initialDate);
        } else {
            mapLoadingStatusDiv.textContent = 'Map ID not found.';
        }
        
        // Placeholder for date change event listener (next step)
        if (mapAvailabilityDateInput) {
            mapAvailabilityDateInput.addEventListener('change', function() {
                fetchAndRenderMap(mapId, this.value);
            });
        }
    }

    // --- Home Page Specific Logic ---
    const availableResourcesListDiv = document.getElementById('available-resources-now-list');
    if (availableResourcesListDiv) {
        displayAvailableResourcesNow();
    }

    // --- Accessibility Controls ---
    const toggleHighContrastBtn = document.getElementById('toggle-high-contrast');
    const increaseFontSizeBtn = document.getElementById('increase-font-size');
    const decreaseFontSizeBtn = document.getElementById('decrease-font-size');
    const resetFontSizeBtn = document.getElementById('reset-font-size');

    // High Contrast
    function toggleHighContrast() {
        document.body.classList.toggle('high-contrast');
        const isEnabled = document.body.classList.contains('high-contrast');
        localStorage.setItem('highContrastEnabled', isEnabled);
    }

    function loadHighContrastPreference() {
        const isEnabled = localStorage.getItem('highContrastEnabled') === 'true';
        if (isEnabled) {
            document.body.classList.add('high-contrast');
        }
    }

    if (toggleHighContrastBtn) {
        toggleHighContrastBtn.addEventListener('click', toggleHighContrast);
    }

    // Font Size Adjustment
    const BASE_FONT_SIZE_REM = 1.0; // Corresponds to 1rem, assuming root font-size in CSS is 16px
    const FONT_SIZE_STEP_REM = 0.1;
    const MAX_FONT_SIZE_REM = 2.0; // Max 2rem
    const MIN_FONT_SIZE_REM = 0.7; // Min 0.7rem

    function getCurrentRootFontSizeRem() {
        const currentSizeStyle = document.documentElement.style.fontSize;
        if (currentSizeStyle && currentSizeStyle.endsWith('rem')) {
            return parseFloat(currentSizeStyle);
        } else if (currentSizeStyle && currentSizeStyle.endsWith('px')) {
            // Convert px to rem if :root has px (should not happen with current CSS)
            const rootBasePx = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-size').trim().replace('px','')) || 16;
            return parseFloat(currentSizeStyle) / rootBasePx;
        }
        // If no style is set directly on <html>, check computed style from CSS (:root font-size)
        const computedRootFontSize = getComputedStyle(document.documentElement).fontSize;
        if (computedRootFontSize && computedRootFontSize.endsWith('px')) {
             const rootBasePxFromCSS = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-size').trim().replace('px','')) || 16;
            return parseFloat(computedRootFontSize) / rootBasePxFromCSS;
        }
        return BASE_FONT_SIZE_REM; // Default if nothing is found
    }


    function changeFontSize(amountInRem) {
        let currentSizeRem = getCurrentRootFontSizeRem();
        let newSizeRem = currentSizeRem + amountInRem;

        // Clamp the new font size
        newSizeRem = Math.max(MIN_FONT_SIZE_REM, Math.min(newSizeRem, MAX_FONT_SIZE_REM));
        
        document.documentElement.style.fontSize = `${newSizeRem}rem`;
        localStorage.setItem('rootFontSize', `${newSizeRem}rem`);
    }

    function increaseFontSize() {
        changeFontSize(FONT_SIZE_STEP_REM);
    }

    function decreaseFontSize() {
        changeFontSize(-FONT_SIZE_STEP_REM);
    }

    function resetFontSize() {
        document.documentElement.style.removeProperty('font-size');
        localStorage.removeItem('rootFontSize');
        // Re-apply the :root default from CSS by forcing a re-evaluation (if needed)
        // Or simply rely on the CSS default to take over.
        // Forcing a re-evaluation can be tricky. Easiest is to set it to initial or empty.
        // The browser will then use the CSS defined on :root or its default.
    }

    function loadFontSizePreference() {
        const savedFontSize = localStorage.getItem('rootFontSize');
        if (savedFontSize) {
            // Validate before applying (e.g. ensure it's a rem value)
            if (savedFontSize.endsWith('rem') && !isNaN(parseFloat(savedFontSize))) {
                 document.documentElement.style.fontSize = savedFontSize;
            } else {
                localStorage.removeItem('rootFontSize'); // Clear invalid value
            }
        }
    }

    if (increaseFontSizeBtn) {
        increaseFontSizeBtn.addEventListener('click', increaseFontSize);
    }
    if (decreaseFontSizeBtn) {
        decreaseFontSizeBtn.addEventListener('click', decreaseFontSize);
    }
    if (resetFontSizeBtn) {
        resetFontSizeBtn.addEventListener('click', resetFontSize);
    }

    // Load preferences on script load
    loadHighContrastPreference();
    loadFontSizePreference();

    // --- Language Selection ---
    const languageSelector = document.getElementById('language-selector');

    function handleLanguageChange() {
        const selectedLang = languageSelector.value;
        localStorage.setItem('selectedLanguage', selectedLang);
        
        // Update the lang query parameter and reload
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
            // If there's a language in localStorage, and it's not already in the URL,
            // or if it's different from the one in the URL, update the URL.
            if (queryLang !== storedLang) {
                currentParams.set('lang', storedLang);
                // This redirect ensures the URL reflects the stored preference,
                // and the backend get_locale can pick it up.
                // This should ideally only redirect if necessary to avoid loops.
                // The condition queryLang !== storedLang helps prevent immediate redirect loops.
                window.location.search = currentParams.toString();
                return; // Return to avoid further processing if a redirect is happening
            }
        } else if (queryLang && languageSelector) {
            // If no storedLang, but lang in query, update dropdown and localStorage
            languageSelector.value = queryLang;
            localStorage.setItem('selectedLanguage', queryLang);
        }
        // If languageSelector does not exist on the page, do nothing further.
        // This can happen on pages that don't include the accessibility footer (e.g. login page if it uses a different base template)
        // However, the task implies index.html is the primary target for the selector.
    }

    if (languageSelector) {
        languageSelector.addEventListener('change', handleLanguageChange);
    }

    // Load language preference - this needs to be careful about redirect loops
    // The current logic in loadLanguagePreference tries to mitigate this.
    loadLanguagePreference();

});
