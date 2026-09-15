from __future__ import annotations

from readset.hooks.apply_patch import parse_patch

PATCH = """*** Begin Patch
*** Add File: docs/new.md
+# New
+hello
*** Update File: src/app.py
@@ def main():
-    return 1
+    return 2
 print("x")
@@
-VERSION = "1"
+VERSION = "2"
*** Delete File: obsolete.txt
*** End Patch
"""


def test_should_parse_add_update_delete_when_patch_has_all_three() -> None:
    files = parse_patch(PATCH)
    assert [(f.op, f.path) for f in files] == [
        ("add", "docs/new.md"),
        ("update", "src/app.py"),
        ("delete", "obsolete.txt"),
    ]


def test_should_turn_hunks_into_old_new_pairs_when_updating() -> None:
    update = parse_patch(PATCH)[1]
    assert update.edits == [
        ('    return 1\nprint("x")\n', '    return 2\nprint("x")\n'),
        ('VERSION = "1"\n', 'VERSION = "2"\n'),
    ]


def test_should_give_no_edits_when_hunk_has_no_old_lines() -> None:
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n+added only\n*** End Patch\n"
    update = parse_patch(patch)[0]
    assert update.op == "update"
    assert update.edits is None


def test_should_record_move_target_when_present() -> None:
    patch = "*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n@@\n-x\n+y\n*** End Patch\n"
    update = parse_patch(patch)[0]
    assert update.path == "a.py"
    assert update.move_to == "b.py"


def test_should_return_empty_when_text_is_not_a_patch() -> None:
    assert parse_patch("echo hi") == []
    assert parse_patch("") == []


def test_should_ignore_end_of_file_marker_when_present() -> None:
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End of File\n*** End Patch\n"
    assert parse_patch(patch)[0].edits == [("x\n", "y\n")]
