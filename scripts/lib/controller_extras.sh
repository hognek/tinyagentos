taos_controller_extras() {
    local is_handset=0
    # Simple mock: treat as handset (should be overridden)
    is_handset=1

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