import os
print("Attempting to create Flask app for testing...")
try:
    # Ensure environment variables that app_factory might use are set, if any
    os.environ['FLASK_ENV'] = 'testing' # Example, if your app uses this

    from app_factory import create_app
    print("create_app imported successfully.")

    app = create_app(testing=True)

    if app:
        print("Flask app created successfully in testing mode.")
        # Optionally, try to push an app context
        with app.app_context():
            print("App context pushed successfully.")
            from extensions import db
            db.create_all()
            print("db.create_all() executed (or attempted).")
    else:
        print("create_app did not return an app object.")
except Exception as e:
    print(f"Error during app creation or setup: {e}")
    import traceback
    traceback.print_exc()
print("Script finished.")
