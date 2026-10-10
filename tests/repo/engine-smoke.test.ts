/**
 * The engine smoke and the browser smoke live in guest/image-builder/test/smoke/ and run in CI (the
 * `smoke` and `browser-smoke` jobs of .github/workflows/tests.yml). These checks keep the pieces
 * together: the files are there and reference nothing outside the repository,
 * the jobs run the entry and the gate waits for them, and the entry exits
 * non-zero on a failed check and on a skipped one.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repo = resolve(fileURLToPath(new URL(".", import.meta.url)), "../..");
const smoke = join(repo, "guest/image-builder/test/smoke");

const FILES = ["README.md", "run.sh", "prepare-engine.sh", "lib.sh", "smoke.sh", "browser/smoke.sh", "fake_openrouter.py", "host-stream.sh"];
const SCRIPTS = FILES.filter((name) => name !== "README.md");

function read(path: string): string {
  return readFileSync(path, "utf8").replace(/\r\n/g, "\n");
}

/** The lines of a shell script or Python file that are not comments. */
function code(text: string): string {
  return text
    .split("\n")
    .filter((line) => !/^\s*#/.test(line))
    .join("\n");
}

/** The text of one job of the workflow, up to the next job. */
function job(workflow: string, name: string): string {
  const start = workflow.indexOf(`\n  ${name}:\n`);
  expect(start, `job ${name}`).toBeGreaterThanOrEqual(0);
  const next = workflow.slice(start + 1).search(/\n {2}[a-z][a-z-]*:\n/);
  return next === -1 ? workflow.slice(start) : workflow.slice(start, start + 1 + next);
}

describe("the engine smoke", () => {
  it("is in the repository, with the README that says what it proves and how to run it", () => {
    for (const name of FILES) expect(existsSync(join(smoke, name)), name).toBe(true);
    const readme = read(join(smoke, "README.md"));
    expect(readme).toContain("guest/image-builder/test/smoke/run.sh");
    expect(readme).toContain("--archive");
    expect(readme).toContain("WSL");
    expect(readme).toContain(".github/workflows/tests.yml");
    expect(readme).toContain("SMOKE: <passed> passed, <failed> failed, <skipped> skipped");
  });

  it("is LF-only, because it runs on Linux", () => {
    for (const name of FILES) expect(readFileSync(join(smoke, name), "utf8"), name).not.toContain("\r");
  });

  it("points nowhere outside the repository and keeps no state between runs", () => {
    for (const name of SCRIPTS) {
      const text = code(read(join(smoke, name)));
      expect(text, name).not.toMatch(/\.local\/(smoke|port)|scratchpad|\/mnt\/[a-z]\/|\bC:[\\/]|~\//);
      expect(text, name).not.toMatch(/\brm\s+(-\w*[rR]\w*|--recursive)\b/);
    }
    // The entry names no fixed path on the host: a docker volume per run, a mktemp file for its log.
    expect(code(read(join(smoke, "run.sh")))).not.toMatch(/\/tmp\b/);
    expect(code(read(join(smoke, "prepare-engine.sh")))).not.toMatch(/\/tmp\b/);
  });

  it("builds the engine's environment with the repository's own script and lock, as provision.sh does", () => {
    const prepare = read(join(smoke, "prepare-engine.sh"));
    expect(prepare).toContain("build-engine-env.sh");
    expect(prepare).toContain("engine-requirements.lock");
    expect(prepare).toContain("pins.json");
    const provision = read(join(repo, "guest/image-builder/builder/provision.sh"));
    expect(provision).toContain("ENGINE_BUILD");
    expect(provision).toContain("ENGINE_LOCK");
  });

  it("is run by the smoke job of the workflow, and the gate needs that job", () => {
    const workflow = read(join(repo, ".github/workflows/tests.yml"));
    const smokeJob = job(workflow, "smoke");
    expect(smokeJob).toContain("runs-on: ubuntu-latest");
    expect(smokeJob).toContain("uses: actions/checkout@v4");
    expect(smokeJob).toMatch(/run: bash guest\/image-builder\/test\/smoke\/run\.sh\s*$/m);

    const gate = job(workflow, "gate");
    const needs = /needs: \[([^\]]*)\]/.exec(gate);
    expect(needs).not.toBeNull();
    const jobs = [...workflow.slice(workflow.indexOf("\njobs:\n")).matchAll(/^ {2}([a-z][a-z-]*):$/gm)]
      .map((m) => m[1]!)
      .filter((name) => name !== "gate");
    const needed = needs![1]!.split(",").map((name) => name.trim());
    expect(needed).toContain("smoke");
    expect([...needed].sort()).toEqual([...jobs].sort());
    expect(gate).toContain(`names.length !== ${jobs.length}`);
  });

  it("runs the browser smoke in its own job, which the gate needs, from the same entry", () => {
    const workflow = read(join(repo, ".github/workflows/tests.yml"));
    const browserJob = job(workflow, "browser-smoke");
    expect(browserJob).toContain("runs-on: ubuntu-latest");
    expect(browserJob).toContain("uses: actions/checkout@v4");
    expect(browserJob).toMatch(/run: bash guest\/image-builder\/test\/smoke\/run\.sh --suite browser\s*$/m);
    expect(/needs: \[([^\]]*)\]/.exec(job(workflow, "gate"))![1]).toContain("browser-smoke");

    const entry = read(join(smoke, "run.sh"));
    expect(entry).toContain("--suite");
    expect(entry).toContain('-e SMOKE_SUITE="$suite"');
    expect(read(join(smoke, "prepare-engine.sh"))).toContain("browser/smoke.sh");
  });

  it("builds the browser smoke's browser with the image builder's own script, lock and apt packages, and runs the real server", () => {
    const prepare = read(join(smoke, "prepare-engine.sh"));
    expect(prepare).toContain("build-browser-env.sh");
    expect(prepare).toContain("mcp-requirements.lock");
    expect(prepare).toContain(".apt_packages[]");
    const provision = read(join(repo, "guest/image-builder/builder/provision.sh"));
    expect(provision).toContain("BROWSER_BUILD");

    const checks = code(read(join(smoke, "browser/smoke.sh")));
    // No stand-in for the browser: the engine runs what is on its PATH, in front of the real desktop script.
    expect(checks).toContain("unset MCP_COMMAND");
    expect(checks).not.toMatch(/fake_mcp|MCP_COMMAND=/);
    expect(checks).toContain("/opt/invisible-dots/bin/dot-desktop");
    expect(checks).toContain("dot-desktop.sh");
    expect(checks).toContain("/v1/screenshot");
    expect(checks).toContain(".stealth-identity.json");
    expect(checks).toContain("pkill -9 -u dotengine");
  });

  it("runs the browser seams against the engine's one MCP stand-in and the tool list captured from the pinned server", () => {
    const checks = read(join(smoke, "smoke.sh"));
    const lib = read(join(smoke, "lib.sh"));
    const fake = "invisible_engine_dots/tests/fakes/fake_mcp_server.py";
    expect(existsSync(join(repo, fake)), fake).toBe(true);
    // The smoke copies that file, not a second stand-in of its own, and the tool list beside it.
    expect(checks).toContain("fakes/fake_mcp_server.py");
    expect(checks).toContain("fixtures/mcp-tools-*.json");
    expect(readdirSync(join(repo, "invisible_engine_dots/tests/fixtures")).filter((n) => /^mcp-tools-.*\.json$/.test(n))).toHaveLength(1);
    expect(existsSync(join(smoke, "fake_mcp.py"))).toBe(false);
    // It is the program the engine runs for a browser, under the name the engine reads: lib.sh writes the
    // engine's environment, and only a smoke that sets MCP_COMMAND gives the engine a program of its own.
    expect(code(lib)).toContain("export INVISIBLE_DOTS_MCP_COMMAND=");
    expect(code(checks)).toContain("MCP_COMMAND=$FAKE_MCP");
    expect(read(join(repo, "invisible_engine_dots/nanobot/dots/main.py"))).toContain('"INVISIBLE_DOTS_MCP_COMMAND"');
    expect(read(join(smoke, "fake_openrouter.py"))).toContain("RUN-TOOL");
  });

  it("pins the offered tools of a Dot granted everything to the permission table, tool for tool", () => {
    const table = read(join(repo, "invisible_engine_dots/nanobot/dots/permissions.py"));
    const tools = [...table.matchAll(/^ {8}"(\w+)": ToolEntry\(/gm)].map((m) => m[1]!).sort();
    expect(tools.length).toBeGreaterThanOrEqual(27);
    const checks = read(join(smoke, "smoke.sh"));
    const first = /check_offered 1 [^\n]*\\\n[^\n]*\\\n\s+'(\[[^\n]*\])'/.exec(checks);
    expect(first, "check_offered 1").not.toBeNull();
    expect(JSON.parse(first![1]!)).toEqual(tools);
  });

  it.each(["smoke.sh", "browser/smoke.sh"])("%s exits non-zero on a failed check and on a skipped one, and prints the summary", (name) => {
    const checks = read(join(smoke, name));
    expect(checks).toContain('echo "SMOKE: $PASS passed, $FAIL failed, $SKIP skipped"');
    expect(checks.trimEnd().split("\n").pop()).toBe('[ "$FAIL" = 0 ] && [ "$SKIP" = 0 ]');
  });

  it("the entry exits non-zero on a failed check, a skipped one and a run that never reached the summary", () => {

    const entry = read(join(smoke, "run.sh"));
    // The container's status and the summary line must both say "nothing failed, nothing skipped,
    // something passed"; a run that never printed the summary is not a pass.
    expect(entry).toContain("^SMOKE: [1-9][0-9]* passed, 0 failed, 0 skipped$");
    expect(entry).toContain('[ "$status" -eq 0 ]');
    expect(entry.trimEnd().split("\n").pop()).toBe("exit 1");
  });
});
