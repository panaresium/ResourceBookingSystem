// static/js/resource_booking.js
document.addEventListener('DOMContentLoaded', () => {
    // Attempt to find a specific container for resources.
    // If 'resource-buttons-container' (from current resources.html) is the intended list, use it.
    // Otherwise, use 'resource-list-container' as a generic ID, or fallback to document.body.
    const resourceListContainer = document.getElementById('resource-buttons-container') || document.getElementById('resource-list-container');
    const statusDiv = document.getElementById('resources-page-status'); // Optional status div for this page

    // Function to display status messages on this page
    function showResourcePageStatus(message, type = 'info') {
        if (statusDiv) {
            statusDiv.textContent = message;
            statusDiv.className = `alert alert-${type} mt-2`; // Added margin for spacing
            statusDiv.style.display = 'block';
        } else {
            // Fallback if no specific status div is on the page
            const mainStatusDiv = document.getElementById('main-status-message'); // Check for a global status div
            if (mainStatusDiv) {
                 mainStatusDiv.textContent = message;
                 mainStatusDiv.className = `alert alert-${type}`;
                 mainStatusDiv.style.display = 'block';
            } else {
                console.log(`Resource Page Status (${type}): ${message}`);
                // alert(`Status (${type}): ${message}`); // Avoid alert if possible
            }
        }
    }

    const containerToWatch = resourceListContainer || document.body;

    containerToWatch.addEventListener('click', function(event) {
        const target = event.target;
        const bookButton = target.closest('.book-resource-btn'); // Standardized class for book buttons

        if (bookButton) {
            const resourceId = bookButton.dataset.resourceId;
            const resourceName = bookButton.dataset.resourceName;
            // userNameForRecord is crucial for creating bookings.
            // booking_modal_handler.js expects this in currentModalOptions.userNameForRecord
            const globalUserName = document.body.dataset.userName;

            if (!resourceId || !resourceName) {
                console.error('Book button clicked, but resourceId or resourceName is missing from data attributes.');
                showResourcePageStatus('Could not initiate booking: resource data missing.', 'danger');
                return;
            }

            if (!globalUserName && globalUserName !== "") { // Check if it's undefined or null, empty string is allowed for anonymous if backend supports
                console.error('User name for record (globalUserName) is not available. Cannot create booking.');
                showResourcePageStatus('Cannot initiate booking: user information missing. Please ensure you are logged in.', 'danger');
                return;
            }


            if (typeof openBookingModal === 'function') {
                openBookingModal({
                    mode: 'create',
                    resourceId: resourceId,
                    resourceName: resourceName,
                    bookingId: null,
                    currentTitle: `Booking for ${resourceName}`,
                    currentStartTimeISO: null,
                    currentEndTimeISO: null,
                    userNameForRecord: globalUserName, // This is passed to the modal handler
                    onSaveSuccess: function(newBookingData) {
                        console.log('New booking created successfully via resources page:', newBookingData);
                        showResourcePageStatus(`Successfully booked ${resourceName}! Booking ID: ${newBookingData.bookings && newBookingData.bookings[0] ? newBookingData.bookings[0].id : 'N/A'}. You will be redirected shortly.`, 'success');
                        setTimeout(() => {
                            // Redirect to "My Bookings" page after a short delay
                             window.location.href = '/my_bookings';
                        }, 3000); // Increased delay for user to read message
                    }
                });
            } else {
                console.error("openBookingModal function is not defined. Ensure booking_modal_handler.js is loaded.");
                showResourcePageStatus("Booking functionality is currently unavailable. Please try again later.", 'danger');
            }
        }
    });

    // Note: The dynamic fetching and rendering of resources (fetchAndDisplayResources example)
    // is not included here as per the subtask focus, but would be necessary if resources
    // are not already rendered by the server or another script in resources.html.
    // If resource_management.js handles rendering, ensure buttons have 'book-resource-btn' class
    // and data-resource-id / data-resource-name attributes.
});
