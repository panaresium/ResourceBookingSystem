// JavaScript for Smart Resource Booking

// --- Authentication Logic ---
async function updateAuthLink() {
    const authLinkContainer = document.getElementById('auth-link-container');
    const adminMapsNavLink = document.getElementById('admin-maps-nav-link');
    let welcomeMessageContainer = document.getElementById('welcome-message-container');

    // Ensure welcome message container exists or create it (it should be in HTML already)
    if (!welcomeMessageContainer && authLinkContainer && authLinkContainer.parentNode) {
        console.warn("'welcome-message-container' not found, creating dynamically. Best to add it to HTML templates.");
        const newWelcomeLi = document.createElement('li');
        newWelcomeLi.id = 'welcome-message-container';
        newWelcomeLi.style.display = 'none'; // Initially hidden
        newWelcomeLi.style.marginRight = '10px';
        authLinkContainer.parentNode.insertBefore(newWelcomeLi, authLinkContainer.parentNode.firstChild); // Insert at the beginning
        welcomeMessageContainer = newWelcomeLi; // Assign the newly created element
    }
    
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();

        if (data.logged_in && data.user) {
            sessionStorage.setItem('loggedInUserUsername', data.user.username);
            sessionStorage.setItem('loggedInUserIsAdmin', data.user.is_admin ? 'true' : 'false');

            if (welcomeMessageContainer) {
                welcomeMessageContainer.textContent = `Welcome, ${data.user.username}!`;
                welcomeMessageContainer.style.display = 'list-item'; 
            }
            if (authLinkContainer) {
                authLinkContainer.innerHTML = '<a href="#" id="logout-link">Logout</a>';
                const logoutLink = document.getElementById('logout-link');
                if (logoutLink) {
                    logoutLink.addEventListener('click', handleLogout);
                }
            }
            if (adminMapsNavLink) {
                adminMapsNavLink.style.display = data.user.is_admin ? 'list-item' : 'none';
            }
        } else {
            sessionStorage.removeItem('loggedInUserUsername');
            sessionStorage.removeItem('loggedInUserIsAdmin');
            if (welcomeMessageContainer) {
                welcomeMessageContainer.textContent = '';
                welcomeMessageContainer.style.display = 'none';
            }
            if (authLinkContainer) {
                authLinkContainer.innerHTML = `<a href="${document.body.dataset.loginUrl || '/login'}">Login</a>`;
            }
            if (adminMapsNavLink) {
                adminMapsNavLink.style.display = 'none';
            }
        }
    } catch (error) {
        console.error("Error fetching auth status:", error);
        if (welcomeMessageContainer) welcomeMessageContainer.style.display = 'none';
        if (authLinkContainer) authLinkContainer.innerHTML = `<a href="${document.body.dataset.loginUrl || '/login'}">Login</a>`;
        if (adminMapsNavLink) adminMapsNavLink.style.display = 'none';
        sessionStorage.removeItem('loggedInUserUsername');
        sessionStorage.removeItem('loggedInUserIsAdmin');
    }
}

async function handleLogout(event) {
    if(event) event.preventDefault(); 
    
    console.log("Handling logout...");
    try {
        const response = await fetch('/api/auth/logout', { method: 'POST' });
        // Try to parse JSON, but handle cases where it might not be (e.g. network error page)
        let responseData = { success: false, error: "Logout request failed or unexpected response." };
        try {
            responseData = await response.json();
        } catch (e) {
            console.warn("Could not parse JSON from logout response:", e);
            if (response.ok) { // If status is OK but no JSON, assume success
                 responseData = { success: true, message: "Logout successful (no content)." };
            }
        }


        if (response.ok && responseData.success) {
            console.log("Logout successful from API:", responseData.message);
            sessionStorage.removeItem('loggedInUserUsername');
            sessionStorage.removeItem('loggedInUserIsAdmin');
            
            await updateAuthLink(); 
            
            if (window.location.pathname.startsWith('/admin')) {
                window.location.href = '/';
            } else if (window.location.pathname === (document.body.dataset.loginUrl || '/login')) {
                // If on login page, just update links, no redirect.
            } else {
                 window.location.href = document.body.dataset.loginUrl || '/login';
            }

        } else {
            console.error("Logout failed from API:", responseData.error || "Unknown error");
            alert("Logout failed: " + (responseData.error || "Unknown error"));
        }
    } catch (error) {
        console.error("Error during logout fetch operation:", error);
        alert("Logout request failed. Please check your connection.");
    }
}

// --- Home Page: Display Available Resources Now ---
async function displayAvailableResourcesNow() {
    const availableResourcesListDiv = document.getElementById('available-resources-now-list');
    if (!availableResourcesListDiv) {
        return; // Not on the home page or div is missing
    }

    availableResourcesListDiv.innerHTML = '<p>Loading available resources...</p>';

    try {
        // Get current date and hour
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const currentDateYMD = `${year}-${month}-${day}`;
        const currentHour = now.getHours(); // 0-23

        // Fetch all published resources
        const resourcesResponse = await fetch('/api/resources');
        if (!resourcesResponse.ok) {
            throw new Error(`Failed to fetch resources: ${resourcesResponse.status}`);
        }
        const resources = await resourcesResponse.json();

        if (!resources || resources.length === 0) {
            availableResourcesListDiv.innerHTML = '<p>No resources found.</p>';
            return;
        }

        const availableNowResources = [];

        for (const resource of resources) {
            if (resource.status !== 'published') { // Should be redundant due to API default but good to double check
                continue;
            }
            try {
                const availabilityResponse = await fetch(`/api/resources/${resource.id}/availability?date=${currentDateYMD}`);
                if (!availabilityResponse.ok) {
                    console.error(`Failed to fetch availability for resource ${resource.id}: ${availabilityResponse.status}`);
                    continue; // Skip this resource on error
                }
                const bookedSlots = await availabilityResponse.json();

                let isBookedThisHour = false;
                if (bookedSlots && bookedSlots.length > 0) {
                    for (const booking of bookedSlots) {
                        const startTimeHour = parseInt(booking.start_time.split(':')[0], 10);
                        const endTimeHour = parseInt(booking.end_time.split(':')[0], 10);

                        // Check if currentHour falls within the booking slot
                        // Booking: 10:00 to 12:00. currentHour = 10 (booked), currentHour = 11 (booked)
                        // Booking: 10:00 to 10:30. currentHour = 10 (booked)
                        // A booking ends AT the hour, so if endTimeHour is 11, it's booked up to 10:59:59.
                        // So currentHour must be LESS than endTimeHour.
                        if (startTimeHour <= currentHour && currentHour < endTimeHour) {
                            isBookedThisHour = true;
                            break;
                        }
                    }
                }

                if (!isBookedThisHour) {
                    availableNowResources.push(resource.name);
                }
            } catch (availError) {
                console.error(`Error processing availability for resource ${resource.id}:`, availError);
                // Continue to the next resource
            }
        }

        if (availableNowResources.length === 0) {
            availableResourcesListDiv.innerHTML = '<p>No resources currently available.</p>';
        } else {
            const ul = document.createElement('ul');
            availableNowResources.forEach(name => {
                const li = document.createElement('li');
                li.textContent = name;
                ul.appendChild(li);
            });
            availableResourcesListDiv.innerHTML = ''; // Clear loading message
            availableResourcesListDiv.appendChild(ul);
        }

    } catch (error) {
        console.error('Error in displayAvailableResourcesNow:', error);
        availableResourcesListDiv.innerHTML = '<p>Error fetching available resources. Please try refreshing.</p>';
        availableResourcesListDiv.classList.add('error'); // Optional: for styling
    }
}


document.addEventListener('DOMContentLoaded', function() {
    // Set login URL on body for dynamic link creation
    if (document.getElementById('login-form')) { 
        document.body.dataset.loginUrl = "#"; // Avoid self-linking on login page
    } else {
        document.body.dataset.loginUrl = "/login"; 
    }
    
    updateAuthLink(); // Call on every page load

    const bookingForm = document.getElementById('booking-form');
    const bookingResultsDiv = document.getElementById('booking-results');
    const loginForm = document.getElementById('login-form');

    // --- New Booking Page Specific Logic ---
    if (bookingForm) {
        const resourceSelectBooking = document.getElementById('resource-select-booking');

        // Populate Resource Selector for New Booking Page
        if (resourceSelectBooking) {
            fetch('/api/resources')
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    resourceSelectBooking.innerHTML = '<option value="">-- Select a Resource --</option>'; // Clear and add default
                    if (data.length === 0) {
                        const option = new Option('No resources available', '');
                        option.disabled = true;
                        resourceSelectBooking.add(option);
                        return;
                    }
                    data.forEach(resource => {
                        // Only add published resources that are bookable by someone (generic check, API will enforce specific user)
                        if (resource.status === 'published') {
                             const option = new Option(`${resource.name} (Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                             resourceSelectBooking.add(option);
                        }
                    });
                })
                .catch(error => {
                    console.error('Error fetching resources for new booking form:', error);
                    resourceSelectBooking.innerHTML = '<option value="">Error loading resources</option>';
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
            const startTimeInput = document.getElementById('start-time'); // Already defined above for time slots
            const endTimeInput = document.getElementById('end-time');     // Already defined above for time slots
            // const bookingTitleInput = document.getElementById('booking-title'); // Assuming this ID if a title field is added

            const resourceId = resourceSelectBooking ? resourceSelectBooking.value : '';
            const dateValue = dateInput ? dateInput.value : '';
            const startTimeValue = startTimeInput ? startTimeInput.value : '';
            const endTimeValue = endTimeInput ? endTimeInput.value : '';
            // const titleValue = bookingTitleInput ? bookingTitleInput.value.trim() : 'User Booking'; // Use a default or get from input
            const titleValue = `Booking for ${resourceSelectBooking.options[resourceSelectBooking.selectedIndex].text.split(' (Capacity:')[0]}`;


            // Basic Validation
            if (!resourceId) {
                if (bookingResultsDiv) {
                    bookingResultsDiv.innerHTML = '<p>Please select a resource.</p>';
                    bookingResultsDiv.classList.add('error');
                }
                return;
            }
            if (!dateValue || !startTimeValue || !endTimeValue) {
                if (bookingResultsDiv) {
                    bookingResultsDiv.innerHTML = '<p>Please fill in date, start time, and end time.</p>';
                    bookingResultsDiv.classList.add('error');
                }
                return; // Stop further processing
            }
            
            // Construct booking data
            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateValue,
                start_time_str: startTimeValue,
                end_time_str: endTimeValue,
                title: titleValue, 
                user_name: loggedInUsername 
            };

            if (bookingResultsDiv) {
                bookingResultsDiv.innerHTML = '<p>Submitting booking...</p>';
                bookingResultsDiv.classList.remove('error', 'success'); // Clear previous styling
            }

            try {
                const response = await fetch('/api/bookings', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(bookingData)
                });

                const responseData = await response.json();

                if (response.ok) { // Typically 201 Created
                    if (bookingResultsDiv) {
                        // Refined success message construction
                        let resourceName = 'N/A';
                        if (resourceSelectBooking && resourceSelectBooking.selectedIndex !== -1) {
                            const selectedOptionText = resourceSelectBooking.options[resourceSelectBooking.selectedIndex].text;
                            resourceName = selectedOptionText.split(' (Capacity:')[0];
                        }

                        const displayDate = responseData.start_time ? responseData.start_time.split(' ')[0] : 'N/A';
                        const displayStartTime = responseData.start_time ? responseData.start_time.split(' ')[1].substring(0,5) : 'N/A';
                        const displayEndTime = responseData.end_time ? responseData.end_time.split(' ')[1].substring(0,5) : 'N/A';
                        const displayTitle = responseData.title || 'N/A';
                        const displayBookingId = responseData.id || 'N/A';

                        bookingResultsDiv.innerHTML = `
                            <p><strong>Booking Confirmed!</strong><br>
                            Resource: ${resourceName}<br>
                            Date: ${displayDate}<br>
                            Time: ${displayStartTime} - ${displayEndTime}<br>
                            Title: ${displayTitle}<br>
                            Booking ID: ${displayBookingId}</p>
                        `;
                        bookingResultsDiv.className = 'success';
                        bookingForm.reset(); 
                        const manualRadio = document.querySelector('input[name="quick_time_option"][value="manual"]');
                        if(manualRadio) {
                            manualRadio.checked = true;
                            manualRadio.dispatchEvent(new Event('change'));
                        }
                    }
                } else {
                    if (bookingResultsDiv) {
                        bookingResultsDiv.innerHTML = `<p>Booking failed: ${responseData.error || 'Unknown error. Please try again.'}</p>`;
                        bookingResultsDiv.className = 'error';
                    }
                    console.error('Booking failed:', responseData);
                }
            } catch (error) {
                console.error('Error making booking API call:', error);
                if (bookingResultsDiv) {
                    bookingResultsDiv.innerHTML = '<p>Booking request failed due to a network or server error. Please try again.</p>';
                    bookingResultsDiv.className = 'error';
                }
            }
        });
    }

    if (loginForm) {
        loginForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const usernameInput = document.getElementById('username');
            const username = usernameInput ? usernameInput.value.trim() : '';

            if (loginMessageDiv) loginMessageDiv.innerHTML = ''; // Clear previous messages

            event.preventDefault(); // Prevent default form submission
            loginMessageDiv.textContent = 'Logging in...';
            loginMessageDiv.style.color = 'inherit';
            loginMessageDiv.classList.remove('error', 'success'); // Clear previous styling classes

            const usernameInput = document.getElementById('username'); 
            const passwordInput = document.getElementById('password'); 
            
            const username = usernameInput.value.trim();
            const password = passwordInput.value; // Do not trim password

            if (!username || !password) {
                loginMessageDiv.textContent = 'Username and password are required.';
                loginMessageDiv.style.color = 'red';
                loginMessageDiv.classList.add('error');
                return;
            }

            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username: username, password: password })
                });

                const responseData = await response.json();

                if (response.ok) { 
                    loginMessageDiv.textContent = responseData.message || 'Login successful!';
                    loginMessageDiv.style.color = 'green';
                    loginMessageDiv.classList.add('success');

                    if (responseData.user) {
                        sessionStorage.setItem('loggedInUserUsername', responseData.user.username);
                        sessionStorage.setItem('loggedInUserIsAdmin', responseData.user.is_admin ? 'true' : 'false');
                        sessionStorage.setItem('loggedInUserId', responseData.user.id); // **Ensure this is present**
                    } else {
                        // This case should ideally not happen if API guarantees user object on success
                        sessionStorage.setItem('loggedInUserUsername', username); 
                        sessionStorage.removeItem('loggedInUserIsAdmin'); // Clear if no specific info
                        sessionStorage.removeItem('loggedInUserId');    // Clear if no specific info
                    }
                    
                    if (typeof updateAuthLink === 'function') {
                        // updateAuthLink might become async if it directly calls /api/auth/status
                        // For now, assume it's synchronous or handles its own async logic
                        updateAuthLink(); 
                    }
                    
                    // Redirect after a short delay to allow user to see message, or immediately
                    setTimeout(() => {
                        window.location.href = '/'; // Redirect to home page
                    }, 500); // 0.5 second delay

                } else {
                    loginMessageDiv.textContent = responseData.error || 'Login failed. Please try again.';
                    loginMessageDiv.style.color = 'red';
                    loginMessageDiv.classList.add('error');
                    sessionStorage.removeItem('loggedInUserUsername'); 
                    sessionStorage.removeItem('loggedInUserIsAdmin');
                }
            } catch (error) {
                console.error('Login API call error:', error);
                loginMessageDiv.textContent = 'Login request failed. Please check your connection or contact support.';
                loginMessageDiv.style.color = 'red';
                loginMessageDiv.classList.add('error');
                sessionStorage.removeItem('loggedInUserUsername');
                sessionStorage.removeItem('loggedInUserIsAdmin');
            }
        });
    }

// --- Permission Helper Function ---
function checkUserPermissionForResource(resource, currentUserId, currentUserIsAdmin) {
    if (!resource) return false; // Should not happen if resource details are passed

    // 1. Coarse check: 'admin_only'
    if (resource.booking_restriction === 'admin_only') {
        return currentUserIsAdmin;
    }

    // 2. Granular checks (if not 'admin_only')
    // These apply if booking_restriction is 'all_users', null, or empty.
    let canBookByUserId = false;
    if (resource.allowed_user_ids && resource.allowed_user_ids.trim() !== "") {
        const allowedIds = resource.allowed_user_ids.split(',').map(idStr => parseInt(idStr.trim(), 10));
        if (allowedIds.includes(currentUserId)) {
            canBookByUserId = true;
        }
    }

    let canBookByRole = false;
    if (resource.allowed_roles && resource.allowed_roles.trim() !== "") {
        const allowedRolesList = resource.allowed_roles.split(',').map(role => role.trim().toLowerCase());
        const userRole = currentUserIsAdmin ? 'admin' : 'standard_user';
        if (allowedRolesList.includes(userRole)) {
            canBookByRole = true;
        }
    }

    // Determine final permission based on granular rules
    const hasUserIdRestriction = resource.allowed_user_ids && resource.allowed_user_ids.trim() !== "";
    const hasRoleRestriction = resource.allowed_roles && resource.allowed_roles.trim() !== "";

    if (hasUserIdRestriction && hasRoleRestriction) {
        return canBookByUserId || canBookByRole; // User needs to match EITHER if both are set
    } else if (hasUserIdRestriction) {
        return canBookByUserId;
    } else if (hasRoleRestriction) {
        return canBookByRole;
    } else {
        // No specific granular restrictions, and not 'admin_only', so any authenticated user can book.
        // (The @login_required on booking API handles the "authenticated" part for the API itself)
        return true; 
    }
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
            if (!resourceId) {
                clearCalendar();
                return;
            }
            console.log(`Fetching availability for resource ${resourceId} on ${dateString}`, currentResourceDetails);
            try {
                const response = await fetch(`/api/resources/${resourceId}/availability?date=${dateString}`);
                if (!response.ok) {
                    throw new Error(`API request failed: ${response.status} - ${response.statusText}`);
                }
                const bookedSlots = await response.json();
                updateCalendarDisplay(bookedSlots, dateString, currentResourceDetails); 
            } catch (error) {
                console.error('Error fetching or displaying availability:', error);
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

        async function makeBookingApiCall(bookingData) {
            try {
                const response = await fetch('/api/bookings', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(bookingData)
                });

                const responseData = await response.json(); 

                if (response.ok) { 
                    alert(`Booking successful! Title: ${responseData.title || 'Untitled'}
ID: ${responseData.id}`);
                    
                    if (typeof fetchAndDisplayAvailability === 'function' && 
                        roomSelectDropdown && 
                        availabilityDateInput) {
                        fetchAndDisplayAvailability(
                            roomSelectDropdown.value,
                            availabilityDateInput.value
                        );
                    }
                } else {
                    alert(`Booking failed: ${responseData.error || 'Unknown error'}`);
                    console.error('Booking failed:', responseData);
                }
            } catch (error) {
                console.error('Error making booking API call:', error);
                alert('Booking request failed. Please try again or check the console for errors.');
            }
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

        // Initial population of room selector and then fetching availability
        fetch('/api/resources')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                roomSelectDropdown.innerHTML = ''; // Clear existing options
                if (data.length === 0) {
                    const option = new Option('No rooms available', '');
                    roomSelectDropdown.add(option);
                    clearCalendar(); // No rooms, clear calendar
                    return;
                }
                data.forEach(resource => {
                    const option = new Option(resource.name, resource.id);
                    option.dataset.bookingRestriction = resource.booking_restriction || "";
                    option.dataset.allowedUserIds = resource.allowed_user_ids || "";
                    option.dataset.allowedRoles = resource.allowed_roles || "";
                    roomSelectDropdown.add(option);
                });
                
                // After populating, if there are options, select the first and fetch availability
                if (roomSelectDropdown.options.length > 0) {
                    if (!roomSelectDropdown.value && roomSelectDropdown.options[0]) {
                        roomSelectDropdown.value = roomSelectDropdown.options[0].value;
                    }
                    const selectedOption = roomSelectDropdown.selectedOptions[0];
                    const initialResourceDetails = { 
                        id: roomSelectDropdown.value, 
                        booking_restriction: selectedOption.dataset.bookingRestriction,
                        allowed_user_ids: selectedOption.dataset.allowedUserIds,
                        allowed_roles: selectedOption.dataset.allowedRoles
                    };
                    fetchAndDisplayAvailability(initialResourceDetails.id, availabilityDateInput.value, initialResourceDetails);
                } else {
                     clearCalendar(); 
                }
            })
            .catch(error => {
                console.error('Error fetching resources:', error);
                roomSelectDropdown.innerHTML = '<option value="">Error loading rooms</option>';
                clearCalendar(true); // Error fetching rooms, clear calendar
            });
        
        // Logic for displaying floor map links on resources.html
        const floorMapsListUl = document.getElementById('floor-maps-list');
        if (floorMapsListUl) { 
            async function fetchAndDisplayFloorMapLinks() {
                try {
                    const response = await fetch('/api/admin/maps'); 
                    if (!response.ok) {
                        throw new Error(`Failed to fetch floor maps: ${response.status}`);
                    }
                    const maps = await response.json();

                    floorMapsListUl.innerHTML = ''; 

                    if (maps.length === 0) {
                        floorMapsListUl.innerHTML = '<li>No floor maps available.</li>';
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

                } catch (error) {
                    console.error('Error fetching or displaying floor map links:', error);
                    if (floorMapsListUl) { 
                       floorMapsListUl.innerHTML = '<li>Error loading floor maps.</li>';
                    }
                }
            }
            fetchAndDisplayFloorMapLinks();
        }
    }

    // Admin Maps Page Specific Logic
    const adminMapsPageIdentifier = document.getElementById('upload-map-form'); // Check if on admin maps page
    if (adminMapsPageIdentifier) {
        const uploadMapForm = document.getElementById('upload-map-form');
        const mapsListUl = document.getElementById('maps-list');
        const uploadStatusDiv = document.getElementById('upload-status');
        
        // Function to fetch and display maps
        async function fetchAndDisplayMaps() {
            try {
                const response = await fetch('/api/admin/maps');
                if (!response.ok) {
                    throw new Error(`Failed to fetch maps: ${response.status}`);
                }
                const maps = await response.json();
                
                mapsListUl.innerHTML = ''; // Clear existing list
                if (maps.length === 0) {
                    mapsListUl.innerHTML = '<li>No maps uploaded yet.</li>';
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
                    // Add event listener for "Define Areas" button later (Step 5)
                    mapsListUl.appendChild(listItem);
                });

            } catch (error) {
                console.error('Error fetching maps:', error);
                mapsListUl.innerHTML = '<li>Error loading maps.</li>';
            }
        }

        // Handle Map Upload Form Submission
        if (uploadMapForm) {
            uploadMapForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                uploadStatusDiv.textContent = 'Uploading...';
                uploadStatusDiv.style.color = 'inherit';

                const formData = new FormData(uploadMapForm);
                // No need to set Content-Type header for FormData with fetch

                try {
                    const response = await fetch('/api/admin/maps', {
                        method: 'POST',
                        body: formData 
                    });

                    const responseData = await response.json();

                    if (response.ok) { // Status 201 Created
                        uploadStatusDiv.textContent = `Map '${responseData.name}' uploaded successfully!`;
                        uploadStatusDiv.style.color = 'green';
                        uploadMapForm.reset(); // Clear the form
                        fetchAndDisplayMaps(); // Refresh the list
                    } else {
                        uploadStatusDiv.textContent = `Upload failed: ${responseData.error || 'Unknown error'}`;
                        uploadStatusDiv.style.color = 'red';
                    }
                } catch (error) {
                    console.error('Error uploading map:', error);
                    uploadStatusDiv.textContent = 'Upload failed due to a network or server error.';
                    uploadStatusDiv.style.color = 'red';
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
            console.log(`Fetching existing areas for map ID: ${mapId}`);
            existingMapAreas = []; // Clear previous map's areas
    
            try {
                const response = await fetch(`/api/map_details/${mapId}`); // No date needed for just coordinates
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(`Failed to fetch map details for existing areas: ${response.status} ${errorData.error || ''}`);
                }
                const data = await response.json();
    
                if (data.mapped_resources && data.mapped_resources.length > 0) {
                    data.mapped_resources.forEach(resource => {
                        if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                            existingMapAreas.push({ // Store necessary info
                                id: resource.id,
                                name: resource.name,
                                map_coordinates: resource.map_coordinates, // Already an object from this API
                                booking_restriction: resource.booking_restriction, 
                                status: resource.status // **NEW** - Assuming /api/map_details includes status
                            });
                        }
                    });
                    console.log("Fetched existing areas:", existingMapAreas);
                } else {
                    console.log("No existing mapped resources found for this map.");
                }
            } catch (error) {
                console.error('Error fetching existing map areas:', error);
                // Optionally display an error to the user on the UI
            }
            redrawCanvas(); // Redraw canvas to show these areas (and clear any temp drawing)
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
            try {
                const response = await fetch('/api/resources'); // Existing endpoint
                if (!response.ok) {
                    throw new Error(`Failed to fetch resources: ${response.status}`);
                }
                const resources = await response.json();
                
                resourceToMapSelect.innerHTML = '<option value="">-- Select a Resource to Map --</option>'; // Clear and add default

                resources.forEach(resource => {
                    // Filter condition:
                    // 1. Resource is not mapped anywhere (no floor_map_id OR no map_coordinates).
                    // 2. OR Resource is already mapped to the CURRENTLY selected map (allowing re-edit of its coordinates on this map).
                    if ((!resource.floor_map_id || !resource.map_coordinates) || (resource.floor_map_id === parseInt(currentMapId))) {
                        const option = document.createElement('option');
                        option.value = resource.id;
                        // Display name and status
                        option.textContent = `${resource.name} (ID: ${resource.id}) - Status: ${resource.status || 'N/A'}`; 
                        option.dataset.resourceId = resource.id; // Store id
                        option.dataset.resourceStatus = resource.status || 'draft'; // Store status, default to draft if undefined
                        
                        if (resource.floor_map_id === parseInt(currentMapId) && resource.map_coordinates) {
                            option.textContent += ` (Currently on this map - edit coordinates)`;
                        } 
                        resourceToMapSelect.appendChild(option);
                    }
                });

            } catch (error) {
                console.error('Error populating resources for mapping:', error);
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
                
                const payload = {
                    floor_map_id: floorMapId,
                    coordinates: coordinates
                };

                try {
                    const response = await fetch(`/api/admin/resources/${selectedResourceId}/map_info`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(payload)
                    });

                    const responseData = await response.json();

                    if (response.ok) {
                        areaDefinitionStatusDiv.textContent = `Area defined successfully for resource '${responseData.name || selectedResourceId}'!`;
                        areaDefinitionStatusDiv.style.color = 'green';
                        // defineAreaForm.reset(); // Optional: reset form
                        // resourceToMapSelect.value = ''; // Optional: deselect resource
                        
                        const currentMapIdForRefresh = hiddenFloorMapIdInput.value; 
                        // Refresh the resource dropdown (existing logic)
                        if (currentMapIdForRefresh && typeof populateResourcesForMapping === 'function') {
                             await populateResourcesForMapping(currentMapIdForRefresh);
                        }
                        
                        // *** NEW: Refresh the canvas to show the newly saved area ***
                        if (currentMapIdForRefresh && typeof fetchAndDrawExistingMapAreas === 'function') {
                            await fetchAndDrawExistingMapAreas(currentMapIdForRefresh);
                        } else {
                            console.warn("Could not refresh canvas map areas: currentMapId or function missing.");
                        }

                        // Optionally clear the drawing form fields and currentDrawnRect
                        document.getElementById('coord-x').value = '';
                        document.getElementById('coord-y').value = '';
                        document.getElementById('coord-width').value = '';
                        document.getElementById('coord-height').value = '';
                        if (bookingPermissionDropdown) bookingPermissionDropdown.value = ""; // Reset booking permission dropdown
                        currentDrawnRect = null; // Clear the temporary drawn rectangle
                        // fetchAndDrawExistingMapAreas calls redrawCanvas, which will clear the temporary drawing
                        // if currentDrawnRect is null and then draw the updated existingMapAreas.
                        
                    } else {
                        areaDefinitionStatusDiv.textContent = `Failed to define area: ${responseData.error || 'Unknown error'}`;
                        areaDefinitionStatusDiv.style.color = 'red';
                    }
                } catch (error) {
                    console.error('Error defining area:', error);
                    areaDefinitionStatusDiv.textContent = 'Failed to define area due to a network or server error.';
                    areaDefinitionStatusDiv.style.color = 'red';
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
                    const response = await fetch(`/api/admin/resources/${selectedAreaForEditing.id}/map_info`, {
                        method: 'DELETE',
                        headers: {
                            'Content-Type': 'application/json' // Not strictly needed for DELETE with no body, but good practice
                        }
                    });
    
                    let responseData = {};
                    const contentType = response.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        responseData = await response.json();
                    } else {
                        if (response.ok) responseData.message = "Deletion successful (no content).";
                        else responseData.error = `Server returned ${response.status} (no content).`;
                    }
    
                    if (response.ok) { // Status 200 or 204
                        areaDefinitionStatusDiv.textContent = responseData.message || `Mapping for ${resourceName} deleted successfully.`;
                        areaDefinitionStatusDiv.style.color = 'green';
    
                        selectedAreaForEditing = null;
                        document.getElementById('edit-delete-buttons').style.display = 'none';
                        
                    document.getElementById('define-area-form').reset(); // This should reset booking-permission too
                        if(resourceToMapSelect) resourceToMapSelect.value = '';
                    if(bookingPermissionDropdown) bookingPermissionDropdown.value = ""; // Explicit reset
    
                        const currentMapId = hiddenFloorMapIdInput.value;
                        if (currentMapId) {
                            await fetchAndDrawExistingMapAreas(currentMapId);
                            await populateResourcesForMapping(currentMapId); 
                        }
                    } else {
                        areaDefinitionStatusDiv.textContent = `Failed to delete mapping: ${responseData.error || 'Unknown error'}`;
                        areaDefinitionStatusDiv.style.color = 'red';
                    }
                } catch (error) {
                    console.error('Error deleting map mapping:', error);
                    areaDefinitionStatusDiv.textContent = 'Deletion failed due to a network or server error.';
                    areaDefinitionStatusDiv.style.color = 'red';
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
            if (!resourceId) {
                alert("Error: Resource ID not found for publishing.");
                return;
            }
    
            if (!confirm(`Are you sure you want to publish resource ID ${resourceId}?`)) {
                return;
            }
            
            const localResourceActionsContainer = document.getElementById('resource-actions-container'); // Use local var
            if (localResourceActionsContainer) {
                localResourceActionsContainer.innerHTML = `<p>Publishing resource ${resourceId}...</p>`;
            }
    
            try {
                const response = await fetch(`/api/admin/resources/${resourceId}/publish`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json' 
                    }
                });
    
                const responseData = await response.json();
    
                if (response.ok) { 
                    alert(responseData.message || `Resource ${resourceId} published successfully!`);
                    
                    const currentMapId = hiddenFloorMapIdInput.value; 
                    if (typeof populateResourcesForMapping === 'function') {
                        await populateResourcesForMapping(currentMapId); 
                    }
    
                    const resourceSelect = document.getElementById('resource-to-map');
                    if (resourceSelect) {
                        // Find the option and update its dataset, then re-trigger change
                        let foundOption = null;
                        for (let i = 0; i < resourceSelect.options.length; i++) {
                            if (resourceSelect.options[i].dataset.resourceId === resourceId) {
                                foundOption = resourceSelect.options[i];
                                break;
                            }
                        }
                        if (foundOption) {
                            foundOption.dataset.resourceStatus = 'published';
                            // Update text if needed - populateResourcesForMapping should handle this.
                        }
                        
                        // If the published resource is still selected, dispatch change to update buttons
                        if (resourceSelect.value === resourceId) {
                            resourceSelect.dispatchEvent(new Event('change'));
                        } else {
                            // If not selected, but the list was refreshed, the actions container might be blank.
                            // We can clear it or let the next selection handle it.
                            // For now, if it's not the selected one, the user will select another or this one again
                            // to see the updated status in the actions container.
                            // If it was the selected one, the dispatchEvent('change') above handles it.
                             if (localResourceActionsContainer && resourceSelect.value === "") { // No resource selected
                                localResourceActionsContainer.innerHTML = '<p><em>Select a resource from the dropdown above to see its status or publish actions.</em></p>';
                            }
                        }
                    }
                    
                    if (currentMapId && typeof fetchAndDrawExistingMapAreas === 'function') {
                        await fetchAndDrawExistingMapAreas(currentMapId);
                    }
    
                } else {
                    alert(`Failed to publish resource: ${responseData.error || 'Unknown error'}`);
                    // Re-render buttons/status for the currently selected resource to reset UI
                    const resourceSelect = document.getElementById('resource-to-map');
                    if (resourceSelect.value === resourceId) { 
                         resourceSelect.dispatchEvent(new Event('change'));
                    } else if (localResourceActionsContainer) {
                        localResourceActionsContainer.innerHTML = `<p style="color:red;">Publish failed. Refresh needed or select resource again.</p>`;
                    }
                }
            } catch (error) {
                console.error('Error publishing resource:', error);
                alert('Publishing failed due to a network or server error.');
                if (localResourceActionsContainer) {
                     localResourceActionsContainer.innerHTML = `<p style="color:red;">Publishing failed. Check console.</p>`;
                }
            }
        }
    }

    // Map View Page Specific Logic
    const mapContainer = document.getElementById('map-container');
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
                const response = await fetch(apiUrl);

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({})); 
                    throw new Error(`Failed to fetch map details: ${response.status} ${errorData.error || ''}`);
                }
                const data = await response.json();

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
                const response = await fetch(`/api/resources/${resourceId}/availability?date=${dateString}`);
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(`Failed to fetch availability: ${response.status} ${errorData.error || ''}`);
                }
                const detailedBookedSlots = await response.json();
                
                // console.log(`Detailed booked slots for ${resourceName} on ${dateString}:`, detailedBookedSlots);
                // if (mapLoadingStatusDiv) {
                //     mapLoadingStatusDiv.textContent = `Available slots fetched for ${resourceName}. Modal display next.`; // Placeholder
                // }
                // alert(`Fetched ${detailedBookedSlots.length} booked slots for ${resourceName}. Next: Show modal.`);
                openTimeSlotSelectionModal(resourceId, resourceName, dateString, detailedBookedSlots);
                if (mapLoadingStatusDiv) mapLoadingStatusDiv.textContent = ''; // Clear "Fetching..." message


            } catch (error) {
                console.error('Error fetching detailed availability for map area:', error);
                if (mapLoadingStatusDiv) {
                    mapLoadingStatusDiv.textContent = `Error fetching details: ${error.message}`;
                    mapLoadingStatusDiv.style.color = 'red';
                } else {
                    alert(`Error fetching details: ${error.message}`);
                }
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
                    const response = await fetch('/api/bookings', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(bookingData)
                    });

                    const responseData = await response.json();

                    if (response.ok) { // Status 201 Created
                        modalStatusMessage.textContent = `Booking successful! Title: ${responseData.title || 'Untitled'}, ID: ${responseData.id}`;
                        modalStatusMessage.style.color = 'green';
                        
                        setTimeout(() => {
                            if(timeSlotModal) timeSlotModal.style.display = "none";
                            selectedTimeSlotForBooking = null; // Reset
                        }, 1500);

                        const currentMapId = mapContainer ? mapContainer.dataset.mapId : null;
                        const currentDateForRefresh = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : null;
                        if (currentMapId && currentDateForRefresh && typeof fetchAndRenderMap === 'function') {
                            fetchAndRenderMap(currentMapId, currentDateForRefresh);
                        }
                        
                    } else {
                        modalStatusMessage.textContent = `Booking failed: ${responseData.error || 'Unknown error'}`;
                        modalStatusMessage.style.color = 'red';
                        console.error('Booking failed (map view):', responseData);
                    }
                } catch (error) {
                    console.error('Error making booking API call from map view:', error);
                    modalStatusMessage.textContent = 'Booking request failed due to a network or server error.';
                    modalStatusMessage.style.color = 'red';
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
});
