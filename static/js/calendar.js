document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('calendar');
    if (!calendarEl) return;

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        editable: true,
        events: '/api/bookings/calendar',
        eventDrop: handleEventChange,
        eventResize: handleEventChange
    });

    calendar.render();

    async function handleEventChange(info) {
        const event = info.event;
        try {
            await apiCall(`/api/bookings/${event.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_time: event.start.toISOString(),
                    end_time: event.end ? event.end.toISOString() : event.start.toISOString()
                })
            });
        } catch (e) {
            console.error('Failed to update booking time', e);
            info.revert();
        }
    }
});
