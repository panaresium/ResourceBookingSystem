console.log("restore_dry_run_event_listener.js SCRIPT LOADED AND EXECUTING - Test 1");

document.addEventListener('DOMContentLoaded', function () {
    console.log("DOM fully loaded. restore_dry_run_event_listener.js trying to get availableBackupsTable - Test 2");
    const table = document.getElementById('availableBackupsTable'); // This is the ID used in the HTML
    console.log("availableBackupsTable element:", table, "- Test 3");

    // Variables for restore log area and status message, defined once DOM is ready
    // These were previously defined inside the click handler, but are better scoped here if needed by other parts within this DOMContentLoaded
    const restoreLogAreaEl = document.getElementById('restore-log-area');
    const restoreStatusMessageEl = document.getElementById('restore-status-message');


    if (table) {
        console.log("Event listener for dry run SHOULD BE attaching to table now - Test 4");

        table.addEventListener('click', function(event) {
            // Use .closest to find the button, works if user clicks an icon inside the button
            const targetButton = event.target.closest('.restore-dry-run-btn');
            if (!targetButton) {
                return; // Click was not on a dry run button or its child
            }
            event.preventDefault();

            const backupTimestamp = targetButton.dataset.timestamp;
            console.log('Dry Run button clicked. Timestamp:', backupTimestamp, '- Test 5 (Inside Listener)');

            const csrfTokenEl = document.querySelector('meta[name="csrf-token"]');
            let csrfToken = null;
            if (csrfTokenEl) {
                csrfToken = csrfTokenEl.getAttribute('content');
            }
            console.log('CSRF Token for Dry Run:', csrfToken, '- Test 6');

            if (!csrfToken) {
                // Ensure appendLog is available (it should be from admin_backup_common.js)
                if (typeof appendLog === 'function') {
                    appendLog('restore-log-area', 'CSRF token not found. Cannot proceed.', '', 'error', restoreStatusMessageEl);
                }
                console.error("CSRF token not found. Halting dry run request.");
                return;
            }

            // Ensure currentDryRunTaskId and activePolls are available (from admin_backup_common.js)
            if (typeof currentDryRunTaskId !== 'undefined' && typeof activePolls !== 'undefined') {
                if (currentDryRunTaskId && activePolls[currentDryRunTaskId]) {
                    if (typeof appendLog === 'function') {
                        appendLog('restore-log-area', "A dry run operation is already in progress.", "", "warning", restoreStatusMessageEl);
                    }
                    console.warn("Dry run already in progress, new request blocked.");
                    return;
                }
            } else {
                console.error("currentDryRunTaskId or activePolls not defined. Check admin_backup_common.js loading.");
                if (typeof appendLog === 'function') {
                     appendLog('restore-log-area', "Critical error: Task tracking variables not found.", "", "error", restoreStatusMessageEl);
                }
                return;
            }


            if (!confirm("Are you sure you want to perform a dry run restore for backup " + backupTimestamp + "? This will simulate the restore process without making changes.")) {
                console.log("Dry run cancelled by user.");
                return;
            }

            // Ensure disablePageInteractions is available
            if (typeof disablePageInteractions === 'function') {
                disablePageInteractions();
            } else {
                console.error("disablePageInteractions function not found.");
            }

            if (restoreLogAreaEl) {
                restoreLogAreaEl.innerHTML = '';
                restoreLogAreaEl.style.display = 'block';
            }

            const backupLogAreaEl = document.getElementById('backup-log-area'); // For hiding
            if (backupLogAreaEl && backupLogAreaEl.style.display !== 'none') {
                backupLogAreaEl.style.display = 'none';
            }
            // Also hide verify and delete log areas if they exist
            ['verify-log-area', 'delete-log-area'].forEach(id => {
                const area = document.getElementById(id);
                if (area) area.style.display = 'none';
            });


            if (typeof appendLog === 'function') {
                appendLog('restore-log-area', "Initiating restore dry run for " + backupTimestamp + "...", '', 'info', restoreStatusMessageEl);
            }
            console.log('Using Backup Timestamp for Fetch URL:', backupTimestamp, '- Test 7');


            fetch(`/api/admin/restore_dry_run/${backupTimestamp}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({})
            })
            .then(response => {
                if (!response.ok) {
                    return response.text().then(text => {
                        throw new Error(`Server responded with ${response.status}: ${text || 'No error message from server'}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                const message = data.message || (data.success ? "Dry run task started." : "Failed to start dry run task.");
                const taskIdDetail = `Task ID: ${data.task_id || 'N/A'}`;
                if (typeof appendLog === 'function') {
                    appendLog('restore-log-area', message, taskIdDetail, data.success ? 'info' : 'error', restoreStatusMessageEl);
                }

                if (data.success && data.task_id) {
                    // Ensure global task tracking variables from admin_backup_common.js are updated
                    currentDryRunTaskId = data.task_id;
                    if (typeof displayedLogCounts !== 'undefined') {
                         displayedLogCounts[currentDryRunTaskId] = 0;
                    } else {
                        console.error("displayedLogCounts is not defined - check admin_backup_common.js");
                    }

                    if (activePolls[currentDryRunTaskId]) {
                        clearInterval(activePolls[currentDryRunTaskId]);
                    }
                    console.log('Starting pollTaskStatus for Dry Run. Task ID:', currentDryRunTaskId, '- Test 8');

                    // Ensure POLLING_INTERVAL_MS is available (from admin_backup_common.js)
                    const intervalMs = (typeof POLLING_INTERVAL_MS !== 'undefined') ? POLLING_INTERVAL_MS : 3000;
                    if (typeof pollTaskStatus === 'function') {
                        activePolls[currentDryRunTaskId] = setInterval(() => {
                            pollTaskStatus(currentDryRunTaskId, 'restore-log-area', restoreStatusMessageEl, 'restore_dry_run');
                        }, intervalMs);
                    } else {
                        console.error("pollTaskStatus function not found.");
                         if (typeof enablePageInteractions === 'function') enablePageInteractions();
                    }
                } else {
                    if (typeof enablePageInteractions === 'function') enablePageInteractions();
                }
            })
            .catch(error => {
                console.error('Restore Dry Run request error:', error, '- Test 9');
                if (typeof appendLog === 'function') {
                    appendLog('restore-log-area', "Restore Dry Run request failed:", error.message ? error.message : 'Unknown error', 'error', restoreStatusMessageEl);
                }
                if (typeof enablePageInteractions === 'function') enablePageInteractions();
            });
        });

    } else {
        console.error("CRITICAL: availableBackupsTable element NOT FOUND. Event listener for dry run cannot be attached. - Test X");
    }
});
