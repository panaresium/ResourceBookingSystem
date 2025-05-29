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
        const VERTICAL_OFFSET = 5; // Define the vertical offset in pixels

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

        try {
            const apiUrl = `/api/map_details/${mapId}?date=${dateString}`;
            // Assuming apiCall and other helper functions are globally available from script.js
            const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv);

            if (mapContainer) {
                mapContainer.style.backgroundImage = `url(${data.map_details.image_url})`;
            }

            if (data.mapped_resources && data.mapped_resources.length > 0) {
                data.mapped_resources.forEach(resource => {
                    if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                        // const coords = resource.map_coordinates; // First declaration, now potentially redundant
                        // The following 'const coords' is the one introduced by the logging step.
                        // We should use this one and ensure there's no prior 'const coords' in this specific block.
                        // OR, if 'const coords' was already defined above this 'if', then this one should be removed.
                        // Given the error is *at* 168, this implies this line or the one immediately after is the problem.

                        // Corrected: Declare 'coords' once.
                        // The previous logging step likely introduced 'const coords = resource.map_coordinates;'
                        // and then the original code also had 'const coords = resource.map_coordinates;'.
                        // The logging patch correctly had 'const coords = resource.map_coordinates;'
                        // and then used it. The error implies a *second* 'const coords' or 'let coords'.
                        // The issue was:
                        // const coords = resource.map_coordinates; // Original or first one from logging
                        // const areaDiv = document.createElement('div'); // This line is fine
                        // const coords = resource.map_coordinates; // THIS WAS THE DUPLICATE from the merge error.

                        // Corrected structure:
                        const coords = resource.map_coordinates; // Define it once for this resource.
                        console.log('Processing Resource:', resource.name, 'Raw Coords:', coords);

                        // Directly using coordinate values as pixel values, applying offset to top
                        let topPosition = coords.y + VERTICAL_OFFSET;
                        let leftPosition = coords.x;
                        let widthValue = coords.width;
                        let heightValue = coords.height;

                        console.log('Applying to CSS: top=', topPosition + 'px', 
                                    'left=', leftPosition + 'px', 
                                    'width=', widthValue + 'px', 
                                    'height=', heightValue + 'px');
                        // const areaDiv = document.createElement('div'); // This was also duplicated by the faulty merge.
                        // The areaDiv should be created *after* coordinates are established.
                        const areaDiv = document.createElement('div');
                        areaDiv.className = 'resource-area'; // Base class
                        areaDiv.style.left = `${leftPosition}px`;
                        areaDiv.style.top = `${topPosition}px`;
                        areaDiv.style.width = `${widthValue}px`;
                        areaDiv.style.height = `${heightValue}px`;
                        areaDiv.textContent = resource.name;
                        areaDiv.dataset.resourceId = resource.id;
                        areaDiv.title = resource.name;

                        // Determine availability and set class
                        let availabilityClass = 'resource-area-unknown';
                        const bookings = resource.bookings_on_date;

                        if (bookings) {
                            if (bookings.length === 0) {
                                availabilityClass = 'resource-area-available';
                            } else {
                                // Simplified logic: if any bookings, it's partially.
                                // More complex logic (e.g., checking full day) can be added if needed.
                                // For now, any booking means "partially" unless a more robust "fully booked" check is implemented.
                                let totalBookedMinutes = 0;
                                const workDayStartHour = 8; 
                                const workDayEndHour = 17; 

                                bookings.forEach(booking => {
                                    const [sH, sM] = booking.start_time.split(':').map(Number);
                                    const [eH, eM] = booking.end_time.split(':').map(Number);
                                    
                                    const bookingStart = new Date(2000, 0, 1, sH, sM);
                                    const bookingEnd = new Date(2000, 0, 1, eH, eM);
                                    
                                    const slotStartInWorkHours = new Date(2000, 0, 1, Math.max(workDayStartHour, sH), sM);
                                    const slotEndInWorkHours = new Date(2000, 0, 1, Math.min(workDayEndHour, eH), eM);

                                    if (slotEndInWorkHours > slotStartInWorkHours) {
                                        totalBookedMinutes += (slotEndInWorkHours - slotStartInWorkHours) / (1000 * 60);
                                    }
                                });
                                const workDayDurationMinutes = (workDayEndHour - workDayStartHour) * 60;
                                if (totalBookedMinutes >= workDayDurationMinutes * 0.9) { // 90% considered fully booked
                                    availabilityClass = 'resource-area-fully-booked';
                                } else if (totalBookedMinutes > 0) {
                                    availabilityClass = 'resource-area-partially-booked';
                                } else {
                                    availabilityClass = 'resource-area-available';
                                }
                            }
                        }
                        areaDiv.classList.add(availabilityClass);

                        // Make clickable if available or partially booked
                        if (availabilityClass === 'resource-area-available' || availabilityClass === 'resource-area-partially-booked') {
                            areaDiv.classList.add('map-area-clickable');
                            areaDiv.addEventListener('click', function() {
                                // Sync resource to main form when clicked on map
                                if (resourceSelectBooking) {
                                    resourceSelectBooking.value = resource.id;
                                    // Dispatch change event to trigger any listeners on the main form's resource select
                                    resourceSelectBooking.dispatchEvent(new Event('change'));
                                }
                                openResourceDetailModal(resource, dateString);
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

    async function openResourceDetailModal(resource, dateString) {
        if (!resourceDetailModal || !modalResourceNameSpan || !modalDateSpan || !modalResourceImageImg || !modalTimeSlotsListDiv || !modalBookingTitleInput || !modalConfirmBookingBtn || !modalStatusMessageP) {
            console.error('One or more modal elements are missing for new booking.');
            return;
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
                button.classList.add('time-slot-item', 'button'); // Use 'button' class for styling consistency
                button.dataset.slotId = slot.id;

                const isConflicting = checkConflict(slot.startTime, slot.endTime, bookedSlots);

                if (isConflicting) {
                    button.classList.add('time-slot-booked'); // Or a new class like 'time-slot-conflicting'
                    button.disabled = true;
                    button.title = `${slot.name} is unavailable due to existing bookings.`;
                } else {
                    button.classList.add('time-slot-available');
                    button.addEventListener('click', function() {
                        // Remove 'selected' from previously selected button
                        const allButtons = modalTimeSlotsListDiv.querySelectorAll('button.time-slot-item');
                        allButtons.forEach(btn => btn.classList.remove('time-slot-selected', 'selected')); // Ensure 'selected' is also removed

                        // Add 'selected' to current button
                        this.classList.add('time-slot-selected', 'selected');
                        selectedTimeSlotForNewBooking = {
                            startTimeStr: slot.startTime,
                            endTimeStr: slot.endTime
                        };
                        if (modalStatusMessageP) modalStatusMessageP.textContent = '';

                        // Sync to main form's start and end time inputs
                        if (mainFormStartTimeInput) mainFormStartTimeInput.value = slot.startTime;
                        if (mainFormEndTimeInput) mainFormEndTimeInput.value = slot.endTime;
                        
                        // No need to interact with mainFormManualTimeRadio as it's removed.
                        // The main form's quick options will naturally be out of sync if user used them,
                        // but the actual time inputs (start-time, end-time) will be correct.
                    });
                }
                modalTimeSlotsListDiv.appendChild(button);
            });

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
