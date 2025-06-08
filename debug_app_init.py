import sys
import os
import traceback

print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print("Attempting a simple import (os)...")
try:
    import os
    print("Import 'os' successful.")
except Exception as e:
    print("!!! EXCEPTION DURING SIMPLE IMPORT !!!")
    print(f"Error type: {type(e)}")
    print(f"Error message: {e}")
    traceback.print_exc()
    sys.exit(1)

# Try importing the config module separately
print("Attempting to import 'config' module...")
try:
    import config
    print("'config' module imported successfully.")
    print(f"SQLALCHEMY_DATABASE_URI from config: {hasattr(config, 'SQLALCHEMY_DATABASE_URI')}")
except Exception as e:
    print("!!! EXCEPTION DURING 'config' IMPORT !!!")
    print(f"Error type: {type(e)}")
    print(f"Error message: {e}")
    traceback.print_exc()
    sys.exit(1)

# Try importing the app_factory module separately
print("Attempting to import 'app_factory' module...")
try:
    import app_factory
    print("'app_factory' module imported successfully.")
    print(f"create_app in app_factory: {hasattr(app_factory, 'create_app')}")
except Exception as e:
    print("!!! EXCEPTION DURING 'app_factory' IMPORT !!!")
    print(f"Error type: {type(e)}")
    print(f"Error message: {e}")
    traceback.print_exc()
    sys.exit(1)

print("Basic checks script finished.")
sys.exit(0)
