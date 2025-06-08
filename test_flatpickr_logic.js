// Helper functions (copied from new_booking_map.js or simplified for testing)
function getTodayDateString() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function getTomorrowDateString() {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const yyyy = tomorrow.getFullYear();
    const mm = String(tomorrow.getMonth() + 1).padStart(2, '0');
    const dd = String(tomorrow.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

// --- Test Setup ---
let MOCKED_CURRENT_DATE = null;

function setMockedTime(hours, minutes) {
    const now = new Date(); // Use current date to keep month/year consistent
    now.setHours(hours, minutes, 0, 0);
    MOCKED_CURRENT_DATE = now;
    console.log(`Mocking current time to: ${MOCKED_CURRENT_DATE.toString()}`);
}

function isPastFivePM() {
    const now = MOCKED_CURRENT_DATE || new Date();
    return now.getHours() >= 17; // 17 is 5 PM in 24-hour format
}

// Simulating the flatpickr disable function
function flatpickrDisableLogic(date) {
    const todayStr = getTodayDateStringForMock(); // Needs to use mocked date for "today"
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return dateStr === todayStr && isPastFivePM();
}

// Simulating the defaultDate calculation
function calculateDefaultDate() {
    if (isPastFivePM()) {
        return getTomorrowDateStringForMock(); // Needs to use mocked date for "tomorrow"
    }
    return getTodayDateStringForMock(); // Needs to use mocked date for "today"
}

// Helper functions that respect mocked time for "today" and "tomorrow"
function getTodayDateStringForMock() {
    const today = MOCKED_CURRENT_DATE || new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function getTomorrowDateStringForMock() {
    const tomorrow = new Date(MOCKED_CURRENT_DATE || new Date());
    tomorrow.setDate(tomorrow.getDate() + 1);
    const yyyy = tomorrow.getFullYear();
    const mm = String(tomorrow.getMonth() + 1).padStart(2, '0');
    const dd = String(tomorrow.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function getDateObject(dateStr) { // "YYYY-MM-DD"
    const parts = dateStr.split('-');
    return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
}


// --- Test Execution ---
console.log("--- Test Suite for Flatpickr Logic ---");

// Scenario 1: Current time is before 5 PM (e.g., 10:00 AM)
console.log("\nScenario 1: Time is 10:00 AM (Before 5 PM)");
setMockedTime(10, 0); // 10:00 AM

let todayForScenario1 = getDateObject(getTodayDateStringForMock());
let defaultDateScenario1 = calculateDefaultDate();
let isTodayDisabledScenario1 = flatpickrDisableLogic(todayForScenario1);

console.log(`Today's date: ${getTodayDateStringForMock()}`);
console.log(`Calculated defaultDate: ${defaultDateScenario1}`);
console.log(`Is today disabled? ${isTodayDisabledScenario1}`);

if (defaultDateScenario1 === getTodayDateStringForMock() && !isTodayDisabledScenario1) {
    console.log("Scenario 1 PASSED");
} else {
    console.error(`Scenario 1 FAILED: defaultDate was ${defaultDateScenario1} (expected today), isTodayDisabled was ${isTodayDisabledScenario1} (expected false)`);
}

// Scenario 2: Current time is after 5 PM (e.g., 6:00 PM)
console.log("\nScenario 2: Time is 6:00 PM (After 5 PM)");
setMockedTime(18, 0); // 6:00 PM

let todayForScenario2 = getDateObject(getTodayDateStringForMock());
let defaultDateScenario2 = calculateDefaultDate();
let isTodayDisabledScenario2 = flatpickrDisableLogic(todayForScenario2);

console.log(`Today's date: ${getTodayDateStringForMock()}`);
console.log(`Tomorrow's date: ${getTomorrowDateStringForMock()}`);
console.log(`Calculated defaultDate: ${defaultDateScenario2}`);
console.log(`Is today disabled? ${isTodayDisabledScenario2}`);

if (defaultDateScenario2 === getTomorrowDateStringForMock() && isTodayDisabledScenario2) {
    console.log("Scenario 2 PASSED");
} else {
    console.error(`Scenario 2 FAILED: defaultDate was ${defaultDateScenario2} (expected tomorrow), isTodayDisabled was ${isTodayDisabledScenario2} (expected true)`);
}

// Scenario 3: Test a past date (e.g., yesterday)
// This is primarily handled by flatpickr's minDate: "today" option,
// but we can check our disable function just to be sure it doesn't interfere.
console.log("\nScenario 3: Checking a past date (Yesterday)");
setMockedTime(10, 0); // Reset time to before 5 PM for consistency
const yesterday = new Date(MOCKED_CURRENT_DATE || new Date());
yesterday.setDate(yesterday.getDate() - 1);
let isYesterdayDisabled = flatpickrDisableLogic(yesterday);
console.log(`Yesterday's date: ${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`);
console.log(`Is yesterday disabled by our custom logic? ${isYesterdayDisabled}`);
if (!isYesterdayDisabled) {
    console.log("Scenario 3 PASSED (custom logic does not disable past dates, minDate handles this)");
} else {
    console.error("Scenario 3 FAILED: Custom logic disabled yesterday, it shouldn't.");
}
console.log("Note: Past dates being disabled is primarily the role of flatpickr's `minDate: 'today'` option, not the custom `disable` function.");


console.log("\n--- End of Test Suite ---");
