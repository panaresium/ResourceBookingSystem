document.addEventListener('DOMContentLoaded', () => {
    let calendarInstance;
    const calendarEl = document.getElementById('calendar');
    const calendarStatusFilterSelect = document.getElementById('calendar-status-filter'); // Changed ID

    const calendarElementForOffset = document.getElementById('calendar');
    const offsetHours = calendarElementForOffset ? parseInt(calendarElementForOffset.dataset.globalOffset) || 0 : 0;

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
    const cebmStatusMessage = document.getElementById('cebm-status-message');
    const cebmDeleteBookingBtn = document.getElementById('cebm-delete-booking-btn'); // Added

    if (!calendarEl || !calendarStatusFilterSelect || !calendarEditBookingModal || !cebmDeleteBookingBtn) { // Added !cebmSaveChangesBtn to the check
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
                { text: "08:00 - 12:00", value: "08:00,12:00" }, // Removed UTC
                { text: "13:00 - 17:00", value: "13:00,17:00" }, // Removed UTC
                { text: "08:00 - 17:00", value: "08:00,17:00" }  // Removed UTC
            ];

            slotsSelect.innerHTML = '<option value="">-- Select a time slot --</option>'; // Reset

            predefinedSlots.forEach(pSlot => {
                const [pSlotStartStr, pSlotEndStr] = pSlot.value.split(',');
                // Construct Date objects for the predefined slot in Local Time
                const predefinedSlotStartLocal = new Date(dateStr + 'T' + pSlotStartStr + ':00'); // No 'Z', parsed as local
                const predefinedSlotEndLocal = new Date(dateStr + 'T' + pSlotEndStr + ':00');     // No 'Z', parsed as local

                let isConflicting = false;
                for (const existingEvent of otherUserBookingsOnDate) {
                    // FullCalendar events store start/end as Date objects (now local due to timeZone: 'local')
                    const existingBookingStart = existingEvent.start;
                    const existingBookingEnd = existingEvent.end;

                    if (existingBookingStart && existingBookingEnd) { // Standard check for events with duration
                        if ((predefinedSlotStartLocal < existingBookingEnd) && (predefinedSlotEndLocal > existingBookingStart)) {
                            isConflicting = true;
                            break;
                        }
                    } else if (existingBookingStart) {
                        // Handle events that might be point-in-time or have missing end dates
                        // This logic assumes such events conflict if they are within the predefined slot
                        if (predefinedSlotStartLocal <= existingBookingStart && predefinedSlotEndLocal > existingBookingStart) {
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
                slotsSelect.innerHTML = '<option value="">No Available Resource</option>';
                slotsSelect.disabled = true;
            } else {
                slotsSelect.disabled = false;
            }

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

    // Populate the new status filter dropdown
    populateStatusFilter(calendarStatusFilterSelect);

    // --- Logic to initialize and render the calendar ---
    const initializeCalendar = () => {
        let determinedInitialView = 'dayGridMonth'; // Default to month view
        if (window.innerWidth < 768) {
            determinedInitialView = 'timeGridWeek'; // Change to week view for mobile
        }
        calendarInstance = new FullCalendar.Calendar(calendarEl, {
            initialView: determinedInitialView,
            timeZone: 'local', // Keep timezone as UTC for consistency with server
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

                // Get references to new read-only display elements
                const roResourceName = document.getElementById('cebm-ro-resource-name');
                const roLocationFloor = document.getElementById('cebm-ro-location-floor');
                const roBookingTitle = document.getElementById('cebm-ro-booking-title');
                const roDatetimeRange = document.getElementById('cebm-ro-datetime-range');

                // Hide the old general resource name display
                const oldResourceNameP = document.getElementById('cebm-resource-name');
                if (oldResourceNameP && oldResourceNameP.parentNode) {
                    oldResourceNameP.parentNode.style.display = 'none';
                }

                // Populate new read-only fields
                if (roResourceName) {
                    roResourceName.textContent = info.event.extendedProps.resource_name || 'N/A';
                }
                if (roLocationFloor) {
                    const location = info.event.extendedProps.location || "N/A";
                    const floor = info.event.extendedProps.floor || "N/A";
                    roLocationFloor.textContent = `${location} - ${floor}`;
                }
                if (roBookingTitle) {
                    roBookingTitle.textContent = info.event.title || 'N/A';
                }
                if (roDatetimeRange && info.event.start) {
                    const startDate = new Date(info.event.start);
                    const year = startDate.getFullYear();
                    const month = (startDate.getMonth() + 1).toString().padStart(2, '0');
                    const day = startDate.getDate().toString().padStart(2, '0');
                    const datePart = `${year}-${month}-${day}`;

                    let startTimeStr, endTimeStr;
                    if (info.event.extendedProps.booking_display_start_time && info.event.extendedProps.booking_display_end_time) {
                        startTimeStr = info.event.extendedProps.booking_display_start_time; // HH:MM
                        endTimeStr = info.event.extendedProps.booking_display_end_time;   // HH:MM
                    } else {
                        const optionsTime = { hour: '2-digit', minute: '2-digit', hour12: false };
                        startTimeStr = startDate.toLocaleTimeString([], optionsTime);
                        if (info.event.end) {
                            const endDate = new Date(info.event.end);
                            endTimeStr = endDate.toLocaleTimeString([], optionsTime);
                        } else {
                            endTimeStr = "N/A";
                        }
                    }
                    roDatetimeRange.textContent = `${datePart} ${startTimeStr} - ${endTimeStr}`;
                } else if (roDatetimeRange) {
                    roDatetimeRange.textContent = 'N/A';
                }

                // Populate existing editable fields (ensure this logic is preserved)
                cebmBookingId.value = info.event.id;

                // This was the old way of setting the general resource name, ensure it's not needed or adapt
                // cebmResourceName.textContent = info.event.extendedProps.resource_name || info.event.title || 'N/A';
                // Since we hid the parent paragraph of 'cebm-resource-name', this line is not strictly necessary for display,
                // but if other JS logic relies on its textContent, it should be reviewed.
                // For now, the new 'cebm-ro-resource-name' handles the display.

                cebmStatusMessage.textContent = ''; // Clear previous messages
                cebmStatusMessage.className = 'status-message';
                calendarEditBookingModal.style.display = 'block';

                const currentDeleteBtnElement = document.getElementById('cebm-delete-booking-btn');

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
                // Preserve existing logic for title and time display for dayGridMonth view
                if (arg.view.type === 'dayGridMonth') {
                    const MAX_TITLE_LENGTH = 20; // Adjusted for potentially longer content
                    const MAX_TIME_LENGTH = 18;

                    let displayTitle = arg.event.title;
                    if (arg.event.title.length > MAX_TITLE_LENGTH) {
                        displayTitle = arg.event.title.substring(0, MAX_TITLE_LENGTH - 3) + "...";
                    }

                    // Access new properties
                    const location = arg.event.extendedProps.location || "N/A";
                    const floor = arg.event.extendedProps.floor || "N/A";
                    const resourceName = arg.event.extendedProps.resource_name || "N/A";

                    // Construct HTML without labels, each on a new line
                    let eventHtml = `<b>${displayTitle}</b>`; // Title is bold
                    eventHtml += `<br>${location} - ${floor}`;
                    eventHtml += `<br>${resourceName}`;

                    if (arg.event.start) {
                        let startTimeDisplay, endTimeDisplay;

                        if (arg.event.extendedProps.booking_display_start_time && arg.event.extendedProps.booking_display_end_time) {
                            startTimeDisplay = arg.event.extendedProps.booking_display_start_time;
                            endTimeDisplay = arg.event.extendedProps.booking_display_end_time;
                        } else {
                            const fallbackStart = new Date(arg.event.start);
                            const fallbackEnd = arg.event.end ? new Date(arg.event.end) : null;
                            const optionsTimeLocal = { hour: '2-digit', minute: '2-digit', hour12: false };
                            startTimeDisplay = fallbackStart.toLocaleTimeString(undefined, optionsTimeLocal);
                            endTimeDisplay = fallbackEnd ? fallbackEnd.toLocaleTimeString(undefined, optionsTimeLocal) : "";
                        }

                        let fullTimeString = '';
                        if (!arg.event.allDay || (startTimeDisplay && (startTimeDisplay !== '00:00' && !startTimeDisplay.endsWith("00:00 UTC")))) {
                            fullTimeString = startTimeDisplay;
                            if (endTimeDisplay && endTimeDisplay !== startTimeDisplay && endTimeDisplay.replace(" UTC", "") !== "") {
                                fullTimeString += ` - ${endTimeDisplay}`;
                            }
                        }

                        if (fullTimeString) {
                            let displayTime = fullTimeString;
                            if (fullTimeString.length > MAX_TIME_LENGTH) {
                                displayTime = fullTimeString.substring(0, MAX_TIME_LENGTH - 3) + "...";
                            }
                            eventHtml += `<br>${displayTime}`; // Time string on a new line
                        }
                    }
                    return { html: eventHtml };
                }
                // For other views, retain original behavior (bold title, FC handles time)
                // Or apply a similar detailed view if desired for other views as well.
                // For now, only modifying month view as per typical calendar detail levels.
                let displayTitleOtherView = arg.event.title;
                // Potentially add location/floor/resource here as well if desired for week/day views
                // const locationOther = arg.event.extendedProps.location || "N/A";
                // const floorOther = arg.event.extendedProps.floor || "N/A";
                // const resourceNameOther = arg.event.extendedProps.resource_name || "N/A";
                // let otherViewHtml = `<b>${displayTitleOtherView}</b><br>L: ${locationOther}-${floorOther}<br>R: ${resourceNameOther}`;
                // return { html: otherViewHtml };
                return { html: `<b>${arg.event.title}</b>` }; // Original behavior for other views
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

    const floorSelector = document.getElementById('floor-selector');
    let flatpickrInstance;

    function fetchUnavailableDates() {
        if (currentUserId) {
            const floorId = floorSelector.value;
            let apiUrl = `/api/resources/unavailable_dates?user_id=${currentUserId}`;
            if (floorId) {
                apiUrl += `&floor_ids=${floorId}`;
            }
            apiCall(apiUrl)
                .then(dates => {
                    unavailableDates = dates; // Populate the global array
                    console.log("Unavailable dates fetched:", unavailableDates);
                    if (flatpickrInstance) {
                        flatpickrInstance.set('disable', unavailableDates);
                    }
                    if (calendarInstance) {
                        calendarInstance.refetchEvents();
                    }
                })
                .catch(error => {
                    console.error('Error fetching unavailable dates:', error);
                });
        }
    }

    if (currentUserId) {
        apiCall(`/api/resources/unavailable_dates?user_id=${currentUserId}`)
            .then(dates => {
                unavailableDates = dates; // Populate the global array
                console.log("Unavailable dates fetched:", unavailableDates);
                flatpickrInstance = flatpickr("#cebm-booking-date", {
                    disable: unavailableDates,
                    dateFormat: "Y-m-d",
                });
            })
            .catch(error => {
                console.error('Error fetching unavailable dates:', error);
                // Proceed without unavailable dates functionality
                flatpickrInstance = flatpickr("#cebm-booking-date", {
                    dateFormat: "Y-m-d",
                });
            })
            .finally(() => {
                initializeCalendar(); // Initialize calendar after API call attempt
            });
    } else {
        console.info('User ID not found for this calendar instance. Skipping fetching unavailable dates. This is normal for "My Calendar" view.');
        initializeCalendar(); // Initialize calendar immediately if no user ID
        flatpickrInstance = flatpickr("#cebm-booking-date", {
            dateFormat: "Y-m-d",
        });
    }

    floorSelector.addEventListener('change', fetchUnavailableDates);


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
