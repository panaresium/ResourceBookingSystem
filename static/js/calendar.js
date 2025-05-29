document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    if (!calendarEl || !calendarResourceSelect) {
        console.error("Calendar element or resource select dropdown not found.");
        return;
    }

    let allUserEvents = []; // Store all user bookings

    // MORNING_SLOT and AFTERNOON_SLOT are not needed if not generating available slots
    // const MORNING_SLOT = { startHour: 8, endHour: 12, title: 'Morning Available', color: 'green' };
    // const AFTERNOON_SLOT = { startHour: 13, endHour: 17, title: 'Afternoon Available', color: 'green' };

    async function populateResourceSelector() {
        try {
            const resources = await apiCall('/api/resources');
            // Keep the "-- All My Booked Resources --" option, clear others
            const firstOption = calendarResourceSelect.options[0];
            calendarResourceSelect.innerHTML = '';
            calendarResourceSelect.add(firstOption);

            if (resources && resources.length > 0) {
                resources.forEach(resource => {
                    if (resource.status === 'published') {
                        const option = new Option(`${resource.name} (Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                        calendarResourceSelect.add(option);
                    }
                });
                calendarResourceSelect.disabled = false;
            } else {
                // If no other resources, it will just have the "All" option
                // Consider if disabling is desired or if "All" is always sufficient
                // calendarResourceSelect.disabled = true; // Re-evaluate if needed
            }
        } catch (error) {
            console.error('Error fetching resources for calendar selector:', error);
            // Keep "All" option, maybe add an error message or disable
            calendarResourceSelect.options[0].text = '-- Error loading resources --'; // Update existing "All" option text
            // calendarResourceSelect.disabled = true;
        }
    }

    // generateAvailableSlots function is removed

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
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
                    // Check if data is already fetched and cached
                    // The 'force' flag can be used if you add a manual refresh button later
                    if (allUserEvents.length > 0 /* && !fetchInfo.force */) { 
                        const selectedResourceId = calendarResourceSelect.value;
                        let eventsToDisplay = [];
                        if (selectedResourceId === 'all' || !selectedResourceId) {
                            eventsToDisplay = allUserEvents;
                        } else {
                            eventsToDisplay = allUserEvents.filter(event =>
                                String(event.resource_id) === String(selectedResourceId)
                            );
                        }
                        console.log('Using cached allUserEvents, filtered for:', selectedResourceId, JSON.stringify(eventsToDisplay));
                        successCallback(eventsToDisplay);
                        return;
                    }

                    // If not cached or forced, fetch from API
                    apiCall('/api/bookings/calendar') // Fetches current user's bookings
                        .then(bookings => {
                            allUserEvents = bookings.map(b => {
                                // Ensure resource_id is consistently available at the top level of the event object
                                let resourceId = b.resource_id; 
                                if (resourceId === undefined && b.extendedProps && b.extendedProps.resource_id !== undefined) {
                                    resourceId = b.extendedProps.resource_id;
                                } else if (resourceId === undefined && b.resourceId !== undefined){ // Check for resourceId from some FullCalendar versions
                                    resourceId = b.resourceId;
                                }
                                return {
                                    ...b,
                                    resource_id: resourceId, // Standardize access to resource_id
                                    extendedProps: {...b.extendedProps, isActualBooking: true }
                                };
                            });
                            console.log('Fetched and cached allUserEvents:', JSON.stringify(allUserEvents));

                            const selectedResourceId = calendarResourceSelect.value;
                            let eventsToDisplay = [];
                            if (selectedResourceId === 'all' || !selectedResourceId) {
                                eventsToDisplay = allUserEvents;
                            } else {
                                eventsToDisplay = allUserEvents.filter(event =>
                                    String(event.resource_id) === String(selectedResourceId)
                                );
                            }
                            console.log('Displaying events for:', selectedResourceId, JSON.stringify(eventsToDisplay));
                            successCallback(eventsToDisplay);
                        })
                        .catch(error => {
                            console.error('Error fetching user bookings for calendar:', error);
                            allUserEvents = []; // Clear cache on error
                            failureCallback(error);
                        });
                }
            }
            // No 'availableSlots' source anymore
        ],
        eventOrder: function(a, b) { // This might not be strictly necessary if only actual bookings are shown
            if (a.extendedProps && a.extendedProps.isActualBooking) return 1;
            if (b.extendedProps && b.extendedProps.isActualBooking) return -1;
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

    // if (calendarResourceSelect) {
    //     calendarResourceSelect.addEventListener('change', () => {
    //         const actualBookingsSource = calendar.getEventSourceById('actualBookings');
    //         if (actualBookingsSource) actualBookingsSource.refetch();
            
    //         const availableSlotsSource = calendar.getEventSourceById('availableSlots');
    //         if (availableSlotsSource) availableSlotsSource.refetch();
    //     });
    // }

    if (calendarResourceSelect) {
        calendarResourceSelect.addEventListener('change', () => {
            // Just refetch the 'actualBookings' source. It will apply the filter internally.
            const actualBookingsSource = calendar.getEventSourceById('actualBookings');
            if (actualBookingsSource) {
                actualBookingsSource.refetch();
            }
        });
    }

    populateResourceSelector(); // Call after everything is set up
});
