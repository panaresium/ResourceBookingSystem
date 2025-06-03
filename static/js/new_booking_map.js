document.addEventListener('DOMContentLoaded', function () {
    console.log('new_booking_map.js loaded and DOM fully parsed.');

    // Helper function to get today's date in YYYY-MM-DD format
    function getTodayDateString() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0'); // Months are 0-indexed
        const dd = String(today.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    // --- DOM Elements for the New Booking Map ---
    const mapAvailabilityDateInput = document.getElementById('new-booking-map-availability-date');
    const mapLocationSelect = document.getElementById('new-booking-map-location-select');
    const mapFloorSelect = document.getElementById('new-booking-map-floor-select');
    const mapContainer = document.getElementById('new-booking-map-container');
    const mapLoadingStatusDiv = document.getElementById('new-booking-map-loading-status');
    const resourceSelectBooking = document.getElementById('resource-select-booking'); // For auto-selecting resource

    let allMapInfo = []; // To store all map data from /api/admin/maps
    let currentMapId = null; // To store the ID of the currently displayed map

    const mainBookingFormDateInput = document.getElementById('booking-date');
    const mainFormStartTimeInput = document.getElementById('start-time');
    const mainFormEndTimeInput = document.getElementById('end-time');
    const mainFormManualTimeRadio = document.getElementById('time-option-manual');
    // const quickTimeOptionsRadios = document.querySelectorAll('input[name="quick_time_option"]'); // Not directly used in this script after recent changes

    let isSyncingDate = false; // Flag to prevent event loops for date inputs

    // --- Helper UI Functions ---
    function updateMapLoadingStatus(message, isError = false) {
        if (!mapLoadingStatusDiv) return;
        if (isError) {
            showError(mapLoadingStatusDiv, message);
        } else {
            // Using showSuccess for neutral/info messages as well, or create a showInfo if preferred
            showSuccess(mapLoadingStatusDiv, message); 
        }
    }

    function disableMapSelectors() {
        if (mapLocationSelect) {
            mapLocationSelect.innerHTML = '<option value="">-- Not Available --</option>';
            mapLocationSelect.disabled = true;
        }
        if (mapFloorSelect) {
            mapFloorSelect.innerHTML = '<option value="">-- Not Available --</option>';
            mapFloorSelect.disabled = true;
        }
    }

    // --- Function to highlight resource on map based on form selection ---
    function highlightSelectedResourceOnMap() {
        // const resourceSelectBooking = document.getElementById('resource-select-booking'); // Already defined globally in this script
        if (!resourceSelectBooking) {
            console.warn('#resource-select-booking dropdown not found for highlighting.');
            return;
        }
        const selectedResourceId = resourceSelectBooking.value;
        // console.log('Highlighting map resource based on form selection. Selected Resource ID:', selectedResourceId);

        const resourceAreas = document.querySelectorAll('#new-booking-map-container .resource-area');
        resourceAreas.forEach(area => {
            area.classList.remove('resource-area-form-selected');
            if (selectedResourceId && area.dataset.resourceId === selectedResourceId) {
                area.classList.add('resource-area-form-selected');
                // console.log('Applied highlight to resource area:', area.dataset.resourceId);
            }
        });
    }

    // --- Initialize Date Inputs ---
    const today = getTodayDateString();
    if (mapAvailabilityDateInput) {
        mapAvailabilityDateInput.value = today;
    } else {
        console.error('Map availability date input not found.');
    }
    if (mainBookingFormDateInput) {
        mainBookingFormDateInput.value = today;
    } else {
        console.error('Main booking form date input not found.');
    }

    /**
     * Populates the floor select dropdown based on the selected location.
     */
    function updateFloorSelectOptions() {
        if (!mapFloorSelect || !mapLocationSelect) {
            console.error("Floor or Location select dropdown not found for updateFloorSelectOptions");
            return;
        }
        const selectedLocation = mapLocationSelect.value;
        console.log(`Updating floor options for location: '${selectedLocation}'`);

        mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>'; // Reset floors

        if (!selectedLocation) { // No location selected or "-- Select Location --"
            mapFloorSelect.disabled = true;
            console.log("No location selected, floor dropdown disabled.");
            // Optionally, clear the map if no location is selected
            // handleFilterChange('map'); // This would call loadMapDetails(null, ...)
            return;
        }

        const availableFloors = [...new Set(allMapInfo
            .filter(map => map.location === selectedLocation && map.floor) // Filter by selected location and ensure floor exists
            .map(map => map.floor)
            .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
        )];
        
        console.log("Available floors for selected location:", availableFloors);

        if (availableFloors.length > 0) {
            availableFloors.forEach(floor => {
                const option = new Option(floor, floor);
                mapFloorSelect.add(option);
            });
            mapFloorSelect.disabled = false;
        } else {
            mapFloorSelect.disabled = true;
            console.log("No floors found for this location, floor dropdown disabled.");
        }
    }

    /**
     * Loads map details (image and resource areas) based on selected map and date.
     * @param {string} mapId - The ID of the map to load.
     * @param {string} dateString - The date for which to check resource availability.
     */
    async function loadMapDetails(mapId, dateString) {
        // const VERTICAL_OFFSET = 5; // Define the vertical offset in pixels // Removed

        if (!mapId) {
            if (mapContainer) mapContainer.innerHTML = ''; // Clear map
            if (mapContainer) mapContainer.style.backgroundImage = 'none';
            if (mapLoadingStatusDiv) showSuccess(mapLoadingStatusDiv, 'Please select a location and floor to view a map.');
            currentMapId = null;
            return;
        }

        if (!dateString) {
            if (mapLoadingStatusDiv) showError(mapLoadingStatusDiv, 'Please select a date.');
            return;
        }

        if (mapLoadingStatusDiv) showLoading(mapLoadingStatusDiv, 'Loading map details...');
        if (mapContainer) mapContainer.innerHTML = ''; // Clear previous resource areas

        currentMapId = mapId; // Store the current map ID

        let userBookingsForDate = [];
        const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
        if (loggedInUsername) {
            try {
                userBookingsForDate = await apiCall(`/api/bookings/my_bookings_for_date?date=${dateString}`, {}, null);
            } catch (err) {
                console.warn(`Could not fetch user's bookings for date ${dateString}:`, err.message);
                // Proceed with empty userBookingsForDate, map will show general availability
            }
        }

        try {
            const apiUrl = `/api/map_details/${mapId}?date=${dateString}`;
            // Assuming apiCall and other helper functions are globally available from script.js
            const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv);

            const mapDetails = data.map_details;
            const offsetX = parseInt(mapDetails.offset_x) || 0;
            const offsetY = parseInt(mapDetails.offset_y) || 0;

            if (mapContainer) {
                mapContainer.style.backgroundImage = `url(${mapDetails.image_url})`;
            }

            if (data.mapped_resources && data.mapped_resources.length > 0) {
                data.mapped_resources.forEach(resource => {
                    if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                        const coords = resource.map_coordinates; // Define it once for this resource.

                        // Apply offsets from mapDetails
                        let topPosition = coords.y + offsetY;
                        let leftPosition = coords.x + offsetX;
                        let widthValue = coords.width;
                        let heightValue = coords.height;

                        console.log('Processing Resource:', resource.name, 'Raw Coords:', coords, 'Applied Offsets X:', offsetX, 'Y:', offsetY);
                        console.log('Applying to CSS: top=', topPosition + 'px', 
                                    'left=', leftPosition + 'px', 
                                    'width=', widthValue + 'px', 
                                    'height=', heightValue + 'px');
                        const areaDiv = document.createElement('div');
                        areaDiv.className = 'resource-area'; // Base class
                        areaDiv.style.left = `${leftPosition}px`;
                        areaDiv.style.top = `${topPosition}px`;
                        areaDiv.style.width = `${widthValue}px`;
                        areaDiv.style.height = `${heightValue}px`;
                        areaDiv.textContent = resource.name;
                        areaDiv.dataset.resourceId = resource.id;
                        // areaDiv.title = resource.name; // Title will be set based on availability

                        // --- Start of new availability logic ---
                        const primarySlots = [
                            { name: "first_half", start: 8 * 60, end: 12 * 60, isGenerallyAvailable: true, isAvailableToUser: true },
                            { name: "second_half", start: 13 * 60, end: 17 * 60, isGenerallyAvailable: true, isAvailableToUser: true }
                        ];
                        function timeToMinutes(timeStr) { // HH:MM or HH:MM:SS
                            const parts = timeStr.split(':');
                            return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
                        }

                        // Determine General Availability for Primary Slots for THIS resource
                        if (resource.bookings_on_date && resource.bookings_on_date.length > 0) {
                            resource.bookings_on_date.forEach(booking => {
                                const bookingStartMinutes = timeToMinutes(booking.start_time);
                                const bookingEndMinutes = timeToMinutes(booking.end_time);
                                primarySlots.forEach(slot => {
                                    if (Math.max(slot.start, bookingStartMinutes) < Math.min(slot.end, bookingEndMinutes)) {
                                        slot.isGenerallyAvailable = false;
                                    }
                                });
                            });
                        }

                        // Check User's Conflicts for Generally Available Primary Slots
                        if (loggedInUsername && userBookingsForDate && userBookingsForDate.length > 0) {
                            primarySlots.forEach(slot => {
                                if (slot.isGenerallyAvailable) {
                                    for (const userBooking of userBookingsForDate) {
                                        if (String(userBooking.resource_id) !== String(resource.id)) { // User's booking on a DIFFERENT resource
                                            const userBookingStartMinutes = timeToMinutes(userBooking.start_time);
                                            const userBookingEndMinutes = timeToMinutes(userBooking.end_time);
                                            if (Math.max(slot.start, userBookingStartMinutes) < Math.min(slot.end, userBookingEndMinutes)) {
                                                slot.isAvailableToUser = false;
                                                break;
                                            }
                                        }
                                    }
                                }
                            });
                        }

                        let allGenerallyAvailableSlotsBlockedForUser = true;
                        let anyGenerallyAvailableSlotExists = false;
                        primarySlots.forEach(slot => {
                            if (slot.isGenerallyAvailable) {
                                anyGenerallyAvailableSlotExists = true;
                                if (slot.isAvailableToUser) {
                                    allGenerallyAvailableSlotsBlockedForUser = false;
                                }
                            }
                        });
                        if (!anyGenerallyAvailableSlotExists) { // If no slots were generally available to begin with
                            allGenerallyAvailableSlotsBlockedForUser = false;
                        }
                        // --- End of new availability logic ---

                        // Clear existing classes before applying new ones
                        areaDiv.classList.remove('resource-area-available', 'resource-area-partially-booked', 'resource-area-fully-booked', 'resource-area-user-conflict', 'resource-area-restricted', 'resource-area-unknown');

                        let finalAvailabilityClass = 'resource-area-unknown'; // Default
                        let isMapAreaClickable = true;
                        const currentUserId = parseInt(sessionStorage.getItem('loggedInUserId'), 10);
                        const currentUserIsAdmin = sessionStorage.getItem('loggedInUserIsAdmin') === 'true';
                        const resourceForPermission = { // Ensure this object is correctly populated for checkUserPermissionForResource
                            id: resource.id, name: resource.name,
                            booking_restriction: resource.booking_restriction,
                            allowed_user_ids: resource.allowed_user_ids,
                            roles: resource.roles // Ensure roles are passed correctly
                        };

                        if (!checkUserPermissionForResource(resourceForPermission, currentUserId, currentUserIsAdmin)) {
                            finalAvailabilityClass = 'resource-area-restricted';
                            isMapAreaClickable = false;
                            areaDiv.title = `${resource.name} (Access Restricted)`;
                        } else if (!anyGenerallyAvailableSlotExists) { // All primary slots are booked on this resource
                            finalAvailabilityClass = 'resource-area-fully-booked';
                            areaDiv.title = resource.name + " (Fully Booked)";
                            isMapAreaClickable = false;
                        } else if (loggedInUsername && allGenerallyAvailableSlotsBlockedForUser) { // anyGenerallyAvailableSlotExists must be true here
                            finalAvailabilityClass = 'resource-area-user-conflict';
                            areaDiv.title = resource.name + " (Unavailable - Your bookings conflict)";
                            isMapAreaClickable = false;
                        } else {
                            // Slots are generally available, and not all are blocked by user's other bookings.
                            // Determine if available, partial based on remaining generally available slots that are also available to user.
                            const stillBookableSlots = primarySlots.filter(slot => slot.isGenerallyAvailable && slot.isAvailableToUser);
                            if (stillBookableSlots.length === primarySlots.filter(slot => slot.isGenerallyAvailable).length && stillBookableSlots.length > 0) {
                                finalAvailabilityClass = 'resource-area-available';
                            } else if (stillBookableSlots.length > 0) {
                                finalAvailabilityClass = 'resource-area-partially-booked';
                            } else {
                                // This case should ideally be covered by !anyGenerallyAvailableSlotExists or allGenerallyAvailableSlotsBlockedForUser
                                // but as a fallback, if no slots are bookable by the user for other reasons (e.g. partial general booking not covering a full primary slot)
                                finalAvailabilityClass = 'resource-area-fully-booked'; // Or 'unavailable' if a more generic term is preferred
                            }

                            let statusText = finalAvailabilityClass.replace('resource-area-','').replace('-',' ');
                            statusText = statusText.charAt(0).toUpperCase() + statusText.slice(1);
                            areaDiv.title = resource.name + (finalAvailabilityClass !== 'resource-area-available' ? ` (${statusText})` : ' (Available)');

                            // Redundant check for fully-booked, but safe
                            if (finalAvailabilityClass === 'resource-area-fully-booked' || finalAvailabilityClass === 'resource-area-unknown') {
                                isMapAreaClickable = false;
                            }
                        }

                        areaDiv.classList.add(finalAvailabilityClass);

                        // Make clickable if not fully booked, not unknown, not user conflict, and not restricted
                        if (isMapAreaClickable) {
                            areaDiv.classList.add('map-area-clickable');
                            areaDiv.addEventListener('click', function() {
                                if (resourceSelectBooking) {
                                    resourceSelectBooking.value = resource.id;
                                    resourceSelectBooking.dispatchEvent(new Event('change'));
                                }
                                // Pass userBookingsForDate to openResourceDetailModal
                                openResourceDetailModal(resource, dateString, userBookingsForDate);
                            });
                        }
                        // Highlight resource if it's the one selected in the main form
                        if (resourceSelectBooking && resourceSelectBooking.value === resource.id.toString()) {
                            areaDiv.classList.add('resource-area-form-selected');
                        }
                        if (mapContainer) mapContainer.appendChild(areaDiv);
                    }
                });
                if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                     hideMessage(mapLoadingStatusDiv); // Hide "Loading map details..." if no other message took its place
                }
            } else {
                if (mapLoadingStatusDiv) showSuccess(mapLoadingStatusDiv, 'No resources are mapped to this floor plan.');
            }

        } catch (error) {
            // apiCall should have displayed the error in mapLoadingStatusDiv
            console.error('Error fetching or rendering map details:', error);
            if (mapContainer) mapContainer.style.backgroundImage = 'none'; // Clear image on error
             if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error')) { // Fallback error message
                showError(mapLoadingStatusDiv, `Error loading map: ${error.message}`);
            }
        }
    }

    /**
     * Handles changes in location, floor, or date to load the appropriate map.
     */
    function handleFilterChange(source = 'map') { // source can be 'map' or 'form'
        if (isSyncingDate) return;
        isSyncingDate = true;

        const selectedLocation = mapLocationSelect ? mapLocationSelect.value : null;
        const selectedFloor = mapFloorSelect ? mapFloorSelect.value : null;
        let selectedDate = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : null;

        if (source === 'form' && mainBookingFormDateInput) {
            selectedDate = mainBookingFormDateInput.value;
            if (mapAvailabilityDateInput && mapAvailabilityDateInput.value !== selectedDate) {
                mapAvailabilityDateInput.value = selectedDate;
            }
        } else if (source === 'map' && mapAvailabilityDateInput) {
            selectedDate = mapAvailabilityDateInput.value;
            if (mainBookingFormDateInput && mainBookingFormDateInput.value !== selectedDate) {
                mainBookingFormDateInput.value = selectedDate;
            }
        }

        if (!selectedLocation || !selectedFloor) {
            console.log("Location or Floor not selected. Clearing map.");
            loadMapDetails(null, selectedDate).finally(() => { isSyncingDate = false; });
            // isSyncingDate = false; // This was potentially problematic, finally block in loadMapDetails handles it better if async.
                                     // For now, let's assume loadMapDetails is not always async or handles its own flag.
                                     // Simpler: just set it at the end of this function.
            // No, this is fine: if we return early, we must reset.
            isSyncingDate = false; 
            return;
        }

        const mapToLoad = allMapInfo.find(map => map.location === selectedLocation && map.floor === selectedFloor);
        console.log(`Attempting to find map for Location: '${selectedLocation}', Floor: '${selectedFloor}'. Found:`, mapToLoad);

        if (mapToLoad && mapToLoad.id) {
            console.log(`Loading map ID: ${mapToLoad.id} for date: ${selectedDate}`);
            loadMapDetails(mapToLoad.id, selectedDate).finally(() => { isSyncingDate = false; });
        } else {
            console.log("No specific map ID found for selection. Clearing map.");
            loadMapDetails(null, selectedDate).finally(() => { isSyncingDate = false; });
            if (mapLoadingStatusDiv && selectedLocation && selectedFloor) { // Only show if both are selected but no map found
                 showError(mapLoadingStatusDiv, 'No map found for the selected location and floor combination.');
            } else if (mapLoadingStatusDiv) {
                 showSuccess(mapLoadingStatusDiv, 'Please complete location and floor selection.');
            }
        }
        // Highlight selected resource after map loads/reloads (if any)
        // This call might be too early if loadMapDetails hasn't populated areas yet,
        // but it's correctly placed according to the previous plan.
        // highlightSelectedResourceOnMap(); // Call moved to end of loadMapDetails
    }

    /**
     * Fetches available maps and populates selection dropdowns.
     */
    async function loadAvailableMaps() {
        if (!mapLocationSelect || !mapFloorSelect || !mapLoadingStatusDiv) {
            console.error("One or more critical map control elements are missing from the DOM.");
            updateMapLoadingStatus("Map interface error. Please contact support.", true);
            disableMapSelectors();
            return;
        }

        updateMapLoadingStatus("Loading available maps...", false); // Neutral message
        console.log('Attempting to fetch maps from /api/admin/maps');

        try {
            // Directly using fetch to implement detailed logging as per instructions
            const response = await fetch('/api/admin/maps');
            console.log('Response status from /api/admin/maps:', response.status);
            const responseText = await response.text();
            console.log('Raw response text from /api/admin/maps:', responseText);

            if (!response.ok) {
                console.error('Failed to fetch maps. Status:', response.status, 'Response:', responseText);
                let userErrorMessage = `Error fetching map list: ${response.statusText || 'Server error'} (Status: ${response.status})`;
                if (response.status === 403) {
                    userErrorMessage += ". Please check if you have permissions to view maps, or try logging in again.";
                }
                updateMapLoadingStatus(userErrorMessage, true);
                disableMapSelectors();
                return;
            }

            let maps = [];
            try {
                maps = JSON.parse(responseText);
                console.log('Successfully parsed maps:', maps);
            } catch (jsonError) {
                console.error('Error parsing JSON response from /api/admin/maps:', jsonError);
                console.error('JSON parsing error occurred with text:', responseText);
                updateMapLoadingStatus('Error processing map data. Response was not valid JSON.', true);
                disableMapSelectors();
                return;
            }
            
            // Ensure maps is an array before proceeding
            if (!Array.isArray(maps)) {
                console.error('Parsed map data is not an array:', maps);
                updateMapLoadingStatus('Unexpected map data format received.', true);
                disableMapSelectors();
                return; // Exit the function
            }

            allMapInfo = maps; // Store the maps (now confirmed to be an array)

            if (!allMapInfo || allMapInfo.length === 0) {
                console.log('No maps available from API.');
                updateMapLoadingStatus('No maps configured in the system.', false); // Neutral message
                disableMapSelectors();
                return;
            }
            
            console.log('Populating location dropdown with maps:', allMapInfo);
            // Populate Location Select
            const locations = [...new Set(allMapInfo.map(map => map.location).filter(loc => loc))].sort();
            console.log("Unique locations found:", locations);
            
            if (mapLocationSelect) {
                mapLocationSelect.innerHTML = '<option value="">-- Select Location --</option>';
                if (locations.length > 0) {
                    locations.forEach(location => {
                        const option = new Option(location, location);
                        mapLocationSelect.add(option);
                    });
                    mapLocationSelect.disabled = false; // Enable if locations are available
                } else {
                    // No locations found, though maps exist (e.g., maps with no location string)
                    mapLocationSelect.innerHTML = '<option value="">-- No Locations --</option>';
                    mapLocationSelect.disabled = true;
                }
            } else {
                console.error("mapLocationSelect element not found.");
            }

            // Initialize Floor Select (will be updated by location change)
            if (mapFloorSelect) {
                mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>';
                mapFloorSelect.disabled = true; // Remains disabled until a location is chosen
            } else {
                 console.error("mapFloorSelect element not found.");
            }

            // Add event listeners
            if (mapLocationSelect) {
                mapLocationSelect.addEventListener('change', () => {
                    updateFloorSelectOptions();
                    // When location changes, floor is reset, so map should clear until floor is selected.
                    handleFilterChange('map'); 
                });
            }
            if (mapFloorSelect) {
                 mapFloorSelect.addEventListener('change', () => handleFilterChange('map'));
            }
            if (mapAvailabilityDateInput) {
                mapAvailabilityDateInput.addEventListener('change', () => handleFilterChange('map'));
            }
            // Sync from main form date to map date
            if (mainBookingFormDateInput) {
                mainBookingFormDateInput.addEventListener('change', () => handleFilterChange('form'));
            }
            // Event listener for main form resource selection
            if (resourceSelectBooking) {
                resourceSelectBooking.addEventListener('change', highlightSelectedResourceOnMap);
            }
            
            // Initial state: no map loaded, message cleared or set by previous logic
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                 // Use updateMapLoadingStatus for consistency
                updateMapLoadingStatus('Please select a location and floor to see the map.', false);
            }
            // Call highlight after initial setup, in case a resource is pre-selected by browser/form state
            highlightSelectedResourceOnMap(); 

        } catch (error) {
            console.error('Error in loadAvailableMaps fetch operation:', error);
            updateMapLoadingStatus('Could not load map options due to a network or server error.', true);
            disableMapSelectors();
        }
    }

    // --- Initialize ---
    if (mapContainer) { // Only run if the map container element is on the page
        loadAvailableMaps();
    } else {
        console.log("New booking map container not found on this page. Map script not initialized.");
    }

    // --- Modal Handling ---
    const resourceDetailModal = document.getElementById('new-booking-time-slot-modal');
    const closeModalButton = document.getElementById('new-booking-close-modal-btn');
    const modalResourceNameSpan = document.getElementById('new-booking-modal-resource-name');
    const modalResourceImageImg = document.getElementById('new-booking-modal-resource-image');
    const modalDateSpan = document.getElementById('new-booking-modal-date');
    const modalStatusMessageP = document.getElementById('new-booking-modal-status-message');
    const modalTimeSlotsListDiv = document.getElementById('new-booking-modal-time-slots-list');
    const modalBookingTitleInput = document.getElementById('new-booking-modal-booking-title');
    const modalConfirmBookingBtn = document.getElementById('new-booking-modal-confirm-booking-btn');

    let selectedTimeSlotForNewBooking = null; // Variable to store selected slot details

    // Accept userBookingsForDate as a new parameter
    async function openResourceDetailModal(resource, dateString, userBookingsForDate = []) {
        if (!resourceDetailModal || !modalResourceNameSpan || !modalDateSpan || !modalResourceImageImg || !modalTimeSlotsListDiv || !modalBookingTitleInput || !modalConfirmBookingBtn || !modalStatusMessageP) {
            console.error('One or more modal elements are missing for new booking.');
            return;
        }

        modalResourceNameSpan.textContent = resource.name || 'N/A';
        modalDateSpan.textContent = dateString || 'N/A';
        modalBookingTitleInput.value = `Booking for ${resource.name}`; // Pre-fill title
        modalTimeSlotsListDiv.innerHTML = ''; // Clear previous slots
        modalStatusMessageP.textContent = ''; // Clear status message
        selectedTimeSlotForNewBooking = null; // Reset selected slot

        if (resource.image_url) {
            modalResourceImageImg.src = resource.image_url;
            modalResourceImageImg.alt = resource.name || 'Resource Image';
            modalResourceImageImg.style.display = 'block';
        } else {
            modalResourceImageImg.src = '#';
            modalResourceImageImg.alt = 'No image available';
            modalResourceImageImg.style.display = 'none';
        }

        // Store resourceId and dateString for the confirm booking button
        modalConfirmBookingBtn.dataset.resourceId = resource.id;
        modalConfirmBookingBtn.dataset.dateString = dateString;
        modalConfirmBookingBtn.dataset.resourceName = resource.name;


        showLoading(modalStatusMessageP, 'Loading time slots...');

        try {
            const bookedSlots = await apiCall(`/api/resources/${resource.id}/availability?date=${dateString}`, {}, modalStatusMessageP);
            hideMessage(modalStatusMessageP); // Hide loading message if successful

            const predefinedSlots = [
                { name: "First Half-Day", label: "Book First Half-Day (08:00-12:00)", startTime: "08:00", endTime: "12:00", id: "first_half" },
                { name: "Second Half-Day", label: "Book Second Half-Day (13:00-17:00)", startTime: "13:00", endTime: "17:00", id: "second_half" },
                { name: "Full Day", label: "Book Full Day (08:00-17:00)", startTime: "08:00", endTime: "17:00", id: "full_day" }
            ];

            // Helper function to check for conflicts
            function checkConflict(slotStartTimeStr, slotEndTimeStr, existingBookings) {
                if (!existingBookings || existingBookings.length === 0) return false;
                const slotStart = new Date(`${dateString}T${slotStartTimeStr}:00`);
                const slotEnd = new Date(`${dateString}T${slotEndTimeStr}:00`);

                for (const booked of existingBookings) {
                    const bookedStart = new Date(`${dateString}T${booked.start_time}`);
                    const bookedEnd = new Date(`${dateString}T${booked.end_time}`);
                    // Check for overlap: (BookedStart < SlotEnd) and (BookedEnd > SlotStart)
                    if (bookedStart < slotEnd && bookedEnd > slotStart) {
                        return true; // Conflict found
                    }
                }
                return false; // No conflict
            }

            predefinedSlots.forEach(slot => {
                const button = document.createElement('button');
                button.textContent = slot.label;
                button.classList.add('time-slot-item', 'button');
                button.dataset.slotId = slot.id;
                // Clear previous dynamic states
                button.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-user-busy', 'selected', 'time-slot-selected');
                button.disabled = false;
                button.textContent = slot.label; // Reset text to original label
                button.title = ''; // Reset title


                const isGenerallyConflicting = checkConflict(slot.startTime, slot.endTime, bookedSlots);

                if (isGenerallyConflicting) {
                    button.classList.add('time-slot-booked');
                    button.disabled = true;
                    button.title = `${slot.name} is unavailable due to existing bookings on this resource.`;
                } else {
                    let isUserBusyElsewhere = false;
                    const loggedInUsernameChecked = sessionStorage.getItem('loggedInUserUsername'); // Use a different var name to avoid conflict
                    if (loggedInUsernameChecked && userBookingsForDate && userBookingsForDate.length > 0) {
                        const slotStart = new Date(`${dateString}T${slot.startTime}:00`);
                        const slotEnd = new Date(`${dateString}T${slot.endTime}:00`);
                        for (const userBooking of userBookingsForDate) {
                            if (String(userBooking.resource_id) !== String(resource.id)) {
                                const userBookingStart = new Date(`${dateString}T${userBooking.start_time}`);
                                const userBookingEnd = new Date(`${dateString}T${userBooking.end_time}`);
                                if (userBookingStart < slotEnd && userBookingEnd > slotStart) {
                                    isUserBusyElsewhere = true;
                                    break;
                                }
                            }
                        }
                    }

                    if (isUserBusyElsewhere) {
                        button.classList.add('time-slot-user-busy');
                        button.disabled = true;
                        button.title = `${slot.name} is unavailable as you have another booking at this time.`;
                        button.textContent = slot.label + " (Your Conflict)";
                    } else {
                        button.classList.add('time-slot-available');
                        button.title = `${slot.name} is available.`;
                        button.addEventListener('click', function() {
                            const allButtons = modalTimeSlotsListDiv.querySelectorAll('button.time-slot-item');
                            allButtons.forEach(btn => btn.classList.remove('time-slot-selected', 'selected'));
                            this.classList.add('time-slot-selected', 'selected');
                            selectedTimeSlotForNewBooking = {
                                startTimeStr: slot.startTime,
                                endTimeStr: slot.endTime
                            };
                            if (modalStatusMessageP) modalStatusMessageP.textContent = '';
                            if (mainFormStartTimeInput) mainFormStartTimeInput.value = slot.startTime;
                            if (mainFormEndTimeInput) mainFormEndTimeInput.value = slot.endTime;
                        });
                    }
                }
                modalTimeSlotsListDiv.appendChild(button);
            });

            // Refine Full Day Slot Logic
            const firstHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="first_half"]');
            const secondHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="second_half"]');
            const fullDayBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="full_day"]');

            if (fullDayBtn && firstHalfBtn && secondHalfBtn) {
                 // Check if fullDayBtn itself is already booked on the resource (takes highest precedence)
                const isFullDayGenerallyBooked = fullDayBtn.classList.contains('time-slot-booked');

                if (!isFullDayGenerallyBooked) { // Only proceed if full day isn't already resource-booked
                    const firstHalfBooked = firstHalfBtn.classList.contains('time-slot-booked');
                    const secondHalfBooked = secondHalfBtn.classList.contains('time-slot-booked');
                    const firstHalfUserConflict = firstHalfBtn.classList.contains('time-slot-user-busy');
                    const secondHalfUserConflict = secondHalfBtn.classList.contains('time-slot-user-busy');
                    const fullDaySlotDetails = predefinedSlots.find(s => s.id === 'full_day');


                    if (firstHalfBooked || secondHalfBooked) {
                        fullDayBtn.disabled = true;
                        fullDayBtn.classList.remove('time-slot-available', 'time-slot-user-busy', 'selected', 'time-slot-selected');
                        fullDayBtn.classList.add('time-slot-booked');
                        fullDayBtn.title = "Full Day is unavailable because part of the day is booked on this resource.";
                        if (fullDaySlotDetails) fullDayBtn.textContent = fullDaySlotDetails.label + " (Booked)";
                    } else if (firstHalfUserConflict || secondHalfUserConflict) {
                        fullDayBtn.disabled = true;
                        fullDayBtn.classList.remove('time-slot-available', 'time-slot-booked', 'selected', 'time-slot-selected');
                        fullDayBtn.classList.add('time-slot-user-busy');
                        fullDayBtn.title = "Full Day is unavailable because you have other bookings conflicting with part of this day.";
                        if (fullDaySlotDetails) fullDayBtn.textContent = fullDaySlotDetails.label + " (Your Conflict)";
                    }
                }
            }

        } catch (error) {
            // apiCall should have shown error in modalStatusMessageP
            console.error(`Error fetching time slots for resource ${resource.id}:`, error.message);
            if (!modalStatusMessageP.classList.contains('error')) { // Fallback
                showError(modalStatusMessageP, 'Could not load time slots.');
            }
        }
        resourceDetailModal.style.display = 'block';
    }

    if (closeModalButton) {
        closeModalButton.onclick = function() {
            if (resourceDetailModal) resourceDetailModal.style.display = 'none';
            selectedTimeSlotForNewBooking = null; // Reset
        }
    }

    window.onclick = function(event) {
        if (event.target == resourceDetailModal) {
            resourceDetailModal.style.display = "none";
            selectedTimeSlotForNewBooking = null; // Reset
        }
    }

    if (modalConfirmBookingBtn) {
        modalConfirmBookingBtn.addEventListener('click', async function() {
            if (modalStatusMessageP) modalStatusMessageP.textContent = '';

            if (!selectedTimeSlotForNewBooking) {
                showError(modalStatusMessageP, 'Please select an available time slot.');
                return;
            }

            const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
            if (!loggedInUsername) {
                showError(modalStatusMessageP, 'Please login to make a booking. You might need to refresh the page after logging in.');
                // Consider redirecting to login or prompting to login
                return;
            }

            const resourceId = this.dataset.resourceId;
            const dateString = this.dataset.dateString;
            const resourceName = this.dataset.resourceName || "this resource";
            let title = modalBookingTitleInput.value.trim();
            if (!title) { // Default title if user leaves it blank
                title = `Booking for ${resourceName}`;
            }


            const bookingData = {
                resource_id: parseInt(resourceId, 10),
                date_str: dateString,
                start_time_str: selectedTimeSlotForNewBooking.startTimeStr,
                end_time_str: selectedTimeSlotForNewBooking.endTimeStr,
                title: title,
                user_name: loggedInUsername
            };

            showLoading(modalStatusMessageP, 'Submitting booking...');

            try {
                const responseData = await apiCall('/api/bookings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                }, modalStatusMessageP);

                // apiCall handles showing success/error in modalStatusMessageP
                // If successful, responseData will have the booking details.
                // responseData.message might be used by apiCall's showSuccess.
                // If not, we can provide a default.
                if (responseData && (responseData.id || (responseData.bookings && responseData.bookings.length > 0))) {
                     if (!modalStatusMessageP.classList.contains('success')) { // If apiCall didn't set a specific success message
                        showSuccess(modalStatusMessageP, `Booking for '${responseData.title || bookingData.title}' confirmed!`);
                     }
                    setTimeout(() => {
                        if (resourceDetailModal) resourceDetailModal.style.display = "none";
                        selectedTimeSlotForNewBooking = null;
                    }, 2000); // Close modal after 2 seconds

                    // Refresh the map for the current view
                    if (currentMapId && mapAvailabilityDateInput) {
                        loadMapDetails(currentMapId, mapAvailabilityDateInput.value);
                    }
                    // Also, if the main booking form's date matches, and resource selector exists,
                    // it might be good to update that form's view too, or at least clear it.
                    // For now, just focusing on the map.
                } else {
                    // If response doesn't look like a success, but apiCall didn't throw/show error
                    if (!modalStatusMessageP.classList.contains('error') && !modalStatusMessageP.classList.contains('success')) {
                        showError(modalStatusMessageP, "Booking failed. Unexpected response from server.");
                    }
                }
            } catch (error) {
                // apiCall should have displayed the error in modalStatusMessageP.
                // This catch is for any other unexpected errors during the process.
                console.error('Booking from modal failed:', error.message);
                 if (!modalStatusMessageP.classList.contains('error')) {
                     showError(modalStatusMessageP, `Booking failed: ${error.message}`);
                 }
            }
        });
    }

});
console.log('new_booking_map.js script execution finished.');
