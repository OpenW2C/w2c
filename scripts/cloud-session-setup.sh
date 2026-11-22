#!/bin/bash
# Copy-paste SoT for Claude Code / Codex cloud environment setup.
# Keep in sync with docs/cloud-sessions.md (w2c help cloud-sessions).
# Pins: w2c v3.6.1, OpenSpec 2.1.1 (npm needs Node.js 22.20.0 or newer).

# --- W2C setup script start ---
# --- W2C 3.6.1 ---
curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/v3.6.1/install.sh | bash -s -- --ref v3.6.1
npm install -g @fission-ai/openspec@2.1.1
export PATH="$HOME/.local/bin:$PATH"
w2c install-skills
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
# --- W2C setup script end ---
