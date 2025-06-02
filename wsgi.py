from app_factory import create_app
import os

# Create the Flask app instance using the factory.
# The factory (create_app) is responsible for all configurations and initializations.
app = create_app()

# Optional: If your WSGI server needs to be explicitly passed the socketio instance,
# and it's not already integrated with 'app' in a way the server understands,
# you might need to expose it. However, for Gunicorn with Flask-SocketIO,
# often you point Gunicorn to 'your_wsgi_module:app' and specify the worker class.
# from extensions import socketio # Uncomment if socketio instance is needed directly by WSGI config

# Example for Gunicorn with Flask-SocketIO:
# gunicorn --worker-class eventlet -w 1 wsgi:app
# Or for gevent:
# gunicorn --worker-class gevent -w 1 wsgi:app

# The `if __name__ == "__main__":` block for running the development server
# has been removed as it's not standard for a wsgi.py file.
# That logic is now correctly placed in the refactored app.py.
