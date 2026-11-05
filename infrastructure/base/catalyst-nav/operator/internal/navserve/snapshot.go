package navserve

// The handoff between the reconciler and the request path.
//
// WHY A SNAPSHOT AND NOT A PER-REQUEST BUILD. The handler could list IngressRoutes from the
// controller's cache and run navmodel.Build on every request — the cache is in memory and the
// cluster has ~300 routes, so it would be fast enough. It would also be WRONG in a way that is
// hard to see: two requests arriving either side of a reconcile would get models built from
// different cache states, and the served bytes would then disagree with the published
// ConfigMap that phase 6's audit diffs. One build per reconcile, read by every request, makes
// "what the endpoint serves" and "what the ConfigMap holds" the same object by construction.
//
// Also why the store is an atomic pointer rather than a mutex: the reconcile is a single
// goroutine replacing the whole value, requests only ever read, and a read must never be able
// to observe a half-swapped model.

import (
	"sync/atomic"
	"time"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

// Snapshot is one reconcile's output: the unfiltered model, the visibility rules to narrow it
// with, and enough provenance to debug a stale response.
//
// IMMUTABLE ONCE STORED. visibility.Filter does not modify the model it reads, and nothing
// here hands out a reference that would let a caller mutate it — Manifest is reachable through
// the pointer, so "do not write to it" is a convention rather than a guarantee, and the only
// writer is the reconciler that built it before storing.
type Snapshot struct {
	Manifest *navmodel.Manifest
	Index    visibility.Index

	// Revision is the sha256 of the UNFILTERED manifest bytes — the same value the
	// reconciler annotates onto the published ConfigMap. Served as an ETag-shaped header so
	// a human comparing the endpoint against the ConfigMap can see at a glance whether they
	// are looking at the same build.
	//
	// NOT used as an HTTP ETag, deliberately: an ETag is a cache validator, and a validator
	// on a per-identity response invites exactly the shared-cache confusion this endpoint
	// must not permit. It is a plain diagnostic header.
	Revision string

	// BuiltAt is when the reconcile that produced this ran.
	BuiltAt time.Time
}

// Store holds the current Snapshot. Safe for one writer and many readers.
type Store struct {
	cur atomic.Pointer[Snapshot]
}

// Publish replaces the current snapshot.
func (s *Store) Publish(snap *Snapshot) { s.cur.Store(snap) }

// Snapshot returns the current snapshot, or nil before the first reconcile has completed.
func (s *Store) Snapshot() *Snapshot { return s.cur.Load() }
