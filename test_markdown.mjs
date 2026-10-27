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

test("local file links show the name only", () => {
  const html = renderMarkdown("见 [README.md](/mnt/e/PG/x/README.md)");
  assert.ok(html.includes('<span class="file-ref" title="/mnt/e/PG/x/README.md">README.md</span>'));
  assert.ok(!html.includes("href="));
});

test("Windows and spaced local links stay inert and escaped", () => {
  const html = renderMarkdown('[文档](<E:/中文 项目/README.md>) [x](C:\\Users\\a.txt)');
  assert.ok(html.includes('title="E:/中文 项目/README.md"'));
  assert.ok(html.includes('title="C:\\Users\\a.txt"'));
  assert.ok(!html.includes('href='));
  assert.ok(!renderMarkdown('[x](javascript:alert(1))').includes('href='));
});
