/**
 * GFM markdown rendering for agent chat (marked + DOMPurify + optional Mermaid).
 */
const MinionMarkdown = (() => {
  let configured = false;
  let mermaidReady = false;

  const PURIFY_CONFIG = {
    USE_PROFILES: { html: true },
    ADD_ATTR: ["target", "rel", "class", "data-mermaid", "data-rendered"],
    ADD_TAGS: ["table", "thead", "tbody", "tr", "th", "td", "pre", "code", "hr", "input"],
  };

  function configureMarked() {
    if (configured || !window.marked) return !!window.marked;
    window.marked.use({
      gfm: true,
      breaks: true,
      pedantic: false,
    });
    // Marked v15 GFM treats ~word~ as strikethrough; agent copy often uses ~ for
    // approximations (e.g. ~$150B, ~25%), which produced false <del> spans.
    window.marked.use({
      tokenizer: {
        del(src) {
          const match = /^~~(?=\S)([^\n]*?\S)~~/.exec(src);
          if (!match) return;
          return {
            type: "del",
            raw: match[0],
            text: match[1],
            tokens: this.lexer.inlineTokens(match[1]),
          };
        },
      },
    });
    configured = true;
    return true;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function postProcessHtml(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");

    doc.querySelectorAll("h1").forEach((el) => el.classList.add("md-h1"));
    doc.querySelectorAll("h2").forEach((el) => el.classList.add("md-h2"));
    doc.querySelectorAll("h3").forEach((el) => el.classList.add("md-h3"));
    doc.querySelectorAll("h4").forEach((el) => el.classList.add("md-h4"));
    doc.querySelectorAll("h5").forEach((el) => el.classList.add("md-h5"));
    doc.querySelectorAll("h6").forEach((el) => el.classList.add("md-h6"));
    doc.querySelectorAll("hr").forEach((el) => el.classList.add("md-hr"));
    doc.querySelectorAll("blockquote").forEach((el) => el.classList.add("md-blockquote"));
    doc.querySelectorAll("ul, ol").forEach((el) => el.classList.add("md-list"));
    doc.querySelectorAll("pre").forEach((el) => {
      const code = el.querySelector("code");
      const lang = [...(code?.classList || [])]
        .find((c) => c.startsWith("language-"))
        ?.slice("language-".length)
        ?.toLowerCase();

      if (lang === "mermaid") {
        const wrap = doc.createElement("div");
        wrap.className = "md-mermaid-wrap";
        const graph = doc.createElement("pre");
        graph.className = "md-mermaid";
        graph.dataset.mermaid = "1";
        graph.textContent = code?.textContent || el.textContent || "";
        wrap.appendChild(graph);
        el.replaceWith(wrap);
        return;
      }

      el.classList.add("md-code-block");
      if (code) code.classList.add("md-code");
    });

    doc.querySelectorAll("table").forEach((table) => {
      if (table.closest(".md-table-wrap")) return;
      table.classList.add("md-table");
      const wrap = doc.createElement("div");
      wrap.className = "md-table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });

    doc.querySelectorAll("a[href^='http']").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });

    return doc.body.innerHTML;
  }

  function fallbackRender(text) {
    let html = escapeHtml(text);
    html = html.replace(/^#{6}\s+(.+)$/gm, '<h6 class="md-h6">$1</h6>');
    html = html.replace(/^#{5}\s+(.+)$/gm, '<h5 class="md-h5">$1</h5>');
    html = html.replace(/^#{4}\s+(.+)$/gm, '<h4 class="md-h4">$1</h4>');
    html = html.replace(/^#{3}\s+(.+)$/gm, '<h3 class="md-h3">$1</h3>');
    html = html.replace(/^#{2}\s+(.+)$/gm, '<h2 class="md-h2">$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1 class="md-h1">$1</h1>');
    html = html.replace(/^(-{3,}|\*{3,}|_{3,})$/gm, '<hr class="md-hr">');
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\n/g, "<br>");
    return `<div class="chat-markdown">${html}</div>`;
  }

  function render(text) {
    if (!text) return "";
    if (!configureMarked() || !window.DOMPurify) {
      return fallbackRender(text);
    }

    const raw = window.marked.parse(text);
    const safe = window.DOMPurify.sanitize(raw, PURIFY_CONFIG);
    const enriched = postProcessHtml(safe);
    return `<div class="chat-markdown">${enriched}</div>`;
  }

  async function initMermaid() {
    if (mermaidReady || !window.mermaid) return;
    window.mermaid.initialize({
      startOnLoad: false,
      theme: "neutral",
      securityLevel: "strict",
      fontFamily: "inherit",
    });
    mermaidReady = true;
  }

  async function enhanceMermaid(root) {
    const nodes = root?.querySelectorAll?.(".md-mermaid[data-mermaid]");
    if (!nodes?.length || !window.mermaid) return;

    await initMermaid();
    const targets = [];
    nodes.forEach((node) => {
      if (node.dataset.rendered === "1") return;
      const wrap = node.closest(".md-mermaid-wrap");
      const graph = document.createElement("div");
      graph.className = "md-mermaid-graph";
      graph.textContent = node.textContent;
      node.remove();
      if (wrap) {
        wrap.appendChild(graph);
        targets.push(graph);
      }
    });

    if (!targets.length) return;

    try {
      await window.mermaid.run({ nodes: targets });
      targets.forEach((el) => {
        el.dataset.rendered = "1";
      });
    } catch (_) {
      targets.forEach((el) => {
        el.classList.add("md-mermaid-error");
      });
    }
  }

  function enhance(root) {
    if (!root) return;
    enhanceMermaid(root);
  }

  return { render, enhance, initMermaid };
})();

if (typeof window !== "undefined") {
  window.MinionMarkdown = MinionMarkdown;
}
