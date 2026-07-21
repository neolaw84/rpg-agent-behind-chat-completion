# Why Use RACHEL?

Text-based roleplaying games (RPGs) powered by Large Language Models (LLMs) are incredibly immersive, but raw LLMs suffer from severe limitations when running complex games. **RACHEL** (**R**pg **A**gent **CH**at **E**valuation **L**oop) bridges the gap between raw LLMs and traditional tabletop game mechanics (like D&D or custom systems).

---

## Problems RACHEL Aims to Solve

Standard LLM completions APIs operate as stateless text predictors, creating four major bottlenecks for tabletop roleplay:

1. **Hallucinated & Biased Dice Rolls**: When asked to "roll a d20," LLMs do not calculate random probabilities. Instead, they predict text based on narrative bias—often fudging rolls to make player actions succeed cooperatively or producing repetitive number patterns.
2. **Mathematical Inaccuracies**: RPG mechanics require strict calculations (HP tracking, armor class, damage modifiers, gold balance, inventory weight). LLMs regularly hallucinate math (e.g., computing `17 + 4 - 2 = 21` on one turn and `18` on the next).
3. **Context Decay & State Memory Loss**: As roleplay conversations grow, the LLM context window fills up. The AI forgets character stats, loses track of inventory items, forgets hidden campaign triggers, or strays from narrative plot goals.
4. **State Corruption on Retries & Swipes**: Chat clients (like JanitorAI or SillyTavern) allow users to edit previous messages or hit "Retry" to get a new response. Standard stateful APIs treat retries as new turns, causing double-damage, duplicate item drops, or corrupted state histories.

---

## How RACHEL Solves the Problems

RACHEL acts as a stateful proxy between the chat client and the LLM provider (like OpenRouter), intercepting requests to run a stateful LangGraph agent loop:

1. **True Programmatic RNG & Dice Tools**: Intercepts dice requests and executes true Random Number Generators (RNG) behind the scenes (via `roll_xdy` tools). The LLM receives the real roll output and must narrate the outcome based on actual results.
2. **Deterministic Code Sandbox Execution**: Runs an isolated **Code Sandbox** (supporting Python and V8 JavaScript engines). The LLM writes and executes computational scripts to update stats, calculate damage formulas, and manage inventory without mathematical errors.
3. **Multi-Dimensional Session State**: Maintains a structured 4-component state for every campaign:
   * **`state`**: Public character stats, health, gold, and inventory mutated by sandbox scripts.
   * **`plan`**: Checklist of narrative plot goals and NPC schedules keeping the story on track.
   * **`summary`**: Rolling narrative summary injected at intervals to preserve long-term memory across long chats.
   * **`hidden_state`**: Secret parameters (e.g., hidden traps, NPC trust levels) visible only to the LLM for organic storytelling.
4. **Turn Key Tracking & Branching Isolation**: Every turn execution is assigned a **Turn Key** derived from the session ID and timestamp, embedded into assistant replies (`[proxy: session=... turn=...]`). When a user retries or swipes, RACHEL inspects the prior turn key to load the exact state before that turn occurred, isolating conversation branches.

---

## Problems RACHEL Won't Solve

To keep RACHEL lightweight, fast, and drop-in compatible, the following features are intentionally out of scope:

1. **Client-Side UI & Visual Rendering**: RACHEL is a backend proxy server, not a front-end chat application. It does not render character sheets, visual inventory grids, or interactive battle maps (UI rendering remains the responsibility of clients like JanitorAI or SillyTavern).
2. **Anti-Cheat & Strict Rule Enforcement**: RACHEL does not act as an anti-tamper referee. If a user edits their past prompt to claim they found 1,000 gold or ignores a GM narrative penalty, RACHEL respects client-side prompt authority rather than enforcing rigid anti-cheat locks.
3. **Hardcoded Game Rulebooks & Stat Calculators**: RACHEL does not ship with built-in D&D 5e/Pathfinder rulebooks, spell databases, or monster manuals out of the box. All game rules and formulas are defined dynamically by the character card author via system prompts.
4. **Long-Term Knowledge Retrieval (RAG) Beyond Chat Context**: RACHEL does not perform web scraping, vector database embeddings, or perpetual external world-building lookups outside the scope of the active session state and message history.

---

## RACHEL's Assumptions and Design Philosophies

To support external chat clients seamlessly, RACHEL is engineered around four core principles:

### 1. The Client-Side is the Ground Truth (Best-Effort State Rehydration)
* **Philosophy**: RACHEL cannot control client behavior (message edits, deletions, or chat reloads). Therefore, RACHEL's local database is treated as a *cache*, not the absolute source of truth.
* **Assumption**: Any game state needed by RACHEL is derivable or re-constructible from the `messages` array payload sent by the client. If the database is wiped, RACHEL performs a "cold-start" rehydration to rebuild state history from chat history alone.

### 2. Purity of Conversation Paths (Turn Key Isolation)
* **Philosophy**: Roleplay is non-linear; users branch conversations via retries and swipes. The game state must stay pure to each branch.
* **Assumption**: Every turn execution is identified by a **Turn Key** (a hash of the session ID + timestamp embedded in `[proxy: session=... turn=...]`). Because state is indexed by this Turn Key and prior turn keys are read from history, retrying or branching at Turn X loads the exact state prior to that turn without corrupting other branches.

### 3. Client Compatibility and Zero-Configuration Session Resolution
* **Philosophy**: RACHEL should be a drop-in replacement for standard OpenAI/OpenRouter completions APIs without forcing chat clients to add custom API headers or specs.
* **Assumption**: If a chat client does not explicitly pass a session identifier via the URL or query parameters, RACHEL automatically resolves it using a 4-level hierarchy (explicit path/query $\rightarrow$ OOC `[session: name]` tag $\rightarrow$ previous `[proxy: session=...]` annotation $\rightarrow$ system prompt suffix hash + persona username).

### 4. Sandboxed Safety (Deterministic Execution Boundaries)
* **Philosophy**: Giving LLMs code execution capabilities must be completely safe, lightweight, and deterministic.
* **Assumption**: The LLM's scripts are purely computational. The code execution environment (sandbox) is restricted, local, has no network access, and is bound by a strict wall-clock timeout (default 8 seconds) to prevent infinite loops, hangs, or resource exhaustion.
