// Mocking external dependencies and global functions
const mockApiCall = jest.fn().mockResolvedValue({ success: true, bookings: [], pagination: {} });
const mockShowLoading = jest.fn();
const mockShowError = jest.fn();
const mockShowSuccess = jest.fn();

let mockFlatpickrInstance = {
    selectedDates: [],
    clear: jest.fn(),
    destroy: jest.fn() // It's good practice to mock destroy as well
};
const mockFlatpickr = jest.fn().mockImplementation(() => mockFlatpickrInstance);

// Assign mocks to where the script expects them
global.apiCall = mockApiCall;
global.showLoading = mockShowLoading;
global.showError = mockShowError;
global.showSuccess = mockShowSuccess;
global.flatpickr = mockFlatpickr;

// Helper to reset DOM and mocks before each test
function setupDOM() {
    document.body.innerHTML = `
        <select id="my-bookings-date-filter-type">
            <option value="any" selected>Any Date</option>
            <option value="specific">Specific Date</option>
        </select>
        <div id="my-bookings-datepicker-container" style="display: none;">
            <input type="text" id="my-bookings-specific-date-filter">
        </div>
        <button id="apply-my-bookings-filters-btn">Apply Filters</button>
        <button id="clear-my-bookings-filters-btn">Clear Filters</button>
        <div id="upcoming-bookings-container"></div>
        <div id="past-bookings-container"></div>
        <div id="upcoming_bk_pg_pagination_controls_container"></div>
        <div id="past_bk_pg_pagination_controls_container"></div>
        <input type="checkbox" id="toggle-upcoming-bookings" checked>
        <input type="checkbox" id="toggle-past-bookings" checked>
        <div id="my-bookings-status"></div>
        <template id="booking-item-template"></template>
        <!-- Add other elements your script might interact with -->
        <select id="my-bookings-status-filter"><option value="">All</option></select>
        <input type="text" id="resource-name-filter">
    `;
}

// Function to initialize the my_bookings.js script logic
// This assumes your my_bookings.js code is wrapped in a DOMContentLoaded listener
// or can be manually triggered. For this example, we'll manually call the setup part.
function initializeMyBookingsScript() {
    // Reset mocks for each initialization
    mockApiCall.mockClear().mockResolvedValue({ success: true, bookings: [], pagination: { total_items: 0, total_pages: 0, current_page: 1} });
    mockFlatpickr.mockClear();
    mockFlatpickrInstance.clear.mockClear();
    mockFlatpickrInstance.destroy.mockClear();
    mockFlatpickrInstance.selectedDates = [];


    // Simulate DOMContentLoaded
    const script = require('../my_bookings.js'); // This path needs to be correct relative to test runner env
    // If my_bookings.js adds event listeners directly, you might need to re-run its main function
    // For simplicity, let's assume event listeners are re-added or we can trigger them.
    // Or, if your script is wrapped in a function, call that function.
    // document.dispatchEvent(new Event('DOMContentLoaded'));
    // This is a simplified way; Jest/Jasmine might require different setup for script loading.
}


describe('My Bookings Date Filter', () => {
    beforeEach(() => {
        setupDOM();
        // Manually ensure the script's event listeners and initial setup are run.
        // This is a simplified approach. In a real Jest environment, you might use jest.resetModules()
        // and then re-require the script if it self-initializes on DOMContentLoaded.
        // For now, we'll simulate re-attaching listeners or re-running setup logic as needed.
        // This might involve extracting the core logic of my_bookings.js into an init function.
        // For this example, we'll directly manipulate and check elements.

        // Re-initialize parts of the my_bookings.js logic as if it's loading for the first time.
        // This is a placeholder for how you'd re-run your script's setup.
        // A better way is to have an init function in my_bookings.js that you can call.
        // For now, elements are fetched inside tests or helper functions.
        // We will load and execute my_bookings.js for each relevant test section if needed.
        // However, since my_bookings.js is likely adding event listeners on DOMContentLoaded,
        // those listeners need to be active.
        // The `require('../my_bookings.js')` line in initializeMyBookingsScript is a conceptual placeholder.
        // In a real Jest setup, you'd configure JSDOM and ensure the script executes.

        // Let's assume my_bookings.js has an init function or its event listeners are set up
        // by virtue of being included. For this example, we'll manually trigger handlers
        // or check states that would be affected by those handlers.
    });

    // Helper function to simulate DOMContentLoaded and run the script
    // This is a simplified representation.
    const loadScript = () => {
        // In a real test environment, you'd ensure the script is loaded and executed.
        // This might involve using jest.isolateModules or similar.
        // For this example, we'll assume event listeners from my_bookings.js are attached
        // when this is called (or relevant parts are re-initialized).
        // This is highly dependent on how my_bookings.js is structured.
        // If it's all inside DOMContentLoaded, you'd dispatch that event.
        document.dispatchEvent(new Event('DOMContentLoaded'));
    };


    describe('Initialization', () => {
        test('should NOT initialize flatpickr and hide container if date filter type is "any" on load', () => {
            loadScript(); // Simulate script loading
            const datePickerContainer = document.getElementById('my-bookings-datepicker-container');
            expect(datePickerContainer.classList.contains('d-none')).toBe(true);
            expect(datePickerContainer.style.display).toBe('none');
            expect(mockFlatpickr).not.toHaveBeenCalled();
        });

        test('should initialize flatpickr and show container if date filter type is "specific" on load', () => {
            document.getElementById('my-bookings-date-filter-type').value = 'specific';
            loadScript();

            const datePickerContainer = document.getElementById('my-bookings-datepicker-container');
            expect(datePickerContainer.classList.contains('d-none')).toBe(false);
            expect(datePickerContainer.style.display).toBe('flex');
            expect(mockFlatpickr).toHaveBeenCalledWith(
                document.getElementById('my-bookings-specific-date-filter'),
                expect.objectContaining({ dateFormat: "Y-m-d" })
            );
        });
    });

    describe('Date filter type change', () => {
        beforeEach(() => {
            loadScript(); // Ensure event listeners from my_bookings.js are active
        });

        test('should show date picker and initialize flatpickr when type changes to "specific"', () => {
            const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
            const datePickerContainer = document.getElementById('my-bookings-datepicker-container');
            const datePickerInput = document.getElementById('my-bookings-specific-date-filter');

            // Initial state check (assuming it starts as 'any' based on DOM setup)
            expect(datePickerContainer.classList.contains('d-none')).toBe(true);
            expect(datePickerContainer.style.display).toBe('none');

            // Change to "specific"
            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change'));

            expect(datePickerContainer.classList.contains('d-none')).toBe(false);
            expect(datePickerContainer.style.display).toBe('flex');
            expect(mockFlatpickr).toHaveBeenCalledWith(datePickerInput, expect.any(Object));
        });

        test('should hide date picker when type changes back to "any"', () => {
            const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
            const datePickerContainer = document.getElementById('my-bookings-datepicker-container');

            // First, change to "specific" to initialize flatpickr and show container
            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change'));
            expect(datePickerContainer.classList.contains('d-none')).toBe(false);
            expect(datePickerContainer.style.display).toBe('flex');

            // Change back to "any"
            dateFilterTypeSelect.value = 'any';
            dateFilterTypeSelect.dispatchEvent(new Event('change'));

            expect(datePickerContainer.classList.contains('d-none')).toBe(true);
            expect(datePickerContainer.style.display).toBe('none');
        });

        test('should only initialize flatpickr once even if "specific" is selected multiple times', () => {
            const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
            loadScript(); // Load script to attach listeners

            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change')); // First call
            expect(mockFlatpickr).toHaveBeenCalledTimes(1);

            dateFilterTypeSelect.value = 'any';
            dateFilterTypeSelect.dispatchEvent(new Event('change'));

            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change')); // Second call
            expect(mockFlatpickr).toHaveBeenCalledTimes(1); // Should still be 1 if initialized correctly
        });
    });

    describe('API call modification (fetchUpcomingBookings and fetchPastBookings)', () => {
        beforeEach(() => {
            loadScript(); // Ensure event listeners and fetch functions are set up
            // Ensure applyFiltersBtn exists and has its listener
            const applyFiltersBtn = document.getElementById('apply-my-bookings-filters-btn');
            if (!applyFiltersBtn) throw new Error("Apply filters button not found in DOM for test setup");
        });

        const testCases = [
            { fetchFnName: 'fetchUpcomingBookings', apiUrlPart: '/api/bookings/upcoming' },
            { fetchFnName: 'fetchPastBookings', apiUrlPart: '/api/bookings/past' }
        ];

        testCases.forEach(({ fetchFnName, apiUrlPart }) => {
            describe(fetchFnName, () => {
                test(`should include date_filter when type is "specific" and date is selected`, async () => {
                    const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
                    const applyFiltersBtn = document.getElementById('apply-my-bookings-filters-btn');

                    // Setup: select "specific", mock a date selection
                    dateFilterTypeSelect.value = 'specific';
                    dateFilterTypeSelect.dispatchEvent(new Event('change')); // Initialize flatpickr

                    const testDate = new Date(2023, 9, 26); // October 26, 2023
                    mockFlatpickrInstance.selectedDates = [testDate];

                    // Trigger filter application which calls fetch functions
                    applyFiltersBtn.click();
                    await Promise.resolve(); // Allow promises in fetch to resolve

                    expect(mockApiCall).toHaveBeenCalledWith(
                        expect.stringContaining(`${apiUrlPart}?`),
                        expect.anything(), // options object
                        expect.anything()  // statusDiv element
                    );
                    const calledUrl = mockApiCall.mock.calls.find(call => call[0].includes(apiUrlPart))[0];
                    expect(calledUrl).toContain('date_filter=2023-10-26');
                });

                test(`should NOT include date_filter when type is "any"`, async () => {
                    document.getElementById('my-bookings-date-filter-type').value = 'any';
                    mockFlatpickrInstance.selectedDates = [new Date(2023, 9, 26)]; // Date is selected but type is "any"

                    document.getElementById('apply-my-bookings-filters-btn').click();
                    await Promise.resolve();

                    const calledUrl = mockApiCall.mock.calls.find(call => call[0].includes(apiUrlPart))[0];
                    expect(calledUrl).not.toContain('date_filter=');
                });

                test(`should NOT include date_filter when type is "specific" but no date selected`, async () => {
                    document.getElementById('my-bookings-date-filter-type').value = 'specific';
                    document.getElementById('my-bookings-date-filter-type').dispatchEvent(new Event('change'));
                    mockFlatpickrInstance.selectedDates = []; // No date selected

                    document.getElementById('apply-my-bookings-filters-btn').click();
                    await Promise.resolve();

                    const calledUrl = mockApiCall.mock.calls.find(call => call[0].includes(apiUrlPart))[0];
                    expect(calledUrl).not.toContain('date_filter=');
                });
            });
        });
    });

    describe('Clear Filters button', () => {
        beforeEach(() => {
            loadScript(); // Ensure event listeners are active
        });

        test('should reset date filter type, hide date picker, and clear flatpickr instance', () => {
            const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
            const datePickerContainer = document.getElementById('my-bookings-datepicker-container');
            const clearFiltersBtn = document.getElementById('clear-my-bookings-filters-btn');

            // Setup: select "specific" and imagine a date is selected
            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change')); // Initialize flatpickr, show container
            mockFlatpickrInstance.selectedDates = [new Date()];

            clearFiltersBtn.click();

            expect(dateFilterTypeSelect.value).toBe('any');
            expect(datePickerContainer.classList.contains('d-none')).toBe(true);
            expect(datePickerContainer.style.display).toBe('none');
            expect(mockFlatpickrInstance.clear).toHaveBeenCalled();
        });
    });

    describe('Status Filter Auto-Refresh', () => {
        beforeEach(() => {
            loadScript(); // Ensure event listeners are active
            mockApiCall.mockClear(); // Clear previous calls before this test
        });

        test('should call handleFilterOrToggleChange (and thus fetch bookings) when status filter changes', async () => {
            const statusFilter = document.getElementById('my-bookings-status-filter');
            if (!statusFilter) throw new Error("Status filter select not found in DOM for test");

            statusFilter.value = 'approved'; // Change value
            statusFilter.dispatchEvent(new Event('change')); // Dispatch event

            // handleFilterOrToggleChange calls fetchUpcomingBookings and fetchPastBookings
            // Each of those makes one apiCall if the respective section is visible.
            // Assuming both upcoming and past are visible by default in tests (checkboxes checked).

            // Check if apiCall was made for upcoming bookings
            expect(mockApiCall).toHaveBeenCalledWith(
                expect.stringContaining('/api/bookings/upcoming'),
                expect.anything(),
                expect.anything()
            );
            // Check if apiCall was made for past bookings
            expect(mockApiCall).toHaveBeenCalledWith(
                expect.stringContaining('/api/bookings/past'),
                expect.anything(),
                expect.anything()
            );
            // Ensure it was called at least for these two. Could be more if other fetches are triggered.
            expect(mockApiCall.mock.calls.length).toBeGreaterThanOrEqual(2);
        });
    });

    describe('Flatpickr Interaction - Auto-refresh on date selection', () => {
        beforeEach(() => {
            loadScript(); // Load my_bookings.js to attach its event listeners

            // Ensure Flatpickr is initialized for these tests
            const dateFilterTypeSelect = document.getElementById('my-bookings-date-filter-type');
            dateFilterTypeSelect.value = 'specific';
            dateFilterTypeSelect.dispatchEvent(new Event('change')); // This should trigger flatpickr initialization

            // Clear any API calls that might have happened during setup (e.g., initial load)
            mockApiCall.mockClear();
        });

        test('should call handleFilterOrToggleChange when Flatpickr onClose is triggered', () => {
            // Ensure flatpickr was called and we can get its options
            expect(mockFlatpickr).toHaveBeenCalled();
            const flatpickrOptions = mockFlatpickr.mock.calls[0][1]; // Get options from the first call

            if (flatpickrOptions && typeof flatpickrOptions.onClose === 'function') {
                // Simulate Flatpickr's onClose being called
                // Parameters for onClose: selectedDates, dateStr, instance
                // The actual values might not matter if onClose always calls handleFilterOrToggleChange
                mockFlatpickrInstance.selectedDates = [new Date(2024, 0, 15)]; // Simulate a date is selected
                flatpickrOptions.onClose(mockFlatpickrInstance.selectedDates, '2024-01-15', mockFlatpickrInstance);
            } else {
                throw new Error('Flatpickr onClose callback not captured or not a function. Check mockFlatpickr setup and script logic.');
            }

            // Verify handleFilterOrToggleChange was called (indirectly, by checking apiCall)
            // Expect calls for both upcoming and past bookings
            expect(mockApiCall).toHaveBeenCalledWith(
                expect.stringContaining('/api/bookings/upcoming'),
                expect.anything(),
                expect.anything()
            );
            expect(mockApiCall).toHaveBeenCalledWith(
                expect.stringContaining('/api/bookings/past'),
                expect.anything(),
                expect.anything()
            );
            expect(mockApiCall.mock.calls.length).toBeGreaterThanOrEqual(2);

            // Also check if the date_filter parameter is now part of the URL
             const upcomingCall = mockApiCall.mock.calls.find(call => call[0].includes('/api/bookings/upcoming'));
             expect(upcomingCall[0]).toContain('date_filter=2024-01-15');
             const pastCall = mockApiCall.mock.calls.find(call => call[0].includes('/api/bookings/past'));
             expect(pastCall[0]).toContain('date_filter=2024-01-15');
        });

        test('should still call handleFilterOrToggleChange if Flatpickr onClose is triggered with no date selected (cleared)', () => {
            expect(mockFlatpickr).toHaveBeenCalled();
            const flatpickrOptions = mockFlatpickr.mock.calls[0][1];

            if (flatpickrOptions && typeof flatpickrOptions.onClose === 'function') {
                mockFlatpickrInstance.selectedDates = []; // Simulate date cleared
                flatpickrOptions.onClose([], '', mockFlatpickrInstance);
            } else {
                throw new Error('Flatpickr onClose callback not captured or not a function.');
            }

            expect(mockApiCall.mock.calls.length).toBeGreaterThanOrEqual(2); // Fetches should still occur
            const upcomingCall = mockApiCall.mock.calls.find(call => call[0].includes('/api/bookings/upcoming'));
            expect(upcomingCall[0]).not.toContain('date_filter='); // Date filter should not be present
            const pastCall = mockApiCall.mock.calls.find(call => call[0].includes('/api/bookings/past'));
            expect(pastCall[0]).not.toContain('date_filter='); // Date filter should not be present
        });
    });
});

// Note: To run these tests, you'd typically use a test runner like Jest.
// You would need to configure Jest to handle JS files (e.g., using Babel if you use ES6+ features not in Node)
// and set up a JSDOM environment for DOM access.
// The `require('../my_bookings.js')` line is a placeholder for how you'd make the script's code
// available and executable in the test environment. Jest's `jest.mock` and module system would handle this.
// For example, if my_bookings.js is an ES module:
// jest.mock('../my_bookings.js'); // then import functions or trigger its main execution.
// Or, if it's a simple script that attaches to DOMContentLoaded, dispatching that event is key.
// This example assumes `my_bookings.js` modifies the global scope or has an initialization function
// that can be called or triggered.
// The `loadScript()` function is a simplified way to represent the script execution.
// In a real Jest setup, you'd typically `require` or `import` the script after setting up mocks
// and the JSDOM environment.
// For example:
// describe('My Bookings', () => {
//   beforeEach(() => {
//     document.body.innerHTML = `...`; // Setup DOM
//     jest.resetModules(); // Important to get a fresh instance of the script
//     // Mock dependencies before requiring the script
//     jest.mock('flatpickr', () => jest.fn().mockImplementation(() => mockFlatpickrInstance), { virtual: true });
//     require('../my_bookings.js'); // Execute the script
//   });
//   // ... tests ...
// });
// The path '../my_bookings.js' in require would need to be correct based on your test file's location.
// This structure provides a solid foundation for testing the date filter functionality.
// The actual execution depends heavily on the test runner and environment setup.
// The key is to ensure the `my_bookings.js` script runs within the test case's context after mocks and DOM are set up.
// Often, refactoring `my_bookings.js` to have an explicit `init()` function that is called on DOMContentLoaded
// makes testing easier, as you can call `init()` directly in your tests.

/**
 * Conceptual structure of my_bookings.js for easier testing:
 *
 * (function() {
 *   function initMyBookings() {
 *     // All the getElementById and addEventListener calls
 *   }
 *
 *   if (document.readyState === 'loading') {
 *     document.addEventListener('DOMContentLoaded', initMyBookings);
 *   } else {
 *     initMyBookings(); // Or ensure it's idempotent if called multiple times
 *   }
 *
 *   // Make initMyBookings available for testing if needed, or ensure DOMContentLoaded works in JSDOM
 *   // window.__test__initMyBookings = initMyBookings; // Example for direct call in tests
 * })();
 */
