document.addEventListener('DOMContentLoaded', () => {
    let calendarInstance;
    const calendarEl = document.getElementById('calendar');
    const calendarStatusFilterSelect = document.getElementById('calendar-status-filter'); // Changed ID

    let unavailableDates = []; // Store fetched unavailable dates

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
    const cebmDeleteBookingBtn = document.getElementById('cebm-delete-booking-btn'); // Added

    if (!calendarEl || !calendarStatusFilterSelect || !calendarEditBookingModal || !cebmSaveChangesBtn || !cebmDeleteBookingBtn) { // Added !cebmSaveChangesBtn to the check
        console.error("Required calendar elements (calendar, filter, modal, save button, or delete button) not found.");
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

            // API call to availableSlots is kept (as per previous logic), but its direct output isn't used to populate slots here.
            // It could be used for general resource availability checks in a more advanced version.
            if (!availableSlots) {
                console.warn('API call for resource slots returned no data, or resource might be generally unavailable. Proceeding with predefined slots and user conflict check.');
            }

            const allCalendarEvents = calendarInstance.getEvents();
            const currentEditingBookingId = document.getElementById('cebm-booking-id').value;

            // PROACTIVE FIX APPLIED HERE based on prompt's suggestion
            const otherUserBookingsOnDate = allCalendarEvents.filter(event => {
                // Ensure event.id is string if currentEditingBookingId is string.
                if (String(event.id) === String(currentEditingBookingId)) { // Explicitly cast to string for safety
                    return false;
                }
                if (!event.start) {
                    return false;
                }
                // Date comparison: event.start is a Date object. dateStr is 'YYYY-MM-DD'.
                // Convert event.start to a 'YYYY-MM-DD' string in UTC for reliable comparison.
                const eventDateString = event.start.toISOString().split('T')[0];
                return eventDateString === dateStr;
            });

            // Define the predefined slots
            const predefinedSlots = [
                { text: "08:00 - 12:00 UTC", value: "08:00,12:00" },
                { text: "13:00 - 17:00 UTC", value: "13:00,17:00" },
                { text: "08:00 - 17:00 UTC", value: "08:00,17:00" }
            ];

            slotsSelect.innerHTML = '<option value="">-- Select a time slot --</option>'; // Reset

            predefinedSlots.forEach(pSlot => {
                const [pSlotStartStr, pSlotEndStr] = pSlot.value.split(',');
                // Construct Date objects for the predefined slot in UTC
                const predefinedSlotStartUTC = new Date(dateStr + 'T' + pSlotStartStr + ':00Z');
                const predefinedSlotEndUTC = new Date(dateStr + 'T' + pSlotEndStr + ':00Z');

                let isConflicting = false;
                for (const existingEvent of otherUserBookingsOnDate) {
                    // FullCalendar events store start/end as Date objects.
                    // These are already likely in UTC or will be correctly compared if Date objects are consistently used.
                    const existingBookingStart = existingEvent.start;
                    const existingBookingEnd = existingEvent.end;

                    if (existingBookingStart && existingBookingEnd) { // Standard check for events with duration
                        if ((predefinedSlotStartUTC < existingBookingEnd) && (predefinedSlotEndUTC > existingBookingStart)) {
                            isConflicting = true;
                            break;
                        }
                    } else if (existingBookingStart) {
                        // Handle events that might be point-in-time or have missing end dates
                        // This logic assumes such events conflict if they are within the predefined slot
                        if (predefinedSlotStartUTC <= existingBookingStart && predefinedSlotEndUTC > existingBookingStart) {
                           // isConflicting = true; // Uncomment and refine if point-in-time events need specific handling
                           // break;
                        }
                    }
                }
                if (!isConflicting) {
                    const option = new Option(pSlot.text, pSlot.value);
                    // Regarding selectedStartTimeStr:
                    // The original instruction was "we will not attempt to pre-select any of these fixed slots based on selectedStartTimeStr."
                    // If pre-selection for non-conflicting matching slots is desired later, it would be added here.
                    // Example: if (selectedStartTimeStr && pSlotStartStr === selectedStartTimeStr) { option.selected = true; }
                    slotsSelect.add(option);
                }
            });

            if (slotsSelect.options.length <= 1) { // Only the default "-- Select a time slot --" is present
                slotsSelect.innerHTML = '<option value="">No conflict-free slots available</option>';
            }
            slotsSelect.disabled = false;

            if (statusMessage) statusMessage.textContent = ''; // Clear loading/previous status
        } catch (error) {
            console.error('Error fetching available slots or processing conflicts:', error);
            slotsSelect.innerHTML = '<option value="">Error loading or checking slots</option>';
            if (statusMessage) {
                statusMessage.textContent = error.message || 'Failed to load available slots.';
                statusMessage.className = 'status-message error-message';
            }
        }
    }

    // Removed populateResourceSelector function

    function populateStatusFilter(selectElement) {
        selectElement.innerHTML = ''; // Clear existing options

        const statuses = [
            { value: 'active', text: 'Show All Relevant' }, // Default
            { value: 'approved', text: 'Approved (Pending Check-in)' },
            { value: 'checked_in', text: 'Checked In' },
            { value: 'completed', text: 'Completed' },
            { value: 'cancelled_group', text: 'Cancelled/Rejected' }
        ];

        statuses.forEach(status => {
            const option = document.createElement('option');
            option.value = status.value;
            option.textContent = status.text;
            selectElement.appendChild(option);
        });
        selectElement.disabled = false;
    }

    // Function to handle saving changes from the modal
    async function saveBookingChanges(buttonElement, bookingId, title, calendarEventToUpdate) { // Signature updated
        buttonElement.disabled = true;
        buttonElement.textContent = 'Processing...';
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
            // calendarInstance.refetchEvents(); // Corrected, but the original instruction implies this was a standalone line to change

            cebmStatusMessage.textContent = response.message || 'Booking updated successfully!';
            cebmStatusMessage.className = 'status-message success-message'; // Ensure you have .success-message CSS

            allUserEvents = []; // Clear the cache to force a fresh fetch
            calendarInstance.refetchEvents(); // Refresh calendar events

            // Close modal and clear message after a short delay
            setTimeout(() => {
                calendarEditBookingModal.style.display = 'none';
                cebmStatusMessage.textContent = ''; // Clear message
                cebmStatusMessage.className = 'status-message'; // Reset class
                // window.location.href = '/my_bookings'; // REMOVED
            }, 1500);

        } catch (error) {
            console.error('Error updating booking:', error);
            if (error.message && error.message.includes("No changes supplied.")) {
                cebmStatusMessage.textContent = 'No changes detected. Booking details are already up to date.';
                cebmStatusMessage.className = 'status-message success-message'; // Treat as success

                allUserEvents = []; // Clear the cache
                calendarInstance.refetchEvents(); // Refresh calendar events

                setTimeout(() => {
                    calendarEditBookingModal.style.display = 'none';
                    cebmStatusMessage.textContent = ''; // Clear message
                    cebmStatusMessage.className = 'status-message'; // Reset class
                    // window.location.href = '/my_bookings'; // REMOVED
                }, 1500);
            } else {
                cebmStatusMessage.textContent = error.message || 'Failed to update booking.';
                cebmStatusMessage.className = 'status-message error-message';
            }
        } finally {
            buttonElement.disabled = false;
            buttonElement.textContent = 'Save Changes';
        }
    }

    // Populate the new status filter dropdown
    populateStatusFilter(calendarStatusFilterSelect);

    // --- Logic to initialize and render the calendar ---
    const initializeCalendar = () => {
        calendarInstance = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            timeZone: 'UTC', // Keep timezone as UTC for consistency with server
            selectAllow: function(selectInfo) {
                // Convert startStr to 'YYYY-MM-DD' format
                const startDateStr = selectInfo.startStr.split('T')[0];
                if (unavailableDates.includes(startDateStr)) {
                    // console.log(`Selection blocked for unavailable date: ${startDateStr}`);
                    return false; // Date is in the unavailable list, prevent selection
                }
                return true; // Date is not in the list, allow selection
            },
            dayCellDidMount: function(arg) {
                // Convert arg.date (Date object) to 'YYYY-MM-DD' string
                const dateStr = arg.date.toISOString().split('T')[0];
                if (unavailableDates.includes(dateStr)) {
                    arg.el.classList.add('fc-unavailable-date');
                }
            },
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

                // Re-assign to the new button for the current scope
                // let currentSaveBtn = cebmSaveChangesBtn; // Initialize with the original button // Will be assigned after cloning

                const currentSaveBtnElement = document.getElementById('cebm-save-changes-btn');
                const currentDeleteBtnElement = document.getElementById('cebm-delete-booking-btn');
                let currentSaveBtn; // Will hold the (potentially new) save button

                // Remove previous event listener to avoid multiple bindings if any
                if (currentSaveBtnElement && currentSaveBtnElement.parentNode) {
                    const newSaveBtn = currentSaveBtnElement.cloneNode(true);
                    currentSaveBtnElement.parentNode.replaceChild(newSaveBtn, currentSaveBtnElement);
                    currentSaveBtn = newSaveBtn; // Assign the new button to currentSaveBtn
                } else {
                    console.error("Error: Could not find 'currentSaveBtnElement' (ID: cebm-save-changes-btn) or its parent node. Cannot re-attach event listener for save button.");
                    currentSaveBtn = currentSaveBtnElement; // Fallback to original if not found or no parent, though problematic
                }

                // Ensure currentSaveBtn is valid before attaching onclick
                if (currentSaveBtn) {
                    currentSaveBtn.onclick = () => {
                        saveBookingChanges(
                            currentSaveBtn, // Pass the button instance
                            cebmBookingId.value,
                            cebmBookingTitle.value,
                            info.event
                        );
                    };
                } else {
                    // This case should ideally not be reached if cebmSaveChangesBtn was initially found.
                    // If it is reached, it means the original button was also null.
                    console.error("Error: Save changes button ('currentSaveBtnElement', ID: cebm-save-changes-btn) not found. Save functionality will be unavailable.");
                }

                // Logic for delete button
                if (currentDeleteBtnElement && currentDeleteBtnElement.parentNode) {
                    const newDeleteBtn = currentDeleteBtnElement.cloneNode(true);
                    currentDeleteBtnElement.parentNode.replaceChild(newDeleteBtn, currentDeleteBtnElement);

                    newDeleteBtn.onclick = () => {
                        if (confirm("Are you sure you want to delete this booking?")) {
                            const bookingId = cebmBookingId.value;
                            if (!bookingId) {
                                cebmStatusMessage.textContent = 'Error: Booking ID not found.';
                                cebmStatusMessage.className = 'status-message error-message';
                                return;
                            }

                            // Disable button to prevent multiple clicks
                            newDeleteBtn.disabled = true;
                            newDeleteBtn.textContent = 'Deleting...';
                            cebmStatusMessage.textContent = '';
                            cebmStatusMessage.className = 'status-message';

                            apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' })
                                .then(response => {
                                    cebmStatusMessage.textContent = response.message || 'Booking deleted successfully!';
                                    cebmStatusMessage.className = 'status-message success-message';

                                    // Remove event from calendar
                                    const eventToRemove = calendarInstance.getEventById(bookingId);
                                    if (eventToRemove) {
                                        eventToRemove.remove();
                                    }

                                    // Close modal after a short delay
                                    setTimeout(() => {
                                        calendarEditBookingModal.style.display = 'none';
                                        cebmStatusMessage.textContent = '';
                                        cebmStatusMessage.className = 'status-message';
                                    }, 1500);
                                })
                                .catch(error => {
                                    console.error('Error deleting booking:', error);
                                    cebmStatusMessage.textContent = error.message || 'Failed to delete booking.';
                                    cebmStatusMessage.className = 'status-message error-message';
                                })
                                .finally(() => {
                                    // Re-enable button
                                    newDeleteBtn.disabled = false;
                                    newDeleteBtn.textContent = 'Delete Booking';
                                });
                        }
                    };
                } else {
                    console.error("Error: Could not find 'currentDeleteBtnElement' (ID: cebm-delete-booking-btn) or its parent node.");
                }
            },
            eventSources: [
                {
                    id: 'actualBookings',
                    events: function(fetchInfo, successCallback, failureCallback) {
                        let selectedStatusValue = calendarStatusFilterSelect ? calendarStatusFilterSelect.value : 'active';

                        if (selectedStatusValue === 'cancelled_group') {
                            selectedStatusValue = 'cancelled,rejected,cancelled_by_admin,cancelled_admin_acknowledged';
                        }

                        let apiUrl = '/api/bookings/calendar';
                        if (selectedStatusValue && selectedStatusValue !== 'active') {
                            apiUrl += `?status_filter=${encodeURIComponent(selectedStatusValue)}`;
                        }

                        allUserEvents = []; // Clear cache before every fetch for simplicity with filter changes

                        apiCall(apiUrl)
                            .then(bookings => {
                                const mappedEvents = bookings.map(b => {
                                    const apiResourceId = b.resource_id;
                                    const extendedProps = b.extendedProps || {};
                                    extendedProps.isActualBooking = true;
                                    extendedProps.resource_id = apiResourceId;
                                    extendedProps.resource_name = b.resource_name;
                                    extendedProps.original_title = b.title;

                                    const eventObject = {
                                        ...b,
                                        resource_id: apiResourceId,
                                        extendedProps: extendedProps
                                    };
                                    return eventObject;
                                });
                                allUserEvents = mappedEvents; // Re-populate cache (optional, but kept for now)
                                successCallback(mappedEvents);
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
                    const MAX_TITLE_LENGTH = 20;
                    const MAX_TIME_LENGTH = 18; // Max length for "HH:MM - HH:MM UTC"

                    let displayTitle = arg.event.title;
                    if (arg.event.title.length > MAX_TITLE_LENGTH) {
                        displayTitle = arg.event.title.substring(0, MAX_TITLE_LENGTH - 3) + "...";
                    }

                    let eventHtml = `<b>${displayTitle}</b>`;

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

                        let fullTimeString = '';
                        // Construct the time string only if it's not an all-day event or if time is not midnight
                        if (!arg.event.allDay || (startTimeUTC !== '00:00' || (endTimeUTC && endTimeUTC !== '00:00'))) {
                            fullTimeString = startTimeUTC;
                            if (endTimeUTC && endTimeUTC !== startTimeUTC) {
                                fullTimeString += ` - ${endTimeUTC}`;
                            }
                            fullTimeString += ' UTC';
                        }

                        if (fullTimeString) {
                            let displayTime = fullTimeString;
                            if (fullTimeString.length > MAX_TIME_LENGTH) {
                                displayTime = fullTimeString.substring(0, MAX_TIME_LENGTH - 3) + "...";
                            }
                            eventHtml += `<br>${displayTime}`;
                        }
                    }
                    return { html: eventHtml };
                }
                // For other views, retain original behavior (bold title, FC handles time)
                // Consider applying similar truncation for title here if needed for consistency
                let displayTitleOtherView = arg.event.title;
                // const MAX_TITLE_LENGTH_OTHER_VIEW = 30; // Example for other views
                // if (arg.event.title.length > MAX_TITLE_LENGTH_OTHER_VIEW) {
                //     displayTitleOtherView = arg.event.title.substring(0, MAX_TITLE_LENGTH_OTHER_VIEW - 3) + "...";
                // }
                // return { html: `<b>${displayTitleOtherView}</b>` };
                // For now, keeping it as it was for other views, only month view is in scope
                return { html: `<b>${arg.event.title}</b>` };
            }
        });
        calendarInstance.render();
        console.log('FullCalendar effective timeZone:', calendarInstance.getOption('timeZone')); // Log effective timezone

        // Attach event listeners that depend on the calendar object here, after it's rendered.
        if (calendarStatusFilterSelect) {
            calendarStatusFilterSelect.addEventListener('change', () => {
                if (calendarInstance) {
                     calendarInstance.refetchEvents();
                }
            });
        }
    };

    // --- Fetching user ID and then potentially unavailable dates ---
    let currentUserId = null;
    if (calendarEl && calendarEl.dataset.userId) {
        currentUserId = calendarEl.dataset.userId;
    } else if (typeof window.currentUserId !== 'undefined') { // Fallback to a global variable
        currentUserId = window.currentUserId;
    }

    if (currentUserId) {
        apiCall(`/api/resources/unavailable_dates?user_id=${currentUserId}`)
            .then(dates => {
                unavailableDates = dates; // Populate the global array
                console.log("Unavailable dates fetched:", unavailableDates);
            })
            .catch(error => {
                console.error('Error fetching unavailable dates:', error);
                // Proceed without unavailable dates functionality
            })
            .finally(() => {
                initializeCalendar(); // Initialize calendar after API call attempt
            });
    } else {
        console.warn('User ID not found for this calendar instance. Skipping fetching unavailable dates. This is normal for "My Calendar" view.');
        initializeCalendar(); // Initialize calendar immediately if no user ID
    }


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

    // Note: calendarStatusFilterSelect event listener is now inside initializeCalendar
    // to ensure 'calendar' object is available.
});
