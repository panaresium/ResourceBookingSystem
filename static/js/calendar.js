document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    if (!calendarEl || !calendarResourceSelect) {
        console.error("Calendar element or resource select dropdown not found.");
        return;
    }

    const MORNING_SLOT = { startHour: 8, endHour: 12, title: 'Morning Available', color: 'green' };
    const AFTERNOON_SLOT = { startHour: 13, endHour: 17, title: 'Afternoon Available', color: 'green' };
    // Business hours are implicitly defined by the slots for now.

    async function populateResourceSelector() {
        try {
            // Using apiCall helper if available and configured for GET requests without message element
            const resources = await apiCall('/api/resources'); 
            calendarResourceSelect.innerHTML = '<option value="">-- Select a Resource --</option>';
            if (resources && resources.length > 0) {
                resources.forEach(resource => {
                    // Only include published resources if the API returns all statuses
                    if (resource.status === 'published') { 
                        const option = new Option(`${resource.name} (Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                        calendarResourceSelect.add(option);
                    }
                });
            } else {
                calendarResourceSelect.innerHTML = '<option value="">No resources available</option>';
                calendarResourceSelect.disabled = true;
            }
        } catch (error) {
            console.error('Error fetching resources for calendar selector:', error);
            calendarResourceSelect.innerHTML = '<option value="">Error loading resources</option>';
            calendarResourceSelect.disabled = true;
        }
    }

    function generateAvailableSlots(viewStart, viewEnd, actualBookings) {
        const availableEvents = [];
        let currentDate = new Date(viewStart.valueOf()); // Clone to avoid modifying original

        while (currentDate < viewEnd) {
            // Morning Slot
            const morningStart = new Date(currentDate);
            morningStart.setHours(MORNING_SLOT.startHour, 0, 0, 0);
            const morningEnd = new Date(currentDate);
            morningEnd.setHours(MORNING_SLOT.endHour, 0, 0, 0);

            let morningOverlap = false;
            for (const booking of actualBookings) {
                const bookingStart = new Date(booking.start);
                const bookingEnd = new Date(booking.end);
                if (bookingStart < morningEnd && bookingEnd > morningStart) {
                    morningOverlap = true;
                    break;
                }
            }
            if (!morningOverlap) {
                availableEvents.push({
                    title: MORNING_SLOT.title,
                    start: morningStart.toISOString(),
                    end: morningEnd.toISOString(),
                    color: MORNING_SLOT.color,
                    display: 'background', // Or 'block' if preferred
                    extendedProps: { isActualBooking: false }
                });
            }

            // Afternoon Slot
            const afternoonStart = new Date(currentDate);
            afternoonStart.setHours(AFTERNOON_SLOT.startHour, 0, 0, 0);
            const afternoonEnd = new Date(currentDate);
            afternoonEnd.setHours(AFTERNOON_SLOT.endHour, 0, 0, 0);

            let afternoonOverlap = false;
            for (const booking of actualBookings) {
                const bookingStart = new Date(booking.start);
                const bookingEnd = new Date(booking.end);
                if (bookingStart < afternoonEnd && bookingEnd > afternoonStart) {
                    afternoonOverlap = true;
                    break;
                }
            }
            if (!afternoonOverlap) {
                availableEvents.push({
                    title: AFTERNOON_SLOT.title,
                    start: afternoonStart.toISOString(),
                    end: afternoonEnd.toISOString(),
                    color: AFTERNOON_SLOT.color,
                    display: 'background', // Or 'block'
                    extendedProps: { isActualBooking: false }
                });
            }
            currentDate.setDate(currentDate.getDate() + 1); // Move to next day
        }
        return availableEvents;
    }


    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek', // Changed for better slot visibility
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        editable: true,
        eventDrop: handleEventChange,
        eventResize: handleEventChange,
        eventSources: [
            {
                id: 'actualBookings',
                events: function(fetchInfo, successCallback, failureCallback) {
                    const selectedResourceId = calendarResourceSelect.value;
                    if (!selectedResourceId) {
                        successCallback([]);
                        return;
                    }
                    apiCall(`/api/resources/${selectedResourceId}/all_bookings?start=${fetchInfo.startStr}&end=${fetchInfo.endStr}`)
                        .then(bookings => {
                            successCallback(bookings.map(b => ({...b, extendedProps: {...b.extendedProps, isActualBooking: true } })));
                        })
                        .catch(error => {
                            console.error('Error fetching actual bookings:', error);
                            failureCallback(error); // Inform FullCalendar about the error
                        });
                }
            },
            {
                id: 'availableSlots',
                events: function(fetchInfo, successCallback, failureCallback) {
                    const selectedResourceId = calendarResourceSelect.value;
                    if (!selectedResourceId) {
                        successCallback([]);
                        return;
                    }
                    apiCall(`/api/resources/${selectedResourceId}/all_bookings?start=${fetchInfo.startStr}&end=${fetchInfo.endStr}`)
                        .then(actualBookings => {
                            // Ensure actualBookings are in a format that Date constructor can parse if they are strings
                            const parsedBookings = actualBookings.map(b => ({
                                ...b,
                                start: new Date(b.start), // Assuming b.start is ISO string
                                end: new Date(b.end)    // Assuming b.end is ISO string
                            }));
                            const availableEvents = generateAvailableSlots(fetchInfo.start, fetchInfo.end, parsedBookings);
                            successCallback(availableEvents);
                        })
                        .catch(error => {
                            console.error('Error fetching bookings for availability calculation:', error);
                            failureCallback(error);
                        });
                }
            }
        ],
        eventOrder: function(a, b) {
            if (a.extendedProps && a.extendedProps.isActualBooking) return 1; // Actual bookings on top
            if (b.extendedProps && b.extendedProps.isActualBooking) return -1;
            // Then available slots (which are background events so order might not matter as much visually)
            return 0; 
        }
    });

    calendar.render();

    async function handleEventChange(info) {
        // Only allow modification of actual bookings
        if (!info.event.extendedProps || !info.event.extendedProps.isActualBooking) {
            console.log('Attempted to modify a non-booking event (e.g., availability slot). Reverting.');
            info.revert();
            return;
        }

        const event = info.event;
        try {
            await apiCall(`/api/bookings/${event.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_time: event.start.toISOString(),
                    end_time: event.end ? event.end.toISOString() : event.start.toISOString() 
                    // title: event.title // Add if title changes should also be saved
                })
            });
            // Optionally, show a success message to the user
        } catch (e) {
            console.error('Failed to update booking time', e);
            info.revert(); // Revert the change on the calendar if API call fails
        }
    }

    if (calendarResourceSelect) {
        calendarResourceSelect.addEventListener('change', () => {
            const actualBookingsSource = calendar.getEventSourceById('actualBookings');
            if (actualBookingsSource) actualBookingsSource.refetch();
            
            const availableSlotsSource = calendar.getEventSourceById('availableSlots');
            if (availableSlotsSource) availableSlotsSource.refetch();
        });
    }

    populateResourceSelector(); // Call after everything is set up
});
