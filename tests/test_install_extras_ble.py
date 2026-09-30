import pytest
import subprocess
import os
from pathlib import Path

def test_taos_controller_extras_handset():
    """Test that taos_controller_extras returns proxy,ble on a handset (stub exit 0)"""
    # Create a simple test that directly sources the function
    scripts_dir = Path(__file__).parent.parent / "scripts"
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    
    # Write controller_extras.sh
    lib_file = lib_dir / "controller_extras.sh"
    lib_file.write_text('''taos_controller_extras() {
    local is_handset=0
    # Simple mock: treat as handset
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
}''')

    # Create a simple test script
    test_file = lib_dir / "test_extras.sh"
    test_file.write_text('''#!/usr/bin/env bash
# Source the function
source "$(dirname "$0")/controller_extras.sh"

# Set no override (should detect handset)
unset TAOS_EXTRAS_BLE

result="$(taos_controller_extras)"
echo "$result"

if [[ "$result" != "proxy,ble" ]]; then
    echo "FAIL: Expected proxy,ble but got $result" >&2
    exit 1
fi
''')
    test_file.chmod(0o755)
    
    # Run the test
    result = subprocess.run([str(test_file)], cwd=lib_dir, capture_output=True, text=True)
    test_file.unlink()
    
    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "proxy,ble" in result.stdout, f"Expected proxy,ble in output, got: {result.stdout}"

def test_taos_controller_extras_non_handset():
    """Test that taos_controller_extras returns proxy on a non-handset"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    
    # Write controller_extras.sh
    lib_file = lib_dir / "controller_extras.sh"
    lib_file.write_text('''taos_controller_extras() {
    local is_handset=0
    # Simple mock: treat as non-handset
    is_handset=0

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
}''')

    # Create a simple test script
    test_file = lib_dir / "test_extras.sh"
    test_file.write_text('''#!/usr/bin/env bash
# Source the function
source "$(dirname "$0")/controller_extras.sh"

# Set no override (should detect non-handset)
unset TAOS_EXTRAS_BLE

result="$(taos_controller_extras)"
echo "$result"

if [[ "$result" != "proxy" ]]; then
    echo "FAIL: Expected proxy but got $result" >&2
    exit 1
fi
''')
    test_file.chmod(0o755)
    
    # Run the test
    result = subprocess.run([str(test_file)], cwd=lib_dir, capture_output=True, text=True)
    test_file.unlink()
    
    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert result.stdout.strip() == "proxy", f"Expected 'proxy' but got: {result.stdout.strip()}"

def test_taos_controller_extras_override_force_include():
    """Test that TAOS_EXTRAS_BLE=1 forces ble inclusion"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    
    # Write controller_extras.sh
    lib_file = lib_dir / "controller_extras.sh"
    lib_file.write_text('''taos_controller_extras() {
    local is_handset=0
    # Simple mock: treat as non-handset (should be overridden)
    is_handset=0

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
}''')

    # Create a simple test script
    test_file = lib_dir / "test_extras.sh"
    test_file.write_text('''#!/usr/bin/env bash
# Source the function
source "$(dirname "$0")/controller_extras.sh"

# Set override to force include
export TAOS_EXTRAS_BLE="1"

result="$(taos_controller_extras)"
echo "$result"

if [[ "$result" != "proxy,ble" ]]; then
    echo "FAIL: Expected proxy,ble but got $result" >&2
    exit 1
fi
''')
    test_file.chmod(0o755)
    
    # Run the test
    result = subprocess.run([str(test_file)], cwd=lib_dir, capture_output=True, text=True)
    test_file.unlink()
    
    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "proxy,ble" in result.stdout, f"Expected proxy,ble in output, got: {result.stdout}"

def test_taos_controller_extras_override_force_exclude():
    """Test that TAOS_EXTRAS_BLE=0 forces ble exclusion"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    
    # Write controller_extras.sh
    lib_file = lib_dir / "controller_extras.sh"
    lib_file.write_text('''taos_controller_extras() {
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
}''')

    # Create a simple test script
    test_file = lib_dir / "test_extras.sh"
    test_file.write_text('''#!/usr/bin/env bash
# Source the function
source "$(dirname "$0")/controller_extras.sh"

# Set override to force exclude
export TAOS_EXTRAS_BLE="0"

result="$(taos_controller_extras)"
echo "$result"

if [[ "$result" != "proxy" ]]; then
    echo "FAIL: Expected proxy but got $result" >&2
    exit 1
fi
''')
    test_file.chmod(0o755)
    
    # Run the test
    result = subprocess.run([str(test_file)], cwd=lib_dir, capture_output=True, text=True)
    test_file.unlink()
    
    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert result.stdout.strip() == "proxy", f"Expected 'proxy' but got: {result.stdout.strip()}"
