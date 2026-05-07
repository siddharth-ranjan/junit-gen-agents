# Coverage Gap Analysis & Prompt Assembly Agent

Parses Jacoco XML coverage reports, identifies untested code, and generates a structured prompt file for JUnit test generation.

## Overview

This agent analyzes Jacoco XML reports to find coverage gaps (missed methods, lines, branches), produces a detailed coverage report, and assembles a prompt file that combines:
- Coverage gap summary for all classes
- Per-class sections with source code, existing tests, and specific gaps
- A universal JUnit template filled with class-specific data

The output prompt is ready to feed into your existing JUnit test generator.

## Requirements

- Python 3.11+
- Dependencies: `langgraph`, `langchain-openai`, `langchain-core`

```bash
pip install -r requirements.txt
```

## Usage

```bash
python coverage_agent.py \
  --jacoco jacoco.xml \
  --source-dir ./src \
  --tests-dir ./tests \
  --template junit_template.txt \
  --output-prompt ./prompt.txt
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--jacoco` | Yes | Path to `jacoco.xml` coverage report |
| `--source-dir` | Yes | Directory containing `.java` source files |
| `--tests-dir` | Yes | Directory containing existing JUnit test files |
| `--template` | Yes | Path to JUnit prompt template file |
| `--output-prompt` | Yes | Path where the assembled prompt will be written |

## How It Works

### 1. Parse Jacoco XML
Extracts coverage data from `jacoco.xml`:
- Missed methods (where `<counter type="METHOD" missed="N">` with N > 0)
- Missed lines (from `<counter type="LINE">`)
- Missed branches (from `<counter type="BRANCH">`)

### 2. Build Coverage Gap Report
Generates a markdown-style report listing all classes with gaps:
```markdown
# Coverage Gap Report

## BankAccount
- Missed lines    : 25
- Missed branches : 4
- Missed methods  :
    - `withdraw`
    - `transfer`
    - `calculateInterest`
```

### 3. Assemble Prompt
For each class with gaps:
- Reads the source code from `--source-dir`
- Reads existing tests from `--tests-dir` (if present)
- Fills the universal template with placeholders:
  - `{{class_name}}` → class name
  - `{{source_code}}` → full source code
  - `{{coverage_gaps}}` → missed methods/lines/branches
  - `{{existing_tests}}` → existing test code (or empty)

Writes a single prompt file with all classes separated by `=== CLASS: X ===` / `=== END CLASS: X ===` blocks.

## Output Prompt Structure

```
[System instructions]
============================================================
# Coverage Gap Report
[All classes with gaps listed]
============================================================

=== CLASS: BankAccount ===
[Filled template with source, gaps, existing tests, instructions]
=== END CLASS: BankAccount ===

=== CLASS: OrderService ===
[Filled template]
=== END CLASS: OrderService ===
```

## JUnit Template Format

Your template file should use these placeholders:

```
Generate JUnit 5 tests for the class: {{class_name}}

## Coverage Gaps to Address
{{coverage_gaps}}

## Source Code
```java
{{source_code}}
```

## Existing Tests (do NOT duplicate these)
```java
{{existing_tests}}
```

## Instructions
- Write a complete JUnit 5 test class named {{class_name}}Test
- Add @Test methods that cover every missed method listed above
- Cover both happy-path and edge cases
- Return only valid Java source code, no markdown, no explanation
```

## Example

```bash
# Run the agent
python coverage_agent.py \
  --jacoco jacoco.xml \
  --source-dir ./src \
  --tests-dir ./tests \
  --template junit_template.txt \
  --output-prompt ./prompt.txt

# Output
📊 Parsed jacoco.xml: 2 class(es) with coverage gaps
   BankAccount: 6 missed method(s), 25 missed line(s), 4 missed branch(es)
   OrderService: 3 missed method(s), 12 missed line(s), 2 missed branch(es)

# Coverage Gap Report
...

✅ Prompt written to: ./prompt.txt

============================================================
FINAL REPORT
============================================================
  Classes with gaps : 2
  Prompt written to : ./prompt.txt
```

## Integration with JUnit Generator

The output `prompt.txt` is designed to be fed directly into your existing JUnit test generator. The generator can:
- Process the entire file as one prompt (if it handles multi-class generation)
- Split by `=== CLASS: X ===` / `=== END CLASS: X ===` blocks to generate tests per class

## Architecture

Built with LangGraph using a 4-node state machine:

```
parse_jacoco → build_gap_report → [has gaps?] → assemble_prompt → final_report
                                              ↘ (no gaps)      → final_report
```

**Nodes:**
1. `parse_jacoco_node` — Parse XML, extract gaps
2. `build_gap_report_node` — Format markdown report
3. `assemble_prompt_node` — Fill template, write file
4. `final_report_node` — Print summary

## Troubleshooting

**No gaps found:**
- Verify `jacoco.xml` contains `<counter type="METHOD" missed="N">` with N > 0
- Check that source file names in XML match `.java` files in `--source-dir`

**Template placeholders not replaced:**
- Ensure template uses exact placeholder names: `{{class_name}}`, `{{source_code}}`, `{{coverage_gaps}}`, `{{existing_tests}}`

**Source file not found:**
- Jacoco XML uses `<sourcefile name="BankAccount.java">` — ensure `BankAccount.java` exists in `--source-dir`

## Related

- `java_fix_agent.py` — Companion agent that fixes Java compilation errors using LLM
