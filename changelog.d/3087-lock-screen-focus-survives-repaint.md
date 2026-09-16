- Lock screen: keyboard focus now survives the islands' 15-second refresh. The
  poll rebuilt the agent list from scratch, which destroyed whichever island held
  focus and dropped the user back to the top of the page; because the islands and
  their mic buttons come before the notification stacks in tab order, a keyboard
  or switch-access user could never tab far enough to reach a stack. Focus is now
  captured before the rebuild and restored afterwards, keyed on the agent rather
  than its position so a reordered list cannot silently move focus to a different
  agent.
