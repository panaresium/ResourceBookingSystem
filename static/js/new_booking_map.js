document.addEventListener('DOMContentLoaded', function () {
    // console.log('new_booking_map.js loaded and DOM fully parsed.'); // Keep general load confirmation

    function getTodayDateString() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    const mapAvailabilityDateInput = document.getElementById('new-booking-map-availability-date');
    const mapLocationSelect = document.getElementById('new-booking-map-location-select');
    const mapFloorSelect = document.getElementById('new-booking-map-floor-select');
    const mapContainer = document.getElementById('new-booking-map-container');
    const mapLoadingStatusDiv = document.getElementById('new-booking-map-loading-status');
    const resourceSelectBooking = document.getElementById('resource-select-booking');

    let allMapInfo = [];
    let currentMapId = null;

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
        if (mapLocationSelect) {
            mapLocationSelect.innerHTML = '<option value="">-- Not Available --</option>';
            mapLocationSelect.disabled = true;
        }
        if (mapFloorSelect) {
            mapFloorSelect.innerHTML = '<option value="">-- Not Available --</option>';
            mapFloorSelect.disabled = true;
        }
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

    const today = getTodayDateString();
    if (mapAvailabilityDateInput) {
        mapAvailabilityDateInput.value = today;
    } else {
        console.error('Map availability date input not found.'); // Keep this error
    }
    if (mainBookingFormDateInput) {
        mainBookingFormDateInput.value = today;
    }

    function updateFloorSelectOptions() {
        if (!mapFloorSelect || !mapLocationSelect) {
            console.error("Floor or Location select dropdown not found for updateFloorSelectOptions"); // Keep this error
            return;
        }
        const selectedLocation = mapLocationSelect.value;
        mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>';
        if (!selectedLocation) {
            mapFloorSelect.disabled = true;
            return;
        }
        const availableFloors = [...new Set(allMapInfo
            .filter(map => map.location === selectedLocation && map.floor)
            .map(map => map.floor)
            .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
        )];
        if (availableFloors.length > 0) {
            availableFloors.forEach(floor => mapFloorSelect.add(new Option(floor, floor)));
            mapFloorSelect.disabled = false;
        } else {
            mapFloorSelect.disabled = true;
        }
    }

    async function loadMapDetails(mapId, dateString) {
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
            const offsetX = parseInt(mapDetails.offset_x) || 0;
            const offsetY = parseInt(mapDetails.offset_y) || 0;

            if (mapContainer) {
                mapContainer.style.backgroundImage = `url(${mapDetails.image_url})`;
            }

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
                            slot.isBookableByCurrentUser = (!slot.isGenerallyBooked && !slot.isConflictingWithUserOtherBookings);
                        });

                        // REMOVED: console.log("DEBUG MAP: Primary Slots State for " + resource.name + ":", JSON.stringify(primarySlots));

                        let finalClass = '';
                        let finalTitle = resource.name;
                        const numPrimarySlots = primarySlots.length;
                        const numBookableByCurrentUser = primarySlots.filter(s => s.isBookableByCurrentUser).length;
                        const numBookedByCurrentUser = primarySlots.filter(s => s.isBookedByCurrentUser).length;
                        const numGenerallyBooked = primarySlots.filter(s => s.isGenerallyBooked).length;

                        // REMOVED: console.log("DEBUG MAP: Counts for " + resource.name + ": BookedByCU=" + numBookedByCurrentUser + ", GenerallyBooked=" + numGenerallyBooked + ", BookableByCU=" + numBookableByCurrentUser + ", NumPrimarySlots=" + numPrimarySlots);

                        if (numBookedByCurrentUser === numPrimarySlots) {
                            // REMOVED: console.log("DEBUG MAP: Condition for " + resource.name + ": User booked all slots. Assigning map-area-red.");
                            finalClass = 'map-area-red';
                            finalTitle += ' (Booked by You - Full Day)';
                        } else if (numBookedByCurrentUser > 0) {
                            // REMOVED: console.log("DEBUG MAP: Condition for " + resource.name + ": User booked some slots.");
                            if (numBookableByCurrentUser > 0) {
                                // REMOVED: console.log("DEBUG MAP: Path B1 for " + resource.name + ". Assigning map-area-yellow.");
                                finalClass = 'map-area-yellow';
                                finalTitle += ' (Partially Booked by You - More Available Here)';
                            } else {
                                // REMOVED: console.log("DEBUG MAP: Path B2 for " + resource.name + ". Assigning map-area-dark-orange.");
                                finalClass = 'map-area-dark-orange';
                                finalTitle += ' (Partially Booked by You - Fully Utilized by You)';
                            }
                        } else {
                            // REMOVED: console.log("DEBUG MAP: Path C for " + resource.name + " (User has no bookings on this resource)");
                            if (resource.is_under_maintenance && numGenerallyBooked === 0) {
                                // REMOVED: console.log("DEBUG MAP: Path C1 for " + resource.name + ". Assigning map-area-light-blue (Maintenance).");
                                finalClass = 'map-area-light-blue';
                                finalTitle += ' (Under Maintenance)';
                            } else if (numGenerallyBooked === numPrimarySlots) {
                                // REMOVED: console.log("DEBUG MAP: Path C2 for " + resource.name + ". Assigning map-area-light-blue (Fully Booked by Others).");
                                finalClass = 'map-area-light-blue';
                                finalTitle += ' (Fully Booked by Others)';
                            } else if (numGenerallyBooked === 0) {
                                // REMOVED: console.log("DEBUG MAP: Path C3 for " + resource.name + " (Generally fully available)");
                                if (numBookableByCurrentUser === numPrimarySlots) {
                                    // REMOVED: console.log("DEBUG MAP: Path C3a for " + resource.name + ". Assigning map-area-green.");
                                    finalClass = 'map-area-green';
                                    finalTitle += ' (Available)';
                                } else {
                                    // REMOVED: console.log("DEBUG MAP: Path C3b for " + resource.name + ". Assigning map-area-light-blue (User schedule conflicts).");
                                    finalClass = 'map-area-light-blue';
                                    finalTitle += ' (Unavailable - Your Schedule Conflicts)';
                                }
                            } else { // numGenerallyBooked > 0 && numGenerallyBooked < numPrimarySlots
                                // REMOVED: console.log("DEBUG MAP: Path C4 for " + resource.name + " (Generally partially available by others)");
                                if (numBookableByCurrentUser > 0) {
                                    // REMOVED: console.log("DEBUG MAP: Path C4a for " + resource.name + ". Assigning map-area-yellow.");
                                    finalClass = 'map-area-yellow';
                                    finalTitle += ' (Partially Available)';
                                } else {
                                    // REMOVED: console.log("DEBUG MAP: Path C4b for " + resource.name + ". Assigning map-area-light-blue (User schedule conflicts for remaining).");
                                    finalClass = 'map-area-light-blue';
                                    finalTitle += ' (Unavailable - Your Schedule Conflicts)';
                                }
                            }
                        }

                        if (finalClass === 'map-area-unknown') {
                             // REMOVED: console.warn("DEBUG MAP: Condition for " + resource.name + ": Fallback, unknown state. Assigning map-area-unknown.");
                             finalTitle += ' (Status Unknown)';
                        }

                        // REMOVED: console.log("DEBUG MAP: Final Class for " + resource.name + ":", finalClass, ". Final Title:", finalTitle);

                        areaDiv.className = 'resource-area';
                        areaDiv.classList.add(finalClass);
                        areaDiv.title = finalTitle;

                        let isMapAreaClickable = false;
                        if (finalClass === 'map-area-green' || finalClass === 'map-area-yellow') {
                            isMapAreaClickable = true;
                        }

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

    function handleFilterChange(source = 'map') {
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
            isSyncingDate = false; 
            return;
        }
        const mapToLoad = allMapInfo.find(map => map.location === selectedLocation && map.floor === selectedFloor);
        if (mapToLoad && mapToLoad.id) {
            loadMapDetails(mapToLoad.id, selectedDate).finally(() => { isSyncingDate = false; });
        } else {
            loadMapDetails(null, selectedDate).finally(() => { isSyncingDate = false; });
            if (mapLoadingStatusDiv && selectedLocation && selectedFloor) {
                 showError(mapLoadingStatusDiv, 'No map found for the selected location and floor combination.');
            } else if (mapLoadingStatusDiv) {
                 showSuccess(mapLoadingStatusDiv, 'Please complete location and floor selection.');
            }
        }
    }

    async function loadAvailableMaps() {
        if (!mapLocationSelect || !mapFloorSelect || !mapLoadingStatusDiv) {
            console.error("One or more critical map control elements are missing from the DOM."); // Keep this error
            updateMapLoadingStatus("Map interface error. Please contact support.", true);
            disableMapSelectors();
            return;
        }
        updateMapLoadingStatus("Loading available maps...", false);
        try {
            const response = await fetch('/api/admin/maps');
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
                updateMapLoadingStatus('No maps configured.', false);
                disableMapSelectors();
                return;
            }
            const locations = [...new Set(allMapInfo.map(map => map.location).filter(loc => loc))].sort();
            if (mapLocationSelect) {
                mapLocationSelect.innerHTML = '<option value="">-- Select Location --</option>';
                if (locations.length > 0) {
                    locations.forEach(location => mapLocationSelect.add(new Option(location, location)));
                    mapLocationSelect.disabled = false;
                } else {
                    mapLocationSelect.innerHTML = '<option value="">-- No Locations --</option>';
                    mapLocationSelect.disabled = true;
                }
            }
            if (mapFloorSelect) {
                mapFloorSelect.innerHTML = '<option value="">-- Select Floor --</option>';
                mapFloorSelect.disabled = true;
            }
            if (mapLocationSelect) mapLocationSelect.addEventListener('change', () => { updateFloorSelectOptions(); handleFilterChange('map'); });
            if (mapFloorSelect) mapFloorSelect.addEventListener('change', () => handleFilterChange('map'));
            if (mapAvailabilityDateInput) mapAvailabilityDateInput.addEventListener('change', () => handleFilterChange('map'));
            if (mainBookingFormDateInput) mainBookingFormDateInput.addEventListener('change', () => handleFilterChange('form'));
            if (resourceSelectBooking) resourceSelectBooking.addEventListener('change', highlightSelectedResourceOnMap);
            
            if (mapLoadingStatusDiv && !mapLoadingStatusDiv.classList.contains('error') && !mapLoadingStatusDiv.classList.contains('success')) {
                updateMapLoadingStatus('Please select a location and floor to see the map.', false);
            }
            highlightSelectedResourceOnMap(); 
        } catch (error) {
            updateMapLoadingStatus('Could not load map options. Network or server error.', true);
            disableMapSelectors();
        }
    }

    if (mapContainer) {
        loadAvailableMaps();
        document.addEventListener('refreshNewBookingMap', function(event) {
            // console.log('refreshNewBookingMap event received in new_booking_map.js, reloading map details.'); // Keep this
            if (currentMapId && mapAvailabilityDateInput) {
                loadMapDetails(currentMapId, mapAvailabilityDateInput.value);
            } else {
                console.warn('Cannot refresh new_booking_map: currentMapId or mapAvailabilityDateInput is not set.'); // Keep this
            }
        });
    } else {
        // console.log("New booking map container not found on this page. Map script not initialized."); // Keep this
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
                button.classList.remove('time-slot-available', 'time-slot-booked', 'time-slot-user-busy', 'selected', 'time-slot-selected');
                button.disabled = false;
                button.textContent = slot.label;
                button.title = '';
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
                            selectedTimeSlotForNewBooking = { startTimeStr: slot.startTime, endTimeStr: slot.endTime };
                            if (modalStatusMessageP) modalStatusMessageP.textContent = '';
                            if (mainFormStartTimeInput) mainFormStartTimeInput.value = slot.startTime;
                            if (mainFormEndTimeInput) mainFormEndTimeInput.value = slot.endTime;
                        });
                    }
                }
                modalTimeSlotsListDiv.appendChild(button);
            });
            const firstHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="first_half"]');
            const secondHalfBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="second_half"]');
            const fullDayBtn = modalTimeSlotsListDiv.querySelector('[data-slot-id="full_day"]');
            if (fullDayBtn && firstHalfBtn && secondHalfBtn) {
                const isFullDayGenerallyBooked = fullDayBtn.classList.contains('time-slot-booked');
                if (!isFullDayGenerallyBooked) {
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
                    if (currentMapId && mapAvailabilityDateInput) {
                        loadMapDetails(currentMapId, mapAvailabilityDateInput.value);
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

