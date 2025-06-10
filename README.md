# GeminiTest
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
    *   Email notifications for booking updates (requires admin configuration of Flask-Mail).
    *   Microsoft Teams notifications for booking cancellations, check-in/out, and waitlist releases (requires admin configuration of Teams webhook).
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
*   **System Backup & Restore (Azure File Share):**
    *   **Full Backups:**
        *   One-click manual full backup (database, all configurations, media files).
        *   Scheduled automated full backups (daily/weekly).
        *   Backup manifest creation for integrity.
        *   Configurable backup retention policy.
    *   **Booking CSV Backups:**
        *   Manual CSV export/backup of booking data with date range filtering.
        *   Scheduled automated CSV backups of booking data with configurable frequency and date ranges.
    *   **Restore Operations:**
        *   One-click full restore of a backup set.
        *   Selective restore of components (database, map config, specific media).
        *   Restore booking data from CSV backups.
        *   Dry run capability for restore operations.
        *   Verification of backup set integrity against manifest.
    *   **Management:**
        *   List available backup sets (full and CSV).
        *   Delete backup sets (full and CSV).
        *   Manage backup schedules via UI and JSON configuration files.
*   **System Administration:**
    *   Troubleshooting page.
    *   System data cleanup (clear bookings, resources, maps, and uploaded files).
    *   Raw database view (top 100 records from key tables).
    *   Reload configurations (map config, backup schedule).

### Technical & Backend Features

*   **Authentication:**
    *   Local username/password authentication with secure password hashing.
    *   Google OAuth 2.0 for admin login (configurable).
*   **Authorization:**
    *   Role-based access control (RBAC) using permissions assigned to roles.
    *   `is_admin` flag for legacy superuser access.
*   **Database:**
    *   SQLite database with SQLAlchemy ORM.
    *   Optimized for WAL (Write-Ahead Logging) mode.
*   **Scheduling:**
    *   APScheduler for background tasks:
        *   Auto-cancellation of unchecked bookings.
        *   Applying scheduled resource status changes.
        *   Automated full system backups.
        *   Automated booking CSV backups.
*   **Real-time Updates:**
    *   Flask-SocketIO for real-time communication (e.g., booking updates, backup progress).
*   **API-Driven:**
    *   Comprehensive RESTful APIs for most user and admin functionalities.
*   **Deployment:**
    *   Ready for deployment (e.g., Azure Web App via GitHub Actions).
    *   Configuration via environment variables.
*   **Extensibility:**
    *   Modular design with Blueprints.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

*   Python 3.7 or higher. You can download Python from [python.org](https://www.python.org/downloads/).

### Setting up a Virtual Environment

It is highly recommended to use a virtual environment to manage project dependencies and isolate this project from your global Python installation.

1.  **Open your terminal or command prompt.**
2.  **Navigate to the project's root directory** (where this `README.md` file is located).
3.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    ```
    (If `python3` doesn't work, try `python`)

4.  **Activate the virtual environment:**
    *   **On macOS and Linux:**
        ```bash
        source venv/bin/activate
        ```
    *   **On Windows:**
        ```bash
        .\venv\Scripts\activate
        ```
    Your terminal prompt should change to indicate that the virtual environment is active (e.g., `(venv) ...`).

### Running the Initialization Script

After activating your virtual environment, run the initialization script:

```bash
python init_setup.py
```

This script checks your Python version, creates the required directories, and then verifies the database. If no database exists, a new one is created. When a database is present its structure is compared against the expected schema. If the schema is incorrect the old file is removed and recreated. If everything looks good, the existing database is left untouched.

Running `python app.py` or `flask run` performs a minimal check as well, but `init_setup.py` is the preferred method to ensure the environment is healthy.


### Installing Dependencies

Install the necessary Python packages by running:
```bash
pip install -r requirements.txt
```
(This assumes the virtual environment is already activated as per previous instructions).

### Running the Application

To run the application:
1.  Ensure your virtual environment is activated.
2.  Make sure all dependencies are installed by running `pip install -r requirements.txt`.
3.  Run the Flask development server:
    ```bash
    flask run
    ```
    Or, if you prefer (and if `app.py` includes `app.run()`):
    ```bash
    python app.py
    ```
4.  Open your web browser and navigate to `http://127.0.0.1:5000/`.
    You should see the application's home page.

When deploying to platforms like Azure App Service, the host and port are
typically provided via environment variables. The application now reads `PORT`
and `HOST` so you can run:

```bash
HOST=0.0.0.0 PORT=8000 python app.py
```

or configure these variables in your hosting environment.

### Initializing the Database

The application uses an SQLite database to store resource information. If you haven't already, initialize the database and create the necessary tables (this also adds sample resources):
1. Ensure your virtual environment is activated and dependencies are installed (`pip install -r requirements.txt`).
2. Open a Python interactive shell in your project root:
   ```bash
   flask shell
   ```
   (Alternatively, you can use `python` and then `from init_setup import init_db` if you are using the plain python interpreter)
3. In the Flask shell, import the `init_db` function and run it:
   ```python
   >>> from init_setup import init_db
   >>> init_db()  # Creates tables and adds sample data if the database is empty
   ```
This will create a `site.db` file in the `data/` directory and set up the tables.
The database is excluded from version control, but the `azure_backup.py` script
automatically uploads `data/site.db` to Azure File Share whenever its contents
change.
After initialization an administrator account is created automatically with the
credentials **admin/admin**. Log in with this account to access the admin
features and create additional users.
You should see messages indicating success.
Pass `force=True` if you want to **reset and wipe** existing data:
   ```python
   >>> init_db(force=True)
   ```
**Important:** You only need to run `init_db()` once in a fresh environment. Omitting `force=True` will keep existing records intact.

When initialization completes, an administrator account is created automatically.
The default credentials are **admin/admin**. Log in with this account and change
the password immediately in a production deployment.

### Updating Existing Databases

If you upgrade and encounter database errors, run `python init_setup.py` again.
The script will verify the schema of the existing `site.db` file. If it doesn't
match the current models, the old database is deleted and rebuilt. Make sure you
back up any important data before running the script in these situations.

### Email Configuration (Gmail API with OAuth 2.0)

The application sends email notifications (e.g., booking confirmations, alerts) using the Gmail API with OAuth 2.0. This method requires a one-time authorization by the owner of the Gmail account that will be used for sending emails.

**Required Environment Variables:**

*   `GOOGLE_CLIENT_ID`: Your Google Cloud OAuth 2.0 Client ID (typically used for user login, and reused here).
*   `GOOGLE_CLIENT_SECRET`: Your Google Cloud OAuth 2.0 Client Secret.
*   `GMAIL_SENDER_ADDRESS`: The Gmail account the application will send emails *from* (e.g., `your-app-notifications@gmail.com`).
*   `GMAIL_OAUTH_REDIRECT_URI`: The application's redirect URI for the Gmail authorization flow. Example: `http://localhost:5000/admin/gmail_auth/authorize_callback`.
    *   **Important**: You MUST add this exact URI to the "Authorized redirect URIs" list for your OAuth 2.0 Client ID in the Google Cloud Console.
*   `GMAIL_REFRESH_TOKEN`: The refresh token obtained after the one-time authorization process (see below). This token allows the application to continuously send emails without further manual intervention. Store this securely.
*   `MAIL_DEFAULT_SENDER`: Fallback sender email address if `GMAIL_SENDER_ADDRESS` is not determined for some reason (e.g., `fallback@example.com`).

**One-Time Authorization to Obtain Refresh Token:**

To enable email sending, an administrator must perform a one-time authorization:
1.  Ensure all the above environment variables (except `GMAIL_REFRESH_TOKEN` initially) are set.
2.  Start the application.
3.  In a web browser, log in to the Gmail account that will be used as the `GMAIL_SENDER_ADDRESS`.
4.  Navigate to the `/admin/gmail_auth/authorize_sending` route in the application.
5.  You will be redirected to a Google consent screen. Grant the requested permissions (to send emails).
6.  Upon successful authorization, Google will redirect you back to the application's `GMAIL_OAUTH_REDIRECT_URI`, and the application will display the **Refresh Token**.
7.  Copy this Refresh Token and set it as the `GMAIL_REFRESH_TOKEN` environment variable for your application.
8.  Restart the application. It should now be able to send emails.

The old SMTP `MAIL_*` variables (like `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, etc.) are no longer used for the primary email sending mechanism when using the Gmail API with OAuth 2.0.

### Teams Notifications

To enable Microsoft Teams notifications, create an incoming webhook URL in your Teams channel and set it in the environment variable `TEAMS_WEBHOOK_URL` before running the application:

```
export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/your-webhook-url"
```

Users must have an email address set in their profile to receive Teams alerts for booking creation, cancellation and waitlist releases.

## Social Authentication Setup

### Google OAuth

To enable Google authentication for admin login and account linking, you need to configure credentials in your Google Cloud Console and set the following environment variables:

*   `GOOGLE_CLIENT_ID`: Your Google OAuth 2.0 Client ID.
*   `GOOGLE_CLIENT_SECRET`: Your Google OAuth 2.0 Client Secret.
*   `GOOGLE_DISCOVERY_URL`: The Google OpenID Connect discovery document URL (typically `https://accounts.google.com/.well-known/openid-configuration`).
*   `SCOPES` (Optional): A space-separated string of scopes to request. Defaults to `openid email profile`.

**Redirect URIs:**

In your Google Cloud Console, under your OAuth 2.0 Client ID settings, you must add the following "Authorized redirect URIs" (replace `your-app-domain.com` with your application's actual domain and port):

*   `http://your-app-domain.com/login/google/callback` (for admin login)
*   `https://your-app-domain.com/login/google/callback` (if using HTTPS for admin login)
*   `http://your-app-domain.com/profile/link/google/callback` (for user account linking)
*   `https://your-app-domain.com/profile/link/google/callback` (if using HTTPS for user account linking)

Make sure to include both `http` and `https` versions if your application might run on either. The application dynamically generates these callback URLs, so ensure they match what's configured in Google Cloud.

### Facebook OAuth

To enable Facebook account linking, you need to configure your Facebook App credentials and set them as environment variables. While the exact registration code for Facebook OAuth isn't visible in this part of the codebase, Authlib typically uses environment variables such as:

*   `FACEBOOK_CLIENT_ID`: Your Facebook App ID.
*   `FACEBOOK_CLIENT_SECRET`: Your Facebook App Secret.

**Important:** The specific environment variable names might differ if the OAuth client for Facebook is registered with custom keys. If you encounter issues, you may need to verify these in the application's OAuth registration code for Facebook.

**Redirect URIs:**

In your Facebook App settings (under "Facebook Login" -> "Settings"), you must add the following "Valid OAuth Redirect URIs" (replace `your-app-domain.com` with your application's actual domain and port):

*   `http://your-app-domain.com/profile/link/facebook/callback`
*   `https://your-app-domain.com/profile/link/facebook/callback` (if using HTTPS)

Ensure these match the callback URL used by the application.

### Instagram OAuth

Currently, Instagram OAuth is not implemented in this application. If this is a desired feature, it would require adding the necessary integration code and configuration.

### Running Tests

To run the test suite:
1. Activate your virtual environment.
2. Install dependencies from `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
   Alternatively, you can run the helper script:
   ```bash
   ./tests/setup.sh
   ```
3. Execute the tests with `pytest`:
   ```bash
   pytest
   ```

### Enabling Multiple Languages

Translations are stored in simple JSON files under `locales/`. Each file is named after its language code, such as `en.json` or `es.json`. To add a new language:

1. Ensure the desired language code is listed in `app.config['LANGUAGES']` in `app.py`.
2. Create a `locales/<lang>.json` file mapping English phrases to their translations. Example structure:
   ```json
   {
       "Home": "Inicio",
       "Login": "Iniciar sesión"
   }
   ```
3. Restart the application. The language selector in the footer will load strings from the JSON files without any compilation step.

## Deploying to Azure Web App

This project includes a GitHub Actions workflow that can publish the application to Azure Web App. Configure these secrets in your repository settings:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

Pushing to the `main` branch triggers the workflow. The action zips the project and deploys it to an App Service named `resourcebooking`.

Make sure the database is initialized by running `python init_setup.py` locally or as part of your deployment process.


## Backing Up Data to Azure File Share

Use `azure_backup.py` to upload the SQLite database and uploaded images to an Azure File Share. The script reads these environment variables:

- `AZURE_STORAGE_CONNECTION_STRING` – connection string to your storage account
- `AZURE_DB_SHARE` – file share name for database backups (default `db-backups`)
- `AZURE_MEDIA_SHARE` – file share name for uploaded images (default `media`)


Run the script with:
```bash
python azure_backup.py
```
All floor map and resource images from `static/` along with `data/site.db` will be uploaded. The script stores hashes of previous uploads so unchanged files are skipped on subsequent runs. During the process, log messages indicate whether each file was uploaded or skipped because it did not change.

### Automatic Backups

Configure the interval via the `AZURE_BACKUP_INTERVAL_MINUTES` environment variable (default `60`).  Files are only uploaded when their content changes.
