from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
# from flask_mail import Mail # Removed
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()
# mail = Mail() # Removed
csrf = CSRFProtect()
socketio = SocketIO(manage_session=False, logger=True, engineio_logger=True)
migrate = Migrate()
