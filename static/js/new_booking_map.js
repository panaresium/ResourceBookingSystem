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
    const quickTimeOptionsRadios = document.querySelectorAll('input[name="quick_time_option"]');


    let isSyncingDate = false; // Flag to prevent event loops for date inputs

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
        if (!mapFloorSelect || !mapLocationSelect) return;
        const selectedLocation = mapLocationSelect.value;
        const availableFloors = [...new Set(allMapInfo
            .filter(map => !selectedLocation || map.location === selectedLocation)
            .map(map => map.floor)
            .filter(floor => floor) // Remove null or empty floor values
            .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
        )];

        mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>';
        availableFloors.forEach(floor => {
            const option = new Option(floor, floor);
            mapFloorSelect.add(option);
        });
        mapFloorSelect.disabled = availableFloors.length === 0;
    }

    /**
     * Loads map details (image and resource areas) based on selected map and date.
     * @param {string} mapId - The ID of the map to load.
     * @param {string} dateString - The date for which to check resource availability.
     */
    async function loadMapDetails(mapId, dateString) {
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
                        const coords = resource.map_coordinates;
                        const areaDiv = document.createElement('div');
                        areaDiv.className = 'resource-area'; // Base class
                        areaDiv.style.left = `${coords.x}px`;
                        areaDiv.style.top = `${coords.y}px`;
                        areaDiv.style.width = `${coords.width}px`;
                        areaDiv.style.height = `${coords.height}px`;
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
            loadMapDetails(null, selectedDate).finally(() => { isSyncingDate = false; });
            isSyncingDate = false; // Ensure flag is reset even if loadMapDetails is skipped
            return;
        }

        const mapToLoad = allMapInfo.find(map => map.location === selectedLocation && map.floor === selectedFloor);

        if (mapToLoad) {
            loadMapDetails(mapToLoad.id, selectedDate).finally(() => { isSyncingDate = false; });
        } else {
            loadMapDetails(null, selectedDate).finally(() => { isSyncingDate = false; });
            if (mapLoadingStatusDiv) showSuccess(mapLoadingStatusDiv, 'No map found for the selected location and floor.');
        }
        // Highlight selected resource after map loads/reloads
        highlightSelectedResourceOnMap();
    }

    /**
     * Fetches available maps and populates selection dropdowns.
     */
    async function loadAvailableMaps() {
        if (!mapLocationSelect || !mapFloorSelect || !mapLoadingStatusDiv) {
            console.error("One or more map control elements are missing from the DOM.");
            return;
        }
        showLoading(mapLoadingStatusDiv, 'Loading available maps...');
        try {
            allMapInfo = await apiCall('/api/admin/maps', {}, mapLoadingStatusDiv);

            if (!allMapInfo || allMapInfo.length === 0) {
                showError(mapLoadingStatusDiv, 'No maps are currently available.');
                mapLocationSelect.disabled = true;
                mapFloorSelect.disabled = true;
                return;
            }

            // Populate Location Select
            const locations = [...new Set(allMapInfo.map(map => map.location).filter(loc => loc))];
            mapLocationSelect.innerHTML = '<option value="">-- Select Location --</option>';
            locations.forEach(location => {
                const option = new Option(location, location);
                mapLocationSelect.add(option);
            });
            mapLocationSelect.disabled = locations.length === 0;

            // Initialize Floor Select (will be updated by location change)
            mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>';
            mapFloorSelect.disabled = true; // Disabled until a location is chosen

            // Add event listeners
            if (mapLocationSelect) {
                mapLocationSelect.addEventListener('change', () => {
                    updateFloorSelectOptions();
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
            
            // Initial state: no map loaded, message cleared or set by apiCall
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                showSuccess(mapLoadingStatusDiv, 'Please select a location and floor to see the map.');
            }


        } catch (error) {
            // apiCall should have shown the error in mapLoadingStatusDiv
            console.error('Failed to load available maps:', error);
            mapLocationSelect.disabled = true;
            mapFloorSelect.disabled = true;
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error')) {
                 showError(mapLoadingStatusDiv, 'Could not load map options.');
            }
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

            const workDayStartHour = 8;
            const workDayEndHour = 17; // Ends at 17:00, so last slot is 16:00-17:00
            const slotDurationHours = 1;

            for (let hour = workDayStartHour; hour < workDayEndHour; hour += slotDurationHours) {
                const slotStart = new Date(`${dateString}T${String(hour).padStart(2, '0')}:00:00`);
                const slotEnd = new Date(slotStart.getTime() + slotDurationHours * 60 * 60 * 1000);

                const startTimeStr = `${String(slotStart.getHours()).padStart(2, '0')}:00`;
                const endTimeStr = `${String(slotEnd.getHours()).padStart(2, '0')}:00`;
                const slotLabel = `${startTimeStr} - ${endTimeStr}`;

                let isBooked = false;
                if (bookedSlots && bookedSlots.length > 0) {
                    for (const booked of bookedSlots) {
                        // Assuming booked.start_time and booked.end_time are "HH:MM:SS"
                        const bookedStartTime = new Date(`${dateString}T${booked.start_time}`);
                        const bookedEndTime = new Date(`${dateString}T${booked.end_time}`);
                        if (bookedStartTime < slotEnd && bookedEndTime > slotStart) {
                            isBooked = true;
                            break;
                        }
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
                        const previouslySelected = modalTimeSlotsListDiv.querySelector('.time-slot-selected');
                        if (previouslySelected) {
                            previouslySelected.classList.remove('time-slot-selected');
                        }
                        this.classList.add('time-slot-selected');
                        selectedTimeSlotForNewBooking = {
                            startTimeStr: this.dataset.startTime,
                            endTimeStr: this.dataset.endTime
                        };
                        if (modalStatusMessageP) modalStatusMessageP.textContent = '';

                        // Sync to main form
                        if (mainFormStartTimeInput) mainFormStartTimeInput.value = selectedTimeSlotForNewBooking.startTimeStr;
                        if (mainFormEndTimeInput) mainFormEndTimeInput.value = selectedTimeSlotForNewBooking.endTimeStr;
                        if (mainFormManualTimeRadio) {
                            mainFormManualTimeRadio.checked = true;
                            // Trigger change event on manual radio to update UI (e.g., hide quick options)
                            mainFormManualTimeRadio.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    });
                }
                modalTimeSlotsListDiv.appendChild(slotDiv);
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
