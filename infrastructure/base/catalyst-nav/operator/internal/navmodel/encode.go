package navmodel

// Byte-identical JSON to build_nav.py's `json.dump(out, sys.stdout, separators=(",", ":"))`.
//
// WHY THIS FILE EXISTS AT ALL, instead of struct tags and encoding/json: phase 6's audit gate
// is a BYTE comparison against the manifest the sidecar writes today, and encoding/json cannot
// produce those bytes. Two incompatibilities, both silent:
//
//   1. Go sorts map keys; Python emits them in insertion order. `hosts` and `defaults` are
//      genuinely dynamic (hostnames, and whichever of the seven config keys an app set), so
//      they have to be maps in Go — and `{"mode":...,"revealAt":...}` would come back out as
//      `{"mode":...,"revealAt":...}` only by luck of the alphabet. revealAt/hidePast/height/
//      scrollReveal/intensity/fx do NOT sort into CONFIG_KEYS order.
//   2. Python's json writes floats via repr(), so an intensity of 1 ships as `1.0`.
//      json.Marshal(float64(1)) ships `1`. One byte, whole diff fails.
//
// So the writer here is explicit and ordered, and the orderings it encodes are the ones
// build_nav.py gets for free from dict insertion order. Any new key must be added to the
// writer AND to the order it belongs in, or it silently will not be emitted.

import (
	"bytes"
	"encoding/json"
	"strconv"
)

// pyFloat renders a float the way Python's repr() does, which is what json.dump uses.
//
// Go's 'g'/-1 and Python's repr agree on the shortest-roundtrip digits and on when to switch
// to exponent form; they disagree on integral values, where Go drops the fraction ("1") and
// Python keeps it ("1.0"). intensity is the only float in this manifest and `intensity: 1`
// is its single most likely value, so this is not a theoretical difference.
//
// NaN and ±Inf are not handled: Python's json renders them as the non-standard NaN/Infinity
// tokens, and _as_intensity rejects all three before they can reach here (see
// parseIntensity). A NAV_DEFAULTS value could still carry one — it is filtered by key, not by
// type — and would then render as Go's "NaN"/"+Inf", which is invalid JSON. That is a gap, and
// it is left open deliberately rather than papered over: NAV_DEFAULTS is edited by whoever
// edits the Deployment, build_nav.py has the identical hole, and closing it HERE would make
// the parity diff non-empty for an input neither implementation should accept.
func pyFloat(f float64) string {
	s := strconv.FormatFloat(f, 'g', -1, 64)
	if !bytes.ContainsAny([]byte(s), ".eE") {
		s += ".0"
	}
	return s
}

// writeString emits a JSON string. Python's json.dump escapes non-ASCII by default
// (ensure_ascii=True) as \uXXXX; encoding/json emits raw UTF-8. Hostnames and app names are
// ASCII in this cluster, but a non-ASCII gethomepage.dev/name would diverge, so match Python.
func writeString(buf *bytes.Buffer, s string) {
	buf.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		default:
			switch {
			case r < 0x20:
				buf.WriteString(`\u`)
				buf.WriteString(hex4(uint16(r)))
			case r < 0x7f:
				buf.WriteRune(r)
			case r > 0xffff:
				// Python emits a surrogate pair for astral codepoints.
				r -= 0x10000
				buf.WriteString(`\u`)
				buf.WriteString(hex4(uint16(0xd800 + (r >> 10))))
				buf.WriteString(`\u`)
				buf.WriteString(hex4(uint16(0xdc00 + (r & 0x3ff))))
			default:
				buf.WriteString(`\u`)
				buf.WriteString(hex4(uint16(r)))
			}
		}
	}
	buf.WriteByte('"')
}

func hex4(v uint16) string {
	const digits = "0123456789abcdef"
	return string([]byte{
		digits[(v>>12)&0xf], digits[(v>>8)&0xf], digits[(v>>4)&0xf], digits[v&0xf],
	})
}

// writeValue emits one config value. The set of types is closed by CONFIG_KEYS: string
// (mode), int (revealAt/hidePast/height), bool (scrollReveal/fx), float64 (intensity).
// NAV_DEFAULTS can also carry arbitrary JSON for those keys — build_nav.py filters by KEY
// only, never by type, and ships whatever JSON value was there (see navDefaults), so the
// json.RawMessage arm is the faithful behaviour, not a loose end.
func writeValue(buf *bytes.Buffer, v any) {
	switch t := v.(type) {
	case string:
		writeString(buf, t)
	case bool:
		if t {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case int:
		buf.WriteString(strconv.Itoa(t))
	case int64:
		buf.WriteString(strconv.FormatInt(t, 10))
	case float64:
		buf.WriteString(pyFloat(t))
	case json.RawMessage:
		buf.Write(compactRaw(t))
	case []Applet:
		buf.WriteByte('[')
		for i, a := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			buf.WriteString(`{"src":`)
			writeString(buf, a.Src)
			buf.WriteByte('}')
		}
		buf.WriteByte(']')
	default:
		// Unreachable for values this package produces; emitting `null` rather than
		// panicking keeps a future key from taking down the reconcile loop.
		buf.WriteString("null")
	}
}

func compactRaw(raw json.RawMessage) []byte {
	var out bytes.Buffer
	if err := json.Compact(&out, raw); err != nil {
		return []byte("null")
	}
	return out.Bytes()
}

// Encode renders the manifest exactly as build_nav.py would.
func Encode(m *Manifest) []byte {
	var buf bytes.Buffer
	buf.WriteString(`{"groups":[`)
	for gi, g := range m.Groups {
		if gi > 0 {
			buf.WriteByte(',')
		}
		buf.WriteString(`{"name":`)
		writeString(&buf, g.Name)
		buf.WriteString(`,"items":[`)
		for ii, it := range g.Items {
			if ii > 0 {
				buf.WriteByte(',')
			}
			// Field order is build_nav.py's dict literal minus "group":
			// name, weight, href, themed. Not alphabetical, deliberately.
			buf.WriteString(`{"name":`)
			writeString(&buf, it.Name)
			buf.WriteString(`,"weight":`)
			buf.WriteString(strconv.Itoa(it.Weight))
			buf.WriteString(`,"href":`)
			writeString(&buf, it.Href)
			buf.WriteString(`,"themed":`)
			if it.Themed {
				buf.WriteString("true")
			} else {
				buf.WriteString("false")
			}
			buf.WriteByte('}')
		}
		buf.WriteString(`]}`)
	}
	buf.WriteByte(']')

	if len(m.Defaults.Keys) > 0 {
		buf.WriteString(`,"defaults":{`)
		for i, k := range m.Defaults.Keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeString(&buf, k)
			buf.WriteByte(':')
			writeValue(&buf, m.Defaults.Values[k])
		}
		buf.WriteByte('}')
	}

	if len(m.Hosts.Keys) > 0 {
		buf.WriteString(`,"hosts":{`)
		for i, h := range m.Hosts.Keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeString(&buf, h)
			buf.WriteString(`:{`)
			cfg := m.Hosts.Values[h]
			for j, k := range cfg.Keys {
				if j > 0 {
					buf.WriteByte(',')
				}
				writeString(&buf, k)
				buf.WriteByte(':')
				writeValue(&buf, cfg.Values[k])
			}
			buf.WriteByte('}')
		}
		buf.WriteByte('}')
	}

	buf.WriteByte('}')
	return buf.Bytes()
}
