"use strict";

// The Lounge configuration. Read at startup only — the configMapGenerator hash
// in kustomization.yaml is what rolls the pod when this changes, because this
// is a subPath mount and those are frozen at pod start.
module.exports = {
  // false = PRIVATE mode, which is the whole point here: accounts persist,
  // and The Lounge stays connected to IRC on your behalf while you are away.
  // That is the bouncer behaviour soju provided — this replaces it rather than
  // sitting in front of it, so there is only one login and one thing to run.
  public: false,

  host: "0.0.0.0",
  port: 9000,

  // Behind Traefik, which terminates TLS. Without this The Lounge trusts the
  // socket's peer address and every client looks like the ingress pod.
  reverseProxy: true,

  // Keep IRC connections alive when no browser is attached. This is the single
  // setting that makes it a bouncer; without it closing the tab leaves the
  // channel, which is the behaviour we are paying a whole service to avoid.
  maxHistory: 10000,

  // Persist messages to per-user SQLite so scrollback survives restarts, and
  // is searchable in the UI.
  messageStorage: ["sqlite", "text"],

  // Quality-of-life the minimal client lacked: inline image/link previews and
  // uploads. Uploads land on the same PVC as everything else.
  prefetch: true,
  prefetchStorage: true,
  prefetchMaxImageSize: 2048,
  fileUpload: {
    enable: true,
    maxFileSize: 10240,
    baseUrl: null,
  },

  // Leave the network list open so /list and arbitrary servers work — the
  // reason we moved off the previous client.
  lockNetwork: false,

  defaults: {
    name: "Libera.Chat",
    host: "irc.libera.chat",
    port: 6697,
    tls: true,
    rejectUnauthorized: true,
    nick: "panda",
    username: "panda",
    realname: "panda",
    join: "#soju",
  },

  theme: "default",
};
