document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    // Old modal elements are removed as the shared modal is now used.
    // const calendarEditBookingModal = document.getElementById('calendar-edit-booking-modal'); // REMOVED
    // ... other cebm- prefixed variables ... // REMOVED

    if (!calendarEl || !calendarResourceSelect) { // calendarEditBookingModal removed from check
        console.error("Required calendar elements not found.");
        return;
    }

    let allUserEvents = []; // Store all user bookings

    // Removed fetchAndDisplayAvailableSlots as this logic is now in booking_modal_handler.js
    // Removed saveBookingChanges as this logic is now in booking_modal_handler.js

    async function populateResourceSelector() {
        try {
            const resources = await apiCall('/api/bookings/my_booked_resources');
            const firstOption = calendarResourceSelect.options[0];
            calendarResourceSelect.innerHTML = ''; // Clear existing options except the first one
            calendarResourceSelect.add(firstOption); // Re-add "All My Booked Resources"

            if (resources && resources.length > 0) {
                resources.forEach(resource => {
                    const option = new Option(`${resource.name} (Status: ${resource.status}, Capacity: ${resource.capacity || 'N/A'})`, resource.id);
                    calendarResourceSelect.add(option);
                });
                calendarResourceSelect.disabled = false;
            }
        } catch (error) {
            console.error('Error fetching resources for calendar selector:', error);
            if (calendarResourceSelect.options.length > 0) {
                 calendarResourceSelect.options[0].text = '-- Error loading resources --';
            }
        }
    }

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        timeZone: 'UTC',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        editable: false,
        eventClick: function(info) {
            const bookingId = info.event.id;
            const resourceId = info.event.extendedProps.resource_id;
            const resourceName = info.event.extendedProps.resource_name || info.event.title || 'N/A (Resource Name Missing)'; // Fallback for resource name
            const currentTitle = info.event.title;
            const currentStartTimeISO = info.event.start ? info.event.start.toISOString() : null;
            const currentEndTimeISO = info.event.end ? info.event.end.toISOString() : null;
            const globalUserName = document.body.dataset.userName || 'Unknown User';

            if (!resourceId) {
                console.error("Resource ID is missing in event's extendedProps. Cannot open modal.", info.event);
                alert("Error: Cannot edit this event due to missing resource information.");
                return;
            }
             if (!currentStartTimeISO) {
                console.error("Event start time is missing. Cannot open modal.", info.event);
                alert("Error: Event start time is missing.");
                return;
            }


            if (typeof openBookingModal === 'function') {
                openBookingModal({
                    mode: 'update',
                    bookingId: bookingId,
                    resourceId: String(resourceId),
                    resourceName: resourceName,
                    currentTitle: currentTitle,
                    currentStartTimeISO: currentStartTimeISO,
                    currentEndTimeISO: currentEndTimeISO,
                    userNameForRecord: globalUserName,
                    onSaveSuccess: function(updatedBookingData) {
                        console.log('Booking updated via calendar modal:', updatedBookingData);
                        if (calendar) {
                            calendar.refetchEvents();
                        }
                        // Optionally, show a global success message on the page if needed
                        // e.g., using a global status display function
                    }
                });
            } else {
                console.error("openBookingModal function is not defined. Ensure booking_modal_handler.js is loaded before calendar.js.");
                alert("Error: Booking functionality is currently unavailable.");
            }
        },
        eventSources: [
            {
                id: 'actualBookings',
                events: function(fetchInfo, successCallback, failureCallback) {
                    if (allUserEvents.length > 0 ) {
                        const selectedResourceId = calendarResourceSelect.value;
                        let eventsToDisplay = (selectedResourceId === 'all' || !selectedResourceId)
                            ? allUserEvents
                            : allUserEvents.filter(event => String(event.extendedProps.resource_id) === String(selectedResourceId)); // Filter by extendedProps.resource_id
                        console.log('Using cached allUserEvents, filtered for resource ID:', selectedResourceId, 'Events count:', eventsToDisplay.length);
                        successCallback(eventsToDisplay);
                        return;
                    }

                    apiCall('/api/bookings/calendar') 
                        .then(bookings => {
                            allUserEvents = bookings.map(b => {
                                // Ensure resource_id and resource_name are consistently in extendedProps
                                const apiResourceId = b.resource_id; 
                                const resourceName = b.resource_name || 'Unknown Resource'; // Fallback for resource_name

                                const extendedProps = {
                                    ...b.extendedProps, // Preserve any existing extendedProps
                                    isActualBooking: true,
                                    resource_id: apiResourceId,
                                    resource_name: resourceName,
                                    original_title: b.title
                                };
                                
                                return {
                                    id: b.id,
                                    title: b.title,
                                    start: b.start, // Assuming these are ISO strings
                                    end: b.end,
                                    allDay: b.allDay || false, // Assuming allDay might be a property
                                    // resource_id: apiResourceId, // Keep at top level if FullCalendar uses it for resource views
                                    extendedProps: extendedProps
                                };
                            });
                            console.log('Fetched and cached allUserEvents. Count:', allUserEvents.length);
                            const selectedResourceId = calendarResourceSelect.value;
                            let eventsToDisplay = (selectedResourceId === 'all' || !selectedResourceId)
                                ? allUserEvents
                                : allUserEvents.filter(event => String(event.extendedProps.resource_id) === String(selectedResourceId));
                            console.log('Displaying events for resource ID:', selectedResourceId, 'Events count:', eventsToDisplay.length);
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
            // This logic might need adjustment if isActualBooking is not always present
            const isAActual = a.extendedProps && a.extendedProps.isActualBooking;
            const isBActual = b.extendedProps && b.extendedProps.isActualBooking;
            if (isAActual && !isBActual) return 1;
            if (!isAActual && isBActual) return -1;
            return 0;
        },
        eventContent: function(arg) {
            // Simplified event content, can be expanded later if needed
            let titleHtml = `<b>${arg.event.title}</b>`;
            if (arg.event.extendedProps.resource_name) {
                 titleHtml += `<br><small>${arg.event.extendedProps.resource_name}</small>`;
            }
            // Time display is handled by FullCalendar views by default.
            // Custom time formatting like in the original can be added back if necessary.
            return { html: titleHtml };
        }
    });

    calendar.render();
    console.log('FullCalendar effective timeZone:', calendar.getOption('timeZone'));

    // Old modal listeners (cebmCloseModalBtn, window click) are removed.

    if (calendarResourceSelect) {
        calendarResourceSelect.addEventListener('change', () => {
            // Refetch events when resource filter changes
            // The eventSource function will use the new select value.
            // Clearing allUserEvents ensures fresh data or re-filter of full set if logic allows.
            allUserEvents = []; // Clear cache to force re-fetch or re-process based on new filter
            calendar.refetchEvents();
        });
    }

    populateResourceSelector();
});
