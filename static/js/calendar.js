document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    const calendarResourceSelect = document.getElementById('calendar-resource-select');

    // Modal elements
    const calendarEditBookingModal = document.getElementById('calendar-edit-booking-modal');
    const cebmCloseModalBtn = document.getElementById('cebm-close-modal-btn');
    const cebmResourceName = document.getElementById('cebm-resource-name');
    const cebmBookingId = document.getElementById('cebm-booking-id');
    const cebmBookingTitle = document.getElementById('cebm-booking-title');
    // const cebmStartTime = document.getElementById('cebm-start-time'); // Replaced by date and select
    // const cebmEndTime = document.getElementById('cebm-end-time');   // Replaced by date and select
    const cebmBookingDate = document.getElementById('cebm-booking-date');
    const cebmAvailableSlotsSelect = document.getElementById('cebm-available-slots-select');
    const cebmSaveChangesBtn = document.getElementById('cebm-save-changes-btn');
    const cebmStatusMessage = document.getElementById('cebm-status-message');

    if (!calendarEl || !calendarResourceSelect || !calendarEditBookingModal) {
        console.error("Required calendar elements or modal not found.");
        return;
    }

    let allUserEvents = []; // Store all user bookings

    // Helper function to format Date objects for datetime-local input
    // function formatDateForDatetimeLocal(date) { // No longer needed for datetime-local inputs
    //     if (!date) return '';
    //     const year = date.getUTCFullYear();
    //     const month = (date.getUTCMonth() + 1).toString().padStart(2, '0');
    //     const day = date.getUTCDate().toString().padStart(2, '0');
    //     const hours = date.getUTCHours().toString().padStart(2, '0');
    //     const minutes = date.getUTCMinutes().toString().padStart(2, '0');
    //     return `${year}-${month}-${day}T${hours}:${minutes}`;
    // }

    async function fetchAndDisplayAvailableSlots(resourceId, dateStr, selectedStartTimeStr) {
        const slotsSelect = document.getElementById('cebm-available-slots-select');
        const statusMessage = document.getElementById('cebm-status-message'); // Or a dedicated message area for slots

        slotsSelect.innerHTML = '<option value="">Loading slots...</option>';
        slotsSelect.disabled = true;

        try {
            const availableSlots = await apiCall(`/api/resources/${resourceId}/available_slots?date=${dateStr}`);

            // Reset the select element
            slotsSelect.innerHTML = '<option value="">-- Select a time slot --</option>'; // Reset

            // Define the predefined slots
            const predefinedSlots = [
                { text: "08:00 - 12:00 UTC", value: "08:00,12:00" },
                { text: "13:00 - 17:00 UTC", value: "13:00,17:00" },
                { text: "08:00 - 17:00 UTC", value: "08:00,17:00" }
            ];

            // Populate the select element with predefined slots
            predefinedSlots.forEach(slot => {
                const option = new Option(slot.text, slot.value);
                slotsSelect.add(option);
            });
            slotsSelect.disabled = false;

            // The original logic for handling empty or error states for availableSlots can be kept
            // or adapted if the API call itself is still meaningful for other purposes (e.g. general availability check)
            if (!availableSlots) { // Example: if API call failed or indicated resource is generally unavailable
                 console.warn('API call for slots succeeded but returned no data, or resource might be unavailable. Proceeding with predefined slots.');
            }
            // if (availableSlots && availableSlots.length > 0) { // This block is replaced
            //     availableSlots.forEach(slot => {
            //         const optionValue = `${slot.start_time},${slot.end_time}`;
            //         const optionText = `${slot.start_time} - ${slot.end_time} UTC`;
            //         const option = new Option(optionText, optionValue);
            //
            //         if (selectedStartTimeStr && slot.start_time === selectedStartTimeStr) {
            //             option.selected = true;
            //         }
            //         slotsSelect.add(option);
            //     });
            //     slotsSelect.disabled = false;
            // } else { // This logic might need adjustment if API call result is still used
            //     slotsSelect.innerHTML = '<option value="">No available slots (using predefined)</option>';
            //     // Populate with predefined even if API says no specific slots, or handle as error.
            //     // For now, predefined slots are added regardless of API's slot list.
            // }
            if (statusMessage) statusMessage.textContent = ''; // Clear loading/previous status
        } catch (error) {
            console.error('Error fetching available slots:', error);
            // Even if API fails, we might still want to show predefined slots,
            // or show an error and not show slots. For now, let's assume error means no slots.
            slotsSelect.innerHTML = '<option value="">Error loading slots</option>';
            if (statusMessage) {
                statusMessage.textContent = error.message || 'Failed to load available slots.';
                statusMessage.className = 'status-message error-message';
            }
        }
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
    async function saveBookingChanges(bookingId, title, calendarEventToUpdate) { // Signature updated
        cebmStatusMessage.textContent = '';
        cebmStatusMessage.className = 'status-message';

        const bookingDateStr = document.getElementById('cebm-booking-date').value;
        const selectedSlotValue = document.getElementById('cebm-available-slots-select').value;

        if (!bookingDateStr || !selectedSlotValue) {
            cebmStatusMessage.textContent = 'Please select a date and a time slot.';
            cebmStatusMessage.className = 'status-message error-message';
            return;
        }

        const [slotStartTime, slotEndTime] = selectedSlotValue.split(',');

        // Construct full ISO datetime strings for start and end
        const localStartDate = new Date(`${bookingDateStr}T${slotStartTime}:00Z`); // Parsed as UTC
        const localEndDate = new Date(`${bookingDateStr}T${slotEndTime}:00Z`);   // Parsed as UTC

        if (localEndDate <= localStartDate) { // Validation for new slot times
            cebmStatusMessage.textContent = 'End time must be after start time.';
            cebmStatusMessage.className = 'status-message error-message';
            return;
        }

        const eventPayload = {
            title: title,
            start_time: localStartDate.toISOString(),
            end_time: localEndDate.toISOString(),
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
                // Use the localStartDate and localEndDate, FullCalendar will handle timezone conversion
                calendarEventToUpdate.setStart(localStartDate.toISOString());
                calendarEventToUpdate.setEnd(localEndDate.toISOString());
            }
            // calendar.refetchEvents();

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
        initialView: 'dayGridMonth',
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

            // Store resource_id in hidden input
            const cebmResourceIdInput = document.getElementById('cebm-resource-id');
            cebmResourceIdInput.value = info.event.extendedProps.resource_id;

            const cebmBookingDateInput = document.getElementById('cebm-booking-date');

            if (info.event.start) {
                const startDate = new Date(info.event.start); // Local representation of event's start
                const year = startDate.getFullYear();
                const month = (startDate.getMonth() + 1).toString().padStart(2, '0');
                const day = startDate.getDate().toString().padStart(2, '0');
                cebmBookingDateInput.value = `${year}-${month}-${day}`;

                const startHours = info.event.start.getUTCHours().toString().padStart(2, '0');
                const startMinutes = info.event.start.getUTCMinutes().toString().padStart(2, '0');
                const selectedStartTimeHHMM = `${startHours}:${startMinutes}`;

                fetchAndDisplayAvailableSlots(info.event.extendedProps.resource_id, cebmBookingDateInput.value, selectedStartTimeHHMM);
            } else {
                cebmBookingDateInput.value = ''; // Or today's date
                // Optionally fetch slots for a default date or leave selector empty
                document.getElementById('cebm-available-slots-select').innerHTML = '<option value="">-- Select a date first --</option>';
            }

            cebmBookingDateInput.onchange = () => {
                const resourceId = cebmResourceIdInput.value;
                if (resourceId && cebmBookingDateInput.value) {
                    fetchAndDisplayAvailableSlots(resourceId, cebmBookingDateInput.value, null);
                }
            };

            cebmStatusMessage.textContent = ''; // Clear previous messages
            cebmStatusMessage.className = 'status-message';
            calendarEditBookingModal.style.display = 'block';

            // Remove previous event listener to avoid multiple bindings if any
            const newSaveBtn = cebmSaveChangesBtn.cloneNode(true);
            cebmSaveChangesBtn.parentNode.replaceChild(newSaveBtn, cebmSaveChangesBtn);
            // Re-assign to the new button for the current scope
            const currentSaveBtn = document.getElementById('cebm-save-changes-btn');

            currentSaveBtn.onclick = () => {
                saveBookingChanges(
                    cebmBookingId.value,
                    cebmBookingTitle.value,
                    // startTime and endTime are no longer passed directly
                    info.event
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
        eventContent: function(arg) {
            if (arg.view.type === 'dayGridMonth') {
                let eventHtml = `<b>${arg.event.title}</b>`;
                if (arg.event.start) {
                    const startHours = arg.event.start.getUTCHours().toString().padStart(2, '0');
                    const startMinutes = arg.event.start.getUTCMinutes().toString().padStart(2, '0');
                    const startTimeUTC = `${startHours}:${startMinutes}`;

                    let endTimeUTC = '';
                    if (arg.event.end) {
                        const endHours = arg.event.end.getUTCHours().toString().padStart(2, '0');
                        const endMinutes = arg.event.end.getUTCMinutes().toString().padStart(2, '0');
                        endTimeUTC = `${endHours}:${endMinutes}`;
                    }

                    // Show time if not an all-day event or if time is not midnight
                    if (!arg.event.allDay || (startTimeUTC !== '00:00' || (endTimeUTC && endTimeUTC !== '00:00'))) {
                        eventHtml += `<br>${startTimeUTC}`;
                        if (endTimeUTC && endTimeUTC !== startTimeUTC) {
                            eventHtml += ` - ${endTimeUTC}`;
                        }
                        eventHtml += ' UTC'; // Append UTC label
                    }
                }
                return { html: eventHtml };
            }
            // For other views, retain original behavior (bold title, FC handles time)
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
