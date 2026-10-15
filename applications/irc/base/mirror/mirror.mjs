// Mirrors THELOUNGE_HOME onto an NFS-backed PVC that Velero can actually read.
//
// WHY THIS EXISTS
// ---------------
// thelounge-data lives on `local-path`, and rancher local-path-provisioner
// emits PersistentVolumes of type `hostPath`. Velero's file-system backup
// refuses those outright -- pkg/podvolume/backupper.go calls
// isHostPathVolume(), which resolves a PVC to its PV and returns true when
// pv.Spec.HostPath != nil, then logs
//   "Volume data in pod irc/thelounge-... is a hostPath volume which is not
//    supported for pod volume backup, skipping"
// and moves on. The Backup still reports Completed, so the failure is silent:
// no PodVolumeBackup is ever created no matter what you annotate.
//
// So the data is copied to a volume Velero CAN back up, and that copy is what
// gets snapshotted. This runs as a sidecar rather than a CronJob on purpose:
// Velero only creates a PodVolumeBackup for a volume that some RUNNING pod has
// mounted. A CronJob's pod is gone by 02:00 and the mirror would never be
// captured.
//
// No shell, and not one dollar sign in this file: the irc Flux Kustomization
// has postBuild.substituteFrom enabled, and envsubst rewrites ConfigMap
// contents indiscriminately. A shell script here would come out mangled.
//
// RESTORE
// -------
// Restoring the namespace brings thelounge-data back EMPTY (Velero only has
// the PVC object). The real payload is on the mirror PVC at /mirror/current.
// Scale the Deployment to 0, copy /mirror/current/* into the data volume, then
// scale back up. /mirror/.previous holds the sync before last.

import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, join } from "node:path";
import { DatabaseSync, backup } from "node:sqlite";

const SRC = "/var/opt/thelounge";
const DST = "/mirror";
const INTERVAL_MS = 900000;

// storage/ is The Lounge's link-prefetch thumbnail cache. It is regenerable,
// it is the only part of the home directory that grows without bound, and
// nobody wants it back after a restore.
const SKIP_PATHS = new Set([join(SRC, "storage")]);

// Copied by the online backup API below instead, so the bulk copy must not
// also grab them -- a plain byte copy of a live SQLite file can be torn.
function isSqliteArtifact(name) {
  return (
    name.endsWith(".sqlite3") ||
    name.endsWith(".sqlite3-journal") ||
    name.endsWith(".sqlite3-wal") ||
    name.endsWith(".sqlite3-shm")
  );
}

function log(message) {
  console.log("[mirror] " + new Date().toISOString() + " " + message);
}

function copyPlainFiles(stage) {
  cpSync(SRC, stage, {
    recursive: true,
    filter: (path) => !SKIP_PATHS.has(path) && !isSqliteArtifact(basename(path)),
  });
}

// node:sqlite's backup() is SQLite's online backup API: it takes the read lock
// page by page and produces a file that is consistent as of a single point in
// time, even while The Lounge is writing. That is the whole reason the sidecar
// reuses the thelounge image -- its Node 22 runtime ships node:sqlite, so
// there is no second image to track and no sqlite3 binary to install.
async function snapshotDatabases(stage) {
  const logsDir = join(SRC, "logs");
  if (!existsSync(logsDir)) {
    return 0;
  }
  const outDir = join(stage, "logs");
  mkdirSync(outDir, { recursive: true });

  let count = 0;
  for (const name of readdirSync(logsDir)) {
    if (!name.endsWith(".sqlite3")) {
      continue;
    }
    const db = new DatabaseSync(join(logsDir, name), { readOnly: true });
    try {
      await backup(db, join(outDir, name));
      count += 1;
    } finally {
      db.close();
    }
  }
  return count;
}

// Stage then rename, so /mirror/current is never a half-written tree. If
// Velero snapshots mid-sync it captures the previous complete copy, not a
// torn one.
async function syncOnce() {
  const stage = join(DST, ".staging");
  const current = join(DST, "current");
  const previous = join(DST, ".previous");

  rmSync(stage, { recursive: true, force: true });
  mkdirSync(stage, { recursive: true });

  copyPlainFiles(stage);
  const databases = await snapshotDatabases(stage);
  writeFileSync(join(stage, "MIRROR-TIMESTAMP"), new Date().toISOString() + "\n");

  rmSync(previous, { recursive: true, force: true });
  if (existsSync(current)) {
    renameSync(current, previous);
  }
  renameSync(stage, current);

  log("synced, " + String(databases) + " sqlite database(s) snapshotted");
}

log("starting, source " + SRC + " target " + DST);
while (true) {
  try {
    await syncOnce();
  } catch (err) {
    log("sync FAILED: " + (err && err.stack ? err.stack : String(err)));
  }
  await new Promise((resolve) => setTimeout(resolve, INTERVAL_MS));
}
