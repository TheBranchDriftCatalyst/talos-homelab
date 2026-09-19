---
title: The Old Plan
author: somebody who left
sla: 99.99%
status: superseded
type: wildly-invalid
covers: [flow, sequence, nonsense]
freshness: yesterday
---

EXPECT: none

Not "none today" — none ever. This file violates nearly every rule at once — three banned keys, a type outside the enum, a
freshness outside the enum, `superseded` with no `superseded_by`, a flow sequence for `covers`
full of tokens that match nothing, keys in the wrong order, no H1, no `## Tracking` footer, and
a [dead link](./vanished.md). It sits under `handbook/_attic/`, which this sample's config
excludes.

If ANY finding is ever attributed to this path, `exclude` stopped working, and the first
casualty in a real repo is the archive nobody will ever action — which is how a linter gets
switched off.
