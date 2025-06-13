document.addEventListener('DOMContentLoaded', function () {
    // console.log('new_booking_map.js loaded and DOM fully parsed.'); // Keep general load confirmation

    function getTodayDateString() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function getEffectiveClientNow(adjustmentHours) {
        const now = new Date();
        // Subtracting hours: if adjustmentHours is positive (allow past booking), effective time is earlier.
        // If adjustmentHours is negative (restrict future booking), effective time is later.
        now.setHours(now.getHours() - adjustmentHours);
        return now;
    }

    // const mapAvailabilityDateInput = document.getElementById('new-booking-map-availability-date'); // Old input field, now removed from HTML
    const calendarContainer = document.getElementById('inline-calendar-container'); // New container for inline flatpickr
    const userId = calendarContainer ? calendarContainer.dataset.userId : null;
    console.log('[Debug] Flatpickr User ID:', userId);

    let pastBookingAdjustmentHours = 0; // Default
    if (calendarContainer && calendarContainer.dataset.pastBookingAdjustmentHours) {
        pastBookingAdjustmentHours = parseFloat(calendarContainer.dataset.pastBookingAdjustmentHours);
        if (isNaN(pastBookingAdjustmentHours)) {
            pastBookingAdjustmentHours = 0;
            console.warn('[Debug] Invalid past_booking_adjustment_hours, defaulting to 0.');
        }
    }
    console.log('[Debug] Using pastBookingAdjustmentHours:', pastBookingAdjustmentHours);
    const mapLocationButtonsContainer = document.getElementById('new-booking-map-location-buttons-container'); // Will be used for combined buttons
    const mapContainer = document.getElementById('new-booking-map-container');
    const mapLoadingStatusDiv = document.getElementById('new-booking-map-loading-status');
    const resourceSelectBooking = document.getElementById('resource-select-booking');

    // New UI elements for instruction and visibility control
    const dateSelectionInstructionDiv = document.getElementById('date-selection-instruction');
    const locationSelectionInstructionDiv = document.getElementById('location-selection-instruction');
    const locationFloorWrapperDiv = document.getElementById('location-floor-wrapper');
    const mapViewWrapperDiv = document.getElementById('map-view-wrapper');

    let allMapInfo = []; // Stores full map configuration {id, name, location, floor, ...}
    // let allUniqueLocations = []; // Removed
    // let selectedLocationName = null; // Removed
    let selectedMapId = null; // Stores the ID of the currently selected map
    let currentMapId = null; // Still used by loadMapDetails, perhaps can be merged with selectedMapId
    let currentSelectedDateStr = getTodayDateString(); // Initialize with today's date

    let systemBookingSettings = { allowMultipleResourcesSameTime: false }; // Global variable for booking settings

    const mainBookingFormDateInput = document.getElementById('booking-date');
    const mainFormStartTimeInput = document.getElementById('start-time');
    const mainFormEndTimeInput = document.getElementById('end-time');

    let isSyncingDate = false;

    function updateMapLoadingStatus(message, isError = false) {
        if (!mapLoadingStatusDiv) return;
        if (isError) {
            showError(mapLoadingStatusDiv, message);
        } else {
            showSuccess(mapLoadingStatusDiv, message);
        }
    }

    function disableMapSelectors() {
        // if (mapLocationSelect) { // Removed
        //     mapLocationSelect.innerHTML = '<option value="">-- Not Available --</option>';
        //     mapLocationSelect.disabled = true;
        // }
        if (mapLocationButtonsContainer) {
            mapLocationButtonsContainer.innerHTML = '<p>No maps available or date not selected.</p>'; // Updated message
        }
        // if (mapFloorSelect) { // Removed
        //     mapFloorSelect.innerHTML = '<option value="">-- Not Available --</option>';
        //     mapFloorSelect.disabled = true;
        // }
    }

    function highlightSelectedResourceOnMap() {
        if (!resourceSelectBooking) {
            // console.warn('#resource-select-booking dropdown not found for highlighting.'); // Kept for internal debugging if needed
            return;
        }
        const selectedResourceId = resourceSelectBooking.value;
        const resourceAreas = document.querySelectorAll('#new-booking-map-container .resource-area');
        resourceAreas.forEach(area => {
            area.classList.remove('resource-area-form-selected');
            if (selectedResourceId && area.dataset.resourceId === selectedResourceId) {
                area.classList.add('resource-area-form-selected');
            }
        });
    }

    // const today = getTodayDateString(); // currentSelectedDateStr is initialized with this

    // serverTodayDateStr removed

    function fetchDataAndInitializeFlatpickr() { // Renamed and async removed
        // Directly proceed with existing Flatpickr initialization logic that depends on unavailableDatesList
        const calendarContainer = document.getElementById('inline-calendar-container');
        const userId = calendarContainer ? calendarContainer.dataset.userId : null;

        if (userId && calendarContainer) {
            apiCall(`/api/resources/unavailable_dates?user_id=${userId}`)
                .then(fetchedDates => {
                    console.log('[Debug] Fetched unavailable dates for Flatpickr:', fetchedDates);
                    initializeFlatpickr(fetchedDates);
                })
                .catch(error => {
                    console.error('Error fetching unavailable dates for Flatpickr:', error);
                    initializeFlatpickr([]);
                });
        } else {
            if (!calendarContainer) {
                 console.info('Calendar container not found, Flatpickr setup skipped.');
            } else if (!userId) {
                console.info('User ID not found. Initializing Flatpickr without user-specific unavailable dates.');
            }
            if (calendarContainer) {
                initializeFlatpickr([]); // Initialize with empty list if no user, calendar still needs to show
            }
        }
    }

    function initializeFlatpickr(unavailableDatesList = []) {
        if (calendarContainer) {
            // currentSelectedDateStr is an outer scope variable.
            // Initialize/update it here before Flatpickr uses it for defaultDate.
            currentSelectedDateStr = getTodayDateString();

            flatpickr(calendarContainer, {
                inline: true,
                static: true, // Keep existing options
                dateFormat: "Y-m-d",
                disable: [
                    function(date) {
                        const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
                        const today = new Date();
                        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

                        // Check for "today" and time
                        if (dateStr === todayStr) {
                            const effectiveNow = getEffectiveClientNow(pastBookingAdjustmentHours);
                            const actualNow = new Date(); // For logging actual time
                            const latestSlotEndTimeHour = 17;
                            const latestSlotEndTimeMinute = 0;
                            let shouldDisableToday = false;

                            if (effectiveNow.getHours() > latestSlotEndTimeHour || (effectiveNow.getHours() === latestSlotEndTimeHour && effectiveNow.getMinutes() > latestSlotEndTimeMinute)) {
                                shouldDisableToday = true;
                            }

                            console.log('[Debug] Flatpickr disable check for TODAY (' + dateStr + '): Actual time: ' + actualNow.getHours() + ':' + String(actualNow.getMinutes()).padStart(2, '0') + ', Effective time: ' + effectiveNow.getHours() + ':' + String(effectiveNow.getMinutes()).padStart(2, '0') + ' (Adjustment: ' + pastBookingAdjustmentHours + 'h). Disabling? ' + shouldDisableToday);
                            if (shouldDisableToday) {
                                return true;
                            }
                        }

                        // unavailableDatesList is passed to initializeFlatpickr
                        const isDisabledByUnavailableList = unavailableDatesList.includes(dateStr);

                        // Optional: keep a simple log for debugging
                        // Added a condition to ensure some logging for relevant test dates if list is empty
                        // Modified to avoid logging twice for today if it wasn't disabled by time
                        if (! (dateStr === todayStr) && (unavailableDatesList.length > 0 || dateStr.startsWith("2025-06"))) {
                           console.log(`[Debug] Flatpickr disable check for ${dateStr}: inList = ${isDisabledByUnavailableList} (list length: ${unavailableDatesList.length})`);
                        }

                        return isDisabledByUnavailableList;
                    }
                ],
                defaultDate: currentSelectedDateStr, // Set defaultDate to client's current date
                onChange: function(selectedDates, dateStr, instance) {
                    currentSelectedDateStr = dateStr; // Update on change

                    if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'none';
                    if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'flex'; // Assuming flex display
                    if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'block';
                    if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'none'; // Hide map view when date changes

                    updateLocationFloorButtons().then(() => {
                        // loadMapDetails is called within updateLocationFloorButtons if a map is selected,
                        // or map is cleared if no map is selected after buttons update.
                        // For now, ensure map is cleared if no map is selected yet.
                        if (!selectedMapId) {
                            loadMapDetails(null, currentSelectedDateStr); // Clears map
                        }
                        // Scroll to location/floor selection area
                        if (locationFloorWrapperDiv) {
                            locationFloorWrapperDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                    });
                }
            });
            // Also update the main booking form's date input if it exists, to reflect this initial date
            if (mainBookingFormDateInput && mainBookingFormDateInput.value !== currentSelectedDateStr) {
                mainBookingFormDateInput.value = currentSelectedDateStr;
            }
        } else {
            console.error('Inline calendar container not found for Flatpickr.');
        }
    }

    fetchDataAndInitializeFlatpickr(); // Call the refactored function

    // function updateFloorSelectOptions() { // Removed }

    async function updateLocationFloorButtons() {
        // Now uses currentSelectedDateStr instead of mapAvailabilityDateInput.value
        if (!calendarContainer || !mapLocationButtonsContainer) {
            console.error("Calendar container or location buttons container not found for updateLocationFloorButtons");
            return;
        }
        // const selectedDate = mapAvailabilityDateInput.value; // Old way
        const selectedDate = currentSelectedDateStr; // Use global date string
        if (!selectedDate) {
            mapLocationButtonsContainer.innerHTML = "<p>Please select a date to see map availability.</p>";
            return;
        }

        showLoading(mapLoadingStatusDiv, 'Fetching map availability...');
        try {
            // mapsAvailabilityData structure: [{ map_id, map_name, location, floor, is_available_for_user }, ...]
            const mapsAvailabilityData = await apiCall(`/api/maps-availability?date=${selectedDate}`, {}, mapLoadingStatusDiv);
            mapLocationButtonsContainer.innerHTML = ''; // Clear previous buttons

            if (!allMapInfo || allMapInfo.length === 0) { // Use allMapInfo to render all configured maps
                mapLocationButtonsContainer.innerHTML = "<p>No maps configured in the system.</p>";
                hideMessage(mapLoadingStatusDiv);
                return;
            }

            allMapInfo.forEach(mapInfo => { // Iterate through all configured maps
                const button = document.createElement('button');
                // Assuming mapInfo.name is descriptive like "EAPRO FL1" or similar.
                // If not, use: button.textContent = `${mapInfo.location} - ${mapInfo.floor}`;
                button.textContent = mapInfo.name;
                button.classList.add('location-button', 'button'); // Re-use 'location-button' or new 'map-button'
                button.dataset.mapId = mapInfo.id;

                // Remove all potential old/new classes first
                button.classList.remove('location-button-available', 'location-button-unavailable', 'location-button-partially-available');

                const availabilityInfo = mapsAvailabilityData.find(availMap => availMap.map_id === mapInfo.id);

                if (availabilityInfo && availabilityInfo.availability_status) {
                    switch (availabilityInfo.availability_status) {
                        case 'high':
                            button.classList.add('location-button-available');
                            button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - High Availability`;
                            break;
                        case 'medium':
                            button.classList.add('location-button-partially-available');
                            button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Medium Availability`;
                            break;
                        case 'low':
                            button.classList.add('location-button-unavailable');
                            button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Low Availability`;
                            break;
                        default:
                            button.classList.add('location-button-unavailable'); // Default to unavailable visually
                            button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Availability Status Unknown`;
                            break;
                    }
                } else {
                    // If map not in availability data or availability_status is missing.
                    button.classList.add('location-button-unavailable'); // Default to unavailable visually
                    button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Availability Data Missing`;
                }

                if (mapInfo.id === selectedMapId) {
                    button.classList.add('selected-map-button'); // Or reuse 'selected-location-button'
                }

                // Disable button if it's marked as unavailable
                // This check is after all class assignments and title settings.
                if (button.classList.contains('location-button-unavailable')) {
                    button.disabled = true;
                }

                button.addEventListener('click', function() {
                    selectedMapId = mapInfo.id;
                    currentMapId = mapInfo.id; // Sync currentMapId as well

                    document.querySelectorAll('#new-booking-map-location-buttons-container .location-button').forEach(btn => {
                        btn.classList.remove('selected-map-button'); // Or 'selected-location-button'
                    });
                    this.classList.add('selected-map-button'); // Or 'selected-location-button'

                    loadMapDetails(selectedMapId, currentSelectedDateStr); // Use global date string

                    if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
                    if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'block';

                    if (mapViewWrapperDiv) { // Scroll to the map view wrapper
                        mapViewWrapperDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                });
                mapLocationButtonsContainer.appendChild(button);
            });

            if (!mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                 hideMessage(mapLoadingStatusDiv);
            }

        } catch (error) {
            console.error('Error fetching map availability:', error);
            mapLocationButtonsContainer.innerHTML = `<p style="color: red;">Error loading map availability: ${error.message}</p>`;
            if (!mapLoadingStatusDiv.classList.contains('error')) {
                 showError(mapLoadingStatusDiv, `Error loading map availability: ${error.message}`);
            }
        }
    }

    async function getEffectiveMapResourceOpacity() {
        const defaultOpacity = 0.7;
        let uiOpacity;

        try {
            const response = await fetch('/api/admin/system-settings/map-opacity'); // Use the correct API endpoint path
            if (response.ok) {
                const data = await response.json();
                if (data.opacity !== undefined && typeof data.opacity === 'number' && data.opacity >= 0.0 && data.opacity <= 1.0) {
                    uiOpacity = data.opacity;
                    // console.log('Using UI configured opacity:', uiOpacity); // Optional: for debugging
                    return uiOpacity;
                } else {
                    // console.warn('UI configured opacity is invalid or not found, falling back. Data:', data); // Optional: for debugging
                }
            } else {
                // console.warn('Failed to fetch UI configured opacity, status:', response.status); // Optional: for debugging
                // If response is not ok (e.g. 403 for non-admins), this path is taken.
                // We want to treat this as a non-critical failure and proceed to fallbacks.
                console.warn(`API call to fetch map opacity failed with status ${response.status}. Using fallback opacity values.`);
            }
        } catch (error) {
            // console.error('Error fetching UI configured opacity:', error); // Original console.error
            console.warn(`Error fetching UI configured opacity: ${error.message}. Using fallback opacity values.`);
        }

        // Fallback to environment variable if UI opacity is not valid or fetch failed
        if (typeof window.MAP_RESOURCE_OPACITY === 'number' && window.MAP_RESOURCE_OPACITY >= 0.0 && window.MAP_RESOURCE_OPACITY <= 1.0) {
            // console.log('Falling back to environment variable opacity:', window.MAP_RESOURCE_OPACITY); // Optional: for debugging
            return window.MAP_RESOURCE_OPACITY;
        } else if (typeof window.MAP_RESOURCE_OPACITY !== 'undefined') {
            // console.warn('Environment MAP_RESOURCE_OPACITY is invalid. Using default. Value:', window.MAP_RESOURCE_OPACITY); // Optional: for debugging
        }

        // console.log('Falling back to default opacity:', defaultOpacity); // Optional: for debugging
        return defaultOpacity;
    }

    // Make loadMapDetails async
    async function loadMapDetails(mapId, dateString) {
        // Get opacity using the new async function
        const mapResourceOpacity = await getEffectiveMapResourceOpacity();
        // console.log('Effective mapResourceOpacity to be used:', mapResourceOpacity); // Optional: for debugging

        if (!mapId) {
            if (mapContainer) {
                 mapContainer.innerHTML = '';
                 mapContainer.style.backgroundImage = 'none';
            }
            if (mapLoadingStatusDiv) showSuccess(mapLoadingStatusDiv, 'Please select a location and floor to view a map.');
            currentMapId = null;
            return;
        }
        if (!dateString) {
            if (mapLoadingStatusDiv) showError(mapLoadingStatusDiv, 'Please select a date.');
            return;
        }

        if (mapLoadingStatusDiv) showLoading(mapLoadingStatusDiv, 'Loading map details...');
        if (mapContainer) mapContainer.innerHTML = '';
        currentMapId = mapId;

        let userBookingsForDate = [];
        const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');
        if (loggedInUsername) {
            try {
                userBookingsForDate = await apiCall(`/api/bookings/my_bookings_for_date?date=${dateString}`, {}, null);
            } catch (err) {
                console.warn(`Could not fetch user's bookings for date ${dateString}:`, err.message); // Keep this warning
            }
        }
        // REMOVED: console.log("DEBUG MAP: User's other bookings for the day (userBookingsForDate) at start of loadMapDetails:", JSON.stringify(userBookingsForDate));

        function timeToMinutes(timeStr) {
            const parts = timeStr.split(':');
            return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
        }

        try {
            const apiUrl = `/api/map_details/${mapId}?date=${dateString}`;
            const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv);
            const mapDetails = data.map_details;
            // These offsets are specific to the "Resource Availability" page (new_booking_map.js)
            // and are intentionally applied here to adjust resource positions on this particular display.
            const offsetX = parseInt(mapDetails.offset_x) || 0;
            const offsetY = parseInt(mapDetails.offset_y) || 0;

            if (mapContainer) {
                mapContainer.style.backgroundImage = `url(${mapDetails.image_url})`;
            }

            // Define colorMap before the loop
            const colorMap = {
                'map-area-green': '212, 237, 218',        // #d4edda
                'map-area-yellow': '255, 243, 205',       // #fff3cd
                'map-area-light-blue': '209, 236, 241',   // #d1ecf1
                'map-area-red': '248, 215, 218',          // #f8d7da
                'map-area-dark-orange': '255, 232, 204'   // #ffe8cc
                // Add other map-area-* classes if they are used for backgrounds and need translucency
            };

            if (data.mapped_resources && data.mapped_resources.length > 0) {
                data.mapped_resources.forEach(resource => {
                    if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
                        // REMOVED: console.log("DEBUG MAP: --- Resource:", resource.name, "(ID:", resource.id, ") ---");
                        // REMOVED: console.log("DEBUG MAP: Maintenance:", resource.is_under_maintenance, "Maintenance Until:", resource.maintenance_until);
                        // REMOVED: console.log("DEBUG MAP: General Bookings on this resource (resource.bookings_on_date):", JSON.stringify(resource.bookings_on_date));

                        const coords = resource.map_coordinates;
                        const areaDiv = document.createElement('div');
                        areaDiv.className = 'resource-area';
                        areaDiv.style.left = `${coords.x + offsetX}px`;
                        areaDiv.style.top = `${coords.y + offsetY}px`;
                        areaDiv.style.width = `${coords.width}px`;
                        areaDiv.style.height = `${coords.height}px`;
                        areaDiv.textContent = resource.name;
                        areaDiv.dataset.resourceId = resource.id;

                        console.log("[DEBUG MAP] Processing resource:", resource.id, resource.name, "current_user_can_book:", resource.current_user_can_book);

                        console.log("[DEBUG MAP] About to check current_user_can_book for resource:", resource.id);
                        if (resource.current_user_can_book === false) {
                            console.log("[DEBUG MAP] Entered current_user_can_book === false for resource:", resource.id);
                            areaDiv.className = 'resource-area resource-area-permission-denied';
                            areaDiv.title = resource.name + ' (Permission Denied)';
                            // Ensure 'resource-area-permission-denied' is in colorMap or CSS handles its appearance
                            const permissionDeniedRgbString = colorMap['resource-area-permission-denied'] || '173, 216, 230'; // Fallback to light blue
                            areaDiv.style.setProperty('background-color', `rgba(${permissionDeniedRgbString}, ${mapResourceOpacity})`, 'important');
                            // No event listener, not clickable.
                        } else {
                            console.log("[DEBUG MAP] Entered ELSE (current_user_can_book is true or undefined) for resource:", resource.id);
                            // User has permission, proceed with detailed availability logic
                            const primarySlots = [
                                { name: "first_half", start: 8 * 60, end: 12 * 60, isGenerallyBooked: false, isBookedByCurrentUser: false, isConflictingWithUserOtherBookings: false, isBookableByCurrentUser: false },
                                { name: "second_half", start: 13 * 60, end: 17 * 60, isGenerallyBooked: false, isBookedByCurrentUser: false, isConflictingWithUserOtherBookings: false, isBookableByCurrentUser: false }
                            ];

                            primarySlots.forEach(slot => {
                                slot.isGenerallyBooked = false;
                                slot.isBookedByCurrentUser = false;
                                slot.isConflictingWithUserOtherBookings = false;
                                slot.isBookableByCurrentUser = false;

                                if (resource.bookings_on_date && resource.bookings_on_date.length > 0) {
                                    for (const booking of resource.bookings_on_date) {
                                        const bookingStartMinutes = timeToMinutes(booking.start_time);
                                        const bookingEndMinutes = timeToMinutes(booking.end_time);
                                        if (Math.max(slot.start, bookingStartMinutes) < Math.min(slot.end, bookingEndMinutes)) {
                                            slot.isGenerallyBooked = true;
                                            if (loggedInUsername && booking.user_name === loggedInUsername) {
                                                slot.isBookedByCurrentUser = true;
                                            }
                                        }
                                    }
                                }
                                if (!slot.isGenerallyBooked && loggedInUsername && userBookingsForDate && userBookingsForDate.length > 0) {
                                    for (const userBooking of userBookingsForDate) {
                                        if (String(userBooking.resource_id) !== String(resource.id)) {
                                            const userBookingStartMinutes = timeToMinutes(userBooking.start_time);
                                            const userBookingEndMinutes = timeToMinutes(userBooking.end_time);
                                            if (Math.max(slot.start, userBookingStartMinutes) < Math.min(slot.end, userBookingEndMinutes)) {
                                                slot.isConflictingWithUserOtherBookings = true;
                                                break;
                                            }
                                        }
                                    }
                                }
                            });

                            primarySlots.forEach(slot => {
                                // Original conflict status based on user's other bookings
                                const originalUserConflictStatus = slot.isConflictingWithUserOtherBookings;

                                let consideredConflictForBookableStatus = slot.isConflictingWithUserOtherBookings;
                                if (systemBookingSettings.allowMultipleResourcesSameTime) {
                                    consideredConflictForBookableStatus = false; // Ignore user's own schedule conflict
                                    // console.log(`[Debug MAP] Resource ${resource.id}, Slot ${slot.name}: AllowMultiple is TRUE. UserConflictInitially: ${originalUserConflictStatus}, ConsideredConflict: ${consideredConflictForBookableStatus}`);
                                } else {
                                    // console.log(`[Debug MAP] Resource ${resource.id}, Slot ${slot.name}: AllowMultiple is FALSE. UserConflictInitially: ${originalUserConflictStatus}, ConsideredConflict: ${consideredConflictForBookableStatus}`);
                                }
                                slot.isBookableByCurrentUser = (!slot.isGenerallyBooked && !consideredConflictForBookableStatus);
                            });

                            let finalClass = '';
                            let finalTitle = resource.name;
                            let isMapAreaClickable = false;

                            const numPrimarySlots = primarySlots.length;
                            const numBookableByCurrentUser = primarySlots.filter(s => s.isBookableByCurrentUser).length;
                            const numBookedByCurrentUser = primarySlots.filter(s => s.isBookedByCurrentUser).length;
                            const numGenerallyBooked = primarySlots.filter(s => s.isGenerallyBooked).length;

                            if (numBookedByCurrentUser === numPrimarySlots) {
                                finalClass = 'map-area-red';
                                finalTitle += ' (Booked by You - Full Day)';
                            } else if (numBookedByCurrentUser > 0) {
                                if (numBookableByCurrentUser > 0) {
                                    finalClass = 'map-area-yellow';
                                    finalTitle += ' (Partially Booked by You - More Available Here)';
                                } else {
                                    finalClass = 'map-area-dark-orange';
                                    finalTitle += ' (Partially Booked by You - Fully Utilized by You)';
                                }
                            } else {
                                if (resource.is_under_maintenance && numGenerallyBooked === 0) {
                                    finalClass = 'map-area-light-blue';
                                    finalTitle += ' (Under Maintenance)';
                                } else if (numGenerallyBooked === numPrimarySlots) {
                                    finalClass = 'map-area-light-blue';
                                    finalTitle += ' (Fully Booked by Others)';
                                } else if (numGenerallyBooked === 0) {
                                    if (numBookableByCurrentUser === numPrimarySlots) {
                                        finalClass = 'map-area-green';
                                        finalTitle += ' (Available)';
                                    } else if (numBookableByCurrentUser > 0) {
                                        finalClass = 'map-area-yellow';
                                        finalTitle += ' (Partially Available to You - Schedule Conflicts)';
                                    } else {
                                        finalClass = 'map-area-light-blue';
                                        finalTitle += ' (Unavailable - Your Schedule Conflicts)';
                                    }
                                } else {
                                    if (numBookableByCurrentUser > 0) {
                                        finalClass = 'map-area-yellow';
                                        finalTitle += ' (Partially Available)';
                                    } else {
                                        finalClass = 'map-area-light-blue';
                                        finalTitle += ' (Unavailable - Your Schedule Conflicts)';
                                    }
                                }
                            }

                            if (finalClass === 'map-area-unknown' || finalClass === '') {
                                 finalClass = 'map-area-light-blue';
                                 finalTitle += ' (Status Unknown)';
                            }

                            if (finalClass === 'map-area-green' || finalClass === 'map-area-yellow') {
                                isMapAreaClickable = true;
                            }

                            areaDiv.className = 'resource-area'; // Reset class
                            areaDiv.classList.add(finalClass);
                            const rgbString = colorMap[finalClass] || colorMap['map-area-light-blue'];
                            if (rgbString) {
                                areaDiv.style.setProperty('background-color', `rgba(${rgbString}, ${mapResourceOpacity})`, 'important');
                            }
                            areaDiv.title = finalTitle;

                            console.log("[DEBUG MAP] In ELSE block, for resource:", resource.id, "finalClass:", finalClass, "isMapAreaClickable:", isMapAreaClickable);
                            if (isMapAreaClickable) { // This check is now correctly placed after all logic for permitted users
                                areaDiv.classList.add('map-area-clickable');
                                areaDiv.addEventListener('click', function() {
                                    console.log("[DEBUG MAP] Click listener EXECUTED for resource:", resource.id, "Name:", resource.name);
                                    if (resourceSelectBooking) {
                                        resourceSelectBooking.value = resource.id;
                                        resourceSelectBooking.dispatchEvent(new Event('change'));
                                    }
                                    openResourceDetailModal(resource, dateString, userBookingsForDate || []);
                                });
                            } else {
                                areaDiv.classList.remove('map-area-clickable');
                            }
                        }

                        if (resourceSelectBooking && resourceSelectBooking.value === resource.id.toString()) {
                            areaDiv.classList.add('resource-area-form-selected');
                        }
                        if (mapContainer) mapContainer.appendChild(areaDiv);
                    }
                });
                if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                     hideMessage(mapLoadingStatusDiv);
                }
            } else {
                if (mapLoadingStatusDiv) showSuccess(mapLoadingStatusDiv, 'No resources are mapped to this floor plan.');
            }
        } catch (error) {
            console.error('Error fetching or rendering map details:', error); // Keep this error
            if (mapContainer) mapContainer.style.backgroundImage = 'none';
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error')) {
                showError(mapLoadingStatusDiv, `Error loading map: ${error.message}`);
            }
        }
        highlightSelectedResourceOnMap();
    }

    function handleFilterChange(source = 'map') { // 'source' might be less relevant now
        if (isSyncingDate) return; // Still useful if date syncing from main form
        isSyncingDate = true;

        // let newDate = mapAvailabilityDateInput ? mapAvailabilityDateInput.value : getTodayDateString(); // Old way
        let newDate = currentSelectedDateStr; // Use global

        if (source === 'form' && mainBookingFormDateInput) { // If change initiated from main booking form's date
            newDate = mainBookingFormDateInput.value;
            // if (mapAvailabilityDateInput && mapAvailabilityDateInput.value !== newDate) { // Old way
            if (currentSelectedDateStr !== newDate) {
                currentSelectedDateStr = newDate; // Update global
                // Update flatpickr instance if possible
                const flatpickrInstance = calendarContainer ? calendarContainer._flatpickr : null;
                if (flatpickrInstance) {
                    flatpickrInstance.setDate(newDate, false); // Update flatpickr without triggering its onChange
                }
            }
        } else { // If flatpickr initiated or general call, currentSelectedDateStr is already set by flatpickr's onChange
             newDate = currentSelectedDateStr; // Ensure we use the global
             if (mainBookingFormDateInput && mainBookingFormDateInput.value !== newDate) {
                 mainBookingFormDateInput.value = newDate;
             }
        }

        // Primary action on date change is to update buttons and then reload map if one is active
        // Flatpickr's onChange now calls updateLocationFloorButtons and then loadMapDetails directly.
        // So, handleFilterChange, if called from mainBookingFormDateInput, needs to ensure flatpickr UI is updated
        // and then trigger the same sequence.
        updateLocationFloorButtons().then(() => {
            if (selectedMapId) {
                loadMapDetails(selectedMapId, newDate);
            } else {
                loadMapDetails(null, newDate); // Ensure map is cleared if no map is selected
            }
        }).finally(() => {
            isSyncingDate = false;
        });
    }

    async function initializeMapSelectionUI() { // Renamed from loadAvailableMaps
        // Fetch booking config status at the beginning
        await fetchBookingConfigStatus(); // Ensure this is awaited if subsequent logic depends on it immediately

        if (!mapLocationButtonsContainer || !mapLoadingStatusDiv) { // Removed mapFloorSelect check
            console.error("Map buttons container or loading status div are missing from the DOM.");
            updateMapLoadingStatus("Map interface error. Please contact support.", true);
            disableMapSelectors();
            return;
        }
        updateMapLoadingStatus("Loading map configurations...", false);
        try {
            // Fetch all basic map configurations first to have a list of all maps
            const response = await fetch('/api/maps');
            const responseText = await response.text();
            if (!response.ok) {
                let userErrorMessage = `Error fetching map list: ${response.statusText || 'Server error'} (Status: ${response.status})`;
                if (response.status === 403) userErrorMessage += ". Please check permissions or login again.";
                updateMapLoadingStatus(userErrorMessage, true);
                disableMapSelectors();
                return;
            }
            let maps = [];
            try {
                maps = JSON.parse(responseText);
            } catch (jsonError) {
                updateMapLoadingStatus('Error processing map data. Invalid JSON.', true);
                disableMapSelectors();
                return;
            }
            if (!Array.isArray(maps)) {
                updateMapLoadingStatus('Unexpected map data format.', true);
                disableMapSelectors();
                return;
            }
            allMapInfo = maps; // Store {id, name, location, floor, ...} for all maps
            if (!allMapInfo || allMapInfo.length === 0) {
                updateMapLoadingStatus('No maps configured in the system.', true); // Make it an error
                disableMapSelectors();
                return;
            }

            // Now call updateLocationFloorButtons which fetches availability and renders
            await updateLocationFloorButtons();

            // No floor select to initialize or add event listeners to
            // Event listener for mapAvailabilityDateInput (flatpickr) is set up when flatpickr is initialized.
            // Main booking form date input listener:
            if (mainBookingFormDateInput) mainBookingFormDateInput.addEventListener('change', () => handleFilterChange('form'));
            if (resourceSelectBooking) resourceSelectBooking.addEventListener('change', highlightSelectedResourceOnMap);
            
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                if (allMapInfo.length > 0) {
                    updateMapLoadingStatus('Please select a map to view details.', false);
                } else {
                    // This case is already handled above, but as a fallback:
                    updateMapLoadingStatus('No maps found in configurations.', false);
                }
            }
            // highlightSelectedResourceOnMap(); // Removed duplicate call, one at the end of the function is sufficient

            
            highlightSelectedResourceOnMap();

            // If a map was previously selected (e.g. selectedMapId is not null from a previous state or default)
            // ensure its details are loaded for the current date.
            // This might be more relevant if we introduce persisting selectedMapId (e.g. in URL params or localStorage)
            // Initial state setup:
            if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'block';
            if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
            if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'none';
            if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'none';

            if (selectedMapId) {
                 loadMapDetails(selectedMapId, currentSelectedDateStr); // Use global
                 // If a map is pre-selected, potentially show map view and hide location instruction
                 if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
                 if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'block';
                 if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'none'; // Hide date instruction too
                 if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'flex'; // Show location wrapper
            } else {
                // Ensure map is cleared if no specific map is selected on load
                loadMapDetails(null, currentSelectedDateStr); // Use global
            }

        } catch (error) {
            updateMapLoadingStatus('Could not load map configurations. Network or server error.', true);
            disableMapSelectors();
        }
    }

    if (mapContainer) {
        initializeMapSelectionUI(); // Call the renamed function
        document.addEventListener('refreshNewBookingMap', function(event) {
            if (selectedMapId && currentSelectedDateStr) { // Use selectedMapId and global date string
                loadMapDetails(selectedMapId, currentSelectedDateStr);
            } else {
                console.warn('Cannot refresh new_booking_map: selectedMapId or currentSelectedDateStr is not set.');
            }
        });
    } else {
        // console.log("New booking map container not found on this page. Map script not initialized.");
    }

    async function fetchBookingConfigStatus() {
        try {
            // console.log('Fetching booking config status...'); // Optional: for debugging
            const data = await apiCall('/api/settings/booking_config_status', {}, null); // No specific error display element for this background fetch
            if (data && typeof data.allow_multiple_resources_same_time === 'boolean') {
                systemBookingSettings.allowMultipleResourcesSameTime = data.allow_multiple_resources_same_time;
                // console.log('Successfully fetched booking config status:', systemBookingSettings); // Optional: for debugging
            } else {
                console.warn('Booking config status API response was not in the expected format. Using default.', data);
                // systemBookingSettings.allowMultipleResourcesSameTime remains false (default)
            }
        } catch (error) {
            console.error('Error fetching booking config status:', error.message, 'Using default settings.');
            // systemBookingSettings.allowMultipleResourcesSameTime remains false (default)
        }
    }

    const resourceDetailModal = document.getElementById('new-booking-time-slot-modal');
    const closeModalButton = document.getElementById('new-booking-close-modal-btn');
    const modalResourceNameSpan = document.getElementById('new-booking-modal-resource-name');
    const modalResourceImageImg = document.getElementById('new-booking-modal-resource-image');
    const modalDateSpan = document.getElementById('new-booking-modal-date');
    const modalStatusMessageP = document.getElementById('new-booking-modal-status-message');
    const modalTimeSlotsListDiv = document.getElementById('new-booking-modal-time-slots-list');
    const modalBookingTitleInput = document.getElementById('new-booking-modal-booking-title');
    const modalConfirmBookingBtn = document.getElementById('new-booking-modal-confirm-booking-btn');
    let selectedTimeSlotForNewBooking = null;

    async function openResourceDetailModal(resource, dateString, userBookingsForDate = []) {
        if (!resourceDetailModal || !modalResourceNameSpan || !modalDateSpan || !modalResourceImageImg || !modalTimeSlotsListDiv || !modalBookingTitleInput || !modalConfirmBookingBtn || !modalStatusMessageP) {
            console.error('One or more modal elements are missing for new booking.'); // Keep this
            return;
        }
        modalResourceNameSpan.textContent = resource.name || 'N/A';
        modalDateSpan.textContent = dateString || 'N/A';
        modalBookingTitleInput.value = `Booking for ${resource.name}`;
        modalTimeSlotsListDiv.innerHTML = '';
        modalStatusMessageP.textContent = '';
        selectedTimeSlotForNewBooking = null;
        if (resource.image_url) {
            modalResourceImageImg.src = resource.image_url;
            modalResourceImageImg.alt = resource.name || 'Resource Image';
            modalResourceImageImg.style.display = 'block';
        } else {
            modalResourceImageImg.src = '#';
            modalResourceImageImg.alt = 'No image available';
            modalResourceImageImg.style.display = 'none';
        }
        modalConfirmBookingBtn.dataset.resourceId = resource.id;
        modalConfirmBookingBtn.dataset.dateString = dateString;
        modalConfirmBookingBtn.dataset.resourceName = resource.name;
        showLoading(modalStatusMessageP, 'Loading time slots...');
        try {
            const bookedSlots = await apiCall(`/api/resources/${resource.id}/availability?date=${dateString}`, {}, modalStatusMessageP);
            hideMessage(modalStatusMessageP);
            const predefinedSlots = [
                { name: "First Half-Day", label: "Book First Half-Day (08:00-12:00)", startTime: "08:00", endTime: "12:00", id: "first_half" },
                { name: "Second Half-Day", label: "Book Second Half-Day (13:00-17:00)", startTime: "13:00", endTime: "17:00", id: "second_half" },
                { name: "Full Day", label: "Book Full Day (08:00-17:00)", startTime: "08:00", endTime: "17:00", id: "full_day" }
            ];
            function checkConflict(slotStartTimeStr, slotEndTimeStr, existingBookings) {
                if (!existingBookings || existingBookings.length === 0) return false;
                const slotStart = new Date(`${dateString}T${slotStartTimeStr}:00`);
                const slotEnd = new Date(`${dateString}T${slotEndTimeStr}:00`);
                for (const booked of existingBookings) {
                    const bookedStart = new Date(`${dateString}T${booked.start_time}`);
                    const bookedEnd = new Date(`${dateString}T${booked.end_time}`);
                    if (bookedStart < slotEnd && bookedEnd > slotStart) return true;
                }
                return false;
            }
            predefinedSlots.forEach(slot => {
                const button = document.createElement('button');
                button.textContent = slot.label;
                button.classList.add('time-slot-item', 'button');
                button.dataset.slotId = slot.id;
                button.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-user-busy', 'selected', 'time-slot-selected', 'time-slot-passed');
                button.disabled = false;
                button.textContent = slot.label;
                button.title = '';

                const isToday = dateString === getTodayDateString();
                let slotHasPassed = false;

                if (isToday) {
                    const effectiveNow = getEffectiveClientNow(pastBookingAdjustmentHours);
                    // const actualNow = new Date(); // For potential logging of actual vs effective
                    const currentHours = effectiveNow.getHours();
                    const currentMinutes = effectiveNow.getMinutes();
                    const [slotEndHours, slotEndMinutes] = slot.endTime.split(':').map(Number);

                    // console.log(`[Debug Modal] Slot ${slot.name} (${slot.endTime}) on ${dateString}: Actual Time: ${actualNow.getHours()}:${String(actualNow.getMinutes()).padStart(2,'0')}, Effective Time: ${currentHours}:${String(currentMinutes).padStart(2,'0')}`);

                    if (currentHours > slotEndHours || (currentHours === slotEndHours && currentMinutes >= slotEndMinutes)) {
                        slotHasPassed = true;
                        button.classList.add('time-slot-passed');
                        button.disabled = true;
                        button.title = slot.name + ' has passed for today (effective time).';
                        button.textContent = slot.label + " (Passed)";
                        // console.log(`[Debug Modal] Slot ${slot.name} disabled as passed. Effective: ${currentHours}:${currentMinutes} vs SlotEnd: ${slotEndHours}:${slotEndMinutes}`);
                    }
                }

                if (!slotHasPassed) { // Only apply other logic if slot hasn't passed
                    const isGenerallyConflicting = checkConflict(slot.startTime, slot.endTime, bookedSlots);
                    if (isGenerallyConflicting) {
                        button.classList.add('time-slot-booked');
                        button.disabled = true;
                        button.title = `${slot.name} is unavailable due to existing bookings on this resource.`;
                    } else {
                        let isUserBusyElsewhere = false;
                        const loggedInUsernameChecked = sessionStorage.getItem('loggedInUserUsername');
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
                        // Determine if the button should be disabled due to user conflict, considering the setting
                        let disableButtonDueToUserConflict = isUserBusyElsewhere;
                        if (systemBookingSettings.allowMultipleResourcesSameTime) {
                            disableButtonDueToUserConflict = false; // If multiple bookings allowed, don't disable/mark as conflict due to user's other bookings
                            // console.log(`[Debug Modal] Slot ${slot.name} for Resource ${resource.id}: AllowMultiple is TRUE. UserConflictInitially: ${isUserBusyElsewhere}, ConsideredConflictForButton: ${disableButtonDueToUserConflict}`);
                        } else {
                            // console.log(`[Debug Modal] Slot ${slot.name} for Resource ${resource.id}: AllowMultiple is FALSE. UserConflictInitially: ${isUserBusyElsewhere}, ConsideredConflictForButton: ${disableButtonDueToUserConflict}`);
                        }

                        if (disableButtonDueToUserConflict) { // Check the modified flag
                            button.classList.add('time-slot-user-busy');
                            button.disabled = true;
                            button.title = `${slot.name} is unavailable as you have another booking at this time.`;
                            button.textContent = slot.label + " (Your Conflict)";
                        } else { // Slot is available from the user's schedule perspective (or conflicts are ignored)
                            button.classList.add('time-slot-available');
                            button.title = `${slot.name} is available.`;
                            button.addEventListener('click', function() {
                                const allButtons = modalTimeSlotsListDiv.querySelectorAll('button.time-slot-item');
                                allButtons.forEach(btn => btn.classList.remove('time-slot-selected', 'selected'));
                                this.classList.add('time-slot-selected', 'selected');
                                selectedTimeSlotForNewBooking = { startTimeStr: slot.startTime, endTimeStr: slot.endTime };
                                if (modalStatusMessageP) modalStatusMessageP.textContent = '';
                                if (mainFormStartTimeInput) mainFormStartTimeInput.value = slot.startTime;
                                if (mainFormEndTimeInput) mainFormEndTimeInput.value = slot.endTime;
                            });
                        }
                    }
                }
                modalTimeSlotsListDiv.appendChild(button);
            });

            const firstHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="first_half"]');
            const secondHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="second_half"]');
            const fullDayBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="full_day"]');

            if (fullDayBtn && firstHalfBtn && secondHalfBtn) {
                const fullDaySlotDetails = predefinedSlots.find(s => s.id === 'full_day');
                // Check if Full Day itself has passed first (most restrictive)
                if (fullDayBtn.classList.contains('time-slot-passed')) {
                    // Title and text already set by the loop if it passed.
                    // Ensure it's disabled.
                    fullDayBtn.disabled = true;
                } else {
                    // If Full Day hasn't passed, check constituent slots
                    const firstHalfBooked = firstHalfBtn.classList.contains('time-slot-booked'); // General booking conflict
                    const secondHalfBooked = secondHalfBtn.classList.contains('time-slot-booked'); // General booking conflict

                    // User conflict for full day depends on the setting.
                    // The classes 'time-slot-user-busy' on half-day buttons are now conditional on the setting.
                    // So, if allowMultipleResourcesSameTime is true, these classes won't be there for user conflicts.
                    const firstHalfShowsUserConflict = firstHalfBtn.classList.contains('time-slot-user-busy');
                    const secondHalfShowsUserConflict = secondHalfBtn.classList.contains('time-slot-user-busy');

                    const firstHalfPassed = firstHalfBtn.classList.contains('time-slot-passed');
                    const secondHalfPassed = secondHalfBtn.classList.contains('time-slot-passed');

                    if (firstHalfBooked || secondHalfBooked) {
                        fullDayBtn.disabled = true;
                        fullDayBtn.classList.remove('time-slot-available', 'time-slot-user-busy', 'time-slot-passed', 'selected', 'time-slot-selected');
                        fullDayBtn.classList.add('time-slot-booked');
                        fullDayBtn.title = "Full Day is unavailable because part of the day is booked on this resource.";
                        if (fullDaySlotDetails) fullDayBtn.textContent = fullDaySlotDetails.label + " (Booked)";
                    } else if (firstHalfShowsUserConflict || secondHalfShowsUserConflict) {
                        // This condition is now naturally correct. If allowMultiple is true,
                        // firstHalfShowsUserConflict/secondHalfShowsUserConflict will be false for user-only conflicts.
                        fullDayBtn.disabled = true;
                        fullDayBtn.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-passed', 'selected', 'time-slot-selected');
                        fullDayBtn.classList.add('time-slot-user-busy');
                        fullDayBtn.title = "Full Day is unavailable because you have other bookings conflicting with part of this day.";
                        if (fullDaySlotDetails) fullDayBtn.textContent = fullDaySlotDetails.label + " (Your Conflict)";
                    } else if (firstHalfPassed || secondHalfPassed) {
                        // If either half has passed, and full day itself hasn't been marked as passed yet (e.g. if full_day.endTime is later)
                        fullDayBtn.disabled = true;
                        fullDayBtn.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-user-busy', 'selected', 'time-slot-selected');
                        fullDayBtn.classList.add('time-slot-passed'); // Mark full day as passed too
                        fullDayBtn.title = "Full Day is unavailable because part of the day has already passed.";
                        if (fullDaySlotDetails) fullDayBtn.textContent = fullDaySlotDetails.label + " (Passed)";
                    }
                    // If fullDayBtn was already generally booked (isFullDayGenerallyBooked from before), it would be caught by the slot.isGenerallyBooked check
                    // This explicit check here might be redundant if the loop correctly handles fullDayBtn's general booking status.
                    // However, keeping it for now as a safeguard for combined conditions.
                    // The main thing is that if fullDay itself hasn't passed by its own end time, but one of its sub-slots has,
                    // it becomes unavailable due to that sub-slot.
                }
            }
        } catch (error) {
            console.error(`Error fetching time slots for resource ${resource.id}:`, error.message); // Keep this error
            if (!modalStatusMessageP.classList.contains('error')) {
                showError(modalStatusMessageP, 'Could not load time slots.');
            }
        }
        resourceDetailModal.style.display = 'block';
    }

    if (closeModalButton) {
        closeModalButton.onclick = function() {
            if (resourceDetailModal) resourceDetailModal.style.display = 'none';
            selectedTimeSlotForNewBooking = null;
        }
    }
    window.onclick = function(event) {
        if (event.target == resourceDetailModal) {
            resourceDetailModal.style.display = "none";
            selectedTimeSlotForNewBooking = null;
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
                return;
            }
            const resourceId = this.dataset.resourceId;
            const dateString = this.dataset.dateString;
            const resourceName = this.dataset.resourceName || "this resource";
            let title = modalBookingTitleInput.value.trim();
            if (!title) {
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
                if (responseData && (responseData.id || (responseData.bookings && responseData.bookings.length > 0))) {
                     if (!modalStatusMessageP.classList.contains('success')) {
                        showSuccess(modalStatusMessageP, `Booking for '${responseData.title || bookingData.title}' confirmed!`);
                     }
                    setTimeout(() => {
                        if (resourceDetailModal) resourceDetailModal.style.display = "none";
                        selectedTimeSlotForNewBooking = null;
                    }, 2000);
                    if (currentMapId && currentSelectedDateStr) { // Use global date string
                        loadMapDetails(currentMapId, currentSelectedDateStr);
                        updateLocationFloorButtons(); // Update map selection buttons

                        // <<< START NEW CODE >>>
                        if (userId && calendarContainer) { // Ensure userId and calendarContainer are available
                            try {
                                console.log('[Booking Success] Attempting to refresh Flatpickr unavailable dates...');
                                // Ensure userId is defined and available in this scope.
                                // It's typically defined globally in the script like:
                                // const userId = calendarContainer ? calendarContainer.dataset.userId : null;
                                // Ensure calendarContainer is also defined and available.

                                const newUnavailableDates = await apiCall(`/api/resources/unavailable_dates?user_id=${userId}`);
                                const fpInstance = calendarContainer._flatpickr;

                                if (fpInstance && newUnavailableDates) {
                                    console.log('[Booking Success] Fetched new unavailable dates:', newUnavailableDates);

                                    fpInstance.set('disable', [
                                        function(date) {
                                            const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
                                            // Check against the newly fetched unavailable dates
                                            if (newUnavailableDates.includes(dateStr)) {
                                                return true;
                                            }
                                            // Add any other conditions for disabling dates here if necessary,
                                            // otherwise, if only newUnavailableDates matters, this function can be simplified.
                                            // For now, we will assume that if it's not in newUnavailableDates, it's not disabled by this specific part.
                                            return false; // Or return based on other existing logic if present
                                        }
                                    ]);
                                    fpInstance.redraw(); // Trigger a redraw to apply changes
                                    console.log('[Booking Success] Flatpickr unavailable dates refreshed.');
                                } else {
                                    if (!fpInstance) console.warn('[Booking Success] Flatpickr instance not found for refresh.');
                                    if (!newUnavailableDates) console.warn('[Booking Success] New unavailable dates not fetched (or empty) for refresh.');
                                }
                            } catch (error) {
                                console.error('[Booking Success] Error refreshing Flatpickr unavailable dates:', error);
                            }
                        } else {
                            if (!userId) console.warn('[Booking Success] userId not available for Flatpickr refresh.');
                            if (!calendarContainer) console.warn('[Booking Success] calendarContainer not available for Flatpickr refresh.');
                        }
                        // <<< END NEW CODE >>>
                    }
                } else {
                    if (!modalStatusMessageP.classList.contains('error') && !modalStatusMessageP.classList.contains('success')) {
                        showError(modalStatusMessageP, "Booking failed. Unexpected response from server.");
                    }
                }
            } catch (error) {
                console.error('Booking from modal failed:', error.message); // Keep this error
                 if (!modalStatusMessageP.classList.contains('error')) {
                     showError(modalStatusMessageP, `Booking failed: ${error.message}`);
                 }
            }
        });
    }

});
// console.log('new_booking_map.js script execution finished.'); // Keep general load confirmation
