package main

// Ginkgo bootstrap for the unit layer.
//
// Every top-level container in *_unit_test.go carries Label("unit") so the Taskfile's
// `--label-filter=unit` selects exactly this layer and nothing else. The pre-existing
// table-driven `go test` functions in generate_test.go run alongside these specs under plain
// `go test`; they are untouched by the label filter because the filter only applies to specs.

import (
	"testing"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

func TestDocsgen(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "docsgen suite")
}
