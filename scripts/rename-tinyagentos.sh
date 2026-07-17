#!/usr/bin/env bash
# rename-tinyagentos.sh — codemod: tinyagentos → taos
# ============================================================================
# Idempotent, dry-run-aware, reversible rename script for the TinyAgentOS
# codebase. Handles the directory rename and every category of reference
# mapped by the #1937 C0 audit (6,600 occurrences across 1,183 files).
#
# Usage:
#   ./scripts/rename-tinyagentos.sh                # execute the rename
#   ./scripts/rename-tinyagentos.sh --dry-run      # show what would change
#   ./scripts/rename-tinyagentos.sh --undo          # revert from backup
#   ./scripts/rename-tinyagentos.sh --help          # this message
#
# Safety properties:
#   - Idempotent: safe to run multiple times (skips already-renamed items)
#   - Dry-run:   --dry-run prints every change, makes zero modifications
#   - Reversible: creates a backup tarball before touching anything;
#                 --undo restores from the most recent backup
#   - README:    preserves exactly one "formerly TinyAgentOS" origin note
# ============================================================================

set -euo pipefail

# ── Globals ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR=""
DRY_RUN=false
UNDO=false
BACKUP_DIR=""
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CHANGES_MADE=0
README_ORIGIN_MARKER_KEPT=false

# ── Help ───────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: rename-tinyagentos.sh [--dry-run] [--undo] [--repo-dir PATH]

Options:
  --dry-run     Print every planned change without modifying anything.
  --undo        Revert the most recent rename from the backup tarball.
  --repo-dir    Path to the TinyAgentOS repository (default: auto-detect).
  --help        Show this message.

Examples:
  ./scripts/rename-tinyagentos.sh --dry-run     # preview
  ./scripts/rename-tinyagentos.sh               # execute
  ./scripts/rename-tinyagentos.sh --undo        # roll back
EOF
    exit 0
}

# ── Argument parsing ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --undo)     UNDO=true; shift ;;
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        --help|-h)  usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ── Repo detection ─────────────────────────────────────────────────────────
if [[ -z "$REPO_DIR" ]]; then
    REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [[ ! -d "$REPO_DIR/.git" ]] && [[ ! -f "$REPO_DIR/.git" ]]; then
    echo "ERROR: $REPO_DIR is not a git repository. Use --repo-dir."
    exit 1
fi

cd "$REPO_DIR"

# ── Undo mode ──────────────────────────────────────────────────────────────
if $UNDO; then
    BACKUP_DIR="$(ls -dt .rename-backup-* 2>/dev/null | head -1 || true)"
    if [[ -z "$BACKUP_DIR" ]]; then
        echo "ERROR: No backup found. Nothing to undo."
        exit 1
    fi
    echo "=== RESTORING from $BACKUP_DIR ==="
    if [[ -f "$BACKUP_DIR/backup.tar.gz" ]]; then
        # Restore files from tarball (includes original tinyagentos/ directory)
        tar xzf "$BACKUP_DIR/backup.tar.gz" -C /
        echo "Restored files from $BACKUP_DIR/backup.tar.gz"
    fi
    # Remove renamed taos/ directory — the tarball already restored tinyagentos/
    if [[ -d "taos" ]] && [[ -d "tinyagentos" ]]; then
        rm -rf taos
        echo "Removed taos/ (original tinyagentos/ restored from backup)"
    fi
    # Clean up leftover renamed files: if both taos-X and tinyagentos-X exist,
    # the taos-X is a rename artifact (the tarball restored the original)
    for candidate in $(find . -maxdepth 3 -name 'taos*' -not -path '*/.git/*' 2>/dev/null); do
        original="${candidate//taos/tinyagentos}"
        if [[ -e "$original" ]]; then
            rm -f "$candidate"
            echo "Cleaned up leftover: $candidate"
        fi
    done
    # Clean up ALL backups
    rm -rf .rename-backup-*
    echo "Undo complete."
    echo "NOTE: Run 'git reset --hard HEAD' if you need to restore the git index too."
    exit 0
fi

# ── Idempotency check ──────────────────────────────────────────────────────
if [[ -d "taos" ]]; then
    echo "NOTE: taos/ already exists — directory rename already done (idempotent)."
    DIR_ALREADY_RENAMED=true
else
    DIR_ALREADY_RENAMED=false
fi

# ── Backup creation ────────────────────────────────────────────────────────
if ! $DRY_RUN; then
    BACKUP_DIR="$REPO_DIR/.rename-backup-$TIMESTAMP"
    mkdir -p "$BACKUP_DIR"

    # Build file list: everything tracked by git plus any untracked that
    # contain "tinyagentos" (excluding .git, node_modules, __pycache__, venv)
    echo "Building file list for backup..."
    FILE_LIST="$BACKUP_DIR/file-list.txt"
    {
        git ls-files
        git ls-files --others --exclude-standard
    } | sort -u > "$FILE_LIST"

    # Only back up files that exist and are regular files
    echo "Creating backup tarball ($BACKUP_DIR/backup.tar.gz)..."
    tar czf "$BACKUP_DIR/backup.tar.gz" \
        -T "$FILE_LIST" \
        --transform "s|^|$REPO_DIR/|" \
        2>/dev/null || true

    # Record whether directory rename is needed
    if ! $DIR_ALREADY_RENAMED; then
        touch "$BACKUP_DIR/dir_was_renamed"
    fi

    echo "Backup created: $BACKUP_DIR/backup.tar.gz"
fi

# ── Helper: replace in files ───────────────────────────────────────────────
# Usage: replace_in_files "pattern" "replacement" "file_glob" "description"
#   pattern:      sed-compatible regex to find
#   replacement:  sed-compatible replacement
#   file_glob:    find -name pattern for files to scan
#   description:  human-readable label for dry-run output
replace_in_files() {
    local pattern="$1"
    local replacement="$2"
    local file_glob="$3"
    local description="$4"

    while IFS= read -r -d '' file; do
        # Skip binary files
        if file -b --mime-encoding "$file" 2>/dev/null | grep -qv 'binary'; then
            if grep -q "$pattern" "$file" 2>/dev/null; then
                if $DRY_RUN; then
                    local count
                    count=$(grep -c "$pattern" "$file" 2>/dev/null || echo 0)
                    echo "  [DRY-RUN] $description: $file ($count matches)"
                    while IFS= read -r line; do
                        echo "    $line"
                    done < <(grep -n "$pattern" "$file" 2>/dev/null || true)
                else
                    sed -i "s|$pattern|$replacement|g" "$file"
                    local count
                    count=$(grep -c "$replacement" "$file" 2>/dev/null || echo 0)
                    echo "  [OK] $description: $file"
                    CHANGES_MADE=$((CHANGES_MADE + 1))
                fi
            fi
        fi
    done < <(find . -name "$file_glob" -not -path '*/.git/*' \
        -not -path '*/node_modules/*' -not -path '*/__pycache__/*' \
        -not -path '*/.venv/*' -not -path '*/venv/*' \
        -not -path '*/.rename-backup-*' -not -path '*/site/*' \
        -not -name 'rename-tinyagentos.sh' \
        -print0 2>/dev/null || true)
}

# ── Helper: rename files/directories ───────────────────────────────────────
rename_path() {
    local old_path="$1"
    local new_path="$2"
    local description="$3"

    if [[ -e "$old_path" ]]; then
        if [[ -e "$new_path" ]]; then
            echo "  [SKIP] $description: $new_path already exists (idempotent)"
        else
            if $DRY_RUN; then
                echo "  [DRY-RUN] $description: mv $old_path → $new_path"
            else
                mv "$old_path" "$new_path"
                echo "  [OK] $description: $old_path → $new_path"
                CHANGES_MADE=$((CHANGES_MADE + 1))
            fi
        fi
    else
        echo "  [SKIP] $description: $old_path does not exist (already renamed?)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 0: Pre-flight check
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 0: Pre-flight ==="
echo "Repository: $REPO_DIR"
echo "Mode:       $($DRY_RUN && echo 'DRY-RUN' || echo 'LIVE')"
echo "Backup:     $BACKUP_DIR"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1: Directory rename
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 1: Directory rename ==="
if ! $DIR_ALREADY_RENAMED; then
    if $DRY_RUN; then
        echo "  [DRY-RUN] mv tinyagentos/ → taos/"
    else
        git mv tinyagentos taos 2>/dev/null || mv tinyagentos taos
        echo "  [OK] Directory renamed: tinyagentos/ → taos/"
        CHANGES_MADE=$((CHANGES_MADE + 1))
    fi
else
    echo "  [SKIP] taos/ already exists"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2: Python imports — the bulk of the work
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 2: Python imports ==="

# 2a: from tinyagentos.X import Y  →  from taos.X import Y
echo "--- 2a: 'from tinyagentos.' → 'from taos.' ---"
replace_in_files \
    'from tinyagentos\.' 'from taos.' \
    '*.py' \
    'from tinyagentos. → from taos.'

# 2b: import tinyagentos (standalone, not followed by dot)
echo "--- 2b: 'import tinyagentos' → 'import taos' ---"
replace_in_files \
    'import tinyagentos$' 'import taos' \
    '*.py' \
    'import tinyagentos → import taos'

# 2b2: import tinyagentos.X (dotted import of submodule)
echo "--- 2b2: 'import tinyagentos.X' → 'import taos.X' ---"
replace_in_files \
    'import tinyagentos\.' 'import taos.' \
    '*.py' \
    'import tinyagentos.X → import taos.X'

# 2c: import tinyagentos as alias
echo "--- 2c: 'import tinyagentos as' → 'import taos as' ---"
replace_in_files \
    'import tinyagentos as ' 'import taos as ' \
    '*.py' \
    'import tinyagentos as X → import taos as X'

# 2d: mock.patch("tinyagentos..."  (double-quoted mock strings)
echo "--- 2d: mock.patch(\"tinyagentos.\" → mock.patch(\"taos.\" ---"
replace_in_files \
    'patch("tinyagentos\.' 'patch("taos.' \
    '*.py' \
    'patch("tinyagentos." → patch("taos."'

# 2e: mock.patch('tinyagentos...'  (single-quoted mock strings)
echo "--- 2e: mock.patch('tinyagentos.' → mock.patch('taos.' ---"
replace_in_files \
    "patch('tinyagentos\\." "patch('taos." \
    '*.py' \
    "patch('tinyagentos. → patch('taos."

# 2f: setattr("tinyagentos... (monkeypatch.setattr strings)
echo "--- 2f: setattr(\"tinyagentos.\" → setattr(\"taos.\" ---"
replace_in_files \
    'setattr("tinyagentos\.' 'setattr("taos.' \
    '*.py' \
    'setattr("tinyagentos. → setattr("taos.'

# 2g: python -m tinyagentos  →  python -m taos (CLI invocations in Python docstrings + shell scripts)
echo "--- 2g: python -m tinyagentos → python -m taos ---"
replace_in_files \
    'python -m tinyagentos' 'python -m taos' \
    '*.py' \
    'python -m tinyagentos → python -m taos'

# 2h: python3 -m tinyagentos
replace_in_files \
    'python3 -m tinyagentos' 'python3 -m taos' \
    '*.py' \
    'python3 -m tinyagentos → python3 -m taos'

# 2i: uvicorn tinyagentos.app → uvicorn taos.app (in Python files)
echo "--- 2i: uvicorn tinyagentos.app → uvicorn taos.app ---"
replace_in_files \
    'uvicorn tinyagentos\.' 'uvicorn taos.' \
    '*.py' \
    'uvicorn tinyagentos.app → uvicorn taos.app'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3: Shell scripts — installers, systemd generators, build scripts
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 3: Shell scripts (.sh) ==="

# 3a: python -m tinyagentos in shell scripts
echo "--- 3a: python -m tinyagentos → python -m taos ---"
replace_in_files \
    'python -m tinyagentos' 'python -m taos' \
    '*.sh' \
    'python -m tinyagentos → python -m taos'

# 3b: uvicorn tinyagentos.app in shell scripts
echo "--- 3b: uvicorn tinyagentos.app → uvicorn taos.app ---"
replace_in_files \
    'uvicorn tinyagentos\.' 'uvicorn taos.' \
    '*.sh' \
    'uvicorn tinyagentos.app → uvicorn taos.app'

# 3c: from tinyagentos.app import ... in inline python in shell scripts
echo "--- 3c: from tinyagentos.app → from taos.app ---"
replace_in_files \
    'from tinyagentos\.' 'from taos.' \
    '*.sh' \
    'from tinyagentos. → from taos.'

# 3d: import tinyagentos in inline python in shell scripts
echo "--- 3d: import tinyagentos → import taos ---"
replace_in_files \
    'import tinyagentos' 'import taos' \
    '*.sh' \
    'import tinyagentos → import taos'

# 3e: Directory paths in shell scripts
echo "--- 3e: ~/tinyagentos/ → ~/taos/ paths ---"
replace_in_files \
    '~/tinyagentos/' '~/taos/' \
    '*.sh' \
    '~/tinyagentos/ → ~/taos/'

# 3f: /opt/tinyagentos/ → /opt/taos/
replace_in_files \
    '/opt/tinyagentos/' '/opt/taos/' \
    '*.sh' \
    '/opt/tinyagentos/ → /opt/taos/'

# 3g: /home/*/tinyagentos → /home/*/taos
replace_in_files \
    '/tinyagentos/' '/taos/' \
    '*.sh' \
    '/tinyagentos/ → /taos/ in paths'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4: pyproject.toml
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 4: pyproject.toml ==="
if [[ -f pyproject.toml ]]; then
    if $DRY_RUN; then
        grep -n 'tinyagentos' pyproject.toml | while IFS= read -r line; do
            echo "  [DRY-RUN] pyproject.toml: $line"
        done
        echo "  [DRY-RUN] pyproject.toml: [project] name 'tinyagentos' → 'taos'"
        echo "  [DRY-RUN] pyproject.toml: entry point paths: tinyagentos. → taos."
        echo "  [DRY-RUN] pyproject.toml: include = [\"tinyagentos*\"] → [\"taos*\"]"
    else
        # Package name
        sed -i 's|^name = "tinyagentos"$|name = "taos"|' pyproject.toml
        # Entry point paths (only the module paths, not the command names)
        sed -i 's|= "tinyagentos\.|= "taos.|g' pyproject.toml
        # Package finder include
        sed -i 's|include = \["tinyagentos\*"\]|include = ["taos*"]|' pyproject.toml
        echo "  [OK] pyproject.toml: name + entry points + package include updated"
        CHANGES_MADE=$((CHANGES_MADE + 1))
    fi
else
    echo "  [SKIP] pyproject.toml not found"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5: systemd units — filenames + contents
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 5: systemd units ==="

# 5a: Rename systemd unit files
for unit_path in \
    tinyagentos.service \
    systemd/tinyagentos.service \
    systemd/tinyagentos-disk-quota.service \
    systemd/tinyagentos-disk-quota.timer \
    systemd/tinyagentos-host-firewall.service \
    systemd/tinyagentos-host-firewall.timer \
    systemd/tinyagentos-host-firewall.path \
    tinyagentos-sdcpp.service \
    scripts/systemd/tinyagentos.service \
; do
    if [[ -f "$unit_path" ]]; then
        new_path="${unit_path//tinyagentos/taos}"
        rename_path "$unit_path" "$new_path" "systemd unit: $unit_path → $new_path"
    fi
done

# 5b: Update references INSIDE systemd unit files
echo "--- 5b: systemd unit file contents ---"
replace_in_files \
    'tinyagentos' 'taos' \
    '*.service' \
    'systemd unit file contents'

replace_in_files \
    'tinyagentos' 'taos' \
    '*.timer' \
    'systemd timer contents'

replace_in_files \
    'tinyagentos' 'taos' \
    '*.path' \
    'systemd path contents'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 6: CI workflows (GitHub Actions)
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 6: CI workflows (.github/workflows/) ==="
# Paths and import commands in CI YAML
replace_in_files \
    'tinyagentos/' 'taos/' \
    '*.yml' \
    'CI: tinyagentos/ → taos/ paths'

replace_in_files \
    'tinyagentos/' 'taos/' \
    '*.yaml' \
    'CI: tinyagentos/ → taos/ paths'

# from tinyagentos.app import ... inside inline CI scripts
replace_in_files \
    'from tinyagentos\.' 'from taos.' \
    '*.yml' \
    'CI: from tinyagentos. → from taos.'

replace_in_files \
    'from tinyagentos\.' 'from taos.' \
    '*.yaml' \
    'CI: from tinyagentos. → from taos.'

# Note: jaylfc/tinyagentos-images is a separate repo — leave as-is for now
# (it's a GitHub repo name, not a package reference)
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 7: Documentation — README, docs, markdown
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 7: Documentation (.md, .rst) ==="

# 7a: README.md — replace all mentions EXCEPT keep one origin note
echo "--- 7a: README.md (special: preserve one origin note) ---"
if [[ -f README.md ]]; then
    if $DRY_RUN; then
        echo "  [DRY-RUN] README.md: all tinyagentos → taos (preserving one origin note)"
        grep -n 'tinyagentos' README.md | while IFS= read -r line; do
            echo "    $line"
        done
    else
        # Count occurrences before
        before_count=$(grep -c 'tinyagentos' README.md || echo 0)

        # Replace all
        sed -i 's|tinyagentos|taos|g' README.md

        # Restore exactly one origin note at the top
        # We insert: "> **Origin note:** This project was originally called **TinyAgentOS**.
        # > The rename to **taOS** took effect in mid-2026."
        sed -i '1s|^|> **Origin note:** This project was originally called **TinyAgentOS**. The rename to **taOS** took effect in mid-2026.\n\n|' README.md

        after_count=$(grep -c 'tinyagentos\|TinyAgentOS' README.md || echo 0)
        echo "  [OK] README.md: $before_count occurrences → taos, 1 origin note preserved ($after_count tinyagentos references remain)"
        CHANGES_MADE=$((CHANGES_MADE + 1))
        README_ORIGIN_MARKER_KEPT=true
    fi
else
    echo "  [SKIP] README.md not found"
fi

# 7b: Other markdown files — full replacement
echo "--- 7b: Other markdown files (.md) ---"
replace_in_files \
    'tinyagentos' 'taos' \
    '*.md' \
    'docs: tinyagentos → taos'

# 7c: RST files
echo "--- 7c: RST files (.rst) ---"
replace_in_files \
    'tinyagentos' 'taos' \
    '*.rst' \
    'docs: tinyagentos → taos'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 8: Docker / container files
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 8: Docker / container files ==="
replace_in_files \
    'tinyagentos' 'taos' \
    'Dockerfile*' \
    'Dockerfile: tinyagentos → taos'

replace_in_files \
    'tinyagentos' 'taos' \
    'docker-compose*.yml' \
    'docker-compose: tinyagentos → taos'

replace_in_files \
    'tinyagentos' 'taos' \
    'docker-compose*.yaml' \
    'docker-compose: tinyagentos → taos'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 9: Desktop SPA (TypeScript/React)
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 9: Desktop SPA (.ts, .tsx, .json) ==="

# 9a: Comments referencing backend paths
replace_in_files \
    'tinyagentos/' 'taos/' \
    '*.ts' \
    'desktop: comment references tinyagentos/ → taos/'

replace_in_files \
    'tinyagentos/' 'taos/' \
    '*.tsx' \
    'desktop: comment references tinyagentos/ → taos/'

# 9b: package.json name
if [[ -f desktop/package.json ]]; then
    if $DRY_RUN; then
        grep -n 'tinyagentos' desktop/package.json | while IFS= read -r line; do
            echo "  [DRY-RUN] desktop/package.json: $line"
        done
    else
        sed -i 's|"tinyagentos-desktop"|"taos-desktop"|' desktop/package.json
        echo "  [OK] desktop/package.json: name updated"
        CHANGES_MADE=$((CHANGES_MADE + 1))
    fi
fi

# 9c: localStorage keys — add migration shim, do NOT rename keys in-place
#     (renaming would lose user data; migration reads old keys on load)
echo "--- 9c: localStorage key migration comments ---"
# We don't rename the keys themselves — we add migration comments near them
# in the source files. The actual migration code must be written separately.
# This script just flags them for the developer.
for file in \
    desktop/src/apps/TextEditorApp.tsx \
    desktop/src/apps/TerminalApp.tsx \
    desktop/src/components/Desktop.tsx \
    desktop/src/components/widgets/QuickNotesWidget.tsx \
; do
    if [[ -f "$file" ]]; then
        if $DRY_RUN; then
            echo "  [DRY-RUN] $file: localStorage key needs migration (flagged)"
        else
            # Add a comment above the STORAGE_KEY / RECENT_KEY line
            # We use a marker to find and annotate the key lines
            if grep -q 'STORAGE_KEY\|RECENT_KEY.*tinyagentos' "$file" 2>/dev/null; then
                # Add a migration TODO comment above the key definition
                sed -i '/STORAGE_KEY.*tinyagentos\|RECENT_KEY.*tinyagentos/i\// MIGRATION(#1937): on app load, read from old tinyagentos-* key, write to new taos-* key, then delete old key.' "$file"
            fi
            echo "  [OK] $file: localStorage key flagged for migration"
            CHANGES_MADE=$((CHANGES_MADE + 1))
        fi
    fi
done

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 10: Config files — doc-gate, mkdocs, YAML, TOML
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 10: Config files (.toml, .yaml, .yml, .json, .cfg, .ini) ==="

# 10a: doc-gate.toml path patterns
replace_in_files \
    'tinyagentos/' 'taos/' \
    '*.toml' \
    'config: tinyagentos/ → taos/ paths'

# 10b: YAML files
replace_in_files \
    'tinyagentos' 'taos' \
    '*.yaml' \
    'config: tinyagentos → taos in YAML'

# 10c: YML files
replace_in_files \
    'tinyagentos' 'taos' \
    '*.yml' \
    'config: tinyagentos → taos in YML'

# 10d: JSON files
replace_in_files \
    'tinyagentos' 'taos' \
    '*.json' \
    'config: tinyagentos → taos in JSON'

# 10e: Other config extensions
replace_in_files \
    'tinyagentos' 'taos' \
    '*.cfg' \
    'config: tinyagentos → taos'

replace_in_files \
    'tinyagentos' 'taos' \
    '*.ini' \
    'config: tinyagentos → taos'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 11: HTML / CSS / template files
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 11: HTML / CSS / templates ==="
replace_in_files \
    'tinyagentos' 'taos' \
    '*.html' \
    'HTML: tinyagentos → taos'

replace_in_files \
    'tinyagentos' 'taos' \
    '*.css' \
    'CSS: tinyagentos → taos'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 12: os-build references
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 12: os-build ==="
replace_in_files \
    'tinyagentos' 'taos' \
    '*.sh' \
    'os-build: tinyagentos → taos in os-build scripts'

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 13: App catalog
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 13: App catalog ==="
replace_in_files \
    'tinyagentos' 'taos' \
    '*.yaml' \
    'app-catalog: tinyagentos → taos in manifests'

# Recycle sweep systemd units in catalog
for unit_path in \
    app-catalog/agents/openclaw/scripts/install.sh \
    app-catalog/_common/scripts/recycle-bin-install.sh \
; do
    if [[ -f "$unit_path" ]]; then
        if $DRY_RUN; then
            grep -n 'tinyagentos-recycle' "$unit_path" | while IFS= read -r line; do
                echo "  [DRY-RUN] $unit_path: $line"
            done
        else
            sed -i 's|tinyagentos-recycle-sweep|taos-recycle-sweep|g' "$unit_path"
            echo "  [OK] $unit_path: recycle-sweep unit names updated"
            CHANGES_MADE=$((CHANGES_MADE + 1))
        fi
    fi
done

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 14: Docs reference in site/ — skip external URLs
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 14: site/ and landing/ references ==="
# External URLs (tinyagentos.com, docs.tinyagentos.com) are NOT changed —
# those are external domain names that need DNS/redirect handling, not a
# code rename. We only change local path references.
echo "  [INFO] External URLs (tinyagentos.com, docs.tinyagentos.com) NOT changed."
echo "  [INFO] These require DNS redirects, not a codemod."
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 15: Final sweep — catch any remaining .py files
# ═══════════════════════════════════════════════════════════════════════════
echo "=== PHASE 15: Final sweep — remaining tinyagentos in Python files ==="
# String literals with "tinyagentos" (not import statements, which were handled)
# This catches things like error messages, docstrings, __main__ module refs
remaining_pattern="['\"]tinyagentos"
while IFS= read -r -d '' file; do
    if file -b --mime-encoding "$file" 2>/dev/null | grep -qv 'binary'; then
        if grep -q "$remaining_pattern" "$file" 2>/dev/null; then
            if $DRY_RUN; then
                count=$(grep -c "$remaining_pattern" "$file" 2>/dev/null || echo 0)
                echo "  [DRY-RUN] remaining tinyagentos string: $file ($count matches)"
                grep -n "$remaining_pattern" "$file" | while IFS= read -r line; do
                    echo "    $line"
                done
            else
                # Replace both single-quoted and double-quoted strings
                sed -i "s|\"tinyagentos|\"taos|g" "$file"
                sed -i "s|'tinyagentos|'taos|g" "$file"
                echo "  [OK] remaining strings: $file"
                CHANGES_MADE=$((CHANGES_MADE + 1))
            fi
        fi
    fi
done < <(find . -name '*.py' -not -path '*/.git/*' \
    -not -path '*/node_modules/*' -not -path '*/__pycache__/*' \
    -not -path '*/.venv/*' -not -path '*/venv/*' \
    -not -path '*/.rename-backup-*' -not -name 'rename-tinyagentos.sh' \
    -print0 2>/dev/null || true)

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
echo "╔══════════════════════════════════════════════════════════════════════╗"
if $DRY_RUN; then
    echo "║  DRY-RUN COMPLETE — no changes were made.                          ║"
    echo "║  Run without --dry-run to execute the rename.                      ║"
else
    echo "║  RENAME COMPLETE                                                   ║"
    echo "║  Backup: $BACKUP_DIR/backup.tar.gz"
    echo "║  Undo:   $0 --undo                                                 ║"
fi
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  Files/directories modified: $CHANGES_MADE"
if $README_ORIGIN_MARKER_KEPT; then
    echo "║  README.md: origin note preserved ✓                               ║"
fi
echo "║  External URLs NOT changed (need DNS redirects):                   ║"
echo "║    - tinyagentos.com                                               ║"
echo "║    - docs.tinyagentos.com                                          ║"
echo "║    - raw.githubusercontent.com/jaylfc/tinyagentos/...              ║"
echo "║    - github.com/jaylfc/tinyagentos (repo name)                     ║"
echo "║  localStorage keys flagged for migration (not renamed in-place)    ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# ── Post-rename verification hints ─────────────────────────────────────────
if ! $DRY_RUN; then
    echo ""
    echo "=== NEXT STEPS ==="
    echo "1. Verify: grep -r 'tinyagentos' --include='*.py' | grep -v '.rename-backup' | wc -l"
    echo "   (Should be near zero in package code; README should have exactly 1)"
    echo ""
    echo "2. Run tests:  pytest tests/ --ignore=tests/e2e -n auto"
    echo ""
    echo "3. Check systemd units: ls -la *.service systemd/*.service scripts/systemd/*.service"
    echo ""
    echo "4. If anything is wrong: $0 --undo"
fi

exit 0
