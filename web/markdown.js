// Small, safe Markdown renderer: everything is escaped first, then a limited
// set of block and inline forms is rebuilt. No raw HTML ever reaches the page.

const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function inline(text) {
  const fragments = [];
  const keep = (html) => `\u0000${fragments.push(html) - 1}\u0000`;
  const restore = (s) => s.replace(/\u0000(\d+)\u0000/g, (_, i) => fragments[i]);
  let s = escapeHtml(text).replace(/`([^`\n]+)`/g, (_, code) => {
    return keep(`<code>${code}</code>`);
  });
  s = s.replace(/\[([^\]]+)\]\((?:&lt;([^\n]*?)&gt;|([^\s()]*(?:\([^\s()]*\)[^\s()]*)*))\)/g,
    (match, label, angle, plain) => {
      const path = angle ?? plain;
      if (!path || /[\u0000-\u001f]/.test(path)) return match;
      label = restore(label);
      if (/^https?:\/\//i.test(path)) {
        return keep(`<a href="${path}" target="_blank" rel="noopener">${label}</a>`);
      }
      // File references are desktop actions: browsers refuse HTTP -> file:// navigation.
      if (path.startsWith("#") || path.startsWith("//") ||
          (/^[a-z][a-z0-9+.-]*:/i.test(path) && !/^file:\/\//i.test(path) &&
           !/^[a-z]:[\\/]/i.test(path) && !/^[^:]+:\d+(?::\d+)?(?:-\d+)?$/.test(path))) return match;
      return keep(`<button type="button" class="file-ref" data-file-path="${path}" title="用系统默认应用打开：${path}">${label}</button>`);
    });
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
    (_, pre, url) => `${pre}${keep(`<a href="${url}" target="_blank" rel="noopener">${url}</a>`)}`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return restore(s);
}

function table(lines) {
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const head = cells(lines[0]).map((c) => `<th>${inline(c)}</th>`).join("");
  const body = lines.slice(2).map((l) => `<tr>${cells(l).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

export function renderMarkdown(source) {
  const lines = (source || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*```(\S*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i += 1;
      out.push(`<pre class="code"><button class="copy" type="button">复制</button><code>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      out.push(table(rows));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${inline(quote.join(" "))}</blockquote>`);
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,4}\s|[-*]\s|\d+\.\s|>|\|)/.test(lines[i])) {
      para.push(inline(lines[i++]));
    }
    if (!para.length) para.push(inline(lines[i++]));
    out.push(`<p>${para.join("<br>")}</p>`);
  }
  return out.join("");
}

export { escapeHtml };
