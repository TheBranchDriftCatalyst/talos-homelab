package main

// The `flux` strategy: one component per Flux Kustomization.
//
// That is right for a Flux repo because the directory tree alone is ambiguous — some
// directories are grouping dirs whose CHILDREN are the real units (the correct pattern), while
// others are a single Kustomization wrapping many nested ones (not). Flux names the real
// deployable boundary; the filesystem does not.
//
// Nothing outside this file mentions `flux`. It is reachable only through the registry, via the
// init() below.

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

func init() { register(fluxStrategy{}) }

type fluxStrategy struct{}

func (fluxStrategy) Name() string { return "flux" }

// Provides: everything. A Kustomization declares a name that drifts from its filename, a path
// that may not exist, a suspend flag and dependency edges — and its tree can be counted for
// nested kustomizations.
func (fluxStrategy) Provides() FactSet {
	return FactSet{
		FactDeclaredName:   true,
		FactSubUnits:       true,
		FactInactive:       true,
		FactDependsOn:      true,
		FactPathIsDeclared: true,
	}
}

// DefaultGlob is `*.yaml`, not `*`. The entries are handed to a YAML decoder expecting a
// Kustomization, so a bare `*` would pull README.md and every loose file in the cluster
// directory into the decode loop.
func (fluxStrategy) DefaultGlob() string { return "*.yaml" }

func (fluxStrategy) UnitNoun() string { return "Flux Kustomization" }

type fluxDoc struct {
	Kind     string `yaml:"kind"`
	Metadata struct {
		Name string `yaml:"name"`
	} `yaml:"metadata"`
	Spec struct {
		Path      string `yaml:"path"`
		Suspend   bool   `yaml:"suspend"`
		DependsOn []struct {
			Name string `yaml:"name"`
		} `yaml:"dependsOn"`
	} `yaml:"spec"`
}

// Enumerate never returns an error: a malformed manifest is a warning and a skipped unit, so
// one typo cannot make the linter useless in exactly the moment you want it.
func (s fluxStrategy) Enumerate(root string, cfg *Config) (Enumeration, error) {
	var enum Enumeration
	glob := globFor(s, cfg)
	dir := filepath.Join(root, cfg.Components.Path)
	entries, err := filepath.Glob(filepath.Join(dir, glob))
	if err != nil || len(entries) == 0 {
		enum.Warnings = append(enum.Warnings,
			fmt.Sprintf("%s: no component manifests matched %q", cfg.Components.Path, glob))
		return enum, nil
	}
	sort.Strings(entries)
	for _, f := range entries {
		raw, err := os.ReadFile(f)
		if err != nil {
			enum.Warnings = append(enum.Warnings,
				fmt.Sprintf("%s: %v", mustRel(root, f), pathErrorCause(err)))
			continue
		}
		// A single file may hold several documents; decoding only the first would silently
		// drop components. At least one file in this repo does exactly that.
		dec := yaml.NewDecoder(strings.NewReader(string(raw)))
		var inFile []fluxDoc
		for {
			var fd fluxDoc
			if err := dec.Decode(&fd); err != nil {
				break
			}
			if fd.Kind != "Kustomization" {
				continue
			}
			if strings.TrimPrefix(strings.TrimPrefix(fd.Spec.Path, "."), "/") == "" {
				enum.Warnings = append(enum.Warnings,
					fmt.Sprintf("%s: Kustomization with no spec.path", filepath.Base(f)))
				continue
			}
			inFile = append(inFile, fd)
		}
		base := strings.TrimSuffix(filepath.Base(f), filepath.Ext(f))
		for _, fd := range inFile {
			var deps []string
			for _, d := range fd.Spec.DependsOn {
				if d.Name != "" {
					deps = append(deps, d.Name)
				}
			}
			rel := strings.TrimPrefix(strings.TrimPrefix(fd.Spec.Path, "."), "/")
			enum.Components = append(enum.Components, Component{
				Slug:      slugFor(cfg, base, fd, len(inFile)),
				Name:      fd.Metadata.Name,
				Path:      rel,
				DependsOn: deps,
				Suspend:   fd.Spec.Suspend,
				Source:    mustRel(root, f),
				Nested:    countNested(root, rel),
			})
		}
	}
	return enum, nil
}

// slugFor picks the stable handle for one component.
//
// The filename is preferred, because metadata.name drifts from it in this repo and a slug that
// changes when someone renames a field is not a slug. But the filename is only a handle while it
// identifies ONE thing: external-secrets.yaml declares both `external-secrets-operator` and
// `external-secrets`, so under filename-slugging both collapsed to `external-secrets` and
// Ctx.BySlug silently kept whichever decoded last. That made `covers: external-secrets` resolve
// to an arbitrary one of two different paths — and therefore produced an arbitrary colocation
// verdict — with nothing reporting it.
//
// So: filename while the file declares exactly one Kustomization, metadata.name the moment it
// declares more. Uniqueness is the property that matters; the filename is just the usual way to
// get it.
func slugFor(cfg *Config, base string, fd fluxDoc, inFile int) string {
	if cfg.Components.SlugFrom == "metadata.name" && fd.Metadata.Name != "" {
		return fd.Metadata.Name
	}
	if inFile > 1 && fd.Metadata.Name != "" {
		return fd.Metadata.Name
	}
	return base
}
