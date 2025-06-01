document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    // Modal elements
    const calendarEditBookingModal = document.getElementById('calendar-edit-booking-modal');
    const cebmCloseModalBtn = document.getElementById('cebm-close-modal-btn');
    const cebmResourceName = document.getElementById('cebm-resource-name');
    const cebmBookingId = document.getElementById('cebm-booking-id');
    const cebmBookingTitle = document.getElementById('cebm-booking-title');
    const cebmStartTime = document.getElementById('cebm-start-time');
    const cebmEndTime = document.getElementById('cebm-end-time');
    const cebmSaveChangesBtn = document.getElementById('cebm-save-changes-btn');
    const cebmStatusMessage = document.getElementById('cebm-status-message');

    if (!calendarEl || !calendarResourceSelect || !calendarEditBookingModal) {
        console.error("Required calendar elements or modal not found.");
        return;
    }

    let allUserEvents = []; // Store all user bookings

    // Helper function to format Date objects for datetime-local input
    function formatDateForDatetimeLocal(date) {
        if (!date) return '';
        // Create a new Date object from the UTC time, then slice to YYYY-MM-DDTHH:MM
        // This interprets the UTC date as if it were local, to fill the input correctly.
        // The input itself doesn't carry timezone info, it's just a local datetime string.
        const year = date.getUTCFullYear();
        const month = (date.getUTCMonth() + 1).toString().padStart(2, '0');
        const day = date.getUTCDate().toString().padStart(2, '0');
        const hours = date.getUTCHours().toString().padStart(2, '0');
        const minutes = date.getUTCMinutes().toString().padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }


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

    // Function to handle saving changes from the modal
    async function saveBookingChanges(bookingId, title, startTimeStr, endTimeStr, calendarEventToUpdate) {
        cebmStatusMessage.textContent = '';
        cebmStatusMessage.className = 'status-message';

        // Basic validation
        const startDate = new Date(startTimeStr); // Parsed as local time by Date constructor
        const endDate = new Date(endTimeStr);   // Parsed as local time

        if (endDate <= startDate) {
            cebmStatusMessage.textContent = 'End time must be after start time.';
            cebmStatusMessage.className = 'status-message error-message'; // Ensure you have .error-message CSS
            return;
        }

        const eventPayload = {
            title: title,
            start_time: startDate.toISOString(), // Convert to UTC ISO string
            end_time: endDate.toISOString(),     // Convert to UTC ISO string
        };

        try {
            cebmSaveChangesBtn.disabled = true;
            cebmSaveChangesBtn.textContent = 'Saving...';
            const response = await apiCall(`/api/bookings/${bookingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventPayload)
            });

            console.log('Booking update successful:', response);
            
            // Update the event on the calendar
            if (calendarEventToUpdate) {
                calendarEventToUpdate.setProp('title', title);
                // When setting start/end, FullCalendar interprets these based on its timeZone (UTC)
                // The date objects created from datetime-local are local. Convert them to what FC expects.
                // Since FC is in UTC, and API needs UTC, we ensure these are UTC dates.
                calendarEventToUpdate.setStart(startDate.toISOString());
                calendarEventToUpdate.setEnd(endDate.toISOString());
            }
            // calendar.refetchEvents(); // Alternative: refetch all events for the current source

            cebmStatusMessage.textContent = response.message || 'Booking updated successfully!';
            cebmStatusMessage.className = 'status-message success-message'; // Ensure you have .success-message CSS

            setTimeout(() => {
                calendarEditBookingModal.style.display = 'none';
                cebmStatusMessage.textContent = ''; // Clear message
                 cebmStatusMessage.className = 'status-message';
            }, 1500); // Close modal after a short delay

        } catch (error) {
            console.error('Error updating booking:', error);
            cebmStatusMessage.textContent = error.message || 'Failed to update booking.';
            cebmStatusMessage.className = 'status-message error-message';
        } finally {
            cebmSaveChangesBtn.disabled = false;
            cebmSaveChangesBtn.textContent = 'Save Changes';
        }
    }


    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        timeZone: 'UTC', // Keep timezone as UTC for consistency with server
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        editable: false, // Disable drag-and-drop and resize
        eventClick: function(info) {
            // Populate modal with event details
            cebmBookingId.value = info.event.id;
            cebmBookingTitle.value = info.event.title;

            // Ensure resource_name is correctly sourced. Assuming it's in extendedProps.
            cebmResourceName.textContent = info.event.extendedProps.resource_name || info.event.title || 'N/A';

            // Convert event's UTC start/end times to format suitable for datetime-local input
            cebmStartTime.value = formatDateForDatetimeLocal(info.event.start);
            cebmEndTime.value = info.event.end ? formatDateForDatetimeLocal(info.event.end) : '';

            cebmStatusMessage.textContent = ''; // Clear previous messages
            cebmStatusMessage.className = 'status-message';
            calendarEditBookingModal.style.display = 'block';

            // Remove previous event listener to avoid multiple bindings if any
            const newSaveBtn = cebmSaveChangesBtn.cloneNode(true);
            cebmSaveChangesBtn.parentNode.replaceChild(newSaveBtn, cebmSaveChangesBtn);
            // Re-assign to the new button for the current scope
            const currentSaveBtn = document.getElementById('cebm-save-changes-btn');

            currentSaveBtn.onclick = () => { // Use onclick for simplicity here, or manage event listeners carefully
                saveBookingChanges(
                    cebmBookingId.value,
                    cebmBookingTitle.value,
                    cebmStartTime.value,
                    cebmEndTime.value,
                    info.event // Pass the FullCalendar event object to update it directly
                );
            };
        },
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
                                extendedProps.resource_name = b.resource_name; // Populate resource_name
                                extendedProps.original_title = b.title; // Preserve original booking title if needed

                                const eventObject = {
                                    // Spread booking properties. Ensure 'title', 'start', 'end' are correctly formatted for FullCalendar if not already.
                                    // FullCalendar will use 'title', 'start', 'end' directly.
                                    // Other properties like 'id' from 'b' should also be spread.
                                    ...b, // This should include id, title, start, end, etc.
                                    resource_id: apiResourceId, // Ensure this is not overwritten by spread if b also has it.
                                    extendedProps: extendedProps 
                                };
                                
                                console.log('Created event object. Resource ID:', eventObject.resource_id, 'ExtendedProps Resource ID:', eventObject.extendedProps.resource_id, 'Resource Name:', eventObject.extendedProps.resource_name);
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
    console.log('FullCalendar effective timeZone:', calendar.getOption('timeZone')); // Log effective timezone

    // Event listener for the modal's close button
    if (cebmCloseModalBtn) {
        cebmCloseModalBtn.addEventListener('click', () => {
            calendarEditBookingModal.style.display = 'none';
        });
    }

    // Close modal if user clicks outside of the modal content
    window.addEventListener('click', (event) => {
        if (event.target === calendarEditBookingModal) {
            calendarEditBookingModal.style.display = 'none';
        }
    });

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
