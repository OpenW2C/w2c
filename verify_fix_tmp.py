import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
import os
_TEST_HOME = Path(tempfile.mkdtemp(prefix="w2c-verify-"))
os.environ["W2C_CONFIG"] = str(_TEST_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_TEST_HOME / "data")

from w2c import cli as w2c

root = Path(tempfile.mkdtemp(prefix="w2c-repo-verify-"))
w2c.cmd_init(root, track=True, git_delivery="slice-commit-milestone-push-pr")
mid = w2c.cmd_milestone_new(root, "demo")

plan_dir = w2c.plan_dir_for(root, "M001")
mroad = plan_dir / "M001-ROADMAP.md"
# Simulate the real-world bug: author the Slices section as a table instead
# of the required checkbox lines.
text = w2c.read_text(mroad)
text = text.replace(
    "## Slices\n",
    "## Slices\n\n| Slice | Title |\n| --- | --- |\n| S01 | Demo slice |\n",
    1,
)
w2c.atomic_write(mroad, text)

# Create a slice plan file on disk (as if planning had produced it).
slice_plan = plan_dir / "M001-S01-PLAN.md"
w2c.atomic_write(slice_plan, "# M001-S01: Demo slice\n\n- [x] **T01**: do the thing\n  - Verify: true\n")

report = w2c.run_smoke(root)
match = [r for r in report.checks if r.name == "roadmap-slices-match-plans"]
print("roadmap-slices-match-plans row:", match)
assert match, "expected new check to be present"
assert match[0].status == "FAIL", "expected FAIL when table used instead of checkboxes"
print("PASS: new smoke check correctly flags the table-vs-checkbox mismatch")

try:
    w2c.cmd_milestone_status(root, "M001", "DONE")
    print("FAIL: expected W2CError")
except w2c.W2CError as e:
    print("milestone-complete error message:", e)
    assert "S01" in str(e) or "no slices" in str(e).lower()
    print("PASS: error message is actionable")
