# GeminiTest
# Smart Resource Booking System

This project is a web application designed to help manage and book resources such as meeting rooms and equipment efficiently. It aims to provide a centralized view of resource availability and streamline the booking process. This initial version focuses on the front-end user interface.

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
   You should see messages indicating success.
   Pass `force=True` if you want to **reset and wipe** existing data:
   ```python
   >>> init_db(force=True)
   ```
**Important:** You only need to run `init_db()` once in a fresh environment. Omitting `force=True` will keep existing records intact.

### Updating Existing Databases

If you upgrade and encounter database errors, run `python init_setup.py` again.
The script will verify the schema of the existing `site.db` file. If it doesn't
match the current models, the old database is deleted and rebuilt. Make sure you
back up any important data before running the script in these situations.

### Email Configuration

Flask-Mail is used to send email notifications when bookings are created, updated or cancelled. Configure your SMTP credentials through environment variables before running the application:

* `MAIL_SERVER` – SMTP server address
* `MAIL_PORT` – SMTP port number
* `MAIL_USERNAME` – SMTP username
* `MAIL_PASSWORD` – SMTP password
* `MAIL_USE_TLS` – set to `true` to enable TLS
* `MAIL_USE_SSL` – set to `true` to enable SSL
* `MAIL_DEFAULT_SENDER` – address used as the default sender

If these variables are not provided, placeholder values from `app.py` will be used.

### Teams Notifications

To enable Microsoft Teams notifications, create an incoming webhook URL in your Teams channel and set it in the environment variable `TEAMS_WEBHOOK_URL` before running the application:

```
export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/your-webhook-url"
```

Users must have an email address set in their profile to receive Teams alerts for booking creation, cancellation and waitlist releases.

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

### Filtering Resources

The `/api/resources` endpoint supports optional query parameters to narrow down
results:

- `capacity` – minimum capacity required (e.g. `?capacity=5`)
- `equipment` – comma-separated equipment keywords (e.g. `?equipment=projector,whiteboard`)
- `tags` – comma-separated tags assigned to a resource (e.g. `?tags=quiet`)

These filters can be combined. Only resources with `status='published'` are returned.

## Bulk User Management

Administrators can manage users in bulk from the **User Management** page. The interface provides buttons to export the current users to a JSON file and to import updates from a JSON file. You can also select multiple users and delete them in a single action.

The backing API endpoints are:

- `POST /api/admin/users/import` – create or update users from JSON data
- `GET /api/admin/users/export` – download all users and roles as JSON
- `DELETE /api/admin/users/bulk` – remove several users at once

Exported JSON contains an array of users with their assigned roles. The import endpoint accepts the same structure, allowing you to add new users or update existing ones by ID.

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
All floor map and resource images from `static/` along with `data/site.db` will be uploaded. The script stores hashes of previous uploads so unchanged files are skipped on subsequent runs.

### Automatic Backups

When the app runs, it will attempt to restore `site.db` and uploaded images from the configured Azure File Shares.  A background job then backs up the database and media files at regular intervals.

Configure the interval via the `AZURE_BACKUP_INTERVAL_MINUTES` environment variable (default `60`).  Files are only uploaded when their content changes.
The hashing logic keeps a small `backup_hashes.json` file in `data/` to track the last uploaded state.

