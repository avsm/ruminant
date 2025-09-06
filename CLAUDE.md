Ruminant is a reporting tool to track activity across a series of OCaml community projects, primarily hosted on GitHub.

I'd like to have a CLI tool called `ruminant` that uses the uv package manager, and can use Claude Code to generate weekly reports.

We will do this in stages, based on tools I have prototyped and are present in design/

- first a subcommand to sync github activity for a set of repos (design/gh-fetch.py) into `data/gh`
- then a subcommand that will generate a prompt for a given user/repo/week for claude (design/claude-summary-prompt.py) to stdout, putting the output in `data/summary`
- then a command that invokes `claude` in non-interactive mode on the generated prompt.
- then a subcommand that will annotate the report into a properly hyperlinked one (design/annotate.py) into data/reports

You should use rich and modern Python libraries to make this a beautiful CLI experience.
- 
