#!/bin/bash
# Setup script for running tests. Installs required packages.
# Usage: source this script or execute it before running pytest.

set -e

# Determine the project root (the directory of this script's parent)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

pip install -r "$PROJECT_ROOT/requirements.txt"
