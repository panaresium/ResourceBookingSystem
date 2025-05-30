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

    function createDateAsUTC(dateStr, timeStr) { // dateStr: YYYY-MM-DD, timeStr: HH:MM
        const [year, month, day] = dateStr.split('-').map(Number);
        const [hours, minutes] = timeStr.split(':').map(Number);
        return new Date(Date.UTC(year, month - 1, day, hours, minutes));
    }

    async function getResourceAvailabilityClientSide(resourceId, dateString) { 
        if (!resourceId) {
            console.error("getResourceAvailabilityClientSide: resourceId is undefined or null.");
            return []; 
        }
        try {
            const bookedSlots = await apiCall(`/api/resources/${resourceId}/availability?date=${dateString}`);
            return bookedSlots || []; 
        } catch (error) {
            console.error(`Error fetching availability for resource ${resourceId} on ${dateString}:`, error);
            return []; 
        }
    }

    async function populateResourceSelector() {
        try {
            const resources = await apiCall('/api/bookings/my_booked_resources'); // UPDATED
            const firstOption = calendarResourceSelect.options[0];
            calendarResourceSelect.innerHTML = '';
            calendarResourceSelect.add(firstOption);

            if (resources && resources.length > 0) {
                resources.forEach(resource => {
                    // Displaying all booked resources, not just 'published'
                    const option = new Option(`${resource.name} (Status: ${resource.status}, Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                    calendarResourceSelect.add(option);
                });
                calendarResourceSelect.disabled = false;
            } else {
                // No other resources, only "All My Booked Resources"
            }
        } catch (error) {
            console.error('Error fetching resources for calendar selector:', error);
            calendarResourceSelect.options[0].text = '-- Error loading resources --';
        }
    }

    let handleEventChange; // Forward declared
    let customEventDrop;
    let customEventResize;

    customEventDrop = async function(info) {
        console.log('customEventDrop - Full event object received:', JSON.parse(JSON.stringify(info.event)));
        if (info.event.extendedProps) {
            console.log('customEventDrop - info.event.extendedProps:', JSON.parse(JSON.stringify(info.event.extendedProps)));
        } else {
            console.log('customEventDrop - info.event.extendedProps: undefined');
        }
        if (typeof info.event.getResources === 'function') {
            console.log('customEventDrop - info.event.getResources():', info.event.getResources().map(r => ({id: r.id, title: r.title})));
        } else {
            console.log('customEventDrop - info.event.getResources(): method does not exist');
        }
        console.log('customEventDrop - info.event.resource_id (top-level):', info.event.resource_id);

        const event = info.event;
        const oldEventStart = info.oldEvent.start;
        let resourceId = null;

        if (event.extendedProps && event.extendedProps.resource_id) {
            resourceId = event.extendedProps.resource_id;
        } else if (event.resource_id) {
            resourceId = event.resource_id;
        } else if (typeof event.getResources === 'function') {
            const resources = event.getResources();
            if (resources.length > 0) resourceId = resources[0].id;
        }
        console.log('customEventDrop: final retrieved resourceId after checks:', resourceId);

        if (!resourceId) {
            console.error('customEventDrop: Could not identify resource for event (final check):', JSON.parse(JSON.stringify(event)));
            alert('Could not identify the resource for this booking. Operation cancelled.');
            info.revert();
            return;
        }
        console.log("customEventDrop triggered for event ID:", event.id, "Resource ID:", resourceId);

        const newDateStr = event.start.toISOString().split('T')[0]; 
        const existingBookingsOnDate = await getResourceAvailabilityClientSide(resourceId, newDateStr);
        let targetStart = null;
        let targetEnd = null;
        let alertMessage = 'The selected time slot is not available or does not align with standard booking slots (Morning, Afternoon, Full Day). Reverting.';
        let triedAlternative = false; // Initialize here for broader scope, used in final logging
        
        const isSameDay = (event.start.toDateString() === oldEventStart.toDateString());
        console.log("customEventDrop: isSameDay:", isSameDay);

        const isSlotCompletelyFree = (slotStartUtc, slotEndUtc, bookings, eventIdToIgnore) => {
            console.log(`customEventDrop: Checking availability for UTC slot: ${slotStartUtc.toISOString()} - ${slotEndUtc.toISOString()}, ignoring event ID: ${eventIdToIgnore}`);
            for (const booking of bookings) {
                if (String(booking.booking_id) === String(eventIdToIgnore)) { 
                    console.log(`customEventDrop: Skipping self-check for event ID: ${eventIdToIgnore} (booking_id: ${booking.booking_id})`);
                    continue;
                }
                if (!booking.start_time || !booking.end_time) {
                    console.warn("customEventDrop: Skipping booking with invalid time:", booking);
                    continue;
                }
                const bookingStartUtc = createDateAsUTC(newDateStr, booking.start_time.substring(0, 5)); 
                const bookingEndUtc = createDateAsUTC(newDateStr, booking.end_time.substring(0, 5));   
                
                if (slotStartUtc < bookingEndUtc && slotEndUtc > bookingStartUtc) {
                    console.log(`customEventDrop: Slot conflict with existing booking: ${booking.title} (${bookingStartUtc.toISOString()} - ${bookingEndUtc.toISOString()})`);
                    return false; 
                }
            }
            console.log(`customEventDrop: Slot IS completely free (UTC).`);
            return true;
        };
        
        if (isSameDay) {
            console.log("customEventDrop: Handling same-day drag.");
            const dropHourLocal = info.event.start.getHours(); 
            let targetSlotType = (dropHourLocal < 12) ? 'morning' : 'afternoon'; 
            console.log('customEventDrop: Same-day drag: dropHour (local):', dropHourLocal, 'targetSlotType:', targetSlotType);

            let conceptualDayForLocalSlots = new Date(event.start); 
            let determinedTargetStartLocal = new Date(conceptualDayForLocalSlots);
            determinedTargetStartLocal.setHours(MORNING_SLOT_START_HOUR, 0, 0, 0);
            let determinedTargetEndLocal = new Date(conceptualDayForLocalSlots);
            determinedTargetEndLocal.setHours(MORNING_SLOT_END_HOUR, 0, 0, 0);

            if (targetSlotType === 'afternoon') {
                determinedTargetStartLocal.setHours(AFTERNOON_SLOT_START_HOUR, 0, 0, 0);
                determinedTargetEndLocal.setHours(AFTERNOON_SLOT_END_HOUR, 0, 0, 0);
            }
             console.log('customEventDrop: Same-day drag: conceptual determinedTargetStart (local):', determinedTargetStartLocal.toString(), 
                        'conceptual determinedTargetEnd (local):', determinedTargetEndLocal.toString());

            let targetStartUtcForCheck, targetEndUtcForCheck;
            if (targetSlotType === 'morning') {
                targetStartUtcForCheck = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
                targetEndUtcForCheck = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
            } else { 
                targetStartUtcForCheck = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
                targetEndUtcForCheck = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);
            }
            console.log('customEventDrop: Same-day drag: targetStartForCheck (UTC):', targetStartUtcForCheck.toISOString(), 
                        'targetEndForCheck (UTC):', targetEndUtcForCheck.toISOString());

            if (isSlotCompletelyFree(targetStartUtcForCheck, targetEndUtcForCheck, existingBookingsOnDate, event.id)) {
                targetStart = targetStartUtcForCheck; 
                targetEnd = targetEndUtcForCheck;
                console.log(`customEventDrop: Same-day drag: Snapping to ${targetSlotType} slot (UTC times set).`);
            } else {
                console.log(`customEventDrop: Same-day drag: Target ${targetSlotType} slot on ${newDateStr} is not available. Reverting.`);
                alertMessage = `The target ${targetSlotType} slot on ${newDateStr} (local times implied by drop) is not available. Reverting.`;
                targetStart = null; targetEnd = null; 
            }
        } else { 
            console.log("customEventDrop: Handling new-date drag.");
            const originalDurationMs = (info.oldEvent.end || oldEventStart) - oldEventStart;
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
            console.log("customEventDrop (new-date): Original event type:", originalEventType);

            const newDateMorningStartUtc = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_START_HOUR).padStart(2, '0')}:00`);
            const newDateMorningEndUtc = createDateAsUTC(newDateStr, `${String(MORNING_SLOT_END_HOUR).padStart(2, '0')}:00`);
            const newDateAfternoonStartUtc = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_START_HOUR).padStart(2, '0')}:00`);
            const newDateAfternoonEndUtc = createDateAsUTC(newDateStr, `${String(AFTERNOON_SLOT_END_HOUR).padStart(2, '0')}:00`);
            const newDateFullDayStartUtc = newDateMorningStartUtc;
            const newDateFullDayEndUtc = newDateAfternoonEndUtc;
            
            let triedAlternative = false;

            if (originalEventType === 'morning') {
                if (isSlotCompletelyFree(newDateMorningStartUtc, newDateMorningEndUtc, existingBookingsOnDate, event.id)) {
                    targetStart = newDateMorningStartUtc; targetEnd = newDateMorningEndUtc;
                } else {
                    triedAlternative = true;
                    if (isSlotCompletelyFree(newDateAfternoonStartUtc, newDateAfternoonEndUtc, existingBookingsOnDate, event.id)) {
                        targetStart = newDateAfternoonStartUtc; targetEnd = newDateAfternoonEndUtc;
                    }
                }
            } else if (originalEventType === 'afternoon') {
                if (isSlotCompletelyFree(newDateAfternoonStartUtc, newDateAfternoonEndUtc, existingBookingsOnDate, event.id)) {
                    targetStart = newDateAfternoonStartUtc; targetEnd = newDateAfternoonEndUtc;
                } else {
                    triedAlternative = true;
                    if (isSlotCompletelyFree(newDateMorningStartUtc, newDateMorningEndUtc, existingBookingsOnDate, event.id)) {
                        targetStart = newDateMorningStartUtc; targetEnd = newDateMorningEndUtc;
                    }
                }
            } else if (originalEventType === 'fullday') {
                if (isSlotCompletelyFree(newDateFullDayStartUtc, newDateFullDayEndUtc, existingBookingsOnDate, event.id)) {
                     targetStart = newDateFullDayStartUtc; targetEnd = newDateFullDayEndUtc;
                }
            } else { 
                const morningSlotDuration = MORNING_SLOT_END_HOUR - MORNING_SLOT_START_HOUR;
                const customDurationHours = originalDurationMs / (1000 * 60 * 60);
                if (customDurationHours <= morningSlotDuration) {
                    if (isSlotCompletelyFree(newDateMorningStartUtc, newDateMorningEndUtc, existingBookingsOnDate, event.id)) {
                        targetStart = newDateMorningStartUtc; targetEnd = newDateMorningEndUtc; 
                    } else {
                        triedAlternative = true;
                        if (isSlotCompletelyFree(newDateAfternoonStartUtc, newDateAfternoonEndUtc, existingBookingsOnDate, event.id)) {
                            targetStart = newDateAfternoonStartUtc; targetEnd = newDateAfternoonEndUtc; 
                        }
                    }
                }
                if (!targetStart && customDurationHours <= (AFTERNOON_SLOT_END_HOUR - MORNING_SLOT_START_HOUR)) { 
                     if (isSlotCompletelyFree(newDateFullDayStartUtc, newDateFullDayEndUtc, existingBookingsOnDate, event.id)) {
                        targetStart = newDateFullDayStartUtc; targetEnd = newDateFullDayEndUtc; 
                     }
                }
            }
             if (targetStart && triedAlternative) console.log(`customEventDrop (new-date): Original slot was unavailable, successfully moved to alternative slot.`);
             else if (targetStart) console.log(`customEventDrop (new-date): Successfully moved to target slot.`);
        }
        
        if (targetStart && targetEnd) {
            info.event.start = targetStart; 
            info.event.end = targetEnd;    
            const finalDecisionLogMessage = isSameDay ? 
                `Snapped to ${ (info.event.start.getUTCHours() < 12) ? 'morning' : 'afternoon'} slot on same day.` : 
                (triedAlternative ? `Original slot was unavailable, successfully moved to alternative slot.` : `Successfully moved to target slot.`);
            console.log(`customEventDrop: Final decision - ALLOW. ${finalDecisionLogMessage} New times (UTC): ${targetStart.toISOString()} - ${targetEnd.toISOString()}`);
            
            console.log('[customEventDrop] Valid placement determined. Calling handleEventChange. Event ID:', info.event.id, 
                        'New Start:', info.event.start ? info.event.start.toISOString() : 'null', 
                        'New End:', info.event.end ? info.event.end.toISOString() : 'null',
                        'Title:', info.event.title);
            handleEventChange(info);
        } else {
            console.log(`customEventDrop: Final decision - REVERT. No suitable standard slot available on ${newDateStr}.`);
            alert(alertMessage); 
            info.revert();
        }
    };

    customEventResize = async function(info) {
        const event = info.event;
        let resourceId = null;
        if (event.extendedProps && event.extendedProps.resource_id) {
            resourceId = event.extendedProps.resource_id;
        } else if (event.resource_id) {
            resourceId = event.resource_id;
        } else if (typeof event.getResources === 'function') {
            const resources = event.getResources();
            if (resources.length > 0) resourceId = resources[0].id;
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

        const isSlotFree = (slotStart, slotEnd, bookings) => { 
            for (const booking of bookings) {
                if (String(booking.booking_id) === String(event.id)) {
                    continue; 
                }
                if (!booking.start_time || !booking.end_time) continue;
                const bookingStart = createDateAsUTC(eventDateStr, booking.start_time.substring(0,5));
                const bookingEnd = createDateAsUTC(eventDateStr, booking.end_time.substring(0,5));
                if (slotStart < bookingEnd && slotEnd > bookingStart) return false;
            }
            return true;
        };

        const newStart = event.start; 
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
                info.event.start = dateFullDayStart;
                info.event.end = dateFullDayEnd;
                console.log(`Event ${event.id} resized to full day: ${dateFullDayStart.toISOString()} - ${dateFullDayEnd.toISOString()}`);
                console.log('[customEventResize] Valid resize. Calling handleEventChange. Event ID:', info.event.id, 
                            'New Start:', info.event.start ? info.event.start.toISOString() : 'null', 
                            'New End:', info.event.end ? info.event.end.toISOString() : 'null',
                            'Title:', info.event.title);
                handleEventChange(info);
            } else {
                alert('Cannot resize to full day because the other half of the day is booked. Reverting.');
                info.revert();
            }
        } else if (newStart.getUTCHours() === MORNING_SLOT_START_HOUR && newStart.getUTCMinutes() === 0 &&
                   newEnd.getUTCHours() === MORNING_SLOT_END_HOUR && newEnd.getUTCMinutes() === 0) {
            console.log(`Event ${event.id} resized to morning slot.`);
            console.log('[customEventResize] Valid resize. Calling handleEventChange. Event ID:', info.event.id, 
                        'New Start:', info.event.start ? info.event.start.toISOString() : 'null', 
                        'New End:', info.event.end ? info.event.end.toISOString() : 'null',
                        'Title:', info.event.title);
            handleEventChange(info);
        } else if (newStart.getUTCHours() === AFTERNOON_SLOT_START_HOUR && newStart.getUTCMinutes() === 0 &&
                   newEnd.getUTCHours() === AFTERNOON_SLOT_END_HOUR && newEnd.getUTCMinutes() === 0) {
            console.log(`Event ${event.id} resized to afternoon slot.`);
            console.log('[customEventResize] Valid resize. Calling handleEventChange. Event ID:', info.event.id, 
                        'New Start:', info.event.start ? info.event.start.toISOString() : 'null', 
                        'New End:', info.event.end ? info.event.end.toISOString() : 'null',
                        'Title:', info.event.title);
            handleEventChange(info);
        } else {
            alert('Invalid resize. Bookings can only be full day, morning, or afternoon, or extended from half to full if available. Reverting.');
            info.revert();
        }
    };

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
                    if (allUserEvents.length > 0 ) { 
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
                                const apiResourceId = b.resource_id; 
                                console.log('Mapping booking to event. Raw booking data:', JSON.parse(JSON.stringify(b)));
                                const extendedProps = b.extendedProps || {};
                                extendedProps.isActualBooking = true; 
                                extendedProps.resource_id = apiResourceId; 

                                const eventObject = {
                                    ...b, 
                                    resource_id: apiResourceId, 
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
        eventContent: function(arg) { // For month view time display
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

    handleEventChange = async function(info) { 
        console.log('[handleEventChange] Function called. Event ID:', info.event.id);
        if (!info.event.id) {
            console.error('[handleEventChange] CRITICAL: Event ID is missing. Cannot save.', info.event);
            alert('Error: Booking ID is missing, cannot save the change.');
            return; 
        }
        if (!info.event.start) {
            console.error('[handleEventChange] CRITICAL: Event start time is missing. Cannot save.', info.event);
            alert('Error: Booking start time is missing, cannot save the change.');
            return;
        }

        if (!info.event.extendedProps || !info.event.extendedProps.isActualBooking) {
            console.log('[handleEventChange] Attempted to modify a non-booking event. Reverting.');
            // Check if info.revert is a function before calling, as it might not be available if called directly
            if (typeof info.revert === 'function') {
                info.revert();
            }
            return;
        }

        const event = info.event; // Use info.event directly as it's already the correct reference
        
        const eventPayload = {
            start_time: event.start.toISOString(),
            end_time: event.end ? event.end.toISOString() : event.start.toISOString(), 
            title: event.title 
        };
        console.log('[handleEventChange] Attempting to save booking via API. Event ID:', event.id, 'Payload:', JSON.stringify(eventPayload));
        
        try {
            const response = await apiCall(`/api/bookings/${event.id}`, { // Capture response
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventPayload)
            });
            console.log('[handleEventChange] API call successful. Server response:', response);
            if (response && typeof response === 'object') {
                if (response.message) {
                    console.log('[handleEventChange] Server message:', response.message);
                }
                if (response.error) { // Should ideally not happen if HTTP status is 2xx
                    console.error('[handleEventChange] Server error reported in 2xx response:', response.error);
                }
            }
            console.log(`Booking ${event.id} updated successfully with server.`); // Clarified log
        } catch (e) {
            console.error('[handleEventChange] Error during API call to save booking:', e);
            if (e && e.status) { // Check if error object has status (like from a fetch response error)
                 console.error(`[handleEventChange] API Error Status: ${e.status}`);
            }
            // Attempt to log body if it's a response object that failed
            if (e && typeof e.json === 'function') {
                e.json().then(jsonError => {
                    console.error('[handleEventChange] API Error JSON Body:', jsonError);
                }).catch(jsonParseError => {
                    console.error('[handleEventChange] Could not parse error response as JSON:', jsonParseError);
                     // If not JSON, try to log as text
                    if (typeof e.text === 'function') {
                        e.text().then(textError => {
                            console.error('[handleEventChange] API Error Text Body:', textError);
                        }).catch(textParseError => {
                             console.error('[handleEventChange] Could not parse error response as text:', textParseError);
                        });
                    }
                });
            } else if (e && e.message) {
                 console.error('[handleEventChange] Error message:', e.message);
            }
            alert(`Error updating booking: ${e.message || 'Server error'}. Reverting.`);
            if (typeof info.revert === 'function') {
                info.revert();
            }
        }
    };

    if (calendarResourceSelect) {
        calendarResourceSelect.addEventListener('change', () => {
            const actualBookingsSource = calendar.getEventSourceById('actualBookings');
            if (actualBookingsSource) {
                allUserEvents = []; 
                actualBookingsSource.refetch();
            }
        });
    }

    populateResourceSelector(); 
});
