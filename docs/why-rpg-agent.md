# Why Use the RPG Agent Proxy?

Text-based roleplaying games (RPGs) powered by Large Language Models (LLMs) are incredibly immersive, but standard LLMs suffer from severe limitations when running complex games. The RPG Agent Proxy bridges the gap between raw LLMs and traditional tabletop game mechanics (like D&D or custom systems).

Here is why this proxy exists and the problems it solves.

---

## 1. True, Tamper-Proof Dice Rolling (No More Hallucinated Rolls)
LLMs are text predictors. When you ask an LLM to "roll a d20," it doesn't actually roll a random number. Instead, it guesses a number that sounds likely based on its training data. This leads to:
* **Fudged Rolls**: LLMs tend to make rolls succeed or fail based on narrative bias (usually giving the player high rolls to be cooperative).
* **Repetitive Results**: LLMs are notoriously bad at generating true random distribution.

**The RPG Agent Solution**: The proxy intercept the request and gives the LLM access to actual, programmatic dice rolling tools. When the LLM decides to roll dice, the proxy runs a real random number generator behind the scenes. The LLM receives the real roll output and must narrate based on that result.

---

## 2. Perfect Mathematical Calculations (The Python Sandbox)
RPGs require math—calculating modifiers, armor class, damage reduction, attribute scaling, and inventory weight. LLMs are famously bad at math and will regularly hallucinate calculations (e.g., `17 + 4 - 2 = 21` on one turn, and `18` on the next).

**The RPG Agent Solution**: The proxy runs a secure **Python Code Sandbox**. If a character uses a complex spell or attacks with multiple modifiers, the LLM can write and execute a Python script to calculate the result. This ensures:
* Perfect math for combat calculations and stat modifications.
* Dynamic calculation of complex status effects or mechanics.

---

## 3. Persistent Character State & Inventory (FIFO State Store)
In standard roleplay chats, the LLM has to remember the player's character sheet, health, inventory, and location inside its context window. As the chat gets longer, the LLM starts to forget details, lose track of inventory, or resurrect dead enemies.

**The RPG Agent Solution**: The proxy maintains a structured **Session State**. Every time a turn occurs, it saves the current state (health, inventory, buffs) in a local JSON database. 
* On each turn, the state is injected into the LLM's prompt.
* If the LLM updates a stat (like taking 5 damage), the proxy saves the updated stat so it carries over to the next turn automatically.

---

## 4. Resilience to Retries and Message Edits
Chat clients like JanitorAI allow users to edit previous messages or hit "Retry" to get a different assistant response. For standard stateful APIs, this breaks the game state because the server thinks a new turn happened, leading to double-damage or lost turns.

**The RPG Agent Solution**: The proxy uses a cryptographic **Turn Key** system:
* Every distinct point in a conversation is assigned a unique hash based on the message history.
* The state is saved and indexed by this Turn Key.
* If a user hits "Retry," the proxy detects the duplicate Turn Key and reloads the exact state before that turn was made, allowing a clean retry without state corruption.

---

## Assumptions & Design Philosophies

To support external chat clients seamlessly, the RPG Agent proxy is engineered around several core assumptions and design guidelines:

### 1. The Client-Side is the Ground Truth (Best-Effort State Rehydration)
* **Philosophy**: The proxy cannot control client behavior. The user might edit messages, delete turns, or reload chat history. Therefore, the proxy's local database is treated as a *cache*, not the absolute source of truth.
* **Assumption**: Any game state needed by the proxy is always derivable or re-constructible from the `messages` array payload sent by the client. If the proxy database is wiped or fails to resolve a previous turn, it must be able to perform a "cold-start" rehydration to rebuild the state history from the chat history alone.

### 2. Purity of Conversation Paths (Turn Key Isolation)
* **Philosophy**: Roleplay is non-linear; users branch conversations via retries. The game state must stay pure to each branch.
* **Assumption**: Every unique point of a conversation is identified by a **Turn Key** (a cryptographic hash of the session ID + the last user message + the penultimate assistant response). Because state is indexed by this Turn Key, retrying or branching at Turn X does not corrupt or leak state into Branch Y.

### 3. Client Compatibility and Zero-Configuration Session Resolution
* **Philosophy**: The proxy should be a drop-in replacement for standard OpenAI/OpenRouter completions APIs without forcing chat clients to add custom API headers or specs.
* **Assumption**: If a chat client does not explicitly pass a session identifier via the URL or query parameters, the proxy will automatically resolve it using a 3-level hierarchy (scanning the latest message text for `[session: name]` tags, or falling back to a hash of the system prompt + persona username).

### 4. Sandboxed Safety (Deterministic Execution Boundaries)
* **Philosophy**: Giving LLMs code execution capabilities must be completely safe, lightweight, and deterministic.
* **Assumption**: The LLM's scripts are purely computational. The code execution environment (sandbox) is restricted, local, has no network access, and is bound by a strict wall-clock timeout (default 2 seconds) to prevent infinite loops, hangs, or resource exhaustion.

