"""Read-only drift check for reviewed feature recipes; never certifies behavior."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REVIEW = "validation/feature-map-review.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("引用超出项目：" + value)
    return path


def recipe(text, feature):
    marker = f'<a id="{feature}"></a>'
    if text.count(marker) != 1:
        raise ValueError("功能锚点缺失或重复：" + feature)
    start = text.index(marker)
    heading = text.find("\n## ", start)
    if heading == -1:
        raise ValueError("功能没有操作说明：" + feature)
    end = text.find("\n## ", heading + 4)
    # A following feature's anchor belongs to that feature, not this recipe.
    next_marker = text.find('\n<a id="', heading)
    limits = [n for n in (end, next_marker) if n >= 0]
    return text[start:min(limits) if limits else len(text)].strip()


def inspect(root=ROOT):
    root = Path(root)
    text = (root / "FEATURE-MAP.md").read_text(encoding="utf-8")
    review = json.loads((root / REVIEW).read_text(encoding="utf-8"))
    errors, features = [], []
    for link in re.findall(r"\]\(([^)]+)\)", text):
        url = urlsplit(link)
        if url.scheme in ("http", "https"):
            continue
        try:
            path = local_file(root, unquote(url.path)) if url.path else root / "FEATURE-MAP.md"
            if not path.exists():
                raise ValueError("失效引用：" + link)
            if url.fragment and path.suffix == ".md":
                target = path.read_text(encoding="utf-8")
                anchors = set(re.findall(r'<a id="([^"]+)"', target))
                for heading in re.findall(r"^#{1,6} (.+)$", target, re.MULTILINE):
                    anchors.add(re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-"))
                if unquote(url.fragment) not in anchors:
                    raise ValueError("失效锚点：" + link)
        except ValueError as exc:
            errors.append(str(exc))
    if review.get("version") != 1 or not review.get("features"):
        raise ValueError("地图核对记录缺失或版本不支持")
    anchors = re.findall(r'<a id="([^"]+)"', text)
    if set(anchors) != set(review["features"]) or len(anchors) != len(set(anchors)):
        errors.append("功能索引与核对记录不一致，或有重复功能锚点")
    for feature, saved in review["features"].items():
        changed = []
        try:
            current = hashlib.sha256(recipe(text, feature).encode()).hexdigest()
            if current != saved.get("recipe_sha256"):
                changed.append("功能操作说明已变化")
            if not saved.get("source_reviewed_at") or not saved.get("inputs") or not saved.get("evidence"):
                changed.append("缺源码核对时间、输入或运行证据")
            for value, expected in saved.get("inputs", {}).items():
                path = local_file(root, value)
                if not path.is_file() or digest(path) != expected:
                    changed.append(value)
            for evidence in saved.get("evidence", []):
                path = local_file(root, evidence["path"])
                if not path.is_file() or digest(path) != evidence["sha256"]:
                    changed.append("运行证据缺失或变化：" + evidence["path"])
        except (ValueError, KeyError) as exc:
            changed.append(str(exc))
        features.append({"feature": feature, "status": "needs_review" if changed else "current",
                         "changes": changed, "coverage": saved.get("coverage", "未说明"),
                         "unverified": saved.get("unverified", [])})
    return {"result": "invalid" if errors else "needs_review" if any(f["changes"] for f in features) else "current",
            "errors": errors, "features": features,
            "limits": "current 仅表示已登记的操作说明、源码和证据未变化，不证明描述正确或未覆盖的功能已通过。此命令不会更新核对记录。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"result": "invalid", "errors": [str(exc)]}
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(content, end="")
    if args.output:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    return {"current": 0, "needs_review": 2}.get(result["result"], 1)


if __name__ == "__main__":
    sys.exit(main())
