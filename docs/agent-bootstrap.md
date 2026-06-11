# Agent bootstrap prompts

Copy-paste one of these prompts into your agent and it will set ForgeLab up by
itself: install it, start the MCP server, verify the tools work, and confirm.

ForgeLab is installed from GitHub (it is not yet on PyPI), so the prompts use
`pip install "forgelab[mcp,agent] @ git+https://github.com/andresparraarze/ForgeLab"`.

The only thing you may want to change is the output directory
(`~/forgelab-output` by default).

## Hermes

```text
Set up the ForgeLab MCP server for me. Follow these steps exactly and report the result of each:

1. Check whether ForgeLab is already installed: run `~/.forgelab/venv/bin/forgelab-mcp --help`. If that works, skip to step 4.
2. Install it: run `python3 -m venv ~/.forgelab/venv` and then `~/.forgelab/venv/bin/pip install "forgelab[mcp,agent] @ git+https://github.com/andresparraarze/ForgeLab"`.
3. Create the output directory: `mkdir -p ~/forgelab-output`.
4. Register the MCP server in my Hermes MCP configuration as a stdio server named "forgelab" with command `~/.forgelab/venv/bin/forgelab-mcp`, args `["--transport", "stdio"]`, and environment variable `FORGELAB_OUTPUT_DIR=~/forgelab-output` (expand ~ to my home directory). If you cannot edit the configuration yourself, print the exact JSON block I need to add and tell me which file to put it in.
5. Once connected, call the ForgeLab tool `list_domains` and show me the result.
6. Print: "ForgeLab is ready — domains: <result of list_domains>. Exports will be written to ~/forgelab-output."
```

## OpenClaw

```text
Set up the ForgeLab MCP server for me. Follow these steps exactly and report the result of each:

1. Check whether ForgeLab is already installed: run `~/.forgelab/venv/bin/forgelab-mcp --help`. If that works, skip to step 4.
2. Install it: run `python3 -m venv ~/.forgelab/venv` and then `~/.forgelab/venv/bin/pip install "forgelab[mcp,agent] @ git+https://github.com/andresparraarze/ForgeLab"`.
3. Create the output directory: `mkdir -p ~/forgelab-output`.
4. Add a stdio MCP server named "forgelab" to my OpenClaw MCP configuration: command `~/.forgelab/venv/bin/forgelab-mcp`, args `["--transport", "stdio"]`, env `FORGELAB_OUTPUT_DIR=~/forgelab-output` (expand ~ to my home directory). If you cannot edit the configuration yourself, print the exact JSON block I need to add and tell me which file to put it in.
5. Once connected, call the ForgeLab tool `list_domains` and show me the result.
6. Print: "ForgeLab is ready — domains: <result of list_domains>. Exports will be written to ~/forgelab-output."
```

## Any MCP-compatible agent

```text
Set up the ForgeLab MCP server for me. ForgeLab is a design compiler that exposes MCP tools for generating, validating, importing, and exporting design files (KiCad, glTF, FreeCAD). Follow these steps exactly and report the result of each:

1. Check whether ForgeLab is already installed: run `~/.forgelab/venv/bin/forgelab-mcp --help`. If that works, skip to step 4.
2. Install it: run `python3 -m venv ~/.forgelab/venv` and then `~/.forgelab/venv/bin/pip install "forgelab[mcp,agent] @ git+https://github.com/andresparraarze/ForgeLab"`.
3. Create the output directory: `mkdir -p ~/forgelab-output`.
4. Register a stdio MCP server named "forgelab" in this agent's MCP configuration: command `~/.forgelab/venv/bin/forgelab-mcp`, args `["--transport", "stdio"]`, env `FORGELAB_OUTPUT_DIR=~/forgelab-output` (expand ~ to my home directory). If you cannot edit the configuration yourself, print the exact configuration block I need to add and tell me where to put it.
5. Once connected, call the ForgeLab tool `list_domains` and show me the result (expected: hardware, mechanical, threed).
6. Print: "ForgeLab is ready — domains: <result of list_domains>. Exports will be written to ~/forgelab-output."
```

## Notes

- `generate_document` (natural language → design) additionally needs
  `ANTHROPIC_API_KEY` set in the server's environment. Add it next to
  `FORGELAB_OUTPUT_DIR` in the MCP config, or skip it — every other tool
  (validate / import / export / schemas) works without it and returns a clear
  error message if generation is attempted without a key.
- Claude Code users: the one-line installer
  (`scripts/install-claude-code.sh`) or `forgelab init` does all of this
  automatically — see the README.
