- Phone kiosk: replaced the `cage` compositor with `sway`, which implements
  `wlr-output-power-management-v1`. The screen now really powers down after 30s
  idle (cage could only dim the backlight, leaving the output powered and touch
  live) and the hardware power key toggles the display.
- Added a phone lock screen: console PIN requests render a clock, device and
  battery chips, a native round PIN keypad, and Dynamic-Island style agent pills
  fed by a new console-only `GET /auth/lock-widgets`. LAN browsers still get the
  plain login card.
