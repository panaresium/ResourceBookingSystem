from app import app, socketio

if __name__ == "__main__":
    # Allow usage of the Werkzeug development server when running this script
    # directly, even though Flask-SocketIO discourages it for production.
    socketio.run(app, allow_unsafe_werkzeug=True)

