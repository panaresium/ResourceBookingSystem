import os
from app_factory import create_app
from extensions import socketio # For socketio.run

# Create the Flask app instance using the factory
app = create_app()

if __name__ == "__main__":
    # Configuration for the development server run
    # These could also be moved to a run.py or managed by environment variables fully
    host = os.environ.get("HOST", "0.0.0.0") # Default to 0.0.0.0 for Docker/external access
    port = int(os.environ.get("PORT", 5000))

    # FLASK_DEBUG environment variable is commonly used.
    # Convert string "true" or "1" to boolean True.
    flask_debug_env = os.environ.get("FLASK_DEBUG", "False").lower()
    debug_mode = flask_debug_env in ("true", "1", "yes")

    # Use app.logger for consistency once app is created
    app.logger.info(f"Starting application on {host}:{port} with debug mode: {debug_mode}")

    # allow_unsafe_werkzeug=True is often needed for older Werkzeug versions with SocketIO's dev server.
    # Consider security implications or using a proper WSGI server for production.
    socketio.run(app, host=host, port=port, debug=debug_mode, allow_unsafe_werkzeug=True)
