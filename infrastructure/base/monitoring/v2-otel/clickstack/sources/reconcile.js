// Reconcile HyperDX's source definitions from git into MongoDB.
//
// Run by mongosh from the CronJob beside this file. Idempotent: a run that
// changes nothing prints "unchanged" for every source and exits 0.
//
// ---------------------------------------------------------------------------
// WHY A RECONCILER AND NOT JUST hyperdx.defaultSources
// ---------------------------------------------------------------------------
// defaultSources is FIRST-BOOT-ONLY. setupTeamDefaults has exactly two call
// sites in the 2.8.0 build: POST /register/password (which refuses outright if
// a team already exists) and a boot path guarded by IS_LOCAL_APP_MODE, which is
// FALSE in this deployment. So values in the HelmRelease can never reach an
// existing team -- editing them is a no-op forever after the first install.
//
// That is not theoretical: it is why this cluster had ZERO provisioned sources.
// defaultSources resolves a source's `connection` BY NAME and silently
// `continue`s when the name does not match, and ours said "Local ClickHouse"
// while defaultConnections created "ClickHouse (hyperdx-logs)". Every source
// was dropped with one log line, and someone eventually built one by hand in
// the UI -- exactly the click-ops this replaces.
//
// Running on a schedule also means the UI stops being authoritative: edit a
// source by hand and the next reconcile puts git back.
//
// ---------------------------------------------------------------------------
// WHY IT WRITES MONGO DIRECTLY
// ---------------------------------------------------------------------------
// The alternative is the app's own /sources HTTP API, which would run Zod
// validation for us. It needs a passport SESSION COOKIE -- the internal router
// checks req.isAuthenticated(), HYPERDX_API_KEY is the OTLP *ingestion* key and
// is not accepted, and the Bearer API (/api/v2) exposes only alerts, charts and
// dashboards. That path therefore requires minting and storing a HyperDX user
// password purely for automation.
//
// Writing Mongo needs no new credential: the URI is already in the cluster for
// the app itself. The cost is losing Zod validation, so assertShape() below
// does the checks that schema would have done.
//
// ---------------------------------------------------------------------------
// TWO PASSES, AND WHY
// ---------------------------------------------------------------------------
// A session source REQUIRES traceSourceId at creation, and links are ObjectIds
// that do not exist until their targets do. So: pass 1 writes all four with no
// links, pass 2 resolves names to ids and sets them.
//
// UPSERT BY {team, name}, NEVER delete-and-recreate. Saved searches, dashboard
// tiles and alerts reference a source by ObjectId with no cascade and no
// integrity check -- recreating one mints a new _id and silently orphans every
// referrer, which presents as blank tiles rather than an error.

'use strict';

const DB = 'hyperdx';
const CONNECTION_NAME = 'ClickHouse (hyperdx-logs)';
const SOURCES_PATH = '/config/sources.json';

// Fields HyperDX's Zod schema accepts per kind. Anything else is stripped by
// the API, so writing it through Mongo would persist a field the app ignores --
// and which vanishes the first time someone opens that source in the UI and
// saves. Verified by running each kind's branch in the live 2.8.0 pod.
//
// The asymmetry is real, not an oversight:
//   - a LOG source has no sessionSourceId  (there is no log->session link)
//   - a SESSION source takes ONLY these six fields; 13 others are stripped
//   - a METRIC source has no serviceNameExpression and no trace/session links
const ALLOWED = {
  common: ['name', 'kind', 'from', 'connection', 'team'],
  log: [
    'timestampValueExpression', 'displayedTimestampValueExpression',
    'implicitColumnExpression', 'serviceNameExpression', 'bodyExpression',
    'eventAttributesExpression', 'resourceAttributesExpression',
    'defaultTableSelectExpression', 'severityTextExpression',
    'traceIdExpression', 'spanIdExpression',
    'traceSourceId', 'metricSourceId',
  ],
  trace: [
    'timestampValueExpression', 'displayedTimestampValueExpression',
    'implicitColumnExpression', 'serviceNameExpression', 'bodyExpression',
    'eventAttributesExpression', 'resourceAttributesExpression',
    'defaultTableSelectExpression', 'traceIdExpression', 'spanIdExpression',
    'durationExpression', 'durationPrecision', 'parentSpanIdExpression',
    'spanNameExpression', 'spanKindExpression', 'statusCodeExpression',
    'statusMessageExpression',
    'logSourceId', 'sessionSourceId', 'metricSourceId',
  ],
  metric: [
    'timestampValueExpression', 'resourceAttributesExpression', 'metricTables',
    'logSourceId',
  ],
  session: ['timestampValueExpression', 'resourceAttributesExpression', 'traceSourceId'],
};

// The five keys HyperDX's MetricsDataType enum defines. The exponential one is
// TWO WORDS WITH A SPACE -- "exponential_histogram" is silently dropped by both
// Zod and the Mongoose sub-schema, producing a metric type that simply never
// appears, with no error anywhere.
const METRIC_TABLE_KEYS = ['gauge', 'sum', 'histogram', 'summary', 'exponential histogram'];

function fail(msg) {
  print('ERROR: ' + msg);
  quit(1);
}

function assertShape(src) {
  if (!src.name) fail('a source has no name');
  if (!ALLOWED[src.kind]) fail(src.name + ': unknown kind "' + src.kind + '"');
  if (!src.from || typeof src.from.databaseName !== 'string' || typeof src.from.tableName !== 'string') {
    fail(src.name + ': from.databaseName and from.tableName are both required (tableName may be "")');
  }
  if (src.kind === 'metric') {
    const t = src.metricTables || {};
    const keys = Object.keys(t);
    if (keys.length === 0) fail(src.name + ': a metric source needs at least one metricTables entry');
    keys.forEach(function (k) {
      if (METRIC_TABLE_KEYS.indexOf(k) === -1) {
        fail(src.name + ': invalid metricTables key "' + k + '". Valid: ' + METRIC_TABLE_KEYS.join(', ') +
             ' (note "exponential histogram" is two words)');
      }
    });
  }
  // A session source without a correlated trace source is rejected by the app
  // and leaves the Sessions page reporting "No correlated session source".
  if (src.kind === 'session' && !(src._links || {}).traceSourceId) {
    fail(src.name + ': a session source requires _links.traceSourceId');
  }
}

function pick(src, kind) {
  const allow = ALLOWED.common.concat(ALLOWED[kind]);
  const out = {};
  Object.keys(src).forEach(function (k) {
    if (k === '_links') return;
    if (allow.indexOf(k) === -1) {
      print('  warn  ' + src.name + ': dropping "' + k + '" (not accepted for kind=' + kind + ')');
      return;
    }
    out[k] = src[k];
  });
  return out;
}

// ---- load desired state -----------------------------------------------------
let desired;
try {
  // require('fs'), not cat() -- cat() is the LEGACY mongo shell. mongosh drops
  // it, and the failure is a bare "cat is not defined" that looks nothing like
  // a missing-file error.
  desired = JSON.parse(require('fs').readFileSync(SOURCES_PATH, 'utf8'));
} catch (e) {
  fail('cannot read/parse ' + SOURCES_PATH + ': ' + e);
}
if (!Array.isArray(desired) || desired.length === 0) fail('sources.json is not a non-empty array');
desired.forEach(assertShape);

const d = db.getSiblingDB(DB);

// ---- resolve team + connection ---------------------------------------------
// Both must already exist: the team is created by user registration and the
// connection by defaultConnections on first boot. Creating either here would be
// inventing identity, so this exits non-zero and waits instead.
const teams = d.teams.find({}, { _id: 1 }).toArray();
if (teams.length !== 1) fail('expected exactly 1 team, found ' + teams.length + ' -- refusing to guess');
const TEAM = teams[0]._id;

const conn = d.connections.findOne({ name: CONNECTION_NAME }, { _id: 1 });
if (!conn) {
  fail('no connection named "' + CONNECTION_NAME + '". A name mismatch of exactly this kind ' +
       'is what left this cluster with zero sources -- fix the name, not the symptom.');
}
const CONN = conn._id;

print('team=' + TEAM + '  connection=' + CONN + '  desired=' + desired.length + ' sources');

// ---- pass 1: upsert each source WITHOUT links -------------------------------
const ids = {};
let changed = 0;
desired.forEach(function (src) {
  const doc = pick(src, src.kind);
  doc.team = TEAM;
  doc.connection = CONN;

  const existing = d.sources.findOne({ team: TEAM, name: src.name });
  const now = new Date();

  if (!existing) {
    doc.createdAt = now;
    doc.updatedAt = now;
    doc.__v = 0;
    const r = d.sources.insertOne(doc);
    ids[src.name] = r.insertedId;
    print('  create  ' + src.name + ' (' + src.kind + ') -> ' + r.insertedId);
    changed++;
    return;
  }

  ids[src.name] = existing._id;

  // Compare only the fields we manage, so a link set in pass 2 -- or a field
  // the app adds itself -- does not make every run look like a change.
  let differs = false;
  Object.keys(doc).forEach(function (k) {
    if (JSON.stringify(existing[k]) !== JSON.stringify(doc[k])) differs = true;
  });

  if (differs) {
    doc.updatedAt = now;
    // $set, NOT replaceOne: preserves _id and any field the app owns.
    d.sources.updateOne({ _id: existing._id }, { $set: doc });
    print('  update  ' + src.name + ' -> ' + existing._id);
    changed++;
  } else {
    print('  ok      ' + src.name + ' unchanged');
  }
});

// ---- pass 2: resolve link names to ObjectId strings -------------------------
// The model declares these as String, so store _id.toString(), not ObjectId.
desired.forEach(function (src) {
  const links = src._links || {};
  const allow = ALLOWED[src.kind];
  const set = {};

  Object.keys(links).forEach(function (field) {
    if (allow.indexOf(field) === -1) {
      print('  warn  ' + src.name + ': link "' + field + '" is not valid for kind=' + src.kind + ', skipping');
      return;
    }
    const target = ids[links[field]];
    if (!target) fail(src.name + ': link ' + field + ' points at unknown source "' + links[field] + '"');
    set[field] = target.toString();
  });

  if (Object.keys(set).length === 0) return;

  const cur = d.sources.findOne({ _id: ids[src.name] });
  const needs = Object.keys(set).some(function (k) { return cur[k] !== set[k]; });
  if (needs) {
    set.updatedAt = new Date();
    d.sources.updateOne({ _id: ids[src.name] }, { $set: set });
    print('  link    ' + src.name + ' -> ' +
          Object.keys(set).filter(function (k) { return k !== 'updatedAt'; }).join(', '));
    changed++;
  }
});

// ---- verify -----------------------------------------------------------------
// Assert the end state rather than trusting the writes above. A link left as a
// literal name ("Traces" instead of a 24-hex id) means pass 2 did not run, and
// the UI would report no correlated source with nothing in the logs.
let bad = 0;
d.sources.find({ team: TEAM }).forEach(function (s) {
  ['logSourceId', 'traceSourceId', 'sessionSourceId', 'metricSourceId'].forEach(function (f) {
    if (!s[f]) return;
    if (!/^[0-9a-f]{24}$/.test(s[f])) {
      print('  BAD   ' + s.name + '.' + f + ' is not an ObjectId: "' + s[f] + '"');
      bad++;
    } else if (d.sources.countDocuments({ _id: ObjectId(s[f]) }) !== 1) {
      print('  BAD   ' + s.name + '.' + f + ' points at a missing source: ' + s[f]);
      bad++;
    }
  });
});
if (bad > 0) fail(bad + ' broken link(s) after reconcile');

print('reconciled: ' + changed + ' change(s), ' +
      d.sources.countDocuments({ team: TEAM }) + ' sources, links verified');
