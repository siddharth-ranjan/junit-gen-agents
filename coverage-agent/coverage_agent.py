"""
Coverage Gap Analysis & Prompt Assembly Agent.

Parses a Jacoco XML report, builds a coverage gap report, and assembles
a prompt file for the existing JUnit generator.

Usage:
    python coverage_agent.py --jacoco jacoco.xml --source-dir ./src \
        --tests-dir ./tests --template junit_template.txt \
        --output-prompt ./prompt.txt
"""

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph


# ── State ─────────────────────────────────────────────────────────────────────

class ClassGap(TypedDict):
    missed_methods: list[str]
    missed_lines: int
    missed_branches: int


class AgentState(TypedDict):
    jacoco_xml_path: str
    source_dir: str
    tests_dir: str
    template_path: str
    output_prompt_path: str
    gaps: dict[str, ClassGap]
    gap_report: str
    prompt_written: bool


# ── Node 1: Parse Jacoco XML ──────────────────────────────────────────────────

def parse_jacoco_node(state: AgentState) -> AgentState:
    """Parse jacoco.xml and extract classes with missed coverage."""
    tree = ET.parse(state["jacoco_xml_path"])
    root = tree.getroot()
    gaps: dict[str, ClassGap] = {}

    for package in root.findall("package"):
        for sourcefile in package.findall("sourcefile"):
            class_name = Path(sourcefile.get("name", "")).stem

            missed_methods: list[str] = []
            for method in sourcefile.findall("method"):
                for counter in method.findall("counter"):
                    if counter.get("type") == "METHOD" and int(counter.get("missed", 0)) > 0:
                        missed_methods.append(method.get("name", "<unknown>"))

            missed_lines, missed_branches = 0, 0
            for counter in sourcefile.findall("counter"):
                t, missed = counter.get("type"), int(counter.get("missed", 0))
                if t == "LINE":
                    missed_lines = missed
                elif t == "BRANCH":
                    missed_branches = missed

            if missed_methods or missed_lines > 0 or missed_branches > 0:
                gaps[class_name] = {
                    "missed_methods": missed_methods,
                    "missed_lines": missed_lines,
                    "missed_branches": missed_branches,
                }

    print(f"📊 Parsed {state['jacoco_xml_path']}: {len(gaps)} class(es) with coverage gaps")
    for cls, gap in gaps.items():
        print(f"   {cls}: {len(gap['missed_methods'])} missed method(s), "
              f"{gap['missed_lines']} missed line(s), {gap['missed_branches']} missed branch(es)")

    return {**state, "gaps": gaps}


# ── Node 2: Build coverage gap report ────────────────────────────────────────

def build_gap_report_node(state: AgentState) -> AgentState:
    """Convert gaps dict into a detailed markdown-style coverage gap report."""
    gaps = state["gaps"]
    if not gaps:
        report = "✅ No coverage gaps found — all methods, lines, and branches are covered."
        print(report)
        return {**state, "gap_report": report}

    lines = ["# Coverage Gap Report\n"]
    for cls, gap in gaps.items():
        lines.append(f"## {cls}")
        lines.append(f"- Missed lines    : {gap['missed_lines']}")
        lines.append(f"- Missed branches : {gap['missed_branches']}")
        if gap["missed_methods"]:
            lines.append("- Missed methods  :")
            for m in gap["missed_methods"]:
                lines.append(f"    - `{m}`")
        lines.append("")

    report = "\n".join(lines)
    print(report)
    return {**state, "gap_report": report}


# ── Node 3: Assemble prompt and write to disk ─────────────────────────────────

def assemble_prompt_node(state: AgentState) -> AgentState:
    """Fill the JUnit template with gap report + source code and write prompt file."""
    template = Path(state["template_path"]).read_text()
    source_dir = Path(state["source_dir"])
    tests_dir = Path(state["tests_dir"])

    sections: list[str] = [
        "You are a JUnit 5 test generation expert.",
        "The following Java classes have incomplete test coverage.",
        "For each class, generate JUnit 5 tests that cover ALL missing methods, lines, and branches listed.",
        "Return only valid Java source code — no markdown fences, no explanation.\n",
        "=" * 60,
        state["gap_report"],
        "=" * 60 + "\n",
    ]

    for cls, gap in state["gaps"].items():
        source_file = source_dir / f"{cls}.java"
        source_code = source_file.read_text() if source_file.exists() else f"// {cls}.java not found"

        test_file = tests_dir / f"{cls}Test.java"
        existing_tests = test_file.read_text() if test_file.exists() else ""

        per_class_gap = (
            f"Missed methods  : {', '.join(gap['missed_methods']) or 'none'}\n"
            f"Missed lines    : {gap['missed_lines']}\n"
            f"Missed branches : {gap['missed_branches']}"
        )

        filled = (
            template
            .replace("{{class_name}}", cls)
            .replace("{{source_code}}", source_code)
            .replace("{{coverage_gaps}}", per_class_gap)
            .replace("{{existing_tests}}", existing_tests)
        )

        sections.append(f"=== CLASS: {cls} ===")
        sections.append(filled)
        sections.append(f"=== END CLASS: {cls} ===\n")

    Path(state["output_prompt_path"]).write_text("\n".join(sections))
    print(f"✅ Prompt written to: {state['output_prompt_path']}")
    return {**state, "prompt_written": True}


# ── Node 4: Final report ──────────────────────────────────────────────────────

def final_report_node(state: AgentState) -> AgentState:
    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(f"  Classes with gaps : {len(state['gaps'])}")
    if state.get("prompt_written"):
        print(f"  Prompt written to : {state['output_prompt_path']}")
    else:
        print("  No prompt written (no gaps found).")
    print()
    return state


# ── Routing ───────────────────────────────────────────────────────────────────

def has_gaps(state: AgentState) -> str:
    return "assemble" if state["gaps"] else "done"


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_jacoco", parse_jacoco_node)
    g.add_node("build_gap_report", build_gap_report_node)
    g.add_node("assemble_prompt", assemble_prompt_node)
    g.add_node("final_report", final_report_node)

    g.set_entry_point("parse_jacoco")
    g.add_edge("parse_jacoco", "build_gap_report")
    g.add_conditional_edges("build_gap_report", has_gaps, {
        "assemble": "assemble_prompt",
        "done": "final_report",
    })
    g.add_edge("assemble_prompt", "final_report")
    g.add_edge("final_report", END)
    return g.compile()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Coverage gap analysis & prompt assembly agent")
    parser.add_argument("--jacoco", required=True, help="Path to jacoco.xml")
    parser.add_argument("--source-dir", required=True, help="Directory containing .java source files")
    parser.add_argument("--tests-dir", required=True, help="Directory containing existing JUnit test files")
    parser.add_argument("--template", required=True, help="Path to JUnit prompt template file")
    parser.add_argument("--output-prompt", required=True, help="Path to write the assembled prompt")
    args = parser.parse_args()

    for path, label in [
        (args.jacoco, "jacoco XML"),
        (args.source_dir, "source dir"),
        (args.tests_dir, "tests dir"),
        (args.template, "template"),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found: '{path}'")
            return

    build_graph().invoke({
        "jacoco_xml_path": args.jacoco,
        "source_dir": args.source_dir,
        "tests_dir": args.tests_dir,
        "template_path": args.template,
        "output_prompt_path": args.output_prompt,
        "gaps": {},
        "gap_report": "",
        "prompt_written": False,
    })


if __name__ == "__main__":
    main()
