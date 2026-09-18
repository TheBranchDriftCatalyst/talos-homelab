//go:build tools

package main

// Test-only tool dependencies, declared so `go mod tidy` keeps them pinned in go.mod before any
// spec file imports them — and so the ginkgo CLI version is pinned by the SAME module graph as
// the ginkgo library. A CLI/library version skew is a documented ginkgo footgun, and taking the
// CLI from nixpkgs (2.32.1) while the library tracks latest would guarantee one. `go run
// github.com/onsi/ginkgo/v2/ginkgo` resolves through this file, so the two cannot drift.
//
// Nothing here is compiled into the docsgen binary: the build tag excludes this file from every
// normal build, so `go build` and the shipped tool remain free of test dependencies. A repo
// porting dev/docs-generator/ still gets a dependency-light binary; only `go test` needs network.

import (
	_ "github.com/onsi/ginkgo/v2"
	_ "github.com/onsi/ginkgo/v2/ginkgo"
	_ "github.com/onsi/gomega"
)
