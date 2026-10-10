#!/usr/bin/env python3
"""Package only the synthetic shopping fixture's recorded reports for Pages."""
from __future__ import annotations
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCENARIOS = ("success", "payment_crash", "inventory_timeout")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"href", "src", "poster"} and value:
                self.links.append(value)


def verify(site: Path) -> dict:
    manifest = json.loads((site / "evidence.json").read_text())
    assert manifest["kind"] == "faultdebug-synthetic-showcase"
    for item in manifest["files"]:
        path = site / item["path"]
        assert path.resolve().is_relative_to(site.resolve())
        assert path.is_file() and not path.is_symlink()
        assert digest(path) == item["sha256"], item["path"]
    for path in site.rglob("*.html"):
        parser = Links(); parser.feed(path.read_text())
        for link in parser.links:
            if link.startswith(("http:", "https:", "data:", "#", "mailto:")):
                continue
            target = (path.parent / link.split("#")[0].split("?")[0]).resolve()
            assert target.is_relative_to(site.resolve()) and target.exists(), (path, link)
    return {"status": "PASS", "files": len(manifest["files"]),
            "scenarios": len(manifest["scenarios"])}


def build(args) -> dict:
    from faultdebug.artifact import read_artifact
    from faultdebug.fault_report import write_fault_report
    from faultdebug.service_report_view import render_html
    lab, output = args.lab.resolve(), args.output.resolve()
    if output.exists():
        raise ValueError("Output already exists; use a new directory")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("Recorded revision must be a full Git SHA")
    summary = json.loads((lab / "summary.json").read_text())
    assert summary["backend"] == "docker-compose" and summary["application_processes"] == 8
    selected = {r["scenario"]: r for r in summary["scenarios"]}
    output.mkdir(parents=True)
    (output / "assets").mkdir()
    (output / "downloads").mkdir()
    for name in ("style.css", "site.js"):
        shutil.copyfile(ROOT / "docs/showcase" / name, output / "assets" / name)
    preview = ROOT / "docs/assets/showcase-payment.png"
    shutil.copyfile(preview if preview.exists() else ROOT / "docs/assets/shopping-fault-report.png",
                    output / "assets/preview.png")
    video = ROOT / "docs/assets/faultdebug-demo.webm"
    if video.exists():
        shutil.copyfile(video, output / "assets/demo.webm")
    records = []
    zip_path = output / "downloads/demo-evidence.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "LICENSE", "LICENSE")
        for path in sorted((lab / "bundle").rglob("*")):
            if path.is_file():
                assert not path.is_symlink()
                archive.write(path, "bundle/" + path.relative_to(lab / "bundle").as_posix())
        for scenario in SCENARIOS:
            run = selected[scenario]
            assert run["assertions"] == "PASS"
            source = lab / scenario
            model = json.loads((source / "report/report.json").read_text())
            captures = [(p, read_artifact(p)) for p in source.glob("evidence/*/*.fault")]
            assert len(captures) == len(model["services"]) == 8
            assert all(x["snapshot_consistency"]["stable"] for _, x in captures)
            assert sum(not x["complete"] for _, x in captures) == (scenario == "payment_crash")
            target = output / "reports" / scenario
            shutil.copytree(source / "report", target)
            (target / "report.ko.html").write_text((target / "report.html").read_text())
            (target / "report.html").write_text(render_html(model, language="en"))
            for service in model["services"]:
                if not service.get("fault_report"):
                    continue
                folder = target / Path(service["fault_report"]).parent
                (folder / "report.ko.html").write_text((folder / "report.html").read_text())
                english = target / (folder.name + "-english")
                write_fault_report(source / "evidence" / service["artifact"], english,
                                   bundle=lab / "bundle", language="en")
                for name in ("report.html", "report.json", "report.md"):
                    shutil.copyfile(english / name, folder / name)
                shutil.rmtree(english)
            for path in sorted((source / "evidence").rglob("*")):
                if path.is_file():
                    assert path.suffix in {".fault", ".jsonl"} and not path.is_symlink()
                    archive.write(path, scenario + "/evidence/" + path.relative_to(source / "evidence").as_posix())
            records.append({"scenario": scenario, "processes": 8,
                            "observed_calls": len(model["calls"]),
                            "captures": len(captures),
                            "stable": sum(x["snapshot_consistency"]["stable"] for _, x in captures),
                            "complete": sum(x["complete"] for _, x in captures),
                            "native_crashes": sum(len(x["crashes"]) for _, x in captures),
                            "session_id": model["session_id"]})
    manifest = {"schema": 1, "kind": "faultdebug-synthetic-showcase",
                "recorded_revision": args.revision, "recorded_run_url": args.run_url,
                "image_id": summary["image_id"], "scenarios": records}
    if args.native_capture:
        capture = read_artifact(args.native_capture)
        assert capture["target"]["signal"] == 11
        target = output / "reports/c-sigsegv"
        write_fault_report(args.native_capture, target, bundle=args.native_bundle, language="en")
        model = json.loads((target / "report.json").read_text())
        assert any(c["source_verified"] for c in model["crashes"])
        manifest["native_example"] = {"signal": 11, "artifact_sha256": digest(args.native_capture),
                                     "source_verified": True, "complete": capture["complete"]}
        with zipfile.ZipFile(output / "downloads/c-sigsegv-evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(args.native_capture, args.native_capture.name)
            archive.write(ROOT / "LICENSE", "LICENSE")
            for path in sorted(args.native_bundle.rglob("*")):
                if path.is_file():
                    assert not path.is_symlink()
                    archive.write(path, "bundle/" + path.relative_to(args.native_bundle).as_posix())
    template = (ROOT / "docs/showcase/index.html").read_text()
    template = template.replace("__NATIVE_LINK__", '<p><a href="reports/c-sigsegv/report.html">Also explore a real native C SIGSEGV capture →</a> · <a href="downloads/c-sigsegv-evidence.zip">Download native evidence</a></p>' if args.native_capture else "")
    if not video.exists():
        template = re.sub(r"<video.*?</video>", '<a href="reports/payment_crash/report.html">Open the recorded report →</a>', template, flags=re.S)
    (output / "index.html").write_text(template)
    (output / ".nojekyll").write_text("")
    (output / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    (output / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://lsh235.github.io/FalutDebugMCP/</loc></url></urlset>\n')
    manifest["files"] = [{"path": p.relative_to(output).as_posix(), "sha256": digest(p)}
                         for p in sorted(output.rglob("*")) if p.is_file()]
    (output / "evidence.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    parser.add_argument("--revision")
    parser.add_argument("--run-url")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--native-capture", type=Path)
    parser.add_argument("--native-bundle", type=Path)
    args = parser.parse_args()
    if not args.verify_only and not all((args.lab, args.revision, args.run_url)):
        parser.error("--lab, --revision and --run-url are required")
    if bool(args.native_capture) != bool(args.native_bundle):
        parser.error("--native-capture and --native-bundle must be supplied together")
    print(json.dumps(verify(args.output) if args.verify_only else build(args), indent=2))


if __name__ == "__main__":
    main()
