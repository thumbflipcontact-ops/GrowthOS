# Plugin: WebmasterWorld

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Long-running SEO/webmaster discussion forum — another high-relevance source for ScoutSEO's
ICP, complementary to GSC Community (more experienced/technical audience, different tone).

## Auth

Forum account credentials (username/password or session cookie), stored encrypted. No
public API — `search()` and `publish()` both implemented against the forum's own web
interface. Respect the forum's posting norms and rate expectations; this is a community with
strong norms against low-effort or obviously automated posts, which reinforces (rather than
conflicts with) GrowthOS's human-approval requirement — every post here should read as
genuinely written by the founder, which the approval step is meant to guarantee in
substance, not just in mechanism.

## Known constraints

Forum structure/markup changes are a real maintenance risk for anything web-interface-based;
`search()` and `publish()` should be isolated behind this plugin's own client module so a
forum redesign is a one-file fix, not a cross-codebase one.
