# Contributing to live2note

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/yourname/live2note.git
cd live2note
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=live2note --cov-report=term-missing

# Run a specific test file
pytest tests/test_cli.py -v
```

## Code Quality

We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Check
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/

# Format
ruff format src/ tests/
```

## Project Structure

```
src/live2note/
  cli.py              # Typer CLI entry point
  pipeline.py          # Pipeline executor (transcribe → process → save)
  config.py            # YAML config loading
  task_manager.py      # Task CRUD and persistence
  models/task.py       # TaskState and related models
  adapters/            # Platform adapters (bilibili, douyin, generic)
  recorder/            # ffmpeg recording and stream resolution
  transcriber/         # faster-whisper transcription
  processor/           # Cleaner, chunker, summarizer, final note builder
  storage/             # Markdown/JSON writers and getnote integration
  prompts.py           # LLM prompt templates
```

## Adding a New Platform Adapter

1. Create `src/live2note/adapters/your_platform.py`
2. Implement `BaseAdapter` interface (match, get_platform, check_live)
3. Register in `src/live2note/adapters/registry.py`
4. Add tests in `tests/test_adapters.py`

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests: `pytest`
5. Run linter: `ruff check src/ tests/`
6. Commit with a descriptive message
7. Push and open a PR

## Commit Messages

Use conventional commits:

```
feat: add Douyin live adapter
fix: handle ffmpeg timeout on Windows
docs: update README installation section
test: add pipeline resume tests
```

## Code Style

- Python 3.10+ (use `X | None` instead of `Optional[X]`)
- 88 character line length
- Immutable data patterns preferred
- Functions under 50 lines, files under 800 lines
- Type hints on all public functions

## Reporting Issues

Please open an issue with:
- What you were trying to do
- What happened instead
- Full error output
- Your OS, Python version, and live2note version (`live2note --version`)
