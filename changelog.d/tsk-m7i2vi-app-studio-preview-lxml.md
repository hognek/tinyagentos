### Fixed

- App Studio preview now uses `lxml.html` to assemble the preview document instead of regex surgery, preventing JS strings containing `</script>` and CSS strings containing `</style>` from breaking out of their inline blocks. Also fixes quoted attributes containing `>` being truncated, unquoted attributes being ignored, and `url()` data-URIs containing `)` being corrupted.
