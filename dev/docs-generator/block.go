package main

// BLOCKS: inline documentation that controls its own document structure.
//
// A claim is one kind of knowledge and the narrowest: a checkable statement with a justification
// and a falsifier. Most of what lives in this repo's comments is not that shape — it is prose
// explaining WHY a value is what it is, an ordered recovery procedure, a diagram of how traffic
// reaches a component. Forcing those into `claim` would be worse than not recording them: a
// gotcha has no falsifier, and a rule demanding one would push authors to invent fake ones.
//
// So the grammar takes a KIND, and the kind decides what fields are required and how the block
// renders:
//
//	doc()     prose; renders as a paragraph
//	diagram() mermaid source; renders inside a ```mermaid fence
//	claim()   see claim.go — validated, decays, projects into the claims table
//
// THE DSL CONTROLS THE DOCUMENT, NOT JUST ITS CONTENT. `section:` is a heading path, so a block
// declares where in the generated README it belongs and the document's skeleton emerges from the
// blocks themselves. Without it, structure would have to live in config — another hand-typed
// list of things, positioned away from the code it describes, free to drift from it. The same
// argument that put claims next to the code puts the structure there too.
//
// `order:` sorts within a section. Absent, blocks fall back to file path then line, which is a
// stable and comprehensible default: the document reads in the order the code does.

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type BlockKind string

const (
	KindDoc     BlockKind = "doc"
	KindDiagram BlockKind = "diagram"
)

type Block struct {
	Kind    BlockKind
	ID      string
	Title   string
	Section string // heading path, e.g. "Architecture/Ingress"
	Order   int    // sort key within a section; 0 means unset
	Body    []string

	File string
	Line int
}

var blockHeadRe = regexp.MustCompile(`(doc|diagram)\(\s*\)\s*([a-z0-9][a-z0-9._-]*)\s*:\s*(.+?)\s*$`)

// ParseBlocks extracts doc/diagram blocks from a file's text.
//
// The body is every following comment line that is not a recognised field, dedented against the
// shallowest body line so mermaid's own indentation survives the comment prefix. Getting that
// wrong produces a diagram that renders as a flat list, which is worse than no diagram because
// it looks deliberate.
func ParseBlocks(file, text string) []Block {
	var out []Block
	lines := strings.Split(text, "\n")
	for i := 0; i < len(lines); i++ {
		m := blockHeadRe.FindStringSubmatch(lines[i])
		if m == nil {
			continue
		}
		if inBacktickSpan(lines[i], strings.Index(lines[i], string(m[1])+"(")) {
			continue // a demonstration of the grammar, not a block — same guard as claims
		}
		b := Block{Kind: BlockKind(m[1]), ID: m[2], Title: m[3], File: file, Line: i + 1}
		var raw []string
		for j := i + 1; j < len(lines); j++ {
			if !commentRe.MatchString(lines[j]) {
				break
			}
			stripped := commentRe.ReplaceAllString(lines[j], "")
			// A NEW BLOCK HEADER ENDS THIS ONE. Without this the body keeps consuming, because
			// a bare `#` is still a comment line -- so the first version swallowed the
			// following diagram() header as prose. The damage compounded: the swallowed header
			// sits at indent 0, which made dedent compute a common indent of 0 and stop
			// dedenting, so the surviving block rendered with its comment indentation intact.
			// One greedy continuation, two visible defects, exactly like the claim wrap bug.
			if blockHeadRe.MatchString(stripped) || claimHeadRe.MatchString(stripped) {
				break
			}
			if fm := blockFieldRe.FindStringSubmatch(stripped); fm != nil {
				switch fm[1] {
				case "section":
					b.Section = strings.Trim(strings.TrimSpace(fm[2]), "/")
				case "order":
					if n, err := strconv.Atoi(strings.TrimSpace(fm[2])); err == nil {
						b.Order = n
					}
				}
				i = j
				continue
			}
			if strings.TrimSpace(stripped) == "" && len(raw) == 0 {
				i = j
				continue // leading blank between header and body
			}
			raw = append(raw, stripped)
			i = j
		}
		b.Body = dedent(trimTrailingBlank(raw))
		out = append(out, b)
	}
	return out
}

var blockFieldRe = regexp.MustCompile(`^\s*(section|order)\s*:\s*(.+?)\s*$`)

// dedent removes the common leading whitespace, preserving relative indentation.
//
// Load-bearing for diagrams: mermaid uses indentation for subgraphs, and a comment marker plus
// an author's own indent would otherwise be baked into the rendered source.
func dedent(lines []string) []string {
	min := -1
	for _, l := range lines {
		if strings.TrimSpace(l) == "" {
			continue
		}
		n := len(l) - len(strings.TrimLeft(l, " \t"))
		if min == -1 || n < min {
			min = n
		}
	}
	if min <= 0 {
		return lines
	}
	out := make([]string, len(lines))
	for i, l := range lines {
		if len(l) >= min {
			out[i] = l[min:]
		} else {
			out[i] = strings.TrimLeft(l, " \t")
		}
	}
	return out
}

func trimTrailingBlank(lines []string) []string {
	for len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}

// CollectBlocks walks the non-markdown corpus.
func CollectBlocks(ctx *Ctx) []Block {
	var out []Block
	for _, f := range ctx.BlockSources {
		out = append(out, ParseBlocks(f.Path, f.Text)...)
	}
	return out
}

// Render emits one block as markdown at the given heading depth.
//
// `fromDir` is the directory the host document lives in, and the source link is made relative to
// it. The first version emitted the repo-relative path, which a reader resolves against the
// README's own folder -- so every source link 404'd. docsgen's own broken-links rule caught it
// on the first generate, which is the closest thing to a self-test this tool has.
func (b Block) Render(depth int, fromDir string) string {
	var sb strings.Builder
	// An explicit anchor so other documents can link to a block by its stable id rather than by
	// its title, which is prose and will be reworded.
	fmt.Fprintf(&sb, "%s %s <a id=\"%s\"></a>\n\n", strings.Repeat("#", depth), b.Title, b.ID)
	switch b.Kind {
	case KindDiagram:
		sb.WriteString("```mermaid\n")
		sb.WriteString(strings.Join(b.Body, "\n"))
		sb.WriteString("\n```\n")
	default:
		sb.WriteString(strings.Join(b.Body, "\n"))
		sb.WriteString("\n")
	}
	fmt.Fprintf(&sb, "\n<sub>source: [%s](%s)</sub>\n", shortRef(b.File, b.Line), relFrom(fromDir, b.File))
	return sb.String()
}

// sectionTree groups blocks by their declared section path.
type sectionNode struct {
	Name     string
	Blocks   []Block
	Children map[string]*sectionNode
	order    []string // child insertion order, so a section's shape is deterministic
}

func newSectionNode(name string) *sectionNode {
	return &sectionNode{Name: name, Children: map[string]*sectionNode{}}
}

func (n *sectionNode) add(path []string, b Block) {
	if len(path) == 0 {
		n.Blocks = append(n.Blocks, b)
		return
	}
	head := path[0]
	child, ok := n.Children[head]
	if !ok {
		child = newSectionNode(head)
		n.Children[head] = child
		n.order = append(n.order, head)
	}
	child.add(path[1:], b)
}

// buildSections turns a flat block list into a heading tree.
//
// A block with no `section:` falls under its own FILE, which is the default the whole feature
// rests on: a folder with no structural annotation at all still produces a readable document,
// one heading per file, ordered as the directory is.
func buildSections(blocks []Block) *sectionNode {
	root := newSectionNode("")
	for _, b := range blocks {
		path := []string{}
		if b.Section != "" {
			for _, p := range strings.Split(b.Section, "/") {
				if p = strings.TrimSpace(p); p != "" {
					path = append(path, p)
				}
			}
		} else {
			path = append(path, shortRef(b.File, 1))
		}
		root.add(path, b)
	}
	root.sortAll()
	return root
}

func (n *sectionNode) sortAll() {
	sort.SliceStable(n.Blocks, func(i, j int) bool {
		bi, bj := n.Blocks[i], n.Blocks[j]
		// Explicit order wins; unset (0) sorts after everything explicit, so adding an `order:`
		// to one block does not silently reshuffle its unannotated neighbours.
		oi, oj := bi.Order, bj.Order
		if oi == 0 {
			oi = 1 << 30
		}
		if oj == 0 {
			oj = 1 << 30
		}
		if oi != oj {
			return oi < oj
		}
		if bi.File != bj.File {
			return bi.File < bj.File
		}
		return bi.Line < bj.Line
	})
	sort.Strings(n.order)
	for _, c := range n.Children {
		c.sortAll()
	}
}

func (n *sectionNode) render(depth int, fromDir string, sb *strings.Builder) {
	for _, b := range n.Blocks {
		sb.WriteString(b.Render(depth, fromDir))
		sb.WriteString("\n")
	}
	for _, name := range n.order {
		c := n.Children[name]
		fmt.Fprintf(sb, "%s %s\n\n", strings.Repeat("#", depth), name)
		c.render(depth+1, fromDir, sb)
	}
}

// relFrom builds a link from a document's directory to a repo-relative file.
func relFrom(fromDir, file string) string {
	fromDir = strings.Trim(fromDir, "/")
	if fromDir == "" || fromDir == "." {
		return file
	}
	if strings.HasPrefix(file, fromDir+"/") {
		return strings.TrimPrefix(file, fromDir+"/")
	}
	return strings.Repeat("../", strings.Count(fromDir, "/")+1) + file
}
