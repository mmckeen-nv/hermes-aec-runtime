import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_offline_recipes", ROOT / "tools" / "run_offline_recipes.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_every_documented_offline_recipe_validates_against_runtime():
    document = json.loads((ROOT / "examples" / "offline_recipes.json").read_text(encoding="utf-8"))
    results = MODULE.run(ROOT / "examples" / "offline_recipes.json")
    assert len(results) == len(document["recipes"]) >= 7
    assert {result["kind"] for result in results} == {
        "rhino_operations", "blender_operations", "handoff_manifest", "recovery",
        "workflow_memory", "flight_recorder", "model_evaluation",
    }
    assert all(result["validation"] == "valid" for result in results)


def test_recipe_ids_are_unique_and_operator_metadata_is_present():
    recipes = json.loads((ROOT / "examples" / "offline_recipes.json").read_text(encoding="utf-8"))["recipes"]
    assert len({recipe["id"] for recipe in recipes}) == len(recipes)
    assert all(recipe.get("description") for recipe in recipes)
