# TalkCraft production card modules

This directory is the only allowed location for qualified portrait card modules.
The module for `card-id` is `card-id.tsx`; its bytes must match the
`implementation_sha256` recorded in `card-registry.json`.

An absent module means the card is not implemented. A present module does not
grant production use: the business registry and qualification evidence must also
mark that exact implementation as qualified. Placeholder modules and fallback to
the mechanism probe are not allowed.
