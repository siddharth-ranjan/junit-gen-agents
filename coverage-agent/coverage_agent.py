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

class MethodGap(TypedDict):
    name: str
    start_line: int       # 1-based line number from Jacoco XML
    missed_lines: int
    missed_branches: int
    source: str           # extracted method body from .java file


class ClassGap(TypedDict):
    missed_method_gaps: list[MethodGap]
    total_missed_lines: int
    total_missed_branches: int


class AgentState(TypedDict):
    jacoco_xml_path: str
    source_dir: str
    tests_dir: str
    template_path: str
    output_prompt_path: str
    gaps: dict[str, ClassGap]   # class name → gap detail
    gap_report: str
    prompt_written: bool


# ── Helper: extract method source from .java file ────────────────────────────

def extract_method_source(source_lines: list[str], start_line: int) -> str:
    """Extract a method body starting at start_line (1-based) by matching braces."""
    idx = start_line - 1  # convert to 0-based
    result = []
    depth = 0
    started = False

    for i in range(idx, len(source_lines)):
        line = source_lines[i]
        result.append(line)
        for ch in line:
            if ch == '{':
                depth += 1
                started = True
            elif ch == '}':
                depth -= 1
        if started and depth == 0:
            break

    return "\n".join(result)


# ── Node 1: Parse Jacoco XML ──────────────────────────────────────────────────

def parse_jacoco_node(state: AgentState) -> AgentState:
    """Parse jacoco.xml and extract classes with missed coverage, including per-method source."""
    tree = ET.parse(state["jacoco_xml_path"])
    root = tree.getroot()
    source_dir = Path(state["source_dir"])
    gaps: dict[str, ClassGap] = {}

    for package in root.findall("package"):
        pkg_name = package.get("name", "")

        # Build method gaps from <class> elements
        class_method_gaps: dict[str, list[MethodGap]] = {}
        for cls_el in package.findall("class"):
            sourcefilename = cls_el.get("sourcefilename", "")
            class_name = Path(sourcefilename).stem
            if not class_name:
                continue

            # Load source lines once per class
            candidates = [
                source_dir / pkg_name / sourcefilename,
                source_dir / sourcefilename,
                *source_dir.rglob(sourcefilename),
            ]
            source_lines: list[str] = []
            for c in candidates:
                p = c if isinstance(c, Path) else c
                if p.exists():
                    source_lines = p.read_text().splitlines()
                    break

            for method in cls_el.findall("method"):
                method_missed = 0
                method_missed_lines = 0
                method_missed_branches = 0
                for counter in method.findall("counter"):
                    t, missed = counter.get("type"), int(counter.get("missed", 0))
                    if t == "METHOD":
                        method_missed = missed
                    elif t == "LINE":
                        method_missed_lines = missed
                    elif t == "BRANCH":
                        method_missed_branches = missed

                if method_missed > 0:
                    start_line = int(method.get("line", 0))
                    method_source = (
                        extract_method_source(source_lines, start_line)
                        if source_lines and start_line > 0
                        else "// source not available"
                    )
                    class_method_gaps.setdefault(class_name, []).append({
                        "name": method.get("name", "<unknown>"),
                        "start_line": start_line,
                        "missed_lines": method_missed_lines,
                        "missed_branches": method_missed_branches,
                        "source": method_source,
                    })

        # Build file-level totals from <sourcefile> elements
        for sourcefile in package.findall("sourcefile"):
            class_name = Path(sourcefile.get("name", "")).stem
            total_missed_lines, total_missed_branches = 0, 0
            for counter in sourcefile.findall("counter"):
                t, missed = counter.get("type"), int(counter.get("missed", 0))
                if t == "LINE":
                    total_missed_lines = missed
                elif t == "BRANCH":
                    total_missed_branches = missed

            missed_method_gaps = class_method_gaps.get(class_name, [])
            if missed_method_gaps or total_missed_lines > 0 or total_missed_branches > 0:
                gaps[class_name] = {
                    "missed_method_gaps": missed_method_gaps,
                    "total_missed_lines": total_missed_lines,
                    "total_missed_branches": total_missed_branches,
                }

    print(f"📊 Parsed {state['jacoco_xml_path']}: {len(gaps)} class(es) with coverage gaps")
    for cls, gap in gaps.items():
        print(f"   {cls}: {len(gap['missed_method_gaps'])} missed method(s), "
              f"{gap['total_missed_lines']} missed line(s), {gap['total_missed_branches']} missed branch(es)")

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
        method_names = [m["name"] for m in gap["missed_method_gaps"]]
        lines.append(f"## {cls}")
        lines.append(f"- Missed methods  : {', '.join(method_names) or 'none'}")
        lines.append(f"- Missed lines    : {gap['total_missed_lines']}")
        lines.append(f"- Missed branches : {gap['total_missed_branches']}")
        lines.append("")

    report = "\n".join(lines)
    print(report)
    return {**state, "gap_report": report}


# ── Node 3: Assemble prompt and write to disk ─────────────────────────────────

def assemble_prompt_node(state: AgentState) -> AgentState:
    """Assemble the final prompt matching the draft structure and write to disk."""
    template = Path(state["template_path"]).read_text()
    source_dir = Path(state["source_dir"])
    tests_dir = Path(state["tests_dir"])

    sections: list[str] = [
        template,
        "=" * 60,
        "# Coverage Gap Report — Classes Requiring Additional Tests",
        "",
        "⚠️  STRICT RULES:",
        "  1. Generate @Test methods ONLY for the MISSED METHODS listed per class.",
        "  2. Do NOT modify, remove, or re-implement any method that is NOT in the missed list.",
        "  3. Do NOT duplicate any existing @Test method.",
        "  4. Preserve all existing @Test methods exactly as-is.",
        "=" * 60 + "\n",
    ]

    for cls, gap in state["gaps"].items():
        method_names = [m["name"] for m in gap["missed_method_gaps"]]

        # Resolve source file (package-relative or flat)
        pkg_candidates = list(source_dir.rglob(f"{cls}.java"))
        source_code = pkg_candidates[0].read_text() if pkg_candidates else f"// {cls}.java not found"

        test_candidates = list(tests_dir.rglob(f"{cls}Test.java"))
        existing_tests = test_candidates[0].read_text() if test_candidates else ""

        sections.append(f"=== CLASS: {cls} ===")
        sections.append(f"File: {cls}.java")
        sections.append("")
        sections.append(f"Missed Methods   : {', '.join(method_names) or 'none'}")
        sections.append(f"Missed Line Count: {gap['total_missed_lines']}")
        sections.append(f"Missed Branch Count: {gap['total_missed_branches']}")
        sections.append("")

        # Per-method detail
        sections.append("### Methods (missed — write tests for these):")
        for mg in gap["missed_method_gaps"]:
            sections.append(f"\n#### `{mg['name']}` (line {mg['start_line']}, "
                            f"missed lines: {mg['missed_lines']}, missed branches: {mg['missed_branches']})")
            sections.append(f"```java\n{mg['source']}\n```")

        sections.append("")
        sections.append("### Full Source Code:")
        sections.append(f"```java\n{source_code}\n```")

        if existing_tests:
            sections.append("")
            sections.append("### Existing Tests — DO NOT MODIFY OR REMOVE ANY OF THESE:")
            sections.append(f"```java\n{existing_tests}\n```")

        sections.append(f"\n=== END CLASS: {cls} ===\n")

    Path(state["output_prompt_path"]).write_text("\n".join(sections))
    print(f"✅ Prompt written to: {state['output_prompt_path']}")
    return {**state, "prompt_written": True}


# ── Node 4: Final report ──────────────────────────────────────────────────────

def final_report_node(state: AgentState) -> AgentState:
    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(f"  Classes with gaps : {len(state['gaps'])}")
    for cls, gap in state["gaps"].items():
        print(f"   {cls}: {len(gap['missed_method_gaps'])} missed method(s), "
              f"{gap['total_missed_lines']} missed line(s), {gap['total_missed_branches']} missed branch(es)")
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
