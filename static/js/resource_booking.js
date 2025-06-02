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

    async function fetchAndDisplayResources() {
        // Use the resourceListContainer defined at the top of the DOMContentLoaded listener
        if (!resourceListContainer) {
            // This message might not be visible if statusDiv itself is not found or is part of a non-existent container
            console.error("Resource list container not found on the page. Cannot display resources.");
            showResourcePageStatus("Cannot display resources: page element missing.", "danger");
            return;
        }

        // Clear loading message from HTML template if it exists within this container
        const loadingMessage = resourceListContainer.querySelector('p');
        if (loadingMessage && loadingMessage.textContent.includes('Loading resources...')) {
            loadingMessage.remove();
        }
        showResourcePageStatus("Loading resources...", "info");


        try {
            const resources = await apiCall('/api/resources'); // Public endpoint to get published resources

            resourceListContainer.innerHTML = ''; // Clear loading message or previous content

            if (!resources || resources.length === 0) {
                resourceListContainer.innerHTML = '<p>No resources available at the moment.</p>';
                showResourcePageStatus("No resources found.", "info"); // Update status
                return;
            }

            resources.forEach(resource => {
                const resourceElement = document.createElement('div');
                resourceElement.className = 'col-md-4 mb-4'; // Bootstrap column for grid layout

                // Use a card structure for better presentation
                resourceElement.innerHTML = `
                    <div class="card resource-item h-100">
                        ${resource.image_url ? `<img src="${resource.image_url}" class="card-img-top" alt="${resource.name}" style="max-height: 200px; object-fit: cover;">` : '<div class="card-img-top bg-secondary d-flex align-items-center justify-content-center" style="height: 200px;"><span class="text-light">No Image</span></div>'}
                        <div class="card-body d-flex flex-column">
                            <h5 class="card-title">${resource.name}</h5>
                            <p class="card-text mb-1"><small class="text-muted">ID: ${resource.id}</small></p>
                            <p class="card-text flex-grow-1">
                                ${resource.description ? resource.description.substring(0,100) + (resource.description.length > 100 ? '...' : '') : 'No description available.'}
                            </p>
                            <ul class="list-group list-group-flush mb-2">
                                <li class="list-group-item">Capacity: ${resource.capacity || 'N/A'}</li>
                                <li class="list-group-item">Equipment: ${resource.equipment || 'N/A'}</li>
                                ${resource.tags ? `<li class="list-group-item">Tags: ${resource.tags}</li>` : ''}
                            </ul>
                            <button class="btn btn-primary book-resource-btn mt-auto"
                                    data-resource-id="${resource.id}"
                                    data-resource-name="${resource.name}">
                                Book Now
                            </button>
                        </div>
                    </div>
                `;
                resourceListContainer.appendChild(resourceElement);
            });
            if (statusDiv && statusDiv.textContent === "Loading resources...") { // Clear loading message if no other message replaced it
                 statusDiv.style.display = 'none';
            }
        } catch (error) {
            console.error("Failed to fetch and display resources:", error);
            if (resourceListContainer) {
                resourceListContainer.innerHTML = '<p class="text-danger">Error loading resources. Please try refreshing the page.</p>';
            }
            showResourcePageStatus(`Error loading resources: ${error.message || 'Please try refreshing.'}`, "danger");
        }
    }

    // Call fetchAndDisplayResources if the container exists
    if (resourceListContainer) {
        fetchAndDisplayResources();
    } else {
        // This case is technically handled inside fetchAndDisplayResources, but good to be explicit.
        console.warn("Resource list container ('resource-buttons-container' or 'resource-list-container') not found. Resources will not be displayed by resource_booking.js.");
        showResourcePageStatus("Resource display area not found on page.", "warning");
    }
});
