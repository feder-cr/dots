// Derived from OpenDots (CopilotKit) src/client/ComputerToolCard.tsx at 88f2a08, MIT; changed: the map is over this engine's tool table (permissions.py) and not the demo's computer actions; each entry says in past tense what the call did, in the infinitive what it would do (for an approval card), and which family of tools it belongs to; a tool the table does not know is named as the model called it.

/** What kind of thing a tool does: the chat draws one icon per family. */
export type ToolFamily = "command" | "read" | "write" | "automation" | "screen" | "browser-identity" | "browser" | "other";

export interface ToolLabel {
  /** What the call did, as a short phrase: "Ran a command". */
  label: string;
  /** What the call would do, for a question put to the person: "run a command", to follow "wants to". */
  ask: string;
  family: ToolFamily;
}

/**
 * The words for every tool of the engine's table (`nanobot/dots/permissions.py` `TOOL_PERMISSIONS`); a test reads that
 * file and fails when a tool is missing here or a name here is no longer a tool, so the two cannot drift.
 */
export const TOOL_LABELS: Readonly<Record<string, ToolLabel>> = {
  exec: { label: "Ran a command", ask: "run a command", family: "command" },
  exec_session: { label: "Used a command session", ask: "use a command session", family: "command" },
  list_exec_sessions: { label: "Listed command sessions", ask: "list command sessions", family: "command" },
  read_file: { label: "Read a file", ask: "read a file", family: "read" },
  list_dir: { label: "Listed a folder", ask: "list a folder", family: "read" },
  find_files: { label: "Searched for files", ask: "search for files", family: "read" },
  grep: { label: "Searched in files", ask: "search in files", family: "read" },
  write_file: { label: "Wrote a file", ask: "write a file", family: "write" },
  edit_file: { label: "Edited a file", ask: "edit a file", family: "write" },
  apply_patch: { label: "Applied a patch", ask: "apply a patch", family: "write" },
  cron: { label: "Managed an automation", ask: "manage an automation", family: "automation" },
  computer_screenshot: { label: "Looked at the desktop", ask: "look at the desktop", family: "screen" },
  browser_identity_list: { label: "Listed browser identities", ask: "list browser identities", family: "browser-identity" },
  browser_identity_create: { label: "Created a browser identity", ask: "create a browser identity", family: "browser-identity" },
  browser_identity_delete: { label: "Deleted a browser identity", ask: "delete a browser identity", family: "browser-identity" },
  browser_identity_launch: { label: "Opened a browser", ask: "open a browser", family: "browser-identity" },
  browser_identity_close: { label: "Closed a browser", ask: "close a browser", family: "browser-identity" },
  browser_navigate: { label: "Opened a page", ask: "open a page", family: "browser" },
  browser_snapshot: { label: "Inspected the page", ask: "inspect the page", family: "browser" },
  browser_read_text: { label: "Read the page", ask: "read the page", family: "browser" },
  browser_screenshot: { label: "Looked at the page", ask: "look at the page", family: "browser" },
  browser_click: { label: "Clicked on the page", ask: "click on the page", family: "browser" },
  browser_click_at: { label: "Clicked on the page", ask: "click on the page", family: "browser" },
  browser_type: { label: "Typed on the page", ask: "type on the page", family: "browser" },
  browser_press_key: { label: "Pressed a key", ask: "press a key", family: "browser" },
  browser_select_option: { label: "Chose an option", ask: "choose an option", family: "browser" },
  browser_scroll: { label: "Scrolled the page", ask: "scroll the page", family: "browser" },
};

/** What a command that was started in a terminal (`exec` with `tty`, which the engine reports on `tool.called`) did: it did not just run. */
export const TERMINAL_LABEL = "Started a terminal session";

/**
 * The words for a tool; one the table does not know (the model called a name the engine refuses) keeps its own name.
 * A call that started a terminal session (`tty` of `tool.called`) says so and not "Ran a command".
 */
export function toolLabel(tool: string, tty = false): ToolLabel {
  if (tool === "exec" && tty) return { ...TOOL_LABELS.exec!, label: TERMINAL_LABEL };
  return Object.hasOwn(TOOL_LABELS, tool) ? TOOL_LABELS[tool]! : { label: `Called ${tool}`, ask: `call ${tool}`, family: "other" };
}
