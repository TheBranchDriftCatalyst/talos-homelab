#!/usr/bin/env node
/**
 * Interactive suite/flag picker for `npm test`.
 *
 *   npm test                     → arrow-key checkbox: pick suites + flags, then run
 *   npm test -- --foo --bar      → any args? straight passthrough to jest (no picker)
 *   CI / piped / non-TTY         → passthrough (runs everything, unchanged behaviour)
 *
 * Zero dependencies — a tiny raw-mode checkbox built on node:readline. Suites are read
 * from the root jest.config.js `projects[]`; each suite's friendly name comes from its own
 * jest.config.js `displayName`.
 */
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const passthrough = process.argv.slice(2);
const interactive = passthrough.length === 0 && process.stdin.isTTY && process.stdout.isTTY;

function runJest(args, extraEnv = {}) {
  const bin = path.join(ROOT, "node_modules", ".bin", "jest");
  const child = spawn(bin, args, { stdio: "inherit", env: { ...process.env, ...extraEnv } });
  child.on("exit", (code) => process.exit(code ?? 1));
  child.on("error", (e) => {
    console.error("failed to launch jest:", e.message);
    process.exit(1);
  });
}

function discoverSuites() {
  const root = require(path.join(ROOT, "jest.config.js"));
  return (root.projects || []).map((p) => {
    const dir = p.replace("<rootDir>", ROOT);
    let name = path.basename(path.dirname(dir)); // fallback: component dir name
    try {
      const dn = require(path.join(dir, "jest.config.js")).displayName;
      name = typeof dn === "string" ? dn : (dn && dn.name) || name;
    } catch (_) {}
    return { name, value: name };
  });
}

/** Minimal raw-mode multi-select. Resolves to an array of `value`s. */
function checkbox(message, choices) {
  return new Promise((resolve, reject) => {
    const items = choices.map((c) => ({ ...c, checked: !!c.checked }));
    let cursor = 0;
    let height = 0;
    const { stdin, stdout } = process;
    const wasRaw = stdin.isRaw;

    const render = () => {
      if (height) stdout.write(`\x1b[${height}A`);
      const lines = [`\x1b[36m?\x1b[0m ${message}`];
      items.forEach((it, i) => {
        const pointer = i === cursor ? "\x1b[36m❯\x1b[0m" : " ";
        const box = it.checked ? "\x1b[32m◉\x1b[0m" : "◯";
        const label = i === cursor ? `\x1b[36m${it.name}\x1b[0m` : it.name;
        lines.push(`${pointer} ${box} ${label}`);
      });
      lines.push("\x1b[2m  ↑/↓ move · space toggle · a all · ↵ confirm · ctrl-c cancel\x1b[0m");
      stdout.write(lines.map((l) => `\x1b[2K${l}`).join("\n") + "\n");
      height = lines.length;
    };
    const cleanup = () => {
      stdin.removeListener("keypress", onKey);
      if (stdin.isTTY) stdin.setRawMode(wasRaw);
      stdin.pause();
    };
    const onKey = (str, key) => {
      key = key || {};
      if ((key.ctrl && key.name === "c") || key.name === "escape") {
        cleanup();
        stdout.write("\n");
        reject(Object.assign(new Error("cancelled"), { cancelled: true }));
        return;
      }
      if (key.name === "up") cursor = (cursor - 1 + items.length) % items.length;
      else if (key.name === "down" || key.name === "tab") cursor = (cursor + 1) % items.length;
      else if (key.name === "space" || str === " ") items[cursor].checked = !items[cursor].checked;
      else if (str === "a") {
        const allOn = items.every((i) => i.checked);
        items.forEach((i) => (i.checked = !allOn));
      } else if (key.name === "return" || key.name === "enter") {
        cleanup();
        resolve(items.filter((i) => i.checked).map((i) => i.value));
        return;
      } else return;
      render();
    };

    readline.emitKeypressEvents(stdin);
    if (stdin.isTTY) stdin.setRawMode(true);
    stdin.resume();
    stdin.on("keypress", onKey);
    render();
  });
}

async function main() {
  if (!interactive) return runJest(passthrough);

  const suites = await checkbox("Which test suites? (none = all)", discoverSuites());
  const flags = await checkbox("Options:", [
    { name: "⚠ destructive DR scenarios (disrupts LIVE infra)", value: "dr" },
    { name: "watch mode", value: "watch" },
    { name: "coverage report", value: "coverage" },
    { name: "verbose", value: "verbose" },
    { name: "serial (--runInBand)", value: "runInBand" },
  ]);

  const args = [];
  for (const s of suites) args.push("--selectProjects", s);
  if (flags.includes("watch")) args.push("--watch");
  if (flags.includes("coverage")) args.push("--coverage");
  if (flags.includes("verbose")) args.push("--verbose");
  if (flags.includes("runInBand")) args.push("--runInBand");

  const env = {};
  if (flags.includes("dr")) {
    env.PIHOLE_DR_DESTRUCTIVE = "1";
    env.VPN_DR_DESTRUCTIVE = "1";
  }

  const shown = [...(suites.length ? suites : ["(all suites)"]), ...(flags.length ? flags : [])].join(", ");
  console.log(`\n\x1b[2m▶ jest ${args.join(" ") || "(all)"}\x1b[0m  \x1b[36m${shown}\x1b[0m\n`);
  runJest(args, env);
}

main().catch((e) => {
  if (e && e.cancelled) process.exit(130);
  console.error(e);
  process.exit(1);
});
