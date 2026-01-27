document.addEventListener('DOMContentLoaded', () => {
    let calendarInstance;
    const calendarEl = document.getElementById('calendar');
    const calendarStatusFilterSelect = document.getElementById('calendar-status-filter');

    const calendarElementForOffset = document.getElementById('calendar');
    // offsetHours might be used for logic if we were doing client-side time calc, but we rely on server now mostly.
    const offsetHours = calendarElementForOffset ? parseInt(calendarElementForOffset.dataset.globalOffset) || 0 : 0;

    let unavailableDates = []; // Store fetched unavailable dates

    // Modal elements
    const calendarEditBookingModal = document.getElementById('calendar-edit-booking-modal');
    const cebmCloseModalBtn = document.getElementById('cebm-close-modal-btn');
    const cebmResourceName = document.getElementById('cebm-resource-name');
    const cebmBookingId = document.getElementById('cebm-booking-id');
    const cebmStatusMessage = document.getElementById('cebm-status-message');

    // Edit specific elements
    const cebmEditBookingBtn = document.getElementById('cebm-edit-booking-btn');
    const cebmDeleteBookingBtn = document.getElementById('cebm-delete-booking-btn');
    const cebmEditSection = document.getElementById('cebm-edit-section');
    const cebmEditDate = document.getElementById('cebm-edit-date');
    const cebmEditSlots = document.getElementById('cebm-edit-slots');
    const cebmSaveChangesBtn = document.getElementById('cebm-save-changes-btn');
    const cebmCancelEditBtn = document.getElementById('cebm-cancel-edit-btn');
    const cebmReadOnlyDetails = document.getElementById('cebm-readonly-details');
    const cebmActionButtons = document.getElementById('cebm-action-buttons');

    if (!calendarEl || !calendarStatusFilterSelect || !calendarEditBookingModal) {
        console.error("Required calendar elements not found.");
        return;
    }

    // Initialize flatpickr on the edit date input once
    let editDateFlatpickr;
    if (cebmEditDate) {
        const restrictedPast = calendarEl.dataset.restrictedPast === 'true';
        editDateFlatpickr = flatpickr(cebmEditDate, {
            dateFormat: "Y-m-d",
            minDate: restrictedPast ? "today" : null,
            disable: [], // Will be updated
            onChange: function(selectedDates, dateStr, instance) {
                const bookingId = cebmBookingId.value;
                const resourceId = calendarEditBookingModal.dataset.resourceId; // We'll store this on open
                if (resourceId && bookingId) {
                    fetchAndDisplayAvailableSlots(resourceId, dateStr, bookingId);
                }
            }
        });
    }

    let allUserEvents = []; // Store all user bookings

    async function fetchAndDisplayAvailableSlots(resourceId, dateStr, bookingIdToExclude = null) {
        if (!cebmEditSlots) return;

        cebmEditSlots.innerHTML = '<option value="">Loading...</option>';
        cebmEditSlots.disabled = true;
        cebmStatusMessage.textContent = '';

        try {
            const apiData = await apiCall(`/api/resources/${resourceId}/availability?date=${dateStr}`);

            // apiData structure: { booked_slots: [], standard_slot_statuses: { "first_half": {...}, ... } }
            const bookedSlots = apiData.booked_slots || [];
            const slotStatuses = apiData.standard_slot_statuses || {};

            const standardSlots = [
                { key: 'first_half', text: "08:00 - 12:00", value: "08:00:00,12:00:00" },
                { key: 'second_half', text: "13:00 - 17:00", value: "13:00:00,17:00:00" },
                { key: 'full_day', text: "08:00 - 17:00", value: "08:00:00,17:00:00" }
            ];

            cebmEditSlots.innerHTML = '<option value="">-- Select a time slot --</option>';

            standardSlots.forEach(slot => {
                const statusInfo = slotStatuses[slot.key];

                // Check if passed
                if (statusInfo && statusInfo.is_passed) {
                    // Optionally show passed slots but disabled?
                    // For now, let's just skip them to keep list clean, or show as (Passed)
                    // Showing them as disabled might be better UX.
                    const option = document.createElement('option');
                    option.value = slot.value;
                    option.textContent = `${slot.text} (Passed)`;
                    option.disabled = true;
                    cebmEditSlots.appendChild(option);
                    return;
                }

                // Check for booking conflicts, excluding the current booking
                let isBooked = false;
                const [slotStartStr, slotEndStr] = slot.value.split(',');

                // Convert slot strings to comparable minutes
                const parseTime = (t) => {
                    // Handle HH:MM:SS or HH:MM
                    const [h, m] = t.split(':').map(Number);
                    return h * 60 + m;
                };
                const slotStartMins = parseTime(slotStartStr);
                const slotEndMins = parseTime(slotEndStr);

                for (const booking of bookedSlots) {
                    if (String(booking.booking_id) === String(bookingIdToExclude)) continue;

                    const bStartMins = parseTime(booking.start_time);
                    const bEndMins = parseTime(booking.end_time);

                    // Check overlap
                    if (slotStartMins < bEndMins && slotEndMins > bStartMins) {
                        isBooked = true;
                        break;
                    }
                }

                if (isBooked) {
                    const option = document.createElement('option');
                    option.value = slot.value;
                    option.textContent = `${slot.text} (Unavailable)`;
                    option.disabled = true;
                    cebmEditSlots.appendChild(option);
                } else {
                    const option = document.createElement('option');
                    option.value = slot.value;
                    option.textContent = slot.text;
                    cebmEditSlots.appendChild(option);
                }
            });

            cebmEditSlots.disabled = false;
            // If all options are disabled (except default), show message?
            const enabledOptions = Array.from(cebmEditSlots.options).filter(o => !o.disabled && o.value !== "");
            if (enabledOptions.length === 0) {
                // cebmEditSlots.innerHTML = '<option value="">No slots available</option>';
                // cebmEditSlots.disabled = true;
            }

        } catch (error) {
            console.error('Error fetching slots:', error);
            cebmEditSlots.innerHTML = '<option value="">Error loading slots</option>';
            if (cebmStatusMessage) {
                cebmStatusMessage.textContent = 'Failed to load availability.';
                cebmStatusMessage.className = 'status-message error-message';
            }
        }
    }

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

    populateStatusFilter(calendarStatusFilterSelect);

    // --- Logic to initialize and render the calendar ---
    const initializeCalendar = () => {
        let determinedInitialView = 'dayGridMonth'; // Default to month view
        if (window.innerWidth < 768) {
            determinedInitialView = 'timeGridWeek'; // Change to week view for mobile
        }
        calendarInstance = new FullCalendar.Calendar(calendarEl, {
            initialView: determinedInitialView,
            timeZone: 'local',
            selectAllow: function(selectInfo) {
                const startDateStr = selectInfo.startStr.split('T')[0];
                if (unavailableDates.includes(startDateStr)) {
                    return false;
                }
                return true;
            },
            dayCellDidMount: function(arg) {
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
            editable: false,
            eventClick: function(info) {
                // Populate modal with event details
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

                cebmBookingId.value = info.event.id;
                calendarEditBookingModal.dataset.resourceId = info.event.extendedProps.resource_id;

                cebmStatusMessage.textContent = '';
                cebmStatusMessage.className = 'status-message';

                // Reset Edit UI state
                if (cebmEditSection) cebmEditSection.style.display = 'none';
                if (cebmReadOnlyDetails) cebmReadOnlyDetails.style.display = 'block';
                if (cebmActionButtons) cebmActionButtons.style.display = 'block';

                calendarEditBookingModal.style.display = 'block';

                // Setup Delete Button (Existing Logic)
                if (cebmDeleteBookingBtn) {
                    // Clone to remove previous listeners
                    const newDeleteBtn = cebmDeleteBookingBtn.cloneNode(true);
                    cebmDeleteBookingBtn.parentNode.replaceChild(newDeleteBtn, cebmDeleteBookingBtn);

                    newDeleteBtn.onclick = () => {
                        if (confirm("Are you sure you want to delete this booking?")) {
                            const bookingId = cebmBookingId.value;
                            if (!bookingId) {
                                cebmStatusMessage.textContent = 'Error: Booking ID not found.';
                                cebmStatusMessage.className = 'status-message error-message';
                                return;
                            }

                            newDeleteBtn.disabled = true;
                            newDeleteBtn.textContent = 'Deleting...';
                            cebmStatusMessage.textContent = '';
                            cebmStatusMessage.className = 'status-message';

                            apiCall(`/api/bookings/${bookingId}`, { method: 'DELETE' })
                                .then(response => {
                                    cebmStatusMessage.textContent = response.message || 'Booking deleted successfully!';
                                    cebmStatusMessage.className = 'status-message success-message';
                                    const eventToRemove = calendarInstance.getEventById(bookingId);
                                    if (eventToRemove) eventToRemove.remove();
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
                                    newDeleteBtn.disabled = false;
                                    newDeleteBtn.textContent = 'Delete Booking';
                                });
                        }
                    };
                }

                // Setup Edit Button
                if (cebmEditBookingBtn) {
                    const newEditBtn = cebmEditBookingBtn.cloneNode(true);
                    cebmEditBookingBtn.parentNode.replaceChild(newEditBtn, cebmEditBookingBtn);

                    newEditBtn.onclick = () => {
                        // Switch UI to Edit Mode
                        if (cebmReadOnlyDetails) cebmReadOnlyDetails.style.display = 'none';
                        if (cebmActionButtons) cebmActionButtons.style.display = 'none';
                        if (cebmEditSection) cebmEditSection.style.display = 'block';

                        // Initialize/Update Date Picker
                        const eventDateObj = info.event.start;
                        const dateStr = eventDateObj.toISOString().split('T')[0]; // YYYY-MM-DD

                        if (editDateFlatpickr) {
                            editDateFlatpickr.setDate(dateStr);
                        } else if (cebmEditDate) {
                             cebmEditDate.value = dateStr; // Fallback if flatpickr failed
                        }

                        // Fetch slots for this date
                        fetchAndDisplayAvailableSlots(info.event.extendedProps.resource_id, dateStr, info.event.id);
                    };
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

                        allUserEvents = [];

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
                                allUserEvents = mappedEvents;
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
                    const MAX_TIME_LENGTH = 18;

                    let displayTitle = arg.event.title;
                    if (arg.event.title.length > MAX_TITLE_LENGTH) {
                        displayTitle = arg.event.title.substring(0, MAX_TITLE_LENGTH - 3) + "...";
                    }

                    const location = arg.event.extendedProps.location || "N/A";
                    const floor = arg.event.extendedProps.floor || "N/A";
                    const resourceName = arg.event.extendedProps.resource_name || "N/A";

                    let eventHtml = `<b>${displayTitle}</b>`;
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
                            eventHtml += `<br>${displayTime}`;
                        }
                    }
                    return { html: eventHtml };
                }
                return { html: `<b>${arg.event.title}</b>` };
            }
        });
        calendarInstance.render();
    };

    // --- Fetching user ID and then potentially unavailable dates ---
    let currentUserId = null;
    if (calendarEl && calendarEl.dataset.userId) {
        currentUserId = calendarEl.dataset.userId;
    } else if (typeof window.currentUserId !== 'undefined') {
        currentUserId = window.currentUserId;
    }

    const floorSelector = document.getElementById('floor-selector');

    function fetchUnavailableDates() {
        if (currentUserId) {
            const floorId = floorSelector.value;
            let apiUrl = `/api/resources/unavailable_dates?user_id=${currentUserId}`;
            if (floorId) {
                apiUrl += `&floor_ids=${floorId}`;
            }
            apiCall(apiUrl)
                .then(dates => {
                    unavailableDates = dates;
                    if (editDateFlatpickr) {
                        editDateFlatpickr.set('disable', unavailableDates);
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
                unavailableDates = dates;
                if (editDateFlatpickr) {
                    editDateFlatpickr.set('disable', unavailableDates);
                }
            })
            .catch(error => {
                console.error('Error fetching unavailable dates:', error);
            })
            .finally(() => {
                initializeCalendar();
            });
    } else {
        console.info('User ID not found for this calendar instance.');
        initializeCalendar();
    }

    if (floorSelector) {
        floorSelector.addEventListener('change', fetchUnavailableDates);
    }

    // Modal Close
    if (cebmCloseModalBtn) {
        cebmCloseModalBtn.addEventListener('click', () => {
            calendarEditBookingModal.style.display = 'none';
        });
    }

    window.addEventListener('click', (event) => {
        if (event.target === calendarEditBookingModal) {
            calendarEditBookingModal.style.display = 'none';
        }
    });

    // Edit Section Buttons
    if (cebmCancelEditBtn) {
        cebmCancelEditBtn.addEventListener('click', () => {
            if (cebmEditSection) cebmEditSection.style.display = 'none';
            if (cebmReadOnlyDetails) cebmReadOnlyDetails.style.display = 'block';
            if (cebmActionButtons) cebmActionButtons.style.display = 'block';
            cebmStatusMessage.textContent = '';
            cebmStatusMessage.className = 'status-message';
        });
    }

    if (cebmSaveChangesBtn) {
        cebmSaveChangesBtn.addEventListener('click', async () => {
            const bookingId = cebmBookingId.value;
            const newDate = cebmEditDate.value;
            const selectedSlot = cebmEditSlots.value;

            if (!bookingId || !newDate || !selectedSlot) {
                cebmStatusMessage.textContent = 'Please select a date and a time slot.';
                cebmStatusMessage.className = 'status-message error-message';
                return;
            }

            const [startTime, endTime] = selectedSlot.split(',');
            const startDateTime = `${newDate}T${startTime}`;
            const endDateTime = `${newDate}T${endTime}`;

            cebmSaveChangesBtn.disabled = true;
            cebmSaveChangesBtn.textContent = 'Saving...';
            cebmStatusMessage.textContent = '';

            try {
                const response = await apiCall(`/api/bookings/${bookingId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        start_time: startDateTime,
                        end_time: endDateTime
                    })
                });

                cebmStatusMessage.textContent = 'Booking updated successfully!';
                cebmStatusMessage.className = 'status-message success-message';

                // Refresh calendar
                if (calendarInstance) calendarInstance.refetchEvents();

                setTimeout(() => {
                    calendarEditBookingModal.style.display = 'none';
                    cebmStatusMessage.textContent = '';
                    cebmStatusMessage.className = 'status-message';
                    // Reset UI
                    if (cebmEditSection) cebmEditSection.style.display = 'none';
                    if (cebmReadOnlyDetails) cebmReadOnlyDetails.style.display = 'block';
                    if (cebmActionButtons) cebmActionButtons.style.display = 'block';
                }, 1500);

            } catch (error) {
                console.error('Error updating booking:', error);
                cebmStatusMessage.textContent = error.message || 'Failed to update booking.';
                cebmStatusMessage.className = 'status-message error-message';
            } finally {
                cebmSaveChangesBtn.disabled = false;
                cebmSaveChangesBtn.textContent = 'Save Changes';
            }
        });
    }
});
