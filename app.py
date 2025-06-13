import os
from app_factory import create_app
from extensions import socketio # For socketio.run
import logging

# Create the Flask app instance using the factory
print("PRINT_DEBUG: APP.PY - About to call create_app()", flush=True)
app = create_app()

# Configure logger level based on APP_GLOBAL_LOG_LEVEL environment variable
log_level_str = os.environ.get("APP_GLOBAL_LOG_LEVEL", "INFO").upper()
log_level_map = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
log_level = log_level_map.get(log_level_str, logging.INFO)
app.logger.setLevel(log_level)
app.logger.info(f"Logger level set to: {logging.getLevelName(app.logger.getEffectiveLevel())}")

if __name__ == "__main__":
    # Configuration for the development server run
    # These could also be moved to a run.py or managed by environment variables fully
    host = os.environ.get("HOST", "0.0.0.0") # Default to 0.0.0.0 for Docker/external access
    port = int(os.environ.get("PORT", 5000))

    # FLASK_DEBUG environment variable is commonly used.
    # Convert string "true" or "1" to boolean True.
    #flask_debug_env = os.environ.get("FLASK_DEBUG", "False").lower()
    #debug_mode = flask_debug_env in ("true", "1", "yes")
    #print(f"PRINT_DEBUG: APP.PY - FLASK_DEBUG env var: '{flask_debug_env}', Parsed debug_mode: {debug_mode}", flush=True)

    # Use app.logger for consistency once app is created
    #app.logger.info(f"Starting application on {host}:{port} with debug mode: {debug_mode}")

    # allow_unsafe_werkzeug=True is often needed for older Werkzeug versions with SocketIO's dev server.
    # Consider security implications or using a proper WSGI server for production.
    socketio.run(app, host=host, port=port, debug=debug_mode, allow_unsafe_werkzeug=True)
