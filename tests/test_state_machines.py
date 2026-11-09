import json
import pathlib

import pytest

DIR = pathlib.Path(__file__).parent.parent / "statemachine"
VARS = {
    "timeout_seconds": "1800", "map_concurrency": "10",
    "scan_arn": "arn:scan", "validate_arn": "arn:validate", "merge_arn": "arn:merge",
    "chunker_arn": "arn:chunker", "copy_arn": "arn:copy", "summary_arn": "arn:summary",
}


def render(name):
    text = (DIR / name).read_text()
    for k, v in VARS.items():
        text = text.replace("${" + k + "}", v)
    assert "${" not in text, "unreplaced template variable"
    return json.loads(text)


def all_states(defn):
    for name, state in defn["States"].items():
        yield name, state
        if state["Type"] == "Map":
            yield from all_states(state["ItemProcessor"])


@pytest.mark.parametrize("name", ["manifest_pipeline.asl.json.tftpl", "copy_pipeline.asl.json.tftpl"])
def test_definition_is_valid_and_connected(name):
    defn = render(name)
    states = dict(all_states(defn))
    assert defn["StartAt"] in defn["States"]
    for scope in [defn] + [s["ItemProcessor"] for s in defn["States"].values() if s["Type"] == "Map"]:
        for s in scope["States"].values():
            targets = [s.get("Next")] + [c["Next"] for c in s.get("Catch", [])]
            for t in filter(None, targets):
                assert t in scope["States"], f"dangling transition to {t}"
            assert s["Type"] in ("Fail", "Succeed") or s.get("End") or s.get("Next")
    assert defn["TimeoutSeconds"] == 1800
    assert "PipelineFailed" in states


def test_manifest_pipeline_order_and_parallelism():
    d = render("manifest_pipeline.asl.json.tftpl")["States"]
    assert d["Init"]["Next"] == "Scan" and d["Scan"]["Next"] == "ValidateChunks"
    assert d["ValidateChunks"]["Next"] == "Merge"
    assert d["ValidateChunks"]["MaxConcurrency"] == 10


def test_copy_pipeline_order_and_parallelism():
    d = render("copy_pipeline.asl.json.tftpl")["States"]
    assert d["Init"]["Next"] == "ChunkCopyManifest"
    assert d["CopyChunks"]["Next"] == "Summarise"
    assert d["CopyChunks"]["MaxConcurrency"] == 10


def test_transient_errors_retry_with_jitter_and_run_id_comes_from_execution_name():
    d = render("manifest_pipeline.asl.json.tftpl")["States"]
    retry = d["Scan"]["Retry"][0]
    assert "TransientS3Error" in retry["ErrorEquals"] and retry["JitterStrategy"] == "FULL"
    assert d["Init"]["Parameters"]["run_id.$"] == "$$.Execution.Name"
