# Links to another setup carry the choices and the way back (empty_next, next)

Follow-up to see_also (#276), from Jared: the plain `{text, href: "/workspace/setups/..."}` links ("Bring the Fountain in: Narrate a
story") open the other setup with nothing chosen and no way back.

- [x] `empty_next` and a `next` line take `{text, setup, step?, carry?}` beside `{step}` / `{text, href}` (old ones unchanged)
- [x] lib/wizard.ts `isSetupLink`, `setupLinkHref`, `nextLines`; wizardEmpty `emptyLinks(…, entries)`; page passes `entries`
- [x] validator `_check_setup_link` / `_check_carry` (shared with see_also); `next` checked after the steps (its carry reads any choice)
- [x] docs, node + pytest
- [ ] scratch click-through (an empty step's link, a next line, Back, a bad back)
- [ ] Studio: every such link converted; Grace: two next lines; Storyworld: none
