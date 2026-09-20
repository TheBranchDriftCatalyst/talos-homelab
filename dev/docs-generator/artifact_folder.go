package main

// The `folder-readme` renderer: one document per folder, assembled from that folder's inline
// blocks, with the structure declared by the blocks themselves.
//
// TWO CASES, and the difference between them is the whole safety story.
//
//	NO README EXISTS — the document is generated outright: a title, a generated banner, and the
//	block tree. Nothing can be clobbered because there is nothing there, so the usual
//	"missing markers is a hard error" rule does not apply and would only mean a folder can
//	never acquire a README.
//
//	A README EXISTS — only the marker region is touched. Human prose outside it is never read,
//	never rewritten, and never even parsed. This is the rule that makes the feature adoptable:
//	the cost of turning it on for a folder that already has a good README is bounded to the
//	region, so nobody has to choose between generation and the prose they already wrote.
//
// The failure this design refuses: a generator that "merges" hand-written and generated prose.
// Every such merge eventually guesses wrong about which side is authoritative, and the guess is
// unrecoverable because both sides look like documentation. Block separation means the
// authority question never arises.

import (
	"fmt"
	"path"
	"path/filepath"
	"strings"
)

func renderFolderReadme(ctx *Ctx, spec ArtifactSpec) string {
	root := strings.Trim(strings.TrimSpace(spec.Root), "/")
	blocks := blocksUnder(CollectBlocks(ctx), root)

	var sb strings.Builder
	if len(blocks) == 0 {
		fmt.Fprintf(&sb, "_No inline documentation blocks found under `%s`._\n\n", rootLabel(root))
		sb.WriteString("Write one beside the code it describes:\n\n")
		sb.WriteString("```yaml\n# doc() why-this-value: Why the timeout is 48h\n")
		sb.WriteString("#   section: Configuration\n#   The GC never ran at 720h, so rows accumulated per pod IP.\n```\n")
		return sb.String()
	}

	// Depth 3 because the region sits under a `## ...` heading in the host document. A generated
	// region that emits `#` would produce two H1s, which markdownlint reports as MD025 and which
	// this repo's own frontmatter rules ban for the same reason.
	buildSections(blocks).render(3, path.Dir(path.Join(rootLabel(root), spec.Path)), &sb)
	return strings.TrimRight(sb.String(), "\n") + "\n"
}

// blocksUnder selects blocks whose defining FILE is inside the folder.
//
// Deliberately file-position, not a `scope:` field like claims use. A doc block describes the
// code it sits in; giving it a second, declarable location would let the two disagree, and a
// block claiming to belong somewhere it does not live is precisely the drift this removes.
func blocksUnder(all []Block, root string) []Block {
	var out []Block
	for _, b := range all {
		if root == "" || b.File == root || strings.HasPrefix(b.File, root+"/") {
			out = append(out, b)
		}
	}
	return out
}

// scaffoldReadme is the whole-file content used when a folder has no README at all.
//
// The markers are included even though nothing is outside them yet: the point is that the NEXT
// person can add prose above or below and keep regeneration working. A generated file with no
// markers would force a choice between hand-editing and regeneration the first time someone
// wanted to add a sentence.
func scaffoldReadme(ctx *Ctx, spec ArtifactSpec, region string) string {
	root := strings.Trim(strings.TrimSpace(spec.Root), "/")
	title := filepath.Base(root)
	if title == "." || title == "" {
		title = "Documentation"
	}

	var sb strings.Builder
	fmt.Fprintf(&sb, "# %s\n\n", title)
	sb.WriteString("> Sections between the markers below are generated from inline `doc()` and\n")
	sb.WriteString("> `diagram()` blocks in this folder. Edit the comment beside the code, not here.\n")
	sb.WriteString("> Anything OUTSIDE the markers is yours and is never touched.\n\n")
	sb.WriteString("## Reference\n\n")
	fmt.Fprintf(&sb, "<!-- docs:gen:%s -->\n\n", region)
	sb.WriteString(renderFolderReadme(ctx, spec))
	fmt.Fprintf(&sb, "\n<!-- /docs:gen:%s -->\n", region)
	return sb.String()
}
