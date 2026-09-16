/* CATALYST CONTROL ROOM — board identity.
   Derives the board from the subdomain (llm.homepage.talos00 -> "llm";
   bare homepage.talos00 -> "master"), stamps <html data-board="..."> for
   the per-board CSS accent, and mounts the corner board chip.
   Defensive: must never break the dashboard. */
(function () {
  try {
    var sub = (window.location.hostname.split(".")[0] || "").toLowerCase();
    var board = sub === "homepage" || sub === "localhost" || sub === "" ? "master" : sub;
    document.documentElement.setAttribute("data-board", board);
    var mount = function () {
      if (document.getElementById("board-chip") || !document.body) return;
      var chip = document.createElement("div");
      chip.id = "board-chip";
      var dot = document.createElement("span");
      dot.id = "board-chip-dot";
      chip.appendChild(dot);
      chip.appendChild(document.createTextNode("catalyst / " + board));
      document.body.appendChild(chip);
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mount);
    } else {
      mount();
    }
  } catch (e) {
    /* no-op */
  }
})();
