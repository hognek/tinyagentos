- Phone lock screen: a weather reading between the clock and the agent islands
  (Liverpool, °C and mph), fetched server-side and cached so a woken handset
  does not call the forecast API once per paint.
- Phone lock screen: iOS-style notification stacks under the agent islands.
  One collated pile per source — mail, X, Reddit, missed calls, SMS — newest
  first, with the rest of a source's banners tucked behind the top one and a
  count on it; pressing a pile fans it out in place. Scripted demo content
  only, on the same `TAOS_LOCK_DEMO_AGENTS` flag as the placeholder agents:
  this screen renders before sign-in and never reads a real inbox.
- Phone lock screen: the agent islands and the notifications now scroll as one
  feed instead of the islands scrolling alone, and the cut edge fades rather
  than slicing a card in half.
