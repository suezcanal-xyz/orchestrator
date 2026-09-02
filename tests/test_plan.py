from orchestrator import plan
from orchestrator.milestone import MilestoneStatus
from orchestrator.task_graph import Task, TaskGraph


def test_new_plan_roundtrip():
    doc = plan.new_plan("demo", "0.1.0", "0.2.0", "closed-loop")
    text = doc.render()
    doc2 = plan.parse(text)
    assert doc2.meta.project == "demo"
    assert doc2.meta.current_version == "0.1.0"
    assert doc2.meta.target_version == "0.2.0"
    assert doc2.meta.status == MilestoneStatus.IN_PROGRESS
    assert doc2.get_section("Project") == "demo"


def test_custom_sections_preserved_on_roundtrip():
    doc = plan.new_plan("demo")
    doc.set_section("Known Bugs", "- humanitarian panel drops NGO vessels")
    text = doc.render()
    doc2 = plan.parse(text)
    assert "NGO vessels" in doc2.get_section("Known Bugs")


def test_change_history_appends_dated_entries():
    doc = plan.new_plan("demo")
    doc.append_change_history("User reported NGO vessel panel incomplete.")
    doc.append_change_history("Added task SC-052.")
    text = doc.render()
    doc2 = plan.parse(text)
    hist = doc2.get_section("Change History")
    assert "NGO vessel panel incomplete" in hist
    assert "Added task SC-052" in hist
    # both entries survive, in order
    assert hist.index("NGO vessel panel incomplete") < hist.index("Added task SC-052")


def test_sync_task_section_renders_table():
    doc = plan.new_plan("demo")
    graph = TaskGraph(
        [
            Task(
                id="SC-001",
                title="Fix geolocation",
                status="READY",
                acceptance=["a"],
                verification=["pytest"],
            )
        ]
    )
    doc.sync_task_section(graph)
    assert "SC-001" in doc.get_section("Tasks")
    assert "Fix geolocation" in doc.get_section("Tasks")


def test_missing_frontmatter_raises():
    import pytest

    with pytest.raises(plan.PlanError):
        plan.parse("# not a plan\n")
