// Path presentation and directory-boundary matching, independent of the host browser.
const windows = (p) => /^[a-z]:[\\/]/i.test(p) || /^\\\\/.test(p);
const slash = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "");
export function isWithin(path, parent) {
  if (!path || !parent) return false;
  let value = slash(path), prefix = slash(parent);
  if (windows(path) || windows(parent)) { value = value.toLowerCase(); prefix = prefix.toLowerCase(); }
  return value === prefix || value.startsWith(prefix + "/");
}
export function shortPath(path, home) {
  if (home && isWithin(path, home)) return "~" + slash(path).slice(slash(home).length);
  return path || "";
}
