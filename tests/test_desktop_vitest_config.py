import pathlib
import re


DESKTOP_VITE_CONFIG = pathlib.Path(__file__).resolve().parent.parent / "desktop" / "vite.config.ts"


def test_vitest4_pool_options_are_top_level():
    content = DESKTOP_VITE_CONFIG.read_text()

    assert "poolOptions" not in content, "desktop/vite.config.ts still uses removed `poolOptions`"

    test_block_match = re.search(r"test:\s*\{", content)
    assert test_block_match is not None, "desktop/vite.config.ts missing `test:` block"

    brace_start = test_block_match.start()
    brace_depth = 0
    test_block_end = None
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            brace_depth += 1
        elif content[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                test_block_end = i
                break

    assert test_block_end is not None, "desktop/vite.config.ts `test:` block not closed"
    test_block = content[brace_start:test_block_end]

    assert "maxWorkers" in test_block, "`maxWorkers` not found in `test:` block"
    assert "minWorkers" in test_block, "`minWorkers` not found in `test:` block"
    assert "execArgv" in test_block, "`execArgv` not found in `test:` block"
