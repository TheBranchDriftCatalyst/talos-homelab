---
type: design
status: current
covers:
  - gateway
freshness: follows-code
tickets:
  - ORCH-103
summary: How the gateway terminates TLS and routes to workloads.
---

# Gateway

## Context

The gateway is the single ingress point for the cluster. It is its own Flux Kustomization, so
it is its own component, so this README is its doc home.

EXPECT: none

This doc is CORRECTLY COLOCATED: it covers `gateway`, whose path is `platform/gateway`, and it
lives at `platform/gateway/README.md`.

It is also a STALE doc. The fixture builder's second commit touches `deployment.yaml` beside it
and nothing else, so `gateway` is the only component whose code moved ahead of its docs — and
every doc covering `gateway` goes stale together, which is four of them.

## Tracking

- ORCH-103 — gateway design

## What is known here

<!-- docs:gen:knowledge -->

<!-- /docs:gen:knowledge -->

## Inline reference

<!-- docs:gen:inline-docs -->

<!-- /docs:gen:inline-docs -->
