- Lock screen: plugging in a charger plays a ten-second charging animation
  styled as a coding-agent terminal: a spinner, a rotating slogan ("Drinking
  the juice…"), and the battery percentage counting up with a block bar. With
  the screen off, it plays over pure black before the lock screen fades in.
  Its trigger, `POST /auth/lock-charge`, is gated like every other lock
  control: loopback plus the `X-taOS-Console` header or a JSON body.
