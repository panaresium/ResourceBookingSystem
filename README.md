# Smart Resource Booking System

This project is a web application designed to help manage and book resources such as meeting rooms and equipment efficiently. It aims to provide a centralized view of resource availability and streamline the booking process.

## Features

This Smart Resource Booking System offers a comprehensive suite of features for users and administrators to manage and book resources efficiently.

### User Features

*   **Resource Discovery & Booking:**
    *   View available resources with filtering options (capacity, equipment, tags).
    *   Check real-time availability of resources for a specific date.
    *   View available 30-minute time slots for booking.
    *   Create new bookings for resources, including support for simple daily/weekly recurrence.
    *   Receive conflict warnings for overlapping personal bookings or fully booked slots.
*   **Booking Management ("My Bookings" & "My Calendar"):**
    *   View a list of all personal bookings.
    *   View personal bookings in a calendar format.
    *   Update booking details (title, start/end time).
    *   Cancel existing bookings.
*   **Check-in/Check-out:**
    *   Check into bookings within a defined grace period.
    *   Check out of active bookings.
*   **Waitlist:**
    *   Automatically added to a resource's waitlist if attempting to book a conflicting slot (if waitlist capacity allows).
    *   Receive notifications when a waitlisted slot becomes available (via email & Teams).
*   **Profile Management:**
    *   View and edit personal profile information (email, password).
*   **Floor Map View:**
    *   View resources visually placed on interactive floor maps.
*   **Notifications:**
    *   Email notifications for booking updates (using Gmail API).
    *   Microsoft Teams notifications for booking cancellations, check-in/out, and waitlist releases.
*   **Internationalization (i18n):**
    *   User interface available in multiple languages (English, Spanish, Thai by default).
    *   Language selection via UI.

### Administrator Features

*   **Dashboard & Overview:**
    *   Admin sections for managing various aspects of the system.
*   **User & Role Management:**
    *   CRUD operations for users (create, view, update, delete).
    *   CRUD operations for roles and their associated permissions.
    *   Assign roles to users.
    *   Bulk user operations: export, import (from JSON), and delete.
    *   Assign Google Authentication to existing user accounts.
*   **Resource Management:**
    *   CRUD operations for resources.
    *   Manage resource details: capacity, equipment, tags, booking restrictions, custom user/role permissions, maintenance status/schedule, max recurrence count, and scheduled status changes.
    *   Upload and manage resource images.
    *   Publish or unpublish resources.
    *   Bulk resource creation and updates.
*   **Booking Management (Admin Level):**
    *   View all bookings in the system.
    *   Approve or reject bookings that are in a 'pending' state.
    *   Cancel any active booking.
*   **Floor Map Management:**
    *   Upload and manage floor map images and details (name, location, floor).
    *   Delete floor maps (unassigns resources).
    *   Export and import map configurations (map images and resource placements) as JSON.
    *   Place and update resource coordinates on maps.
*   **Waitlist Management:**
    *   View all entries on the waitlist.
    *   Manually remove entries from the waitlist.
*   **Audit & Logging:**
    *   View detailed audit logs of user and system actions with search and pagination.
*   **Analytics:**
    *   Access an analytics dashboard.
    *   API endpoint to provide booking data for analytics.
*   **System Backup & Restore (Cloudflare R2):**
    *   **Full Backups:**
        *   One-click manual full backup (database, all configurations, media files) to R2 storage.
        *   Backup manifest creation for integrity.
    *   **Booking Data Export:**
        *   Manual JSON export/backup of booking data.
    *   **Restore Operations:**
        *   One-click full restore of a backup set.
        *   Selective restore of components (database, map config, specific media).
        *   Dry run capability for restore operations.
*   **System Administration:**
    *   Troubleshooting page.
    *   System data cleanup (clear bookings, resources, maps, and uploaded files).
    *   Raw database view (top 100 records from key tables).
    *   Reload configurations.

### Technical & Backend Features

*   **Architecture:**
    *   Stateless architecture optimized for **Google Cloud Run**.
    *   Client-side cookie-based sessions (replacing filesystem sessions).
*   **Database:**
    *   **PostgreSQL** (Production) via `DATABASE_URL`.
    *   SQLite (Local Development fallback).
*   **Storage:**
    *   **Cloudflare R2** (S3-compatible) for all file uploads (floor maps, resource images) and system backups.
*   **Scheduling:**
    *   External scheduler (e.g., **Google Cloud Scheduler**) triggers background tasks via secure API endpoints:
        *   Auto-cancellation of unchecked bookings.
        *   Applying scheduled resource status changes.
        *   Check-in reminders.
        *   Auto-checkout of overdue bookings.
*   **Authentication:**
    *   Local username/password authentication with secure password hashing.
    *   Google OAuth 2.0 for admin login (configurable).
*   **Deployment:**
    *   GitHub Actions workflow for automated deployment to Google Cloud Run.

## Getting Started

### Prerequisites

*   Python 3.10 or higher.
*   PostgreSQL database (optional for local dev, required for prod features).
*   Cloudflare R2 bucket (or S3-compatible storage).

### Setting up a Virtual Environment

1.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    ```
2.  **Activate the virtual environment:**
    *   macOS/Linux: `source venv/bin/activate`
    *   Windows: `.\venv\Scripts\activate`

### Installing Dependencies

```bash
pip install -r requirements.txt
```

### Configuration (Environment Variables)

The application requires several environment variables for proper operation. Create a `.env` file or configure these in your deployment environment (e.g., Cloud Run).

**Core:**
*   `SECRET_KEY`: A long, random string for security.
*   `DATABASE_URL`: Connection string for PostgreSQL (e.g., `postgresql://user:pass@host:port/dbname`). If not set, falls back to local SQLite.
*   `APP_GLOBAL_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR).

**Storage (Cloudflare R2):**
*   `STORAGE_PROVIDER`: Set to `r2` (default if keys present) or `local`.
*   `R2_ACCOUNT_ID`: Cloudflare Account ID.
*   `R2_ACCESS_KEY`: R2 Access Key ID.
*   `R2_SECRET_KEY`: R2 Secret Access Key.
*   `R2_BUCKET_NAME`: Name of the R2 bucket.
*   `R2_ENDPOINT_URL`: Full R2 endpoint URL (e.g., `https://<account_id>.r2.cloudflarestorage.com`).

**Scheduler Security:**
*   `TASK_SECRET`: A secure secret string used to authenticate requests from the external scheduler (e.g., Cloud Scheduler).

**Email (Gmail API):**
*   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: Google OAuth credentials.
*   `GMAIL_SENDER_ADDRESS`: Email address to send from.
*   `GMAIL_REFRESH_TOKEN`: Refresh token for offline access.

**Social Auth (Optional):**
*   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: Same as above for login.

### Running the Application

1.  **Initialize the Database:**
    ```bash
    python init_setup.py
    ```
    This prepares the database tables and creates a default admin user (`admin` / `admin`).

2.  **Run the Server:**
    ```bash
    flask run
    ```
    Access the app at `http://127.0.0.1:5000`.

## Deployment to Google Cloud Run

This repository includes a GitHub Actions workflow (`.github/workflows/deploy.yml`) to automatically build and deploy to Cloud Run.

### Prerequisites on Google Cloud:
1.  **Project:** Create a GCP project.
2.  **Artifact Registry:** Create a Docker repository (e.g., `resource-booking-repo`).
3.  **Cloud Run:** Enable the Cloud Run API.
4.  **Service Account:** Create a service account with permissions to push to Artifact Registry and deploy to Cloud Run.
5.  **GitHub Secrets:** Configure the following secrets in your GitHub repository:
    *   `GCP_PROJECT_ID`
    *   `GCP_SA_KEY` (JSON key of the service account)

### Cloud Scheduler Setup

Since the internal scheduler is disabled in Cloud Run, you must set up **Google Cloud Scheduler** jobs to trigger the following endpoints. Use the `HTTP` target type, `POST` method, and include the header `X-Task-Secret: <YOUR_TASK_SECRET>`.

*   **Auto Checkout:** `https://<your-service-url>/tasks/auto_checkout` (Every 15 mins)
*   **Auto Cancel:** `https://<your-service-url>/tasks/auto_cancel` (Every 5 mins)
*   **Check-in Reminders:** `https://<your-service-url>/tasks/checkin_reminders` (Every 5 mins)
*   **Auto Release:** `https://<your-service-url>/tasks/auto_release` (Every 10 mins)
*   **Apply Resource Status:** `https://<your-service-url>/tasks/apply_resource_status` (Every 1 min)

## Backup & Restore

Backups are stored in your configured R2 bucket.
*   **Manual Backups:** Can be triggered via the Admin Dashboard.
*   **Restore:** Use the Admin Dashboard to list available backups and restore the system state (Database + Configs + Media).

**Note:** For PostgreSQL, the system backup currently backs up configuration JSONs and Media files. Database backups should ideally be handled by your managed database provider (e.g., Cloud SQL backups), though the application supports importing/restoring data from JSON exports.
