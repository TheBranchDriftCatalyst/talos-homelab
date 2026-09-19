---
type: spec
status: current
covers:
  - billing
freshness: live
tickets:
  - PD-01
---

# Billing

## Interface

Takes an order, returns an invoice.

Correctly colocated: covers the `billing` component, whose path is `services/billing`, and
lives inside it. Zero findings expected. This is also the sample's STALE doc — the fixture
builder's second commit touches `main.go` beside it.

## Follow-up

- PD-01 — billing interface
