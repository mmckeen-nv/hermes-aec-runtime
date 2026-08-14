import asyncio

from hermes_aec_runtime.rhino import RhinoClient


def test_dry_run_validates_without_contacting_rhino():
    receipt = asyncio.run(RhinoClient("http://not-used/").execute_python(
        intent="create geometry",
        script="import Rhino\nprint(__rhino_doc__.Name)",
        expected_change="no mutation in dry run",
        dry_run=True,
    ))
    assert receipt["status"] == "validated"


def test_dry_run_blocks_unsafe_document_handles():
    receipt = asyncio.run(RhinoClient("http://not-used/").execute_python(
        intent="unsafe edit",
        script="import scriptcontext\nprint(scriptcontext.doc)",
        expected_change="none",
        dry_run=True,
    ))
    assert receipt["status"] == "blocked"
    assert "scriptcontext.doc" in receipt["error"]


def test_dry_run_blocks_process_and_dynamic_code_escape_hatches():
    receipt = asyncio.run(RhinoClient("http://not-used/").execute_python(
        intent="unsafe edit",
        script="import subprocess\neval('1 + 1')",
        expected_change="none",
        dry_run=True,
    ))
    assert receipt["status"] == "blocked"
    assert "import subprocess" in receipt["error"]
    assert "call eval" in receipt["error"]
