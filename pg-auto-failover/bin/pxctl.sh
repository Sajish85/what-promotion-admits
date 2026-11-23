#!/bin/bash
# pxctl.sh CTL_PORT pass|stall|status
printf '%s\n' "$2" | nc -w 3 127.0.0.1 "$1"
