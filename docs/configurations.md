# Configuring Your RPG Agent Proxy (`configs.yaml`)

This guide explains all the configuration settings available in `configs.yaml` in plain English. If you deploy this proxy to run your roleplay campaigns (using clients like JanitorAI or SillyTavern), you can tweak these settings to adjust memory limits, campaign pacing, background LLM models, and combat calculations.

---

## 💾 Section 1: Session State (`state`)
These settings control how the proxy stores the memory, inventory, and stats for your active campaigns.

### `num_states_to_track`
* **Type:** Integer (Whole Number)
* **Default:** `32`
* **What it does:** The number of recent turns the proxy remembers. Think of this as the number of **"autosave slots"** available per chat. If you edit messages or hit "Retry" on a turn within this limit, the proxy can restore your campaign state perfectly. If you exceed this limit, the oldest autosaves are cleaned up.

### `storage_dir`
* **Type:** Filepath/Text
* **Default:** `"data/states"`
* **What it does:** The folder on the server where campaign state JSON files are saved. Each session gets its own file. You rarely need to change this.

---

## 🧪 Section 2: Sandbox Executions (`sandbox`)
These settings manage the calculations engine that runs game rules, dice rules, and attribute updates.

### `timeout_seconds`
* **Type:** Decimal Number
* **Default:** `8.0`
* **What it does:** The maximum number of seconds the proxy allows a math or battle calculation script to run before aborting it. This prevents broken scripts from hanging the game.

---

## 🔄 Section 3: Loop Orchestration (`langgraph`)
These settings manage how the agent handles complex multiple-step loops (e.g., rolling dice → calculating modifier → updating state → describing outcome).

### `max_iterations`
* **Type:** Integer (Whole Number)
* **Default:** `5`
* **What it does:** The maximum number of **tool-calling loops** the LLM can make in a single turn. For example, if combat requires calculating damage, rolling a save, and updating stats, the LLM might call tools 3 times in a row. This setting caps that at `5` to prevent the AI from getting stuck in an infinite loop and costing you extra API money.

---

## 🤖 Section 4: Main AI Model Settings (`llm`)
These settings define the primary AI model acting as the Game Master (GM) in your roleplays.

### `base_url`
* **Type:** URL/Text
* **Default:** `"https://openrouter.ai/api/v1/chat/completions"`
* **What it does:** The completion endpoint URL of your AI provider. Change this if you want to use a provider other than OpenRouter.

### `default_model`
* **Type:** Text
* **Default:** `"google/gemini-3.5-flash"`
* **What it does:** The default AI model the proxy falls back to if your chat client doesn't specify one.

### `include_reasoning`
* **Type:** Boolean (`true`/`false`)
* **Default:** `true`
* **What it does:** Whether to request "reasoning content" (the AI's inner thoughts/planning) from models that support it (such as DeepSeek R1 or Gemini). Recommended to keep as `true` to give you a window into the GM's logic.

### `reasoning_format`
* **Type:** Text
* **Default:** `"Open-Router"`
* **What it does:** The structure in which reasoning thoughts are received. Supported formats include: `Open-Router`, `OpenAI`, `Gemini`, `Anthropic`, `X.AI`, `Z.AI`, `DeepSeek`, or `custom`.

---

## 🎭 Section 5: Story Pacing & Memory updates (`orchestration`)
These settings control the automatic narrative planning and rolling summaries that keep the plot consistent and prevent the GM from forgetting older events. Planning and summarization are executed as independent nodes within the story graph, each configured with its own triggers and dedicated LLM parameters.

### 📋 1. Story Planning Configuration (`orchestration.plan`)
Settings for the narrative planner node that updates your story roadmap checklist:

* **`trigger_type`**: Text (`"periodic"`, `"probabilistic"`, or `"disabled"`). How the planner decides it is time to update.
  * `"periodic"`: Triggers every fixed number of turns (set by `interval_turns`).
  * `"probabilistic"`: Triggers stochastically (chance set by `trigger_probability`).
  * `"disabled"`: The planner is never run.
* **`interval_turns`**: Integer. Trigger frequency if `trigger_type` is periodic (default `10` turns).
* **`trigger_probability`**: Decimal. Trigger chance if `trigger_type` is probabilistic (default `0.10` or 10%).
* **`bundle_llm`**: Boolean (`true`/`false`). Whether to bundle the update with the main roleplay call.
  * `true` (default): Updates are done inline using main GM tool calls (most cost-efficient).
  * `false`: Updates are executed in a separate, isolated graph node using the planner's own LLM settings.
* **`llm.model`**: Text. The model to use for the planner if `bundle_llm` is `false` (default `"google/gemini-3.5-flash"`).
* **`llm.base_url`**: Text. Completion URL override for the planner model.
* **`llm.include_reasoning`**: Boolean (`true`/`false`). Enable reasoning support for models that support it.
* **`llm.temperature`**: Decimal. Model sampling temperature (default `0.2` for logical, factual checklists).

### 📖 2. Narrative Summarization Configuration (`orchestration.summary`)
Settings for the summary node that compiles the rolling story recap:

* **`trigger_type`**: Text (`"periodic"`, `"probabilistic"`, or `"disabled"`). How the summarizer decides it is time to update.
  * `"periodic"`: Triggers every fixed number of turns (set by `interval_turns`).
  * `"probabilistic"`: Triggers stochastically (chance set by `trigger_probability`).
  * `"disabled"`: Summarization is never run.
* **`interval_turns`**: Integer. Trigger frequency if `trigger_type` is periodic (default `10` turns).
* **`trigger_probability`**: Decimal. Trigger chance if `trigger_type` is probabilistic (default `0.10` or 10%).
* **`bundle_llm`**: Boolean (`true`/`false`). Whether to bundle the update with the main roleplay call.
  * `true` (default): Updates are done inline using main GM tool calls (most cost-efficient).
  * `false`: Updates are executed in a separate, isolated graph node using the summarizer's own LLM settings.
* **`summary_target_words`**: Integer. Target word length for the summary block (default `200` words).
* **`llm.model`**: Text. The model to use for the summarizer if `bundle_llm` is `false` (default `"google/gemini-3.5-flash"`).
* **`llm.base_url`**: Text. Completion URL override for the summarizer model.
* **`llm.include_reasoning`**: Boolean (`true`/`false`). Enable reasoning support.
* **`llm.temperature`**: Decimal. Model sampling temperature (default `0.2`).
