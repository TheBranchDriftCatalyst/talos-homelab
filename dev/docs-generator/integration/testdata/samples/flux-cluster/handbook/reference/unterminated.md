---
type: table
status: current
covers:
  - path:handbook/reference

# Quota Table

EXPECT: frontmatter-schema

The opening `---` above is never closed, so there is no frontmatter and no body split.

This doc is NOT on the `docsgen frontmatter` worklist: a parse error is a different state from
"no frontmatter yet", and conflating the two would send somebody to add frontmatter to a file
that already has some. The link to [the handbook](../README.md) still resolves, which pins that
a doc the parser rejected is still walked for links.
