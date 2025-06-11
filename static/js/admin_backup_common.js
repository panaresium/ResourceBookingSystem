// --- Global Interactive Element Selectors ---
const interactiveElementSelectors = [
    '#one-click-backup-btn',
    '#list-backups-btn',
    '.restore-btn',
    '.restore-dry-run-btn',
    '.delete-backup-btn',
    'form[action^="/admin/verify_full_backup/"] button[type="submit"]',
    '#confirm-selective-restore-btn',
    'form[action*="manual_backup_bookings_csv_route"] button[type="submit"]',
    'form[action*="restore_booking_csv_route"] button[type="submit"]',
    'form[action*="verify_booking_csv_backup_route"] button[type="submit"]',
    'form[action*="delete_booking_csv_backup_route"] button[type="submit"]',
    'form[action*="save_booking_csv_schedule_route"] button[type="submit"]',
    '#full-backup-schedule-form button[type="submit"]',
    '#full_backup_enabled',
    '#full_backup_schedule_type',
    '#full_backup_day_of_week',
    '#full_backup_time_of_day',
    '#booking-csv-schedule-form button[type="submit"]',
    '#booking_csv_backup_enabled',
    '#booking_csv_backup_interval_minutes',
    '#booking_backup_type_select',
    '#booking_csv_backup_range_type',
    '#startup-settings-form button[type="submit"]',
    '#auto_restore_booking_records_enabled',
    '#backup-prev-page a.page-link',
    '#backup-next-page a.page-link',
    '#selective-restore-form input.component-checkbox',
    '#selective-restore-form input#component-all',
    // Add new selective booking restore buttons and selects
    '#selectFullBackupForBookingRestore',
    '#btnRestoreBookingsFromFullDb',
    '#selectCsvBackupForBookingRestore',
    '#btnRestoreBookingsFromCsv',
    '#btnRestoreBookingsFromIncremental'
];

function disablePageInteractions() {
    console.log("Disabling page interactions.");
    interactiveElementSelectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
            if (el.tagName === 'A' && el.classList.contains('page-link')) {
                el.classList.add('disabled');
                el.setAttribute('aria-disabled', 'true');
                el.onclick = (event) => event.preventDefault();
            } else {
                el.disabled = true;
            }
        });
    });
}

function enablePageInteractions() {
    console.log("Enabling page interactions.");
    interactiveElementSelectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
            if (el.tagName === 'A' && el.classList.contains('page-link')) {
                el.classList.remove('disabled');
                el.removeAttribute('aria-disabled');
                el.onclick = null;
            } else {
                el.disabled = false;
            }
        });
    });
}

// --- UTC Clock / Server Time Clock ---
function updateUtcClock() {
    const clockElement = document.getElementById('utc-clock');
    if (clockElement) {
        const offsetHours = parseInt(clockElement.dataset.offset) || 0;

        const nowUtc = new Date();
        // Calculate server time by applying the offset to UTC time
        const serverTime = new Date(nowUtc.getTime() + offsetHours * 60 * 60 * 1000);

        // Format the serverTime using UTC methods to reflect the offset time correctly
        const year = serverTime.getUTCFullYear();
        const month = String(serverTime.getUTCMonth() + 1).padStart(2, '0'); // Months are 0-indexed
        const day = String(serverTime.getUTCDate()).padStart(2, '0');
        const hours = String(serverTime.getUTCHours()).padStart(2, '0');
        const minutes = String(serverTime.getUTCMinutes()).padStart(2, '0');
        const seconds = String(serverTime.getUTCSeconds()).padStart(2, '0');

        const formattedTime = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;

        let offsetString = "(UTC)"; // Default to UTC if offset is 0
        if (offsetHours > 0) {
            offsetString = `(UTC+${offsetHours})`;
        } else if (offsetHours < 0) {
            offsetString = `(UTC${offsetHours})`; // Negative sign is included by offsetHours
        }

        clockElement.textContent = `${formattedTime} ${offsetString}`;
    }
}
setInterval(updateUtcClock, 1000);
// updateUtcClock(); // Initial call is at the end of the script

// --- Log Appending ---
function appendLog(logAreaId, message, detail, type = 'info', specificStatusEl = null) {
    const logArea = document.getElementById(logAreaId);
    if (logArea) {
        logArea.style.display = 'block';
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry log-' + type;
        logEntry.textContent = `[${timestamp}] ${message}${detail ? ' - ' + detail : ''}`;
        logArea.appendChild(logEntry);
        logArea.scrollTop = logArea.scrollHeight;
    }
    // Note: specificStatusEl is passed by the caller, so it's fine if it's null here.
    // The original script had this logic, keeping it for functional parity.
    if (specificStatusEl && typeof specificStatusEl === 'object' && specificStatusEl !== null && 'textContent' in specificStatusEl) {
        specificStatusEl.textContent = `${message}${detail ? ' ('+detail+')':''}`;
        specificStatusEl.className = `alert alert-${type === 'error' ? 'danger' : (type === 'success' ? 'success' : 'info')} mt-2`;
    } else if (specificStatusEl) {
        // If specificStatusEl is a string (ID), try to get the element
        const el = document.getElementById(specificStatusEl);
        if (el) {
            el.textContent = `${message}${detail ? ' ('+detail+')':''}`;
            el.className = `alert alert-${type === 'error' ? 'danger' : (type === 'success' ? 'success' : 'info')} mt-2`;
        }
    }
}

// --- Keep Alive ---
function keepAlive() {
    fetch('/ping', { method: 'GET', headers: { 'Accept': 'application/json' } })
    .then(response => {
        if (!response.ok) {
            console.warn('Keep-alive ping failed. Status:', response.status);
            // Attempt to use appendLog, assuming 'backup-log-area' or 'restore-log-area' might exist.
            // This is a best-effort as currentBackupTaskId/currentRestoreTaskId are not global here.
            const logAreaToTry = document.getElementById('backup-log-area') ? 'backup-log-area' : 'restore-log-area';
            appendLog(logAreaToTry,
                      'Session keep-alive ping failed.', `Status: ${response.status}`, 'error');
        }
    })
    .catch(error => {
        console.error('Keep-alive ping error:', error);
        const logAreaToTry = document.getElementById('backup-log-area') ? 'backup-log-area' : 'restore-log-area';
        appendLog(logAreaToTry,
                  'Session keep-alive ping error.', error.message, 'error');
    });
}
setInterval(keepAlive, 4 * 60 * 1000);

// --- Socket.IO Setup ---
const socket = io(); // This makes 'socket' a global variable in this script's scope.
                     // Other scripts loaded after this can access it if they don't re-declare.

socket.on('connect', () => {
    console.log('Socket.IO connected from admin_backup_common.js.');
    // Potentially emit an event or update a UI element if needed globally on connect
});
socket.on('disconnect', (reason) => {
    console.warn('Socket.IO disconnected from admin_backup_common.js:', reason);
});
socket.on('connect_error', (error) => {
    console.error('Socket.IO connection error from admin_backup_common.js:', error);
});

// Initial calls if not dependent on DOM elements that need loading first
updateUtcClock(); // Call once immediately to set the clock
