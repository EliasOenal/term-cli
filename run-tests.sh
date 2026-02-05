#!/bin/bash
#
# Run term-cli tests
#
# Usage:
#   ./run-tests.sh           # Fast: parallel execution
#   ./run-tests.sh -s        # Sequential: all tests in order
#

set -o pipefail

# Sequential mode - just run pytest directly
if [[ "$1" == "-s" || "$1" == "--sequential" ]]; then
    shift
    exec pytest "$@"
fi

# Parallel mode
exec pytest -n auto -q "$@"
