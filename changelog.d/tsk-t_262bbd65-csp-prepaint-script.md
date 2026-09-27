### Fixed

- The desktop SPA applies the saved reduce-effects preference before first paint
  again. The pre-paint snippet was inline, and the app's Content-Security-Policy
  (`script-src 'self'`) blocks inline scripts, so the browser silently refused to
  run it: users who chose "reduce effects" saw the full effects flash on load
  until React mounted. The snippet now ships as an external same-origin script
  (`desktop/public/boot.js`) and the CSP is unchanged.