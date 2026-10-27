#!/usr/bin/env bash
# Read-only check of the actual dual-boot Linux user service. No sudo or edits.
set -u
if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'Run this on the installed Ubuntu system, not Windows/Git Bash.'
    exit 1
fi
if grep -qiE 'microsoft|wsl' /proc/sys/kernel/osrelease; then
    printf '%s\n' 'WSL is not the dual-boot Ubuntu installation; do not treat it as that system.'
    exit 1
fi
printf '%s\n' 'MA4 Linux service check (read-only)'
date -u '+UTC %Y-%m-%dT%H:%M:%SZ'
printf '\n%s\n' 'User service enabled / active:'
systemctl --user is-enabled ma4.service
systemctl --user is-active ma4.service
printf '\n%s\n' 'Effective service state and lifecycle properties:'
systemctl --user show ma4.service --no-pager \
    -p LoadState -p ActiveState -p SubState -p UnitFileState \
    -p MainPID -p ActiveEnterTimestamp -p FragmentPath \
    -p PartOf -p WantedBy -p Restart -p KillMode
printf '\n%s\n' 'Desktop session target:'
systemctl --user show graphical-session.target --no-pager -p ActiveState -p SubState
printf '\n%s\n' 'User manager persistence:'
loginctl show-user "$(id -u)" -p Linger -p State
