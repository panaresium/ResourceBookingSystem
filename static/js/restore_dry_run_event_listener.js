document.addEventListener('DOMContentLoaded', function () {
    const availableBackupsTable = document.getElementById('availableBackupsTable');
    const restoreLogArea = document.getElementById('restore-log-area'); // Assumes this ID exists
    const restoreStatusMessageEl = document.getElementById('restore-status-message'); // Assumes this ID exists
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    if (availableBackupsTable) {
        availableBackupsTable.addEventListener('click', function (event) {
            const target = event.target;
            if (target.classList.contains('restore-dry-run-btn')) {
                event.preventDefault();

                if (currentDryRunTaskId && activePolls[currentDryRunTaskId]) {
                    appendLog('restore-log-area', "A dry run operation is already in progress.", "", "warning", restoreStatusMessageEl);
                    return;
                }

                const backupTimestamp = target.dataset.timestamp;
                if (!backupTimestamp) {
                    appendLog('restore-log-area', "Error: Backup timestamp not found for dry run.", "", "error", restoreStatusMessageEl);
                    return;
                }

                if (!confirm(`Are you sure you want to perform a DRY RUN restore for backup ${backupTimestamp}? This will simulate the restore process without making changes.`)) {
                    return;
                }

                disablePageInteractions();

                // Clear and show the relevant log area
                if (restoreLogArea) {
                    restoreLogArea.innerHTML = '';
                    restoreLogArea.style.display = 'block';
                }
                // Hide other log areas if they exist (e.g., backup-log-area, verify-log-area)
                const otherLogAreas = ['backup-log-area', 'verify-log-area', 'delete-log-area'];
                otherLogAreas.forEach(id => {
                    const area = document.getElementById(id);
                    if (area) area.style.display = 'none';
                });


                appendLog('restore-log-area', `Initiating dry run restore for backup ${backupTimestamp}...`, "", "info", restoreStatusMessageEl);

                fetch(`/api/admin/restore_dry_run/${backupTimestamp}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    },
                    // body: JSON.stringify({}) // No body needed for this request as timestamp is in URL
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.task_id) {
                        currentDryRunTaskId = data.task_id;
                        displayedLogCounts[currentDryRunTaskId] = 0;

                        appendLog('restore-log-area', `Dry run task successfully initiated. Task ID: ${currentDryRunTaskId}`, "", "info", restoreStatusMessageEl);

                        if (activePolls[currentDryRunTaskId]) clearInterval(activePolls[currentDryRunTaskId]); // Clear old poll if any
                        activePolls[currentDryRunTaskId] = setInterval(() => {
                            pollTaskStatus(currentDryRunTaskId, 'restore-log-area', restoreStatusMessageEl, 'restore_dry_run');
                        }, POLLING_INTERVAL_MS);
                    } else {
                        appendLog('restore-log-area', `Failed to start dry run task: ${data.message || 'Unknown error'}`, `Details: ${data.error || ''}`, "error", restoreStatusMessageEl);
                        enablePageInteractions();
                    }
                })
                .catch(error => {
                    console.error('Dry run restore request error:', error);
                    appendLog('restore-log-area', "Dry run restore request failed.", error.message, 'error', restoreStatusMessageEl);
                    enablePageInteractions();
                });
            }
        });
    }
});
