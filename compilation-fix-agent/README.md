# Java Compilation Fix Agent

An agentic tool that automatically detects and fixes Java compilation errors using an LLM, built with LangGraph.

## How It Works

1. Compiles all `.java` files in the target directory using `javac`
2. Groups errors by file and reports them
3. Sends each broken file to an LLM with its errors for a fix
4. Verifies the fix compiles before writing it — reverts if it doesn't
5. Repeats until all errors are resolved or the iteration limit is reached

## Requirements

- Python 3.11+
- Java (`javac`) installed and on `PATH`
- An [OpenRouter](https://openrouter.ai) API key

Install Python dependencies:

```bash
pip install langchain-openai langgraph
```

## Usage

```bash
export OPENROUTER_API_KEY=your_key_here

python java_fix_agent.py <java_dir> [--max-iterations N] [--model MODEL]
```

**Arguments:**

| Argument | Description | Default |
|---|---|---|
| `java_dir` | Directory containing `.java` files | required |
| `--max-iterations` | Maximum LLM fix attempts | `3` |
| `--model` | OpenRouter model ID to use | `nvidia/nemotron-3-super-120b-a12b:free` |

**Example:**

```bash
python java_fix_agent.py ./src --max-iterations 5 --model openai/gpt-4o
```

## Configuration

| Environment Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Required. Your OpenRouter API key. |
| `JAVA_FIX_MODEL` | Optional. Overrides the default model (also overridden by `--model`). |

## Output

The agent prints a compilation report each iteration and a final summary showing which files were fixed, how many iterations each required, and which files (if any) could not be resolved.
