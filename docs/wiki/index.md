---
title: "Home"
nav_order: 1
---

# invisible_dots Wiki

invisible_dots runs Dots: autonomous AI agents, each with its own Linux
computer, that work for a person through chat and tasks. This wiki is where
the work behind them is written up: what was measured, how, what came out,
and what was chosen because of it. Every study has its numbers and its
method, so a reader can check them or run them again.

The [README](https://github.com/feder-cr/invisible_dots#readme) is how to run
invisible_dots; [the architecture](https://github.com/feder-cr/invisible_dots/blob/main/docs/architecture.md)
is how it is built.

## [Studies](studies.md)

- [How a Dot remembers](how-a-dot-remembers.md): past conversations as files,
  a profile in every prompt, and the pass that keeps it current. 7.8% to 90.4%
  on LongMemEval.
- [Agent memory systems, measured on the same questions](agent-memory-systems-compared.md):
  Mastra, LangMem, Hindsight, an agentic "dream" pass and a single request,
  with their cost per pass.
- [Token counts are not portable between models](token-counts-across-models.md):
  tiktoken against five models' own counts, and why a fixed safety margin got
  a request refused.
- [Compacting a thread at the model's own window](compacting-at-the-models-window.md):
  no token cap of our own, old tool results cleared before anything is
  summarized.
- [Benchmarking an agent on real VMs](benchmarking-agents-on-real-vms.md):
  Harbor tasks, two-to-three-hour builds, and eight Dots on one host.
- [Browser calls that lead nowhere](browser-calls-that-lead-nowhere.md):
  45 tasks call by call: addresses from memory, timeouts, and three tools that
  never worked.
