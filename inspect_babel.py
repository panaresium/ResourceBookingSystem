import inspect
from flask_babel import Babel

try:
    # Attempt to get constructor arguments for Babel
    arg_spec = inspect.getfullargspec(Babel.__init__)
    print("Babel.__init__ argument spec:")
    print(arg_spec)
except Exception as e:
    print(f"Error inspecting Babel.__init__: {e}")
    print("Attempting dir(Babel) instead:")
    try:
        # Fallback: print attributes of the Babel class itself
        # This won't show constructor args directly but might give clues
        print(dir(Babel))
    except Exception as e_dir:
        print(f"Error with dir(Babel): {e_dir}")
