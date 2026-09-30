#!/bin/bash

# Script to compute the controller extras based on device type and environment variable
# This is the shell helper that the installer compares against

taos_controller_extras() {
    local is_handset=0
    if systemctl cat taos-kiosk.service >/dev/null 2>&1; then
        is_handset=1
    fi

    local extras="proxy"
    case "${TAOS_EXTRAS_BLE:-}" in
        "1"|"true")
            extras="proxy,ble"
            ;;
        "0"|"false")
            extras="proxy"
            ;;
        *)
            if [[ $is_handset -eq 1 ]]; then
                extras="proxy,ble"
            else
                extras="proxy"
            fi
            ;;
    esac
    echo "$extras"
}
