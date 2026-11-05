package navmodel

// NAV_DEFAULTS parsing, kept beside the model because its KEY ORDER is part of the manifest
// bytes (Python dicts preserve the order keys appeared in the JSON text, and json.dump writes
// them back in that order). encoding/json into a map[string]any throws that order away, so the
// decode has to walk tokens.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// ParseNavDefaultsEnv parses the NAV_DEFAULTS environment value exactly as env_defaults()
// does, including which malformed inputs are ignored-with-a-log rather than fatal.
//
// Returns the filtered, order-preserving config. An unusable value yields an empty config and
// a log line — never an error: this runs in a loop that must keep serving the previous
// manifest, and build_nav.py's whole posture is that a bad input degrades rather than stops.
func ParseNavDefaultsEnv(raw string, log io.Writer) OrderedConfig {
	logf := func(format string, args ...any) {
		if log != nil {
			fmt.Fprintf(log, format+"\n", args...)
		}
	}
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return OrderedConfig{}
	}
	order, values, err := decodeOrderedObject([]byte(raw))
	if err != nil {
		if err == errNotAnObject {
			logf("[nav] NAV_DEFAULTS must be a JSON object, ignoring")
		} else {
			logf("[nav] NAV_DEFAULTS is not valid JSON, ignoring: %s", pyRepr(raw))
		}
		return OrderedConfig{}
	}
	return ParseNavDefaults(order, values)
}

var errNotAnObject = fmt.Errorf("not a JSON object")

// decodeOrderedObject returns a top-level JSON object's keys in source order plus their
// values. Values stay as json.RawMessage unless they are one of the scalar types the manifest
// writer renders natively, so that e.g. `{"revealAt": 4}` emits `4` and not `4.0` — Python's
// json.loads yields an int for 4, and the encoder has to see an int to say so.
func decodeOrderedObject(b []byte) ([]string, map[string]any, error) {
	trimmed := bytes.TrimSpace(b)
	if len(trimmed) == 0 || trimmed[0] != '{' {
		// Distinguish "valid JSON but not an object" from "invalid JSON": env_defaults()
		// logs a different line for each, and an operator reading the log needs to know
		// which mistake they made.
		var probe any
		if json.Unmarshal(trimmed, &probe) == nil {
			return nil, nil, errNotAnObject
		}
		return nil, nil, fmt.Errorf("invalid JSON")
	}

	dec := json.NewDecoder(bytes.NewReader(trimmed))
	dec.UseNumber()
	tok, err := dec.Token()
	if err != nil {
		return nil, nil, err
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil, nil, errNotAnObject
	}

	var order []string
	values := map[string]any{}
	for dec.More() {
		kt, err := dec.Token()
		if err != nil {
			return nil, nil, err
		}
		key, ok := kt.(string)
		if !ok {
			return nil, nil, fmt.Errorf("non-string key")
		}
		var rawVal json.RawMessage
		if err := dec.Decode(&rawVal); err != nil {
			return nil, nil, err
		}
		if _, dup := values[key]; !dup {
			order = append(order, key)
		}
		values[key] = scalarOrRaw(rawVal)
	}
	if _, err := dec.Token(); err != nil { // closing brace
		return nil, nil, err
	}
	// Reject trailing garbage, which json.loads would too.
	if dec.More() {
		return nil, nil, fmt.Errorf("trailing content")
	}
	return order, values, nil
}

// scalarOrRaw narrows a raw value to the Go type the encoder renders Python-identically,
// falling back to the raw bytes for arrays/objects/null.
func scalarOrRaw(raw json.RawMessage) any {
	var v any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		return raw
	}
	switch t := v.(type) {
	case string:
		return t
	case bool:
		return t
	case json.Number:
		// An integral literal is an int in Python and must render without a ".0"; a
		// literal with a fraction or exponent is a float and must keep Python's repr.
		s := t.String()
		if !strings.ContainsAny(s, ".eE") {
			if n, err := t.Int64(); err == nil {
				return int(n)
			}
		}
		if f, err := t.Float64(); err == nil {
			return f
		}
		return raw
	default:
		return raw
	}
}
