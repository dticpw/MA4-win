import { test } from "node:test";
import assert from "node:assert/strict";
import { isWithin, shortPath } from "./web/paths.js";

test("Windows paths match case and separators at directory boundaries", () => {
  assert.ok(isWithin("e:\\PG\\项目\\src", "E:/pg/项目/"));
  assert.ok(isWithin("E:\\PG\\项目", "e:/PG/项目"));
  assert.ok(!isWithin("E:/PG/项目副本", "E:/PG/项目"));
  assert.ok(!isWithin("F:/PG/项目", "E:/PG/项目"));
  assert.ok(!isWithin("E:/PG", ""));
});
test("Linux paths remain case sensitive", () => {
  assert.ok(isWithin("/mnt/e/PG/demo/a", "/mnt/e/PG/demo"));
  assert.ok(!isWithin("/mnt/e/pg/demo", "/mnt/e/PG"));
});
test("home abbreviation only matches the actual home prefix", () => {
  assert.equal(shortPath("c:\\Users\\DTICPW\\项目", "C:/Users/DTICPW"), "~/项目");
  assert.equal(shortPath("C:/Users/DTICPW2/a", "C:/Users/DTICPW"), "C:/Users/DTICPW2/a");
});
