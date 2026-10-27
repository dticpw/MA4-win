import { test } from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "./web/markdown.js";

test("raw HTML is escaped", () => {
  const html = renderMarkdown("<img src=x onerror=alert(1)> **粗体**");
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("<strong>粗体</strong>"));
});

test("only http(s) links become anchors", () => {
  assert.ok(renderMarkdown("[a](https://koa-ol.com)").includes('href="https://koa-ol.com"'));
  assert.ok(!renderMarkdown("[a](javascript:alert(1))").includes("href="));
});

test("code blocks keep content verbatim and escaped", () => {
  const html = renderMarkdown("```js\nconst a = '<b>';\n```");
  assert.ok(html.includes("const a = &#39;&lt;b&gt;&#39;;"));
  assert.ok(html.includes('class="copy"'));
});

test("inline code is not formatted", () => {
  assert.ok(renderMarkdown("`**x**`").includes("<code>**x**</code>"));
});

test("tables, lists and headings", () => {
  const html = renderMarkdown("## 标题\n\n- 一\n- 二\n\n| a | b |\n|---|---|\n| 1 | 2 |");
  assert.ok(html.includes("<h4>标题</h4>"));
  assert.ok(html.includes("<ul><li>一</li><li>二</li></ul>"));
  assert.ok(html.includes("<td>1</td><td>2</td>"));
});

test("local file links are keyboard accessible desktop actions", () => {
  const html = renderMarkdown("见 [README.md](/mnt/e/PG/x/README.md)");
  assert.ok(html.includes('<button type="button" class="file-ref" data-file-path="/mnt/e/PG/x/README.md"'));
  assert.ok(html.includes('>README.md</button>'));
  assert.ok(!html.includes("href="));
});

test("file references preserve relative paths, spaces, parentheses and line citations", () => {
  for (const path of ["README.md:12", "src/ui.js#L3-L9", "./report.html", "../other/file.txt", "file:///home/a.png", "E:/PG/readme.md", "/a/file(1).png"]) {
    assert.ok(renderMarkdown(`[文件](${path})`).includes(`data-file-path="${path}"`), path);
  }
  assert.ok(renderMarkdown("[报告](</home/中文目录/a b.html:5>)").includes('data-file-path="/home/中文目录/a b.html:5"'));
  assert.ok(renderMarkdown("[`README.md`](README.md)").includes('><code>README.md</code></button>'));
});

test("file links cannot inject markup, activate schemes or format code examples", () => {
  for (const path of ["javascript:alert(1)", "data:text/html,evil", "vscode://file/a", "//evil/a", "#heading"]) {
    assert.ok(!renderMarkdown(`[x](${path})`).includes('class="file-ref"'), path);
  }
  const html = renderMarkdown('[<img src=x onerror=alert(1)>](</a/" onclick="evil.txt>)');
  assert.ok(html.includes('&quot; onclick=&quot;'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes(' onclick="'));
  assert.ok(!renderMarkdown('`[README](README.md)`').includes('<button'));
  assert.ok(renderMarkdown('[x](/a/**keep**.txt)').includes('data-file-path="/a/**keep**.txt"'));
});
