document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    if (!calendarEl || !calendarResourceSelect) {
        console.error("Calendar element or resource select dropdown not found.");
        return;
    }

    let allUserEvents = []; // Store all user bookings

    const MORNING_SLOT_START_HOUR = 8;
    const MORNING_SLOT_END_HOUR = 12;
    const AFTERNOON_SLOT_START_HOUR = 13;
    const AFTERNOON_SLOT_END_HOUR = 17;
    // FULL_DAY is derived from these: 8:00 - 17:00

    // Helper to create Date objects in UTC from YYYY-MM-DD date string and HH:MM time string
    function createDateAsUTC(dateStr, timeStr) { // dateStr: YYYY-MM-DD, timeStr: HH:MM
        const [year, month, day] = dateStr.split('-').map(Number);
        const [hours, minutes] = timeStr.split(':').map(Number);
        return new Date(Date.UTC(year, month - 1, day, hours, minutes));
    }

    async function getResourceAvailabilityClientSide(resourceId, dateString) { // dateString YYYY-MM-DD
        if (!resourceId) {
            console.error("getResourceAvailabilityClientSide: resourceId is undefined or null. This can happen if the event object doesn't have resource_id set.");
            // Attempt to get selected resource from dropdown as a fallback if applicable to context
            // const selectedResource = calendarResourceSelect.value;
            // if(selectedResource && selectedResource !== 'all') resourceId = selectedResource;
            // else {
            //     console.error("No specific resource selected or event has no resource_id.");
            //     return [];
            // }
             return []; // Prevent further errors
        }
        try {
            // Uses the global apiCall function defined elsewhere (assuming it's available)
            const bookedSlots = await apiCall(`/api/resources/${resourceId}/availability?date=${dateString}`);
            return bookedSlots || []; // Ensure it's always an array
        } catch (error) {
            console.error(`Error fetching availability for resource ${resourceId} on ${dateString}:`, error);
            return []; // Return empty on error to prevent cascading failures
        }
    }


    async function populateResourceSelector() {
        try {
            // Call the new endpoint to get resources booked by the current user
            const resources = await apiCall('/api/bookings/my_booked_resources');
            // Keep the "-- All My Booked Resources --" option, clear others
            const firstOption = calendarResourceSelect.options[0];
            calendarResourceSelect.innerHTML = '';
            calendarResourceSelect.add(firstOption);

            if (resources && resources.length > 0) {
                resources.forEach(resource => {
                    // Displaying all booked resources regardless of their current status for selection
                    const option = new Option(`${resource.name} (Status: ${resource.status}, Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                    calendarResourceSelect.add(option);
                });
                calendarResourceSelect.disabled = false;
            } else {
                // If no other resources, it will just have the "All" option
            }
        } catch (error) {
            console.error('Error fetching resources for calendar selector:', error);
            calendarResourceSelect.options[0].text = '-- Error loading resources --';
        }
    }

    // generateAvailableSlots function is removed

    // Forward declaration for handleEventChange
    let handleEventChange;

    async function customEventDrop(info) {
        // --- Added Detailed Logging ---
        console.log('customEventDrop - Full event object received:', JSON.parse(JSON.stringify(info.event)));
        if (info.event.extendedProps) {
            console.log('customEventDrop - info.event.extendedProps:', JSON.parse(JSON.stringify(info.event.extendedProps)));
        } else {
            console.log('customEventDrop - info.event.extendedProps: undefined');
        }
        // getResources() might not exist on all event objects or FC versions, check existence.
        if (typeof info.event.getResources === 'function') {
            console.log('customEventDrop - info.event.getResources():', info.event.getResources().map(r => ({id: r.id, title: r.title})));
        } else {
            console.log('customEventDrop - info.event.getResources(): method does not exist');
        }
        console.log('customEventDrop - info.event.resource_id (top-level):', info.event.resource_id);
        // --- End of Added Detailed Logging ---

        const event = info.event;
        const oldEventStart = info.oldEvent.start;

        // Improved resourceId retrieval
        let resourceId = null;
        if (event.extendedProps && event.extendedProps.resource_id) {
            resourceId = event.extendedProps.resource_id;
            console.log('customEventDrop - Resource ID from extendedProps:', resourceId);
        } else if (event.resource_id) { 
            resourceId = event.resource_id;
            console.log('customEventDrop - Resource ID from top-level event.resource_id:', resourceId);
        } else if (typeof event.getResources === 'function') { 
            const resources = event.getResources();
            if (resources.length > 0) {
                resourceId = resources[0].id;
                console.log('customEventDrop - Resource ID from event.getResources():', resourceId);
            }
        }

        // This console.log is now more of a summary after specific attempts
        console.log('customEventDrop: final retrieved resourceId after checks:', resourceId);

        if (!resourceId) {
            console.error('customEventDrop: Could not identify resource for event (final check):', JSON.parse(JSON.stringify(event)));
            alert('Could not identify the resource for this booking. Operation cancelled.');
            info.revert();
            return;
        }
        
        // Add temporary log at the beginning of the function (already done above effectively)
        console.log("customEventDrop triggered for event ID:", event.id, "Attempting to move to resource:", resourceId);

        // Determine the date string for the drop.
        // event.start already reflects the drop time.
        const newDateStr = event.start.toISOString().split('T')[0];
        
        // Fetch existing bookings for the target date (could be same day or new day)
        // For same-day drags, this list will include the event being dragged itself.
        const existingBookingsOnDate = await getResourceAvailabilityClientSide(resourceId, newDateStr);
        
        const originalDurationMs = (info.oldEvent.end || oldEventStart) - oldEventStart;

        // oldEventStart is from info.oldEvent.start, so it's the original start date/time
        const oldDateStr = oldEventStart.toISOString().split('T')[0]; 
        const oldDateMorningStart = createDateAsUTC(oldDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const oldDateMorningEnd = createDateAsUTC(oldDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const oldDateAfternoonStart = createDateAsUTC(oldDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const oldDateAfternoonEnd = createDateAsUTC(oldDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);

        let originalEventType = 'custom';
        const oldEventEnd = info.oldEvent.end || oldEventStart;
        if (oldEventStart.getTime() === oldDateMorningStart.getTime() && oldEventEnd.getTime() === oldDateMorningEnd.getTime()) {
            originalEventType = 'morning';
        } else if (oldEventStart.getTime() === oldDateAfternoonStart.getTime() && oldEventEnd.getTime() === oldDateAfternoonEnd.getTime()) {
            originalEventType = 'afternoon';
        } else if (oldEventStart.getTime() === oldDateMorningStart.getTime() && oldEventEnd.getTime() === oldDateAfternoonEnd.getTime()) {
            originalEventType = 'fullday';
        }
        console.log("customEventDrop: Original event type:", originalEventType);

        const newDateMorningStart = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const newDateMorningEnd = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const newDateAfternoonStart = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const newDateAfternoonEnd = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const newDateFullDayStart = newDateMorningStart;
        const newDateFullDayEnd = newDateAfternoonEnd;

        let targetStart = null;
        let targetEnd = null;

        // Pass event.id to isSlotCompletelyFree to ignore self-collision in same-day drags
        const isSlotCompletelyFree = (slotStart, slotEnd, bookings, eventIdToIgnore) => {
            console.log(`customEventDrop: Checking availability for slot: ${slotStart.toISOString()} - ${slotEnd.toISOString()}, ignoring event ID: ${eventIdToIgnore}`);
            for (const booking of bookings) {
                // booking.id is from the API, which corresponds to FullCalendar's event.id if mapped correctly
                if (String(booking.booking_id) === String(eventIdToIgnore)) { 
                    console.log(`customEventDrop: Skipping self-check for event ID: ${eventIdToIgnore}`);
                    continue;
                }
                if (!booking.start_time || !booking.end_time) {
                    console.warn("customEventDrop: Skipping booking with invalid time in isSlotCompletelyFree check:", booking);
                    continue;
                }
                const bookingStart = createDateAsUTC(newDateStr, booking.start_time.substring(0, 5)); 
                const bookingEnd = createDateAsUTC(newDateStr, booking.end_time.substring(0, 5));   
                
                if (slotStart < bookingEnd && slotEnd > bookingStart) {
                    console.log(`customEventDrop: Slot conflict found with existing booking: ${booking.title} (${bookingStart.toISOString()} - ${bookingEnd.toISOString()})`);
                    return false; 
                }
            }
            console.log(`customEventDrop: Slot IS completely free.`);
            return true;
        };
        
        let triedAlternative = false;

        if (originalEventType === 'morning') {
            console.log("customEventDrop: Original event is 'morning'. Checking morning slot on new date.");
            if (isSlotCompletelyFree(newDateMorningStart, newDateMorningEnd, existingBookingsOnDate, event.id)) {
                targetStart = newDateMorningStart;
                targetEnd = newDateMorningEnd;
            } else {
                triedAlternative = true;
                console.log("customEventDrop: Morning slot taken. Checking afternoon slot on new date.");
                if (isSlotCompletelyFree(newDateAfternoonStart, newDateAfternoonEnd, existingBookingsOnDate, event.id)) {
                    targetStart = newDateAfternoonStart;
                    targetEnd = newDateAfternoonEnd;
                }
            }
        } else if (originalEventType === 'afternoon') {
            console.log("customEventDrop: Original event is 'afternoon'. Checking afternoon slot on new date.");
            if (isSlotCompletelyFree(newDateAfternoonStart, newDateAfternoonEnd, existingBookingsOnDate, event.id)) {
                targetStart = newDateAfternoonStart;
                targetEnd = newDateAfternoonEnd;
            } else {
                triedAlternative = true;
                console.log("customEventDrop: Afternoon slot taken. Checking morning slot on new date.");
                if (isSlotCompletelyFree(newDateMorningStart, newDateMorningEnd, existingBookingsOnDate, event.id)) {
                    targetStart = newDateMorningStart;
                    targetEnd = newDateMorningEnd;
                }
            }
        } else if (originalEventType === 'fullday') {
            console.log("customEventDrop: Original event is 'fullday'. Checking full day slot on new date.");
            if (isSlotCompletelyFree(newDateFullDayStart, newDateFullDayEnd, existingBookingsOnDate, event.id)) {
                 targetStart = newDateFullDayStart;
                 targetEnd = newDateFullDayEnd;
            }
        } else { 
            const morningSlotDuration = MORNING_SLOT_END_HOUR - MORNING_SLOT_START_HOUR; 
            const customDurationHours = originalDurationMs / (1000 * 60 * 60);
            console.log(`customEventDrop: Original event is 'custom' with duration ~${customDurationHours.toFixed(1)}h.`);

            if (customDurationHours <= morningSlotDuration) {
                console.log("customEventDrop: Custom event duration fits a half-day slot. Checking morning slot.");
                if (isSlotCompletelyFree(newDateMorningStart, newDateMorningEnd, existingBookingsOnDate, event.id)) {
                    targetStart = newDateMorningStart;
                    targetEnd = newDateMorningEnd; 
                } else {
                    triedAlternative = true;
                    console.log("customEventDrop: Morning slot taken for custom event. Checking afternoon slot.");
                    if (isSlotCompletelyFree(newDateAfternoonStart, newDateAfternoonEnd, existingBookingsOnDate, event.id)) {
                        targetStart = newDateAfternoonStart;
                        targetEnd = newDateAfternoonEnd; 
                    }
                }
            }
            if (!targetStart && customDurationHours <= (AFTERNOON_SLOT_END_HOUR - MORNING_SLOT_START_HOUR)) { 
                 console.log("customEventDrop: Custom event trying full day slot (either too long for half or half-day failed).");
                 if (isSlotCompletelyFree(newDateFullDayStart, newDateFullDayEnd, existingBookingsOnDate, event.id)) {
                    targetStart = newDateFullDayStart;
                    targetEnd = newDateFullDayEnd; 
                 }
            }
        }

        if (targetStart && targetEnd) {
            info.event.start = targetStart;
            info.event.end = targetEnd;
            const decisionMsg = triedAlternative ? `Original slot was unavailable, successfully moved to alternative slot.` : `Successfully moved to target slot.`;
            console.log(`customEventDrop: Final decision - ALLOW. ${decisionMsg} New times: ${targetStart.toISOString()} - ${targetEnd.toISOString()}`);
            handleEventChange(info);
        } else {
            console.log(`customEventDrop: Final decision - REVERT. No suitable standard slot available on ${newDateStr}.`);
            alert('The selected time slot is not available or does not align with standard booking slots (Morning, Afternoon, Full Day). Reverting.');
            info.revert();
        }
    }

    async function customEventResize(info) {
        const event = info.event;

        // Improved resourceId retrieval with logging
        let resourceId = null;
        if (event.extendedProps && event.extendedProps.resource_id) {
            resourceId = event.extendedProps.resource_id;
        } else if (event.resource_id) {
            resourceId = event.resource_id;
        } else if (typeof event.getResources === 'function') {
            const resources = event.getResources();
            if (resources.length > 0) {
                resourceId = resources[0].id;
            }
        }
        
        console.log('customEventResize: event object:', JSON.parse(JSON.stringify(event)));
        console.log('customEventResize: retrieved resourceId:', resourceId);

        if (!resourceId) {
            console.error('customEventResize: Could not identify resource for event:', JSON.parse(JSON.stringify(event)));
            alert('Could not identify the resource for this booking. Operation cancelled.');
            info.revert();
            return;
        }

        const eventDateStr = event.start.toISOString().split('T')[0];
        const existingBookingsOnDate = await getResourceAvailabilityClientSide(resourceId, eventDateStr);
        
        const dateMorningStart = createDateAsUTC(eventDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const dateMorningEnd = createDateAsUTC(eventDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const dateAfternoonStart = createDateAsUTC(eventDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const dateAfternoonEnd = createDateAsUTC(eventDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const dateFullDayStart = dateMorningStart;
        const dateFullDayEnd = dateAfternoonEnd;

        const isSlotFree = (slotStart, slotEnd, bookings) => { // Simplified for resize, not excluding current event perfectly yet
            for (const booking of bookings) {
                 // Check if the booking from API (which has booking_id) is the same as the event being resized (event.id from FullCalendar)
                if (String(booking.booking_id) === String(event.id)) {
                    continue; // Don't check against self
                }
                if (!booking.start_time || !booking.end_time) continue;
                const bookingStart = createDateAsUTC(eventDateStr, booking.start_time.substring(0,5));
                const bookingEnd = createDateAsUTC(eventDateStr, booking.end_time.substring(0,5));
                if (slotStart < bookingEnd && slotEnd > bookingStart) return false;
            }
            return true;
        };

        const newStart = event.start; // Already reflects the resize attempt
        const newEnd = event.end;

        const isResizedToFullDay = (newStart <= dateFullDayStart && newEnd >= dateFullDayEnd);
        const isOriginalHalfDayMorning = (info.oldEvent.start >= dateMorningStart && info.oldEvent.end <= dateMorningEnd);
        const isOriginalHalfDayAfternoon = (info.oldEvent.start >= dateAfternoonStart && info.oldEvent.end <= dateAfternoonEnd);

        if (isResizedToFullDay && (isOriginalHalfDayMorning || isOriginalHalfDayAfternoon)) {
            let otherHalfIsFree = false;
            if (isOriginalHalfDayMorning) {
                otherHalfIsFree = isSlotFree(dateAfternoonStart, dateAfternoonEnd, existingBookingsOnDate);
            } else {
                otherHalfIsFree = isSlotFree(dateMorningStart, dateMorningEnd, existingBookingsOnDate);
            }

            if (otherHalfIsFree) {
                // event.setStart(dateFullDayStart); // FC5
                // event.setEnd(dateFullDayEnd); // FC5
                info.event.start = dateFullDayStart;
                info.event.end = dateFullDayEnd;
                console.log(`Event ${event.id} resized to full day: ${dateFullDayStart.toISOString()} - ${dateFullDayEnd.toISOString()}`);
                handleEventChange(info);
            } else {
                alert('Cannot resize to full day because the other half of the day is booked. Reverting.');
                info.revert();
            }
        } else if (newStart.getUTCHours() === MORNING_SLOT_START_HOUR && newStart.getUTCMinutes() === 0 &&
                   newEnd.getUTCHours() === MORNING_SLOT_END_HOUR && newEnd.getUTCMinutes() === 0) {
            console.log(`Event ${event.id} resized to morning slot.`);
            handleEventChange(info);
        } else if (newStart.getUTCHours() === AFTERNOON_SLOT_START_HOUR && newStart.getUTCMinutes() === 0 &&
                   newEnd.getUTCHours() === AFTERNOON_SLOT_END_HOUR && newEnd.getUTCMinutes() === 0) {
            console.log(`Event ${event.id} resized to afternoon slot.`);
            handleEventChange(info);
        } else {
            alert('Invalid resize. Bookings can only be full day, morning, or afternoon, or extended from half to full if available. Reverting.');
            info.revert();
        }
    }


    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        editable: true,
        eventDrop: customEventDrop, // Use custom handler
        eventResize: customEventResize, // Use custom handler
        eventSources: [
            {
                id: 'actualBookings',
                events: function(fetchInfo, successCallback, failureCallback) {
                    if (allUserEvents.length > 0 /* && !fetchInfo.force */) {
                        const selectedResourceId = calendarResourceSelect.value;
                        let eventsToDisplay = (selectedResourceId === 'all' || !selectedResourceId)
                            ? allUserEvents
                            : allUserEvents.filter(event => String(event.resource_id) === String(selectedResourceId));
                        console.log('Using cached allUserEvents, filtered for:', selectedResourceId, eventsToDisplay.length);
                        successCallback(eventsToDisplay);
                        return;
                    }

                    apiCall('/api/bookings/calendar')
                        .then(bookings => {
                            allUserEvents = bookings.map(b => {
                                // b.resource_id should now be directly from the API
                                const apiResourceId = b.resource_id; 
                                
                                console.log('Mapping booking to event. Raw booking data:', JSON.parse(JSON.stringify(b)));

                                // Ensure extendedProps exists, initialize if not
                                const extendedProps = b.extendedProps || {};
                                extendedProps.isActualBooking = true; // Mark as an actual booking
                                extendedProps.resource_id = apiResourceId; // Ensure resource_id is in extendedProps

                                const eventObject = {
                                    ...b, // Spread booking properties (id, title, start, end, recurrence_rule, and now resource_id)
                                    resource_id: apiResourceId, // Ensure top-level access for convenience
                                    extendedProps: extendedProps 
                                };
                                
                                console.log('Created event object. Resource ID:', eventObject.resource_id, 'ExtendedProps Resource ID:', eventObject.extendedProps.resource_id);
                                return eventObject;
                            });
                            console.log('Fetched and cached allUserEvents:', allUserEvents.length);
                            const selectedResourceId = calendarResourceSelect.value;
                             let eventsToDisplay = (selectedResourceId === 'all' || !selectedResourceId)
                                ? allUserEvents
                                : allUserEvents.filter(event => String(event.resource_id) === String(selectedResourceId));
                            console.log('Displaying events for:', selectedResourceId, eventsToDisplay.length);
                            successCallback(eventsToDisplay);
                        })
                        .catch(error => {
                            console.error('Error fetching user bookings for calendar:', error);
                            allUserEvents = [];
                            failureCallback(error);
                        });
                }
            }
        ],
        eventOrder: function(a, b) {
            if (a.extendedProps && a.extendedProps.isActualBooking) return 1;
            if (b.extendedProps && b.extendedProps.isActualBooking) return -1;
            return 0;
        },
        eventContent: function(arg) {
            if (arg.view.type === 'dayGridMonth') {
                let eventHtml = `<b>${arg.event.title}</b>`;
                if (arg.event.start) {
                    const startTime = arg.event.start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                    const endTime = arg.event.end ? arg.event.end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
                    if (!arg.event.allDay || (startTime !== '00:00' || (endTime && endTime !== '00:00'))) {
                         eventHtml += `<br>${startTime}${endTime && endTime !== startTime ? ' - ' + endTime : ''}`;
                    }
                }
                return { html: eventHtml };
            }
            return { html: `<b>${arg.event.title}</b>` };
        }
    });

    calendar.render();

    handleEventChange = async function(info) { // Assign to the forward-declared variable
        // Ensure extendedProps exists before trying to access isActualBooking
        if (!info.event.extendedProps || !info.event.extendedProps.isActualBooking) {
            console.log('Attempted to modify a non-booking event. Reverting.');
            info.revert();
            return;
        }

        const event = info.event;
        console.log(`Calling API to update booking ${event.id}: Start: ${event.start.toISOString()}, End: ${event.end ? event.end.toISOString() : 'N/A'}`);
        try {
            await apiCall(`/api/bookings/${event.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_time: event.start.toISOString(),
                    // Ensure end_time is also sent, use start_time if event.end is null (e.g. for all-day events in some FC versions)
                    end_time: event.end ? event.end.toISOString() : event.start.toISOString(),
                    title: event.title // Persist title changes if any future modification allows it
                })
            });
            console.log(`Booking ${event.id} updated successfully.`);
            // calendar.refetchEvents(); // Or more targeted refetch if possible
        } catch (e) {
            console.error('Failed to update booking time via API:', e);
            alert(`Error updating booking: ${e.message || 'Server error'}. Reverting.`);
            info.revert();
        }
    }


    if (calendarResourceSelect) {
        calendarResourceSelect.addEventListener('change', () => {
            const actualBookingsSource = calendar.getEventSourceById('actualBookings');
            if (actualBookingsSource) {
                allUserEvents = []; // Clear cache before refetching for different resource
                actualBookingsSource.refetch();
            }
        });
    }

    populateResourceSelector();
});
