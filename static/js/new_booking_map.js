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

    const calendarContainer = document.getElementById('inline-calendar-container');
    const userId = calendarContainer ? calendarContainer.dataset.userId : null;
    console.log('[Debug] Flatpickr User ID:', userId);

    let pastBookingAdjustmentHours = 0;
    if (calendarContainer && calendarContainer.dataset.pastBookingAdjustmentHours) {
        pastBookingAdjustmentHours = parseFloat(calendarContainer.dataset.pastBookingAdjustmentHours);
        if (isNaN(pastBookingAdjustmentHours)) {
            pastBookingAdjustmentHours = 0;
            console.warn('[Debug] Invalid past_booking_adjustment_hours, defaulting to 0.');
        }
    }
    console.log('[Debug] Using pastBookingAdjustmentHours:', pastBookingAdjustmentHours);

    let globalTimeOffsetHours = 0;
    if (calendarContainer && calendarContainer.dataset.globalTimeOffsetHours) {
        globalTimeOffsetHours = parseFloat(calendarContainer.dataset.globalTimeOffsetHours);
        if (isNaN(globalTimeOffsetHours)) {
            globalTimeOffsetHours = 0;
            console.warn('[Debug] Invalid global_time_offset_hours, defaulting to 0.');
        }
    }
    console.log('[Debug] Using globalTimeOffsetHours:', globalTimeOffsetHours);

    const mapLocationButtonsContainer = document.getElementById('new-booking-map-location-buttons-container');
    const mapContainer = document.getElementById('new-booking-map-container');
    const mapLoadingStatusDiv = document.getElementById('new-booking-map-loading-status');
    const resourceSelectBooking = document.getElementById('resource-select-booking');

    const dateSelectionInstructionDiv = document.getElementById('date-selection-instruction');
    const locationSelectionInstructionDiv = document.getElementById('location-selection-instruction');
    const locationFloorWrapperDiv = document.getElementById('location-floor-wrapper');
    const mapViewWrapperDiv = document.getElementById('map-view-wrapper');

    let allMapInfo = [];
    let selectedMapId = null;
    let currentMapId = null;
    let currentSelectedDateStr = getTodayDateString();

    let systemBookingSettings = { allowMultipleResourcesSameTime: false };

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
        if (mapLocationButtonsContainer) {
            mapLocationButtonsContainer.innerHTML = '<p>No maps available or date not selected.</p>';
        }
    }

    function highlightSelectedResourceOnMap() {
        if (!resourceSelectBooking) {
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

    function fetchDataAndInitializeFlatpickr() {
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
                initializeFlatpickr([]);
            }
        }
    }

    function initializeFlatpickr(unavailableDatesList = []) {
        if (calendarContainer) {
            currentSelectedDateStr = getTodayDateString();

            flatpickr(calendarContainer, {
                inline: true,
                static: true,
                dateFormat: "Y-m-d",
                disable: [
                    function(date) {
                        const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
                        const today = new Date();
                        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

                        if (dateStr === todayStr) {
                            // Get current UTC time
                            const nowUtc = new Date(Date.UTC(
                                today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate(),
                                today.getUTCHours(), today.getUTCMinutes(), today.getUTCSeconds()
                            ));

                            // Calculate effective venue 'now' by applying global offset
                            const effectiveVenueNow = new Date(nowUtc.getTime() + globalTimeOffsetHours * 60 * 60 * 1000);

                            // Calculate the cutoff time at the venue
                            const venueCutoffTime = new Date(effectiveVenueNow.getTime() - pastBookingAdjustmentHours * 60 * 60 * 1000);

                            const latestSlotEndTimeHour = 17; // Assuming venue local time
                            const latestSlotEndTimeMinute = 0;

                            // Create a datetime object for the end of the latest slot on the current day (venue local time)
                            const latestSlotEndTodayVenueLocal = new Date(
                                effectiveVenueNow.getFullYear(), // Use year/month/day from effectiveVenueNow to handle date correctly
                                effectiveVenueNow.getMonth(),
                                effectiveVenueNow.getDate(),
                                latestSlotEndTimeHour,
                                latestSlotEndTimeMinute
                            );

                            let shouldDisableToday = false;
                            // If the venue's cutoff time is at or after the end of the latest standard slot for that day
                            if (venueCutoffTime.getTime() >= latestSlotEndTodayVenueLocal.getTime()) {
                                shouldDisableToday = true;
                            }

                            console.log(`[Debug] Flatpickr disable check for TODAY (${dateStr}):
` +
                                `  Client Local Now: ${today.toISOString()}
` +
                                `  UTC Now: ${nowUtc.toISOString()}
` +
                                `  Global Offset: ${globalTimeOffsetHours}h
` +
                                `  Effective Venue Now: ${effectiveVenueNow.toISOString()}
` +
                                `  Past Adjustment: ${pastBookingAdjustmentHours}h
` +
                                `  Venue Cutoff Time: ${venueCutoffTime.toISOString()}
` +
                                `  Latest Slot End (Venue Local): ${latestSlotEndTodayVenueLocal.toISOString()}
` +
                                `  Disabling Today?: ${shouldDisableToday}`);

                            if (shouldDisableToday) {
                                return true; // Disable the entire day
                            }
                        }
                        const isDisabledByUnavailableList = unavailableDatesList.includes(dateStr);
                        if (! (dateStr === todayStr) && (unavailableDatesList.length > 0 || dateStr.startsWith("2025-06"))) {
                           console.log(`[Debug] Flatpickr disable check for ${dateStr}: inList = ${isDisabledByUnavailableList} (list length: ${unavailableDatesList.length})`);
                        }
                        return isDisabledByUnavailableList;
                    }
                ],
                defaultDate: currentSelectedDateStr,
                onChange: function(selectedDates, dateStr, instance) {
                    currentSelectedDateStr = dateStr;

                    if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'none';
                    if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'flex';
                    if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'block';
                    if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'none';

                    updateLocationFloorButtons().then(() => {
                        if (!selectedMapId) {
                            loadMapDetails(null, currentSelectedDateStr);
                        }
                        if (locationFloorWrapperDiv) {
                            locationFloorWrapperDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                    });
                }
            });
            if (mainBookingFormDateInput && mainBookingFormDateInput.value !== currentSelectedDateStr) {
                mainBookingFormDateInput.value = currentSelectedDateStr;
            }
        } else {
            console.error('Inline calendar container not found for Flatpickr.');
        }
    }

    fetchDataAndInitializeFlatpickr();

    async function updateLocationFloorButtons() {
        if (!calendarContainer || !mapLocationButtonsContainer) {
            console.error("Calendar container or location buttons container not found for updateLocationFloorButtons");
            return;
        }
        const selectedDate = currentSelectedDateStr;
        if (!selectedDate) {
            mapLocationButtonsContainer.innerHTML = "<p>Please select a date to see map availability.</p>";
            return;
        }

        showLoading(mapLoadingStatusDiv, 'Fetching map availability...');
        try {
            const mapsAvailabilityData = await apiCall(`/api/maps-availability?date=${selectedDate}`, {}, mapLoadingStatusDiv);
            mapLocationButtonsContainer.innerHTML = '';

            if (!allMapInfo || allMapInfo.length === 0) {
                mapLocationButtonsContainer.innerHTML = "<p>No maps configured in the system.</p>";
                hideMessage(mapLoadingStatusDiv);
                return;
            }

            allMapInfo.forEach(mapInfo => {
                const button = document.createElement('button');
                button.textContent = mapInfo.name;
                button.classList.add('location-button', 'button');
                button.dataset.mapId = mapInfo.id;
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
                            button.classList.add('location-button-unavailable');
                            button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Availability Status Unknown`;
                            break;
                    }
                } else {
                    button.classList.add('location-button-unavailable');
                    button.title = `${mapInfo.name} (${mapInfo.location} - Floor ${mapInfo.floor}) - Availability Data Missing`;
                }

                if (mapInfo.id === selectedMapId) {
                    button.classList.add('selected-map-button');
                }
                if (button.classList.contains('location-button-unavailable')) {
                    button.disabled = true;
                }

                button.addEventListener('click', function() {
                    selectedMapId = mapInfo.id;
                    currentMapId = mapInfo.id;
                    document.querySelectorAll('#new-booking-map-location-buttons-container .location-button').forEach(btn => {
                        btn.classList.remove('selected-map-button');
                    });
                    this.classList.add('selected-map-button');
                    loadMapDetails(selectedMapId, currentSelectedDateStr);
                    if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
                    if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'block';
                    if (mapViewWrapperDiv) {
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
            const response = await fetch('/api/admin/system-settings/map-opacity');
            if (response.ok) {
                const data = await response.json();
                if (data.opacity !== undefined && typeof data.opacity === 'number' && data.opacity >= 0.0 && data.opacity <= 1.0) {
                    uiOpacity = data.opacity;
                    return uiOpacity;
                }
            } else {
                console.warn(`API call to fetch map opacity failed with status ${response.status}. Using fallback opacity values.`);
            }
        } catch (error) {
            console.warn(`Error fetching UI configured opacity: ${error.message}. Using fallback opacity values.`);
        }
        if (typeof window.MAP_RESOURCE_OPACITY === 'number' && window.MAP_RESOURCE_OPACITY >= 0.0 && window.MAP_RESOURCE_OPACITY <= 1.0) {
            return window.MAP_RESOURCE_OPACITY;
        }
        return defaultOpacity;
    }

    async function loadMapDetails(mapId, dateString) {
        const mapResourceOpacity = await getEffectiveMapResourceOpacity();
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
                console.warn(`Could not fetch user's bookings for date ${dateString}:`, err.message);
            }
        }

        function timeToMinutes(timeStr) {
            const parts = timeStr.split(':');
            return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
        }

        try {
            const apiUrl = `/api/map_details/${mapId}?date=${dateString}`;
            const data = await apiCall(apiUrl, {}, mapLoadingStatusDiv);
            const mapDetails = data.map_details;
            const offsetX = parseInt(mapDetails.offset_x) || 0;
            const offsetY = parseInt(mapDetails.offset_y) || 0;

            if (mapContainer) {
                mapContainer.style.backgroundImage = `url(${mapDetails.image_url})`;
            }
            const colorMap = {
                'map-area-green': '212, 237, 218',
                'map-area-yellow': '255, 243, 205',
                'map-area-light-blue': '209, 236, 241',
                'map-area-red': '248, 215, 218',
                'map-area-dark-orange': '255, 232, 204'
            };

            if (data.mapped_resources && data.mapped_resources.length > 0) {
                data.mapped_resources.forEach(resource => {
                    if (resource.map_coordinates && resource.map_coordinates.type === 'rect') {
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
                        if (resource.current_user_can_book === false) {
                            areaDiv.className = 'resource-area resource-area-permission-denied';
                            areaDiv.title = resource.name + ' (Permission Denied)';
                            const permissionDeniedRgbString = colorMap['resource-area-permission-denied'] || '173, 216, 230';
                            areaDiv.style.setProperty('background-color', `rgba(${permissionDeniedRgbString}, ${mapResourceOpacity})`, 'important');
                        } else {
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
                                const originalUserConflictStatus = slot.isConflictingWithUserOtherBookings;
                                let consideredConflictForBookableStatus = slot.isConflictingWithUserOtherBookings;
                                if (systemBookingSettings.allowMultipleResourcesSameTime) {
                                    consideredConflictForBookableStatus = false;
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
                                    } else if (numBookableByCurrentUser > 0) { // Typo fixed from 'numBookableByCurrentUser'
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

                            areaDiv.className = 'resource-area';
                            areaDiv.classList.add(finalClass);
                            const rgbString = colorMap[finalClass] || colorMap['map-area-light-blue'];
                            if (rgbString) {
                                areaDiv.style.setProperty('background-color', `rgba(${rgbString}, ${mapResourceOpacity})`, 'important');
                            }
                            areaDiv.title = finalTitle;

                            if (isMapAreaClickable) {
                                areaDiv.classList.add('map-area-clickable');
                                areaDiv.addEventListener('click', function() {
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
            console.error('Error fetching or rendering map details:', error);
            if (mapContainer) mapContainer.style.backgroundImage = 'none';
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error')) {
                showError(mapLoadingStatusDiv, `Error loading map: ${error.message}`);
            }
        }
        highlightSelectedResourceOnMap();
    }

    function handleFilterChange(source = 'map') {
        if (isSyncingDate) return;
        isSyncingDate = true;
        let newDate = currentSelectedDateStr;
        if (source === 'form' && mainBookingFormDateInput) {
            newDate = mainBookingFormDateInput.value;
            if (currentSelectedDateStr !== newDate) {
                currentSelectedDateStr = newDate;
                const flatpickrInstance = calendarContainer ? calendarContainer._flatpickr : null;
                if (flatpickrInstance) {
                    flatpickrInstance.setDate(newDate, false);
                }
            }
        } else {
             newDate = currentSelectedDateStr;
             if (mainBookingFormDateInput && mainBookingFormDateInput.value !== newDate) {
                 mainBookingFormDateInput.value = newDate;
             }
        }
        updateLocationFloorButtons().then(() => {
            if (selectedMapId) {
                loadMapDetails(selectedMapId, newDate);
            } else {
                loadMapDetails(null, newDate);
            }
        }).finally(() => {
            isSyncingDate = false;
        });
    }

    async function initializeMapSelectionUI() {
        await fetchBookingConfigStatus();
        if (!mapLocationButtonsContainer || !mapLoadingStatusDiv) {
            console.error("Map buttons container or loading status div are missing from the DOM.");
            updateMapLoadingStatus("Map interface error. Please contact support.", true);
            disableMapSelectors();
            return;
        }
        updateMapLoadingStatus("Loading map configurations...", false);
        try {
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
            allMapInfo = maps;
            if (!allMapInfo || allMapInfo.length === 0) {
                updateMapLoadingStatus('No maps configured in the system.', true);
                disableMapSelectors();
                return;
            }
            await updateLocationFloorButtons();
            if (mainBookingFormDateInput) mainBookingFormDateInput.addEventListener('change', () => handleFilterChange('form'));
            if (resourceSelectBooking) resourceSelectBooking.addEventListener('change', highlightSelectedResourceOnMap);
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                if (allMapInfo.length > 0) {
                    updateMapLoadingStatus('Please select a map to view details.', false);
                } else {
                    updateMapLoadingStatus('No maps found in configurations.', false);
                }
            }
            highlightSelectedResourceOnMap();
            if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'block';
            if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
            if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'none';
            if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'none';

            if (selectedMapId) {
                 loadMapDetails(selectedMapId, currentSelectedDateStr);
                 if (locationSelectionInstructionDiv) locationSelectionInstructionDiv.style.display = 'none';
                 if (mapViewWrapperDiv) mapViewWrapperDiv.style.display = 'block';
                 if (dateSelectionInstructionDiv) dateSelectionInstructionDiv.style.display = 'none';
                 if (locationFloorWrapperDiv) locationFloorWrapperDiv.style.display = 'flex';
            } else {
                loadMapDetails(null, currentSelectedDateStr);
            }
        } catch (error) {
            updateMapLoadingStatus('Could not load map configurations. Network or server error.', true);
            disableMapSelectors();
        }
    }

    if (mapContainer) {
        initializeMapSelectionUI();
        document.addEventListener('refreshNewBookingMap', function(event) {
            if (selectedMapId && currentSelectedDateStr) {
                loadMapDetails(selectedMapId, currentSelectedDateStr);
            } else {
                console.warn('Cannot refresh new_booking_map: selectedMapId or currentSelectedDateStr is not set.');
            }
        });
    }

    async function fetchBookingConfigStatus() {
        try {
            const data = await apiCall('/api/settings/booking_config_status', {}, null);
            if (data && typeof data.allow_multiple_resources_same_time === 'boolean') {
                systemBookingSettings.allowMultipleResourcesSameTime = data.allow_multiple_resources_same_time;
            } else {
                console.warn('Booking config status API response was not in the expected format. Using default.', data);
            }
        } catch (error) {
            console.error('Error fetching booking config status:', error.message, 'Using default settings.');
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
            console.error('One or more modal elements are missing for new booking.');
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

        const resourceId = resource.id;

        try {
            const apiAvailabilityData = await apiCall(`/api/resources/${resource.id}/availability?date=${dateString}`, {}, modalStatusMessageP);
            hideMessage(modalStatusMessageP);

            const actualBookedSlots = apiAvailabilityData.booked_slots || [];
            const standardSlotStatusesFromAPI = apiAvailabilityData.standard_slot_statuses || {};
            const loggedInUsername = sessionStorage.getItem('loggedInUserUsername');

            const predefinedSlotsConfig = [
                { name: "First Half-Day", label: "Book First Half-Day (08:00-12:00)", startTime: "08:00", endTime: "12:00", id: "first_half" },
                { name: "Second Half-Day", label: "Book Second Half-Day (13:00-17:00)", startTime: "13:00", endTime: "17:00", id: "second_half" },
                { name: "Full Day", label: "Book Full Day (08:00-17:00)", startTime: "08:00", endTime: "17:00", id: "full_day" }
            ];

            predefinedSlotsConfig.forEach(slotConf => {
                const button = document.createElement('button');
                button.textContent = slotConf.label;
                button.classList.add('time-slot-item', 'button', 'predefined-slot-btn');
                button.dataset.slotId = slotConf.id;
                button.dataset.startTime = slotConf.startTime;
                button.dataset.endTime = slotConf.endTime;

                button.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-user-busy', 'selected', 'time-slot-selected', 'slot-passed');
                button.disabled = false;
                button.title = '';

                const apiSlotStatus = standardSlotStatusesFromAPI[slotConf.id];

                if (apiSlotStatus && apiSlotStatus.is_passed) {
                    button.classList.add('slot-passed');
                    button.disabled = true;
                    button.textContent = slotConf.label + " (Passed)";
                    button.title = slotConf.name + ' has passed.';
                } else {
                    let isPredefinedBookedOnResource = false;
                    const slotStartPre = new Date(`${dateString}T${slotConf.startTime}:00`);
                    const slotEndPre = new Date(`${dateString}T${slotConf.endTime}:00`);

                    if (actualBookedSlots && actualBookedSlots.length > 0) {
                        for (const booked of actualBookedSlots) {
                            const bookedStartDateTime = new Date(dateString + 'T' + booked.start_time);
                            const bookedEndDateTime = new Date(dateString + 'T' + booked.end_time);
                            if (bookedStartDateTime < slotEndPre && bookedEndDateTime > slotStartPre) {
                                isPredefinedBookedOnResource = true;
                                break;
                            }
                        }
                    }

                    if (isPredefinedBookedOnResource) {
                        button.classList.add('time-slot-booked');
                        button.disabled = true;
                        button.title = `${slotConf.name} is unavailable due to existing bookings on this resource.`;
                        button.textContent = slotConf.label + " (Booked)";
                    } else {
                        let hasPredefinedUserConflict = false;
                        if (!systemBookingSettings.allowMultipleResourcesSameTime && userBookingsForDate && userBookingsForDate.length > 0) {
                            for (const userBooking of userBookingsForDate) {
                                if (String(userBooking.resource_id) !== String(resourceId)) {
                                    const userBookingStartDateTime = new Date(dateString + 'T' + userBooking.start_time);
                                    const userBookingEndDateTime = new Date(dateString + 'T' + userBooking.end_time);
                                    if (userBookingStartDateTime < slotEndPre && userBookingEndDateTime > slotStartPre) {
                                        hasPredefinedUserConflict = true;
                                        break;
                                    }
                                }
                            }
                        }

                        if (hasPredefinedUserConflict) {
                            button.classList.add('time-slot-user-busy');
                            button.disabled = true;
                            button.title = `${slotConf.name} is unavailable as you have another booking at this time.`;
                            button.textContent = slotConf.label + " (Your Conflict)";
                        } else {
                            button.classList.add('time-slot-available');
                            button.title = `${slotConf.name} is available.`;
                            button.addEventListener('click', function() {
                                modalTimeSlotsListDiv.querySelectorAll('.time-slot-item').forEach(btn => btn.classList.remove('time-slot-selected', 'selected'));
                                this.classList.add('time-slot-selected', 'selected');
                                selectedTimeSlotForNewBooking = { startTimeStr: slotConf.startTime, endTimeStr: slotConf.endTime };
                                if (modalStatusMessageP) modalStatusMessageP.textContent = '';
                                if (mainFormStartTimeInput) mainFormStartTimeInput.value = slotConf.startTime;
                                if (mainFormEndTimeInput) mainFormEndTimeInput.value = slotConf.endTime;
                            });
                        }
                    }
                }
                modalTimeSlotsListDiv.appendChild(button);
            });

            const firstHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="first_half"]');
            const secondHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="second_half"]');
            const fullDayBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="full_day"]');

            if (fullDayBtn && !fullDayBtn.classList.contains('slot-passed')) {
                const firstHalfBookedOrPassed = firstHalfBtn && (firstHalfBtn.classList.contains('time-slot-booked') || firstHalfBtn.classList.contains('slot-passed'));
                const secondHalfBookedOrPassed = secondHalfBtn && (secondHalfBtn.classList.contains('time-slot-booked') || secondHalfBtn.classList.contains('slot-passed'));
                const firstHalfUserBusy = firstHalfBtn && firstHalfBtn.classList.contains('time-slot-user-busy');
                const secondHalfUserBusy = secondHalfBtn && secondHalfBtn.classList.contains('time-slot-user-busy');
                const fullDaySlotDetails = predefinedSlotsConfig.find(s => s.id === 'full_day');
                const fullDayBaseText = fullDaySlotDetails ? fullDaySlotDetails.label : "Book Full Day (08:00-17:00)";

                if (firstHalfBookedOrPassed || secondHalfBookedOrPassed) {
                    fullDayBtn.disabled = true;
                    fullDayBtn.classList.remove('time-slot-available', 'time-slot-user-busy', 'time-slot-selected', 'selected');
                    if ((firstHalfBtn && firstHalfBtn.classList.contains('slot-passed')) || (secondHalfBtn && secondHalfBtn.classList.contains('slot-passed'))) {
                        fullDayBtn.classList.add('slot-passed');
                         fullDayBtn.textContent = fullDayBaseText + " (Partially Passed)";
                         fullDayBtn.title = "Full Day is unavailable because part of the day has passed.";
                    } else {
                        fullDayBtn.classList.add('time-slot-booked');
                        fullDayBtn.textContent = fullDayBaseText + " (Booked)";
                        fullDayBtn.title = "Full Day is unavailable because part of the day is booked on this resource.";
                    }
                } else if (firstHalfUserBusy || secondHalfUserBusy) {
                    fullDayBtn.disabled = true;
                    fullDayBtn.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-selected', 'selected');
                    fullDayBtn.classList.add('time-slot-user-busy');
                    fullDayBtn.title = "Full Day is unavailable because you have other bookings conflicting with part of this day.";
                    fullDayBtn.textContent = fullDayBaseText + " (Your Conflict)";
                }
            }

            // REMOVED: Hourly slot generation loop and separator
            // const separator = document.createElement('hr');
            // modalTimeSlotsListDiv.appendChild(separator);
            // const workDayStartHour = 8;
            // const workDayEndHour = 17;
            // const slotDurationHours = 1;
            // for (let hour = workDayStartHour; hour < workDayEndHour; hour += slotDurationHours) { ... }

        } catch (error) {
            console.error(`Error fetching time slots for resource ${resource.id}:`, error.message);
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
                    if (currentMapId && currentSelectedDateStr) {
                        loadMapDetails(currentMapId, currentSelectedDateStr);
                        updateLocationFloorButtons();

                        if (userId && calendarContainer) {
                            try {
                                console.log('[Booking Success] Attempting to refresh Flatpickr unavailable dates...');
                                const newUnavailableDates = await apiCall(`/api/resources/unavailable_dates?user_id=${userId}`);
                                const fpInstance = calendarContainer._flatpickr;

                                if (fpInstance && newUnavailableDates) {
                                    console.log('[Booking Success] Fetched new unavailable dates:', newUnavailableDates);
                                    const newDisableFunc = function(date) {
                                        const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
                                        const today = new Date();
                                        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

                                        if (dateStr === todayStr) {
                                            // Get current UTC time
                                            const nowUtc = new Date(Date.UTC(
                                                today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate(),
                                                today.getUTCHours(), today.getUTCMinutes(), today.getUTCSeconds()
                                            ));
                                            // Calculate effective venue 'now' by applying global offset
                                            const effectiveVenueNow = new Date(nowUtc.getTime() + globalTimeOffsetHours * 60 * 60 * 1000);
                                            // Calculate the cutoff time at the venue
                                            const venueCutoffTime = new Date(effectiveVenueNow.getTime() - pastBookingAdjustmentHours * 60 * 60 * 1000);
                                            const latestSlotEndTimeHour = 17; // Assuming venue local time
                                            const latestSlotEndTimeMinute = 0;
                                            const latestSlotEndTodayVenueLocal = new Date(
                                                effectiveVenueNow.getFullYear(),
                                                effectiveVenueNow.getMonth(),
                                                effectiveVenueNow.getDate(),
                                                latestSlotEndTimeHour,
                                                latestSlotEndTimeMinute
                                            );
                                            if (venueCutoffTime.getTime() >= latestSlotEndTodayVenueLocal.getTime()) {
                                                return true; // Disable the entire day
                                            }
                                        }
                                        return newUnavailableDates.includes(dateStr);
                                    };
                                    fpInstance.set('disable', [newDisableFunc]);
                                    fpInstance.redraw();
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
                    }
                } else {
                    if (!modalStatusMessageP.classList.contains('error') && !modalStatusMessageP.classList.contains('success')) {
                        showError(modalStatusMessageP, "Booking failed. Unexpected response from server.");
                    }
                }
            } catch (error) {
                console.error('Booking from modal failed:', error.message);
                 if (!modalStatusMessageP.classList.contains('error')) {
                     showError(modalStatusMessageP, `Booking failed: ${error.message}`);
                 }
            }
        });
    }

});
// console.log('new_booking_map.js script execution finished.');
