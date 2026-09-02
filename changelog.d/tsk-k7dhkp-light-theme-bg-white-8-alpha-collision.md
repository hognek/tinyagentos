### Fixed
- The light-theme compatibility layer now inverts `bg-white/8` to `rgba(0, 0, 0, 0.05)`
  instead of `0.08`, restoring the strictly increasing scale `/5 (0.04) < /8 (0.05)
  < /10 (0.06) < /15 (0.08) < /20 (0.10)`. Previously `/8` collided with `/15` and
  exceeded `/10`, so surfaces using `bg-white/8` for a subtler affordance than
  `bg-white/15` rendered identically, and darker than `bg-white/10`. The `hover:`
  and `focus:` variant mirrors were fixed alongside the base utility.
