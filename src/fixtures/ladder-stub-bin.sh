#!/bin/sh
# Test fixture: launches the ladder stub under whatever `node` runs the suite.
exec node "$(dirname "$0")/ladder-stub.mjs" "$@"
