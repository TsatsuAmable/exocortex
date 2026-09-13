# ChatGPT ingestion findings — 2026-09-12

## Observed
- ChatGPT desktop is running from /Applications/ChatGPT.app.
- It uses a Chromium-style user-data tree at ~/Library/Application Support/Codex.
- Literal canary AINEKO_CANARY_20260912_0403_GOMSCHAT_7F3C was not found by a direct scan of that tree.
- The app bundle contains internal conversation-oriented methods:
  - registerChatGptConversationSource
  - subscribeChatGptConversation
  - runChatGptConversationAction
- The process exposes local IPC sockets including ~/.codex/ipc/ipc.sock and a codex-browser-use socket.
- Therefore the preferred research path is internal event/IPC observation before filesystem transcript scraping.

## Architectural consequence
Treat ChatGPT local storage as an observed cache until proven otherwise. Do not make GOMS ingestion depend on copying private application databases.

## Probe
scripts/chatgpt_surface_probe.py captures file metadata snapshots, changed files between runs, exact canary byte matches, and ChatGPT open-file handles. The probe is read-only.
