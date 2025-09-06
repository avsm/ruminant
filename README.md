# Ruminant

This CLI tool digests activity from online projects and spits out reports. It's not
as bad-tempered as a camel, though!

![](logo.jpg)

## Features

- 📥 **Sync GitHub Data**: Fetch and cache issues, PRs, and discussions from repositories
- 📝 **Generate Prompts**: Create optimized prompts for Claude AI summarization  
- 🤖 **AI Summarization**: Generate comprehensive weekly reports using Claude CLI
- 🔗 **Link Annotation**: Add GitHub user and repository links to reports
- 📊 **Batch Processing**: Handle multiple repositories and weeks efficiently
- 🗃️ **Smart Caching**: Avoid redundant API calls with intelligent caching
- ⚡ **Rich CLI**: Beautiful command-line interface with progress indicators

## Installation

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- [Claude CLI](https://claude.ai/code) configured with API access
- GitHub token (personal access token)

### Install with uv

```bash
# Clone the repository
git clone https://github.com/avsm/ruminant.git
cd ruminant

# Install with uv
uv sync
uv run ruminant --help
```

### Initialize Project

```bash
# Create configuration files
uv run ruminant init

# Edit the keys file with your GitHub token
editor .ruminant-keys.toml

# Edit the main config with your repositories
editor .ruminant.toml
```

## Configuration

### Main Configuration (`.ruminant.toml`)

```toml
[project]
name = "OCaml Community Activity"
description = "Weekly reports for OCaml ecosystem projects"

[repositories]
repos = [
    "ocaml/opam-repository",
    "mirage/mirage",
    "janestreet/base",
    "ocsigen/lwt"
]

[repositories.custom_prompts]
"ocaml/opam-repository" = """Focus on package submissions, maintenance updates, and ecosystem changes.
Highlight any breaking changes or major version updates."""

[claude]
command = "claude"
args = ["--non-interactive"]

[reporting]
default_weeks = 1
auto_annotate = true
```

### Keys Configuration (`.ruminant-keys.toml`)

```toml
[github]
token = "ghp_your_github_token_here"
```

> ⚠️ The `.ruminant-keys.toml` file is automatically added to `.gitignore` to keep your tokens secure.

## Usage

### Quick Start

```bash
# Generate reports for all configured repositories
uv run ruminant report

# Generate reports for last 4 weeks  
uv run ruminant report --weeks 4

# Generate report for specific repository
uv run ruminant report ocaml/opam-repository
```

### Individual Commands

#### Sync GitHub Data

```bash
# Sync all configured repositories
uv run ruminant sync

# Sync specific repositories for multiple weeks
uv run ruminant sync ocaml/opam-repository mirage/mirage --weeks 4

# Force refresh cached data
uv run ruminant sync --force
```

#### Generate Claude Prompts

```bash
# Generate prompts for all repositories
uv run ruminant prompt

# Generate for specific week
uv run ruminant prompt --year 2024 --week 35
```

#### Generate Summaries

```bash
# Generate summaries using Claude CLI
uv run ruminant summarize

# Use custom Claude arguments
uv run ruminant summarize --claude-args="--model claude-3-5-sonnet-20241022"

# Dry run to see what would be processed
uv run ruminant summarize --dry-run
```

#### Annotate Reports

```bash
# Annotate all summaries with GitHub links
uv run ruminant annotate

# Annotate specific files with wildcards
uv run ruminant annotate 'data/summaries/**/*.md'

# Update files in place instead of creating reports
uv run ruminant annotate --in-place
```

### End-to-End Workflow

The `report` command runs all steps in sequence:

```bash
# Full workflow: sync → prompt → summarize → annotate
uv run ruminant report

# Skip steps if needed
uv run ruminant report --skip-sync --skip-prompt

# Parallel processing for multiple repos/weeks
uv run ruminant report --weeks 4 --repos ocaml/opam-repository mirage/mirage
```

## Directory Structure

Ruminant organizes data in a git-committable structure:

```
data/
├── gh/                    # Raw GitHub API cache
│   └── owner/
│       └── repo/
│           └── week-NN-YYYY.json
├── prompts/               # Generated Claude prompts  
│   └── owner/
│       └── repo/
│           └── week-NN-YYYY-prompt.txt
├── summaries/             # Claude-generated summaries
│   └── owner/
│       └── repo/
│           └── week-NN-YYYY.md
└── reports/               # Final annotated reports
    └── owner/
        └── repo/
            └── week-NN-YYYY.md
```

## Advanced Usage

### Custom Prompts

Add repository-specific prompts in `.ruminant.toml`:

```toml
[repositories.custom_prompts]
"ocaml/opam-repository" = """Focus on package submissions and ecosystem changes."""
"mirage/mirage" = """Emphasize unikernels development and protocol implementations."""
```

### Cache Management

```bash
# View user cache statistics
uv run ruminant annotate stats

# Clear user cache
uv run ruminant annotate clear-cache

# Show configuration
uv run ruminant config
```

### Error Handling

Ruminant continues processing on failures and provides detailed summaries:

- ✅ Successful operations are reported
- ❌ Failed operations are logged with details
- 📊 Summary tables show overall results
- 🔄 Retries are attempted for transient failures

## Development

### Setup Development Environment

```bash
git clone https://github.com/avsm/ruminant.git
cd ruminant

# Install in development mode
uv sync --dev

# Run tests
uv run pytest

# Format code
uv run black ruminant/
uv run isort ruminant/
```

### Project Structure

```
ruminant/
├── pyproject.toml          # Project configuration
├── ruminant/
│   ├── main.py            # CLI entry point
│   ├── config.py          # Configuration management
│   ├── commands/          # Command implementations
│   │   ├── sync.py        # GitHub data fetching
│   │   ├── prompt.py      # Prompt generation
│   │   ├── summarize.py   # Claude integration
│   │   ├── annotate.py    # Link annotation
│   │   └── report.py      # End-to-end workflow
│   └── utils/             # Utility modules
│       ├── github.py      # GitHub API client
│       ├── paths.py       # Path management
│       ├── dates.py       # Date/week utilities
│       ├── logging.py     # Rich console output
│       └── annotate.py    # Link annotation logic
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/)
- Integrates with [Claude CLI](https://claude.ai/code) for AI summarization
- Inspired by the need for better community project tracking
