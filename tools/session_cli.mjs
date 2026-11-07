// One disposable fixture per invocation; finite data, never arbitrary code.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { resolve, relative, isAbsolute, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { validatePlan, DEFAULT_ACTIONS } from "./session_actions.mjs";
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export function parseArgs(args) {
  const result = { message: "独立入口可组合动作验证", actions: DEFAULT_ACTIONS };
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (key === "--help") return { help: true };
    if (!["--output", "--message", "--actions", "--plan", "--python"].includes(key) || !args[i + 1]) throw new Error("unknown/missing option: " + key);
    const value = args[++i];
    if (key === "--actions") result.actions = value.split(",");
    else if (key === "--plan") result.actions = JSON.parse(value);
    else result[key.slice(2)] = value;
  }
  if (!result.output) throw new Error("--output is required (new directory under project .agent-tmp)");
  if (!result.message.trim() || result.message.startsWith("/") || result.message.length > 10000) throw new Error("message must be 1..10000 characters and not a slash command");
  result.actions = validatePlan(result.actions);
  return result;
}
export function checkedOutput(value) {
  const target = resolve(ROOT, value), base = realpathSync(resolve(ROOT, ".agent-tmp"));
  const inside = p => { const rel = relative(base, p); return rel && !rel.startsWith("..") && !isAbsolute(rel); };
  if (base !== resolve(ROOT, ".agent-tmp") || !inside(target) || existsSync(target)) throw new Error("output must be a new project scratch child");
  let parent = dirname(target);
  while (!existsSync(parent)) parent = dirname(parent);
  if (parent !== base && !inside(realpathSync(parent))) throw new Error("output parent escapes scratch through a link");
  return target;
}
export function main(args = process.argv.slice(2)) {
  const options = parseArgs(args);
  if (options.help) {
    console.log(`Usage: node tools/session_cli.mjs --output .agent-tmp/<task>/new-run [options]
--actions fail-create,create,send,wait,reopen,refresh,history (default)
  Available: fail-create/create/open/send/wait/reopen/refresh/history.
--message TEXT  Plain message for send; default: 独立入口可组合动作验证
--plan JSON     Array of action names or {op,session,message}; session is a local alias.
  Each alias must first be created in this invocation; no URL/threadId/cwd/code accepted.
  Every send requires a matching wait before plan end; rejected before fixture startup.
  No wait or send is automatically added to the declared plan.
--python PATH   Defaults to this project's documented Windows/Linux Python.
--output PATH  Required NEW project .agent-tmp child; reports retained, runtime removed.
No retries. First unexpected error stops execution with nonzero exit.
Starts one isolated random-port fixture with local mock model; never connects to 8764.`);
    return 0;
  }
  const output = checkedOutput(options.output);
  mkdirSync(output, { recursive: true });
  const python = options.python || (process.platform === "win32" ? "D:/python/anaconda/envs/th123/python.exe" : "/home/dticpw/conda/envs/py310/bin/python");
  const command = ["-B", "-X", "utf8", "tools/smoke_test.py", "--ui-output", resolve(output, "ui"), "--output", resolve(output, "session.json"), "--scratch-root", resolve(output, "runtime"), "--session-plan", JSON.stringify(options.actions), "--message", options.message];
  console.log(JSON.stringify({ python, argv: command }));
  const child = spawnSync(python, command, { cwd: ROOT, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" }, stdio: "inherit", windowsHide: true });
  writeFileSync(resolve(output, "invocation.json"), JSON.stringify({ at: new Date().toISOString(), argv: args, python, childArgv: command, exitCode: child.status, error: child.error?.message }, null, 2) + "\n");
  if (child.error) throw child.error;
  return child.status ?? 1;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
