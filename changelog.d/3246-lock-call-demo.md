- Lock screen: an incoming-call demo in the live zone. A call from Mary gathers
  the showing islands or cards into one liquid droplet that stretches into a
  call card, with Decline, Voicemail, Answer and a headline Send to PA. With
  Send to PA, the PA's conversation plays as a live transcript that reveals
  word by word, with Take over and End call pinned for the whole call. When the
  PA finishes, the card shrinks to a one-line "Reminder added · Call Mary ·
  Tomorrow 12:30 pm" pill, the feed returns exactly as it was, and the PA's reminder
  appears at the top of Alerts with a Dismiss button.
- Lock screen: the call is scripted demo content served by `/auth/lock-call`
  (with `/ring`, `/reset`, `/action` and `/dismiss`). All five routes are
  console-only and 404 unless `TAOS_LOCK_DEMO_CALL` is set, which is
  independent of the other demo flags; the Settings demo-mode switch turned off
  404s them too. The four POSTs pass the same console-header gate as every
  other `/auth/lock-*` POST, and the call zone listens on the page's one shared
  event stream. There is no path from it to a phone
  line, contacts or a calendar.
