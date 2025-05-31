import os
from app import app, socketio

if __name__ == "__main__":
    # Allow usage of the Werkzeug development server when running this script
    # directly, even though Flask-SocketIO discourages it for production.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

