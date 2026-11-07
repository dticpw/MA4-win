"""Check the task policy dependency boundary; static guidance, not a sandbox."""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = "task_policy.py"
PURE_IMPORTS = {"math", "dataclasses"}
FORBIDDEN_NAMES = {"open", "input", "exec", "eval", "compile", "__import__", "globals", "locals",
                   "getattr", "setattr", "delattr", "breakpoint"}


def inspect_source(source, path=POLICY):
    errors = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [{"path": path, "line": exc.lineno, "rule": "syntax", "message": exc.msg}]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if getattr(node, "level", 0) or any(n not in PURE_IMPORTS for n in names):
                errors.append({"path": path, "line": node.lineno, "rule": "policy-import",
                               "message": "任务规则层只允许 math/dataclasses；把 I/O、调度和会话访问留在 Controllers/Hub，所需事实作为参数传入"})
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append({"path": path, "line": node.lineno, "rule": "policy-effect",
                           "message": f"规则层禁止 {node.id}；不能借动态调用或内置函数访问外部状态"})
    return errors


def inspect(root=ROOT):
    try:
        source = (Path(root) / POLICY).read_text(encoding="utf-8")
    except OSError as exc:
        return [{"path": POLICY, "line": None, "rule": "missing-policy", "message": str(exc)}]
    return inspect_source(source)


def main():
    errors = inspect()
    print(json.dumps({"result": "failed" if errors else "passed", "errors": errors,
                      "scope": "task_policy.py 的静态导入和副作用入口；不证明全部行为正确，也不是权限隔离"},
                     ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
