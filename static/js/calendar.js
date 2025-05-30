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
        console.log("customEventDrop triggered", info);
        const event = info.event;
        const oldEventStart = info.oldEvent.start;

        let resourceId = event.extendedProps && event.extendedProps.resource_id ? event.extendedProps.resource_id : null;
        // The event object from FullCalendar might store resource associations differently.
        // Trying a common way to get associated resource ID if not directly in extendedProps.
        if (!resourceId && typeof event.getResources === 'function') {
            const resources = event.getResources();
            if (resources.length > 0) {
                resourceId = resources[0].id; // Assuming one resource per event for simplicity
            }
        }
        // If resource_id was mapped directly to event root by the event source function:
        if (!resourceId && event.resource_id) {
            resourceId = event.resource_id;
        }


        console.log("Event resource ID for drop:", resourceId);

        if (!resourceId) {
            console.error("Resource ID not found for the event. Reverting drop.");
            alert("Could not identify the resource for this booking. Operation cancelled.");
            info.revert();
            return;
        }
        
        if (event.start.toDateString() === oldEventStart.toDateString()) {
            console.log("Event dropped on the same day. Applying standard handleEventChange (time change only).");
            handleEventChange(info); // Standard handling for same-day time changes
            return;
        }

        const newDateStr = event.start.toISOString().split('T')[0]; // YYYY-MM-DD
        const existingBookingsOnNewDate = await getResourceAvailabilityClientSide(resourceId, newDateStr);
        
        // Duration of the original event
        const originalDurationMs = (info.oldEvent.end || oldEventStart) - oldEventStart;

        // Determine original event type more robustly
        const oldDateStr = oldEventStart.toISOString().split('T')[0];
        const oldDateMorningStart = createDateAsUTC(oldDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const oldDateMorningEnd = createDateAsUTC(oldDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const oldDateAfternoonStart = createDateAsUTC(oldDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const oldDateAfternoonEnd = createDateAsUTC(oldDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);

        let originalEventType = 'custom'; // default to custom
        const oldEventEnd = info.oldEvent.end || oldEventStart; // Handle null end time

        if (oldEventStart.getTime() === oldDateMorningStart.getTime() && oldEventEnd.getTime() === oldDateMorningEnd.getTime()) {
            originalEventType = 'morning';
        } else if (oldEventStart.getTime() === oldDateAfternoonStart.getTime() && oldEventEnd.getTime() === oldDateAfternoonEnd.getTime()) {
            originalEventType = 'afternoon';
        } else if (oldEventStart.getTime() === oldDateMorningStart.getTime() && oldEventEnd.getTime() === oldDateAfternoonEnd.getTime()) { // Covers full day
            originalEventType = 'fullday';
        }
        console.log("Original event type:", originalEventType);

        const newDateMorningStart = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const newDateMorningEnd = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const newDateAfternoonStart = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
        const newDateAfternoonEnd = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);
        const newDateFullDayStart = newDateMorningStart;
        const newDateFullDayEnd = newDateAfternoonEnd;

        let targetStart = null;
        let targetEnd = null;

        const isSlotFree = (slotStart, slotEnd, bookings) => {
            for (const booking of bookings) {
                if (!booking.start_time || !booking.end_time) {
                    console.warn("Skipping booking with invalid time:", booking);
                    continue;
                }
                const bookingStart = createDateAsUTC(newDateStr, booking.start_time.substring(0, 5));
                const bookingEnd = createDateAsUTC(newDateStr, booking.end_time.substring(0, 5));
                if (slotStart < bookingEnd && slotEnd > bookingStart) {
                    return false; 
                }
            }
            return true;
        };
        
        if (originalEventType === 'morning' || originalEventType === 'afternoon') {
            if (isSlotFree(newDateMorningStart, newDateMorningEnd, existingBookingsOnNewDate)) {
                targetStart = newDateMorningStart;
                targetEnd = newDateMorningEnd;
                console.log("Snapped to new morning slot");
            } else if (isSlotFree(newDateAfternoonStart, newDateAfternoonEnd, existingBookingsOnNewDate)) {
                targetStart = newDateAfternoonStart;
                targetEnd = newDateAfternoonEnd;
                console.log("Snapped to new afternoon slot");
            }
        } else if (originalEventType === 'fullday') {
            if (isSlotFree(newDateFullDayStart, newDateFullDayEnd, existingBookingsOnNewDate)) {
                 targetStart = newDateFullDayStart;
                 targetEnd = newDateFullDayEnd;
                 console.log("Snapped to new full day slot");
            }
        } else { // originalEventType is 'custom'
            const customDurationHours = originalDurationMs / (1000 * 60 * 60);
            if (customDurationHours <= (MORNING_SLOT_END_HOUR - MORNING_SLOT_START_HOUR + 0.5)) { 
                 if (isSlotFree(newDateMorningStart, newDateMorningEnd, existingBookingsOnNewDate)) {
                    targetStart = newDateMorningStart;
                    targetEnd = new Date(newDateMorningStart.getTime() + originalDurationMs);
                    if(targetEnd > newDateMorningEnd) targetEnd = newDateMorningEnd; 
                } else if (isSlotFree(newDateAfternoonStart, newDateAfternoonEnd, existingBookingsOnNewDate)) {
                    targetStart = newDateAfternoonStart;
                    targetEnd = new Date(newDateAfternoonStart.getTime() + originalDurationMs);
                    if(targetEnd > newDateAfternoonEnd) targetEnd = newDateAfternoonEnd;
                }
            } else { 
                 if (isSlotFree(newDateFullDayStart, newDateFullDayEnd, existingBookingsOnNewDate)) {
                    targetStart = newDateFullDayStart;
                    const potentialEnd = new Date(newDateFullDayStart.getTime() + originalDurationMs);
                    targetEnd = potentialEnd > newDateFullDayEnd ? newDateFullDayEnd : potentialEnd;
                 }
            }
            if(targetStart) console.log("Custom duration event, attempted to fit.");
        }

        if (targetStart && targetEnd) {
            // For FC4/older or compatibility:
            info.event.start = targetStart;
            info.event.end = targetEnd;

            console.log(`Event ${event.id} moved to ${newDateStr}. New start: ${targetStart.toISOString()}, New end: ${targetEnd.toISOString()}`);
            handleEventChange(info);
        } else {
            alert('The selected date does not have a suitable available slot for this booking. Reverting.');
            info.revert();
        }
    }

    async function customEventResize(info) {
        console.log("customEventResize triggered", info);
        const event = info.event;

        let resourceId = event.extendedProps && event.extendedProps.resource_id ? event.extendedProps.resource_id : null;
         if (!resourceId && typeof event.getResources === 'function') {
            const resources = event.getResources();
            if (resources.length > 0) resourceId = resources[0].id;
        }
        if (!resourceId && event.resource_id) {
            resourceId = event.resource_id;
        }
        console.log("Event resource ID for resize:", resourceId);

        if (!resourceId) {
            console.error("Resource ID not found. Reverting resize.");
            alert("Could not identify the resource for this booking. Operation cancelled.");
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
                                let resourceId = b.resource_id;
                                if (resourceId === undefined && b.extendedProps && b.extendedProps.resource_id !== undefined) {
                                    resourceId = b.extendedProps.resource_id;
                                } else if (resourceId === undefined && b.resourceId !== undefined) {
                                    resourceId = b.resourceId;
                                }
                                // Ensure extendedProps exists
                                const extendedProps = b.extendedProps || {};
                                return {
                                    ...b, // Spread booking properties
                                    resource_id: resourceId, // Standardized top-level access
                                    // Ensure isActualBooking is set, and preserve other extendedProps
                                    extendedProps: { ...extendedProps, resource_id: resourceId, isActualBooking: true }
                                };
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
