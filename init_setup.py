#!/usr/bin/env python3

import sys
import os
import pathlib

MIN_PYTHON_VERSION = (3, 7)
DATA_DIR_NAME = "data"
STATIC_DIR_NAME = "static"
FLOOR_MAP_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "floor_map_uploads")

def check_python_version():
    """Checks if the current Python version meets the minimum requirement."""
    print("Checking Python version...")
    if sys.version_info < MIN_PYTHON_VERSION:
        print(
            f"Error: Your Python version is {sys.version_info.major}.{sys.version_info.minor}."
            f" This project requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher."
        )
        sys.exit(1)
    print(f"Python version {sys.version_info.major}.{sys.version_info.minor} is sufficient.")
    return True

def create_required_directories():
    """Creates the data directory and floor map uploads directory if they don't exist."""
    # Create data directory
    data_dir = pathlib.Path(__file__).resolve().parent / DATA_DIR_NAME
    print(f"Checking for '{DATA_DIR_NAME}' directory...")
    if not data_dir.exists():
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{data_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{data_dir}' directory: {e}")
            sys.exit(1)
    else:
        print(f"'{data_dir}' directory already exists.")

    # Create static directory if it doesn't exist
    static_dir = pathlib.Path(__file__).resolve().parent / STATIC_DIR_NAME
    if not static_dir.exists():
        try:
            static_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{static_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{static_dir}' directory: {e}")
            # Decide if this is fatal, for now, we'll let it pass if data_dir was created
            # sys.exit(1) 
    else:
        print(f"'{static_dir}' directory already exists (good).")
       
    # Create floor map uploads directory
    floor_map_uploads_dir = pathlib.Path(__file__).resolve().parent / FLOOR_MAP_UPLOADS_DIR_NAME
    print(f"Checking for '{FLOOR_MAP_UPLOADS_DIR_NAME}' directory...")
    if not floor_map_uploads_dir.exists():
        try:
            floor_map_uploads_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created '{floor_map_uploads_dir}' directory.")
        except OSError as e:
            print(f"Error: Could not create '{floor_map_uploads_dir}' directory: {e}")
            # Decide if this is fatal
            # sys.exit(1) 
    else:
        print(f"'{floor_map_uploads_dir}' directory already exists.")
    return True

def main():
    """Main function to run setup checks and tasks."""
    print("Starting project initialization...")
    
    check_python_version()
    print("-" * 30)
    create_required_directories()
    
    print("-" * 30)
    print("Project initialization script completed successfully.")
    print("Remember to activate your virtual environment if you haven't already.")
    print("Next steps (if applicable):")
    print("  - Install dependencies: pip install -r requirements.txt")
    print("  - Run the application (see README.md for details)")

if __name__ == "__main__":
    main()
