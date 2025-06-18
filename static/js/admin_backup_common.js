// --- Global Interactive Element Selectors ---
let pageInteractionTimeout = null;

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

// --- HTTP Polling Management ---
let activePolls = {}; // Stores active polling intervals: {taskId: intervalId}
let displayedLogCounts = {}; // Stores count of displayed logs for each task: {taskId: count}
const POLLING_INTERVAL_MS = 3000; // Poll every 3 seconds

// Task ID variables (consider scoping them more locally if possible, or manage clearing them)
let currentBackupTaskId = null;
let currentRestoreTaskId = null; // For one-click full restore
let currentSelectiveRestoreTaskId = null;
let currentDryRunTaskId = null;
let currentVerifyTaskId = null;
let currentDeleteTaskId = null;
let currentBulkDeleteTaskId = null;
// Removed: isAwaiting... flags as they were for Socket.IO

function disablePageInteractions() {
    console.log("Disabling page interactions.");
    if (pageInteractionTimeout) {
        clearTimeout(pageInteractionTimeout);
    }
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
    pageInteractionTimeout = setTimeout(enablePageInteractions, 300000); // 5 minutes
}

function enablePageInteractions() {
    console.log("Enabling page interactions.");
    if (pageInteractionTimeout) {
        clearTimeout(pageInteractionTimeout);
        pageInteractionTimeout = null;
    }
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
        const serverTime = new Date(nowUtc.getTime() + offsetHours * 60 * 60 * 1000);
        const year = serverTime.getUTCFullYear();
        const month = String(serverTime.getUTCMonth() + 1).padStart(2, '0');
        const day = String(serverTime.getUTCDate()).padStart(2, '0');
        const hours = String(serverTime.getUTCHours()).padStart(2, '0');
        const minutes = String(serverTime.getUTCMinutes()).padStart(2, '0');
        const seconds = String(serverTime.getUTCSeconds()).padStart(2, '0');
        const formattedTime = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        let offsetString = "(UTC)";
        if (offsetHours > 0) offsetString = `(UTC+${offsetHours})`;
        else if (offsetHours < 0) offsetString = `(UTC${offsetHours})`;
        clockElement.textContent = `${formattedTime} ${offsetString}`;
    }
}
setInterval(updateUtcClock, 1000);

// --- Log Appending ---
// serverTimestamp parameter is ignored for now, keeping client-side timestamp generation.
function appendLog(logAreaId, message, detail, type = 'info', specificStatusEl = null, serverTimestamp = null) {
    const logArea = document.getElementById(logAreaId);
    if (logArea) {
        logArea.style.display = 'block';
        const timestampToDisplay = serverTimestamp ? new Date(serverTimestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry log-' + type;
        logEntry.textContent = `[${timestampToDisplay}] ${message}${detail ? ' - ' + detail : ''}`;
        logArea.appendChild(logEntry);
        logArea.scrollTop = logArea.scrollHeight;
    }
    if (specificStatusEl && typeof specificStatusEl === 'object' && specificStatusEl !== null && 'textContent' in specificStatusEl) {
        specificStatusEl.textContent = `${message}${detail ? ' ('+detail+')':''}`;
        specificStatusEl.className = `alert alert-${type === 'error' ? 'danger' : (type === 'success' ? 'success' : (type === 'warning' ? 'warning' : 'info'))} mt-2`;
    } else if (typeof specificStatusEl === 'string') {
        const el = document.getElementById(specificStatusEl);
        if (el) {
            el.textContent = `${message}${detail ? ' ('+detail+')':''}`;
            el.className = `alert alert-${type === 'error' ? 'danger' : (type === 'success' ? 'success' : (type === 'warning' ? 'warning' : 'info'))} mt-2`;
        }
    }
}

// --- HTTP Task Polling Function ---
function pollTaskStatus(taskId, logAreaId, statusMessageEl, operationType) {
    if (!activePolls[taskId]) { // Polling might have been cancelled elsewhere
        console.log(`Polling for task ${taskId} was cancelled or already stopped.`);
        return;
    }

    if (operationType === 'restore_dry_run') {
        console.log(`pollTaskStatus: Polling for restore_dry_run task ${taskId}. LogArea: ${logAreaId}.`);
    }

    fetch(`/api/task/${taskId}/status`)
        .then(response => {
            if (!response.ok) {
                // For 404, task might not be found (e.g., expired from server after completion)
                if (response.status === 404) {
                    throw new Error(`Task ${taskId} not found. It might have expired or been cleared from the server.`);
                }
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (!data) {
                appendLog(logAreaId, `Polling for ${operationType} task ${taskId}: Received empty data.`, '', 'error', statusMessageEl);
                // Consider stopping poll if data is consistently empty, though HTTP error should catch issues.
                return;
            }

            if (statusMessageEl && data.status_summary) {
                 statusMessageEl.textContent = `Task ${taskId} (${operationType}): ${data.status_summary}`;
                 statusMessageEl.className = `alert alert-${data.success === false ? 'danger' : (data.success === true ? 'success' : 'info')} mt-2`;
            } else if (statusMessageEl) {
                 statusMessageEl.textContent = `Task ${taskId} (${operationType}): Polling status...`;
            }

            if (data.log_entries && Array.isArray(data.log_entries)) {
                if (displayedLogCounts[taskId] === undefined) {
                    displayedLogCounts[taskId] = 0;
                }
                const newLogs = data.log_entries.slice(displayedLogCounts[taskId]);
                newLogs.forEach(log => {
                    appendLog(logAreaId, log.message, log.detail, log.level.toLowerCase(), null, log.timestamp); // Pass server timestamp
                });
                displayedLogCounts[taskId] = data.log_entries.length;
            }

            if (data.is_done) {
                console.log(`Task ${taskId} (${operationType}) is done. Stopping poll.`);
                if (activePolls[taskId]) {
                    clearInterval(activePolls[taskId]);
                    delete activePolls[taskId];
                }
                // No need to delete displayedLogCounts[taskId] here, let it persist for final view if page isn't reloaded.

                const finalMessage = data.result_message || (data.success ? `${operationType.replace(/_/g, ' ')} completed successfully.` : `${operationType.replace(/_/g, ' ')} failed.`);
                const finalLevel = data.success ? 'success' : 'error';

                // Ensure final status is prominent in statusMessageEl
                if (statusMessageEl) {
                    statusMessageEl.textContent = finalMessage;
                    statusMessageEl.className = `alert alert-${finalLevel} mt-2`;
                }
                // appendLog(logAreaId, finalMessage, '', finalLevel, statusMessageEl); // This might duplicate status if statusMessageEl is also logArea's status.
                                                                                   // The last log entry from server should cover this.

                enablePageInteractions();

                // Post-completion actions
                if (typeof loadAvailableBackups === 'function') { // Check if function exists (it's in backup_system.html)
                    if (operationType === 'full_system_backup' && data.success) {
                        loadAvailableBackups(1, 5, true);
                    }
                    if ((operationType === 'delete_system_backup' || operationType === 'bulk_delete_system_backups') && data.success) {
                         loadAvailableBackups(1, 5, true);
                    }
                }
                // Null out the current task ID for this specific operation type
                if (operationType === 'full_system_backup') currentBackupTaskId = null;
                if (operationType === 'selective_system_restore') currentSelectiveRestoreTaskId = null;
                if (operationType === 'verify_system_backup') currentVerifyTaskId = null;
                if (operationType === 'delete_system_backup') currentDeleteTaskId = null;
                if (operationType === 'bulk_delete_system_backups') currentBulkDeleteTaskId = null;
                if (operationType === 'restore_dry_run') currentDryRunTaskId = null; // Added for dry run
                // currentRestoreTaskId is for one-click full restore, not yet refactored in this common script.
            }
        })
        .catch(error => {
            console.error(`Error polling task ${taskId} (${operationType}):`, error);
            appendLog(logAreaId, `Error polling for ${operationType} task ${taskId}: ${error.message}. Poll stopped.`, '', 'error', statusMessageEl);
            if (activePolls[taskId]) {
                clearInterval(activePolls[taskId]);
                delete activePolls[taskId];
            }
            // Consider not deleting displayedLogCounts[taskId] here.
            enablePageInteractions();
        });
}


// --- Keep Alive ---
function keepAlive() {
    fetch('/ping', { method: 'GET', headers: { 'Accept': 'application/json' } })
    .then(response => {
        if (!response.ok) {
            console.warn('Keep-alive ping failed. Status:', response.status);
            const logAreaToTry = document.getElementById('backup-log-area') ? 'backup-log-area' : (document.getElementById('restore-log-area') ? 'restore-log-area' : 'operation-log-area');
            appendLog(logAreaToTry, 'Session keep-alive ping failed.', `Status: ${response.status}`, 'error');
        }
    })
    .catch(error => {
        console.error('Keep-alive ping error:', error);
        const logAreaToTry = document.getElementById('backup-log-area') ? 'backup-log-area' : (document.getElementById('restore-log-area') ? 'restore-log-area' : 'operation-log-area');
        appendLog(logAreaToTry, 'Session keep-alive ping error.', error.message, 'error');
    });
}
setInterval(keepAlive, 4 * 60 * 1000);

// Initial calls
updateUtcClock();
console.log("admin_backup_common.js loaded and polling system initialized.");

// Note: Event listeners for specific backup/restore buttons are expected to be in their respective HTML templates
// (e.g., backup_system.html, backup_bookings_data.html) because they reference specific element IDs
// like 'backup-log-area', 'restore-status-message', etc. This common script provides the core polling
// and utility functions (disable/enable interactions, appendLog, UTC clock).

// Example of how a specific page (e.g. backup_system.html) would use this:
/*
document.addEventListener('DOMContentLoaded', function () {
    const backupButton = document.getElementById('one-click-backup-btn');
    const backupStatusMessageEl = document.getElementById('backup-status-message'); // For overall status
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    if (backupButton) {
        backupButton.addEventListener('click', function () {
            if (currentBackupTaskId && activePolls[currentBackupTaskId]) {
                appendLog('backup-log-area', "A backup operation is already in progress.", "", "warning", backupStatusMessageEl);
                return;
            }
            disablePageInteractions();
            if (document.getElementById('backup-log-area')) document.getElementById('backup-log-area').innerHTML = '';
            appendLog('backup-log-area', "Initiating full system backup request...", "", "info", backupStatusMessageEl);

            fetch('/api/admin/one_click_backup', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json', 'Content-Type': 'application/json' },
                body: JSON.stringify({}) // Empty body if no params needed
            })
            .then(response => response.json())
            .then(data => {
                const messageType = data.success ? 'info' : 'error';
                appendLog('backup-log-area', data.message || (data.success ? "Backup task started." : "Failed to start backup task."), `Task ID: ${data.task_id || 'N/A'}`, messageType, backupStatusMessageEl);
                if (data.success && data.task_id) {
                    currentBackupTaskId = data.task_id;
                    displayedLogCounts[currentBackupTaskId] = 0;
                    if (activePolls[currentBackupTaskId]) clearInterval(activePolls[currentBackupTaskId]); // Clear old poll if any for this ID
                    activePolls[currentBackupTaskId] = setInterval(() => {
                        pollTaskStatus(currentBackupTaskId, 'backup-log-area', backupStatusMessageEl, 'full_system_backup');
                    }, POLLING_INTERVAL_MS);
                } else {
                    enablePageInteractions();
                }
            })
            .catch(error => {
                console.error('Full system backup request error:', error);
                appendLog('backup-log-area', "Full system backup request failed:", error.message, 'error', backupStatusMessageEl);
                enablePageInteractions();
            });
        });
    }
    // Similar event listeners for other operations like restore, delete, verify, etc.
    // using appropriate task_ids, logAreaIds, statusMessageElements, and operationTypes.
});
*/
