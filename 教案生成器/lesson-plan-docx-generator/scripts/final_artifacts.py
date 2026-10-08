"""Canonical final-artifact boundary; reuse the generator's sole manifest verifier."""
from pathlib import Path

from generate_lesson_plans import verify_artifact_manifest
from lifecycle_digest import read_json_object, sha256_file, semantic_fingerprint, LifecycleContractError
from package_common import DEFAULT_MANIFEST, load_manifest, manifest_template_path
from path_safety import assert_output_path_safe, paths_equal
from source_truth import source_truth_local_file_paths


def output_path(run, run_path, output):
    from run_lesson_pipeline import path_of, SKILL_ROOT
    output = Path(output).absolute()
    workspace = Path(run_path).absolute().parent
    if output == workspace or not output.is_relative_to(workspace) or not output.resolve().is_relative_to(workspace.resolve()):
        raise LifecycleContractError("final output must be a descendant of the run workspace")
    source_path = path_of(run, "source_truth")
    source, _ = read_json_object(source_path, "Source Truth")
    protected = [SKILL_ROOT, Path(run_path), *source_truth_local_file_paths(source, source_path).values(),
                 *(path_of(run, name) for name in run["bindings"] if name not in {"final_output", "artifact_manifest", "artifact_qa"})]
    assert_output_path_safe(output, protected)
    for component in (output, *output.parents):
        if component.is_symlink():
            raise LifecycleContractError("final output path contains a symlink")
    return output


def validate_artifact_files(output, content_path, authorization, pipeline_run_id):
    """Read current bytes; final lifecycle requires a rendered, nonempty Lesson set."""
    output = Path(output)
    for component in (output, *output.parents):
        if component.is_symlink():
            raise LifecycleContractError("final artifacts contain a symlink path")
    manifest, _ = read_json_object(output / "artifact-manifest.json", "Artifact manifest")
    qa, _ = read_json_object(output / "qa-report.json", "Artifact QA")
    content, _ = read_json_object(content_path, "Content")
    if not content.get("lessons"):
        raise LifecycleContractError("zero-Lesson practice_only is outside canonical Lesson lifecycle; release compatibility debt")
    # No second implementation of DOCX/PDF/hash/page-count verification.
    status = verify_artifact_manifest(output, manifest, Path(content_path))
    if status != "production_pass" or manifest["render_status"] != "passed" or qa.get("status") != "passed":
        raise LifecycleContractError("final canonical lifecycle requires passed retained render and Artifact QA")
    if manifest["run_id"] != pipeline_run_id:
        raise LifecycleContractError("Artifact manifest belongs to a different pipeline run")
    template_manifest = load_manifest(DEFAULT_MANIFEST)
    template_path = manifest_template_path(template_manifest)
    expected = authorization["template"]
    if (qa.get("template_id") != expected["template_id"] or
        str(qa.get("template_version")) != expected["template_version"] or
        not paths_equal(qa.get("template_path", ""), template_path) or
        sha256_file(template_path) != expected["template_sha256"].lower() or
        sha256_file(DEFAULT_MANIFEST) != expected["manifest_sha256"].lower() or
        qa.get("validation", {}).get("template") is not True or
        qa.get("validation", {}).get("output") is not True or bool(qa.get("validation_skipped")) or bool(qa.get("validation", {}).get("skipped"))):
        raise LifecycleContractError("Artifact QA does not bind the authorized canonical Template")
    entries = {}
    docs, pdfs = set(), set()
    for path in output.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise LifecycleContractError("final artifact tree contains symlink/special file")
        if path.is_file():
            relative = path.relative_to(output).as_posix()
            entries[relative] = sha256_file(path)
            if path.suffix.lower() == ".docx": docs.add(relative)
            if path.suffix.lower() == ".pdf": pdfs.add(relative)
    records = manifest["artifacts"]
    if docs != {r["final_docx_path"] for r in records} or pdfs != {r["final_pdf_path"] for r in records}:
        raise LifecycleContractError("unexpected DOCX/PDF inventory outside the manifest")
    if not paths_equal(qa.get("output_dir", ""), output):
        raise LifecycleContractError("Artifact QA output directory mismatch")
    return manifest, qa, {
        "docx_count": len(docs), "pdf_count": len(pdfs), "pdf_total_pages": manifest["actual_pdf_page_count"],
        "artifact_manifest_sha256": sha256_file(output / "artifact-manifest.json"),
        "artifact_manifest_identity": manifest["run_id"],
        "output_inventory_fingerprint": semantic_fingerprint(entries), "render_status": "passed",
    }


def validate_run_artifacts(run):
    from run_lesson_pipeline import path_of
    output = path_of(run, "final_output")
    if path_of(run, "artifact_manifest") != output / "artifact-manifest.json" or path_of(run, "artifact_qa") != output / "qa-report.json":
        raise LifecycleContractError("final evidence must bind the canonical output manifest and qa-report")
    authorization, _ = read_json_object(path_of(run, "production_authorization"), "Production Authorization")
    if run["orchestrator_version"] == "2.0":
        manifest, _ = read_json_object(output / "artifact-manifest.json", "O2 Artifact manifest")
        expected = dict(orchestrator_version="2.0", production_authorization_sha256=sha256_file(path_of(run, "production_authorization")),
            semantic_scope=authorization["semantic_scope"])
        if manifest.get("canonical_lifecycle") != expected or sha256_file(output / "production-authorization.json") != expected["production_authorization_sha256"]:
            raise LifecycleContractError("O2 output does not bind exact authorized PA bytes")
    return validate_artifact_files(output, path_of(run, "content"), authorization, run["state"]["pipeline_run_id"])
