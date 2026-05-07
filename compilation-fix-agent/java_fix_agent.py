"""
Java Compilation Fix Agent using LangGraph.

Usage:
    python java_fix_agent.py <java_dir> [--max-iterations N] [--model MODEL]

Environment:
    OPENROUTER_API_KEY - OpenRouter API key
"""

import argparse
import os
import subprocess
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph


# ── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    java_dir: str
    max_iterations: int
    iteration: int
    # {file: [error_line, ...]}
    errors: dict[str, list[str]]
    fixed: list[str]
    failed: list[str]
    report: str
    # {file: {"errors": [original error lines], "iterations": int}}
    fix_log: dict[str, dict]


# ── Helpers ───────────────────────────────────────────────────────────────────

def compile_directory(java_dir: str) -> dict[str, list[str]]:
    """Compile all .java files; return {file: [errors]}."""
    files = list(Path(java_dir).rglob("*.java"))
    if not files:
        return {}

    result = subprocess.run(
        ["javac", "-cp", java_dir] + [str(f) for f in files],
        capture_output=True, text=True
    )
    output = result.stderr

    errors: dict[str, list[str]] = {}
    for line in output.splitlines():
        # javac error lines start with <file>:<line>: error: ...
        if ": error:" in line or ": warning:" in line:
            parts = line.split(":", 1)
            filepath = parts[0].strip()
            if os.path.isfile(filepath):
                errors.setdefault(filepath, []).append(line)

    return errors


def read_file(path: str) -> str:
    return Path(path).read_text()


def write_file(path: str, content: str) -> None:
    Path(path).write_text(content)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def compile_node(state: AgentState) -> AgentState:
    """Compile and collect errors; seed fix_log with initial error counts."""
    errors = compile_directory(state["java_dir"])
    fix_log = dict(state.get("fix_log") or {})
    for filepath, errs in errors.items():
        if filepath not in fix_log:
            fix_log[filepath] = {"errors": errs, "iterations": 0}
    return {**state, "errors": errors, "fix_log": fix_log}


def report_node(state: AgentState) -> AgentState:
    """Build a human-readable compilation error report."""
    errors = state["errors"]
    if not errors:
        report = "✅ No compilation errors found."
    else:
        lines = [f"Compilation Error Report — {len(errors)} file(s) with errors\n"]
        for f, errs in errors.items():
            lines.append(f"\n📄 {f}")
            for e in errs:
                lines.append(f"   {e}")
        report = "\n".join(lines)

    print(report)
    return {**state, "report": report}


def get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.environ.get("JAVA_FIX_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
        openai_api_key=os.environ["OPENROUTER_API_KEY"],
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
    )


def fix_node(state: AgentState) -> AgentState:
    """Ask the LLM to fix each file; only write if the fix compiles."""
    print(f"\n🔁 Iteration {state['iteration'] + 1} / {state['max_iterations']}")
    llm = get_llm()

    system = SystemMessage(content=(
        "You are an expert Java developer. "
        "You will be given a Java source file and its compilation errors. "
        "Return ONLY the corrected Java source code with no markdown fences, "
        "no explanation, and no extra text."
    ))

    fixed = list(state["fixed"])
    failed = list(state["failed"])
    fix_log = dict(state.get("fix_log") or {})
    remaining_errors: dict[str, list[str]] = {}

    for filepath, errs in state["errors"].items():
        source = read_file(filepath)
        error_text = "\n".join(errs)

        prompt = HumanMessage(content=(
            f"File: {filepath}\n\n"
            f"Compilation errors:\n{error_text}\n\n"
            f"Source code:\n{source}"
        ))

        try:
            response = llm.invoke([system, prompt])
            fixed_source = response.content.strip()
        except Exception as e:
            print(f"  ❌ LLM call failed for {filepath}: {e}")
            remaining_errors[filepath] = errs
            continue

        # Swap in the fix, compile to verify, revert if still broken
        original = source
        write_file(filepath, fixed_source)
        verify_errors = compile_directory(state["java_dir"])
        fix_log[filepath]["iterations"] = fix_log.get(filepath, {}).get("iterations", 0) + 1

        if filepath not in verify_errors:
            print(f"  🔧 Fix verified and applied: {filepath}")
            fixed.append(filepath)
        else:
            print(f"  ↩️  Fix didn't compile, reverting: {filepath}")
            write_file(filepath, original)
            remaining_errors[filepath] = verify_errors.get(filepath, errs)

    return {
        **state,
        "errors": remaining_errors,
        "fixed": fixed,
        "failed": failed,
        "fix_log": fix_log,
        "iteration": state["iteration"] + 1,
    }

def final_report_node(state: AgentState) -> AgentState:
    """Print detailed summary: file counts, fixed/failed, per-file bug summary."""
    failed = list(state["failed"]) + list(state["errors"].keys())
    fix_log = state.get("fix_log") or {}
    total_files = len(fix_log)
    fixed_files = state["fixed"]

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(f"\n📁 Total files scanned : {total_files}")
    print(f"✅ Fixed               : {len(fixed_files)}")
    print(f"❌ Failed              : {len(failed)}")

    if fixed_files:
        print("\n── Fixed Files ──────────────────────────────────────────")
        for f in fixed_files:
            log = fix_log.get(f, {})
            errs = log.get("errors", [])
            iters = log.get("iterations", 1)
            print(f"\n  📄 {f}")
            print(f"     Iterations needed : {iters}")
            print(f"     Bugs found        : {len(errs)}")
            for e in errs:
                print(f"       • {e.strip()}")

    if failed:
        print("\n── Failed Files ─────────────────────────────────────────")
        for f in failed:
            log = fix_log.get(f, {})
            errs = log.get("errors", [])
            print(f"\n  📄 {f}")
            print(f"     Bugs remaining : {len(errs)}")
            for e in errs:
                print(f"       • {e.strip()}")

    if not fixed_files and not failed:
        print("\nNo errors were found — nothing to fix.")
    print()

    return {**state, "failed": failed}


# ── Routing ───────────────────────────────────────────────────────────────────

def should_fix(state: AgentState) -> str:
    if not state["errors"]:
        return "done"
    if state["iteration"] >= state["max_iterations"]:
        return "give_up"
    return "fix"


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("compile", compile_node)
    g.add_node("print_report", report_node)
    g.add_node("fix", fix_node)
    g.add_node("final_report", final_report_node)

    g.set_entry_point("compile")
    g.add_edge("compile", "print_report")
    g.add_conditional_edges("print_report", should_fix, {
        "fix": "fix",
        "done": "final_report",
        "give_up": "final_report",
    })
    g.add_conditional_edges("fix", should_fix, {
        "fix": "fix",
        "done": "final_report",
        "give_up": "final_report",
    })
    g.add_edge("final_report", END)

    return g.compile()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Java compilation fix agent")
    parser.add_argument("java_dir", help="Directory containing .java files")
    parser.add_argument("--max-iterations", type=int, default=3,
                        help="Max LLM fix iterations (default: 3)")
    parser.add_argument("--model", default=None,
                        help="Model to use (default: auto-selected based on provider)")
    args = parser.parse_args()

    if args.model:
        os.environ["JAVA_FIX_MODEL"] = args.model

    if not os.path.isdir(args.java_dir):
        print(f"Error: '{args.java_dir}' is not a directory.")
        return

    graph = build_graph()
    initial_state: AgentState = {
        "java_dir": args.java_dir,
        "max_iterations": args.max_iterations,
        "iteration": 0,
        "errors": {},
        "fixed": [],
        "failed": [],
        "report": "",
        "fix_log": {},
    }

    graph.invoke(initial_state)


if __name__ == "__main__":
    main()
