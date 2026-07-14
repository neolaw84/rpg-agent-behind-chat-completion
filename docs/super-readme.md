# RPG Agent Behind Chat Completion (RAB-CC) — Super README & Knowledge Base

This is a comprehensive, self-contained knowledge base and guide for setting up, configuring, and managing **RAB-CC** (RPG Agent Behind Chat Completion). It is designed to be fully readable by digital assistant chatbots and human administrators alike, providing all project parameters, design schemas, and deployment instructions in a single file.

---

## 📖 Quick Links & Project Resources
* **GitHub Repository:** [github.com/neolaw84/rpg-agent-behind-chat-completion](https://github.com/neolaw84/rpg-agent-behind-chat-completion)
* **Hugging Face Space (To Duplicate):** [huggingface.co/spaces/edward-law/rab-cc?duplicate=true](https://huggingface.co/spaces/edward-law/rab-cc?duplicate=true)
* **Setup & Hugging Face Video Walkthrough:** [YouTube Tutorial (https://youtu.be/u0kH7QzaXPY?si=e_yhM5XGRtUVUNZ8)](https://youtu.be/u0kH7QzaXPY?si=e_yhM5XGRtUVUNZ8)

---

## 🎲 What is RAB-CC?

**RAB-CC** is a stateful proxy application built using **FastAPI** and **LangGraph** that sits between front-end chat clients (such as JanitorAI or SillyTavern) and completion providers (such as **OpenRouter**). It intercepts LLM calls to execute game mechanics, run dice rolls, track character sheets, and maintain a robust narrative memory loop.

Standard LLMs suffer from severe limitations when running text-based RPGs (like D&D or custom campaigns). RAB-CC addresses these problems directly:

| Feature / Issue | Standard LLM Behavior | RAB-CC Solution |
| :--- | :--- | :--- |
| **Dice Rolling** | Predicts/hallucinates roll numbers to suit cooperative story narrative (biased/fudged results). | Real, programmatic random number generator (RNG) tools executed behind the scenes. |
| **Calculations / Math** | Frequently hallucinates calculations (modifiers, status durations, inventory weight). | Isolated **Python Sandbox engine** running math/combat code via Python / JavaScript V8 isolates. |
| **Story Progression** | Forgets older details, loses track of inventory items, slips secret facts to players. | Multi-dimensional **Session State** split into State, Plan, Summary, and Hidden State layers. |
| **Message Retries / Edits** | Breaks stateful logic, resulting in duplicate combat damage, lost turns, or state corruption. | Cryptographic **Turn Key** system that matches the conversation branch structure to restore appropriate state. |

---

## 🚀 Cloud Deployment Guides

### 1. Hugging Face Spaces (Free CPU Hosting)

Hugging Face Spaces allows you to run your own private instance of the proxy for free. Follow these steps:

1. **Duplicate the Template:** Go to the [Hugging Face Space Template](https://huggingface.co/spaces/edward-law/rab-cc?duplicate=true).
2. **Configure General Space Options:**
   * **Owner:** Select your Hugging Face username.
   * **Space Name:** Choose a name (e.g., `rab-cc-proxy`).
   * **Visibility:** **IMPORTANT: Set this to Private** to prevent others from using your OpenRouter API credits.
3. **Set Secrets (Variables):**
   * Go to the **Secrets** section (or the **Settings** tab of the space after creation).
   * **`OPENROUTER_API_KEY`** (Required): Enter your OpenRouter API Key. You can get one from the [OpenRouter Dashboard](https://openrouter.ai/keys).
   * **`RPG_AGENT_PROXY_KEY`** (Required for Hugging Face): Enter your Hugging Face Access Token/Key. (While this is optional for local setup, it is **required** for Hugging Face Spaces to authenticate requests and secure your proxy). To generate a token:
     1. Go to your Hugging Face account **Settings** -> **Access Tokens**.
     2. Click **New Token**, configure a token (Read permission is sufficient), and click **Generate token**.
     3. Copy and paste this token into the `RPG_AGENT_PROXY_KEY` secret.
4. **Mount a Hugging Face Storage Bucket for State Persistence:**
   > [!IMPORTANT]
   > Hugging Face Spaces have ephemeral storage by default. When the Space goes to sleep or restarts, all local files (including session states, character inventories, and summaries) will be wiped out.
   > 
   > To prevent data loss, users must create a **Hugging Face Storage Bucket** (non-versioned, S3-compatible persistent storage) and mount it to the Space at `/app/data/states`.
   > 
   > **How to create and mount the storage bucket:**
   > 1. Go to **[huggingface.co/new-bucket](https://huggingface.co/new-bucket)**.
   > 2. Select your account as the **Owner**, enter a name like `rab-cc-states`, set the visibility to **Private** (recommended), and click **Create bucket**.
   > 3. Navigate to the **Settings** tab of your duplicated Space.
   > 4. Scroll down to the **Storage Buckets** section and click to add/attach a bucket.
   > 5. Select your newly created bucket (e.g. `<username>/rab-cc-states`).
   > 6. Set the **Mount Path** to `/app/data/states` (which maps directly to where the proxy writes session files).
   > 7. Configure the **Access Mode** to **Read-Write** (required so the proxy can write and update your save states).
   > 8. Save the configuration.

5. **Start the Space:** Click **Duplicate Space** (or **Save**). The build process will take 2–3 minutes. Once completed, a green **Running** badge will appear at the top.
6. **Obtain Your API Key:**
   * Your API key/Bearer token for the proxy is the **Hugging Face Access Token** you pasted into the `RPG_AGENT_PROXY_KEY` secret field in Step 3.
7. **Configure Your Client (e.g. JanitorAI):**
   * Get the Direct URL of your Space: `https://<your-username>-<space-name>.hf.space`.
   * Set the API URL to: `https://<your-username>-<space-name>.hf.space/v1` (be sure to append `/v1`).
   * Paste your Hugging Face Access Token (used as the `RPG_AGENT_PROXY_KEY`) into the client's API Key/Password field.

---

### 2. Railway.com

Railway is a quick cloud hosting platform that links directly to GitHub:

1. **Deploy Repository:** Click the deploy button in the GitHub repository README, or go to the Railway Dashboard, select **New Project** -> **Deploy from GitHub repo**, and choose `rpg-agent-behind-chat-completion`.
2. **Add Environment Variables:**
   * In the **Variables** tab of the Railway service card, add:
     * `OPENROUTER_API_KEY`: *Your OpenRouter API Key*.
     * `RPG_AGENT_PROXY_KEY` (Optional): *Your custom proxy access key*.
3. **Obtain the Auto-Generated Key:** If you did not supply a custom `RPG_AGENT_PROXY_KEY`, check the **Logs** tab in Railway to view the auto-generated key:
   ```text
   ============================================================
     Proxy API Key (use as Bearer token):
     <YOUR_GENERATED_API_KEY>
   ============================================================
   ```
4. **Generate Public Domain:**
   * Go to the **Settings** tab.
   * Scroll down to **Networking** and click **Generate Domain**. Railway will create a domain (e.g., `https://rpg-agent-behind-chat-completion-production.up.railway.app`).
5. **Configure Chat Client:**
   * API URL: `https://<your-railway-domain>.up.railway.app/v1` (with `/v1` at the end).
   * API Key: The Proxy API Key (custom or auto-generated).

---

## 💻 Local setup & Development

If you prefer to run the proxy on your local machine, follow these commands.

### Prerequisites
* **Python >= 3.12**
* Unix-like shell environment (Linux, macOS, WSL)
* OpenRouter API key

### 1. Bootstrapping Environment
Run these commands from the root of the repository:
```bash
# 1. Create a virtual environment named "venv"
python3.12 -m venv venv

# 2. Activate the virtual environment
source venv/bin/activate

# 3. Install packages in editable mode with development dependencies
pip install -e ".[dev]"
```

### 2. Configuration Setup
Copy `.env.example` to `.env` and set the required variables:
```bash
cp .env.example .env
```
Open `.env` in a text editor and configure:
* `OPENROUTER_API_KEY`: Secret API key for OpenRouter (required).
* `RPG_AGENT_PROXY_KEY`: Custom password for clients (optional).
* `OPENROUTER_BASE_URL`: Completion endpoint URL override (optional).
* `DEFAULT_MODEL`: Default model fallback (optional, defaults to `google/gemini-3.5-flash`).
* `RPG_AGENT_INCLUDE_REASONING`: Set to `true` to pass through model planning/reasoning blocks (optional).

### 3. Validating the Installation
Run the test suite to verify the setup:
```bash
venv/bin/pytest
```
*Expected result: All tests pass in less than 3 seconds.*

### 4. Running the Proxy Server
```bash
PYTHONPATH=src uvicorn rpg_agent.proxy:app --host 0.0.0.0 --port 8000 --reload
```
* The local API is now accessible at `http://localhost:8000/v1/chat/completions`.
* Opening `http://localhost:8000/` in a browser loads the SPA Status Dashboard.
* Every payload received by the proxy is saved into `data/example-janitorai-payload.md` for inspection.

---

## 🛠️ Detailed Configuration Guide (`configs.yaml`)

The primary configurations of the RPG proxy reside in `configs.yaml`.

```yaml
state:
  num_states_to_track: 32
  storage_dir: "data/states"

sandbox:
  timeout_seconds: 8.0

langgraph:
  max_iterations: 6

llm:
  base_url: "https://openrouter.ai/api/v1/chat/completions"
  default_model: "google/gemini-3.5-flash"
  include_reasoning: true
  reasoning_format: "Open-Router"

orchestration:
  plan_summary_gap: 1
  plan:
    trigger_type: "periodic"
    interval_turns: 8
    trigger_probability: 0.10
    bundle_llm: true
    llm:
      model: "google/gemini-3.5-flash"
      base_url: "https://openrouter.ai/api/v1/chat/completions"
      include_reasoning: true
      temperature: 0.9
  summary:
    trigger_type: "periodic"
    interval_turns: 8
    trigger_probability: 0.10
    bundle_llm: true
    summary_target_words: 200
    llm:
      model: "google/gemini-3.5-flash"
      base_url: "https://openrouter.ai/api/v1/chat/completions"
      include_reasoning: true
      temperature: 0.9
```

### Configuration Parameters Explained:

#### 1. Session State (`state`)
* **`num_states_to_track`** *(Integer, Default: `32`)*: The size of the rolling state cache (equivalent to **"autosave slots"**). If you edit messages or retry actions, the proxy can restore the campaign state perfectly if the event is within the last 32 turns.
* **`storage_dir`** *(String, Default: `"data/states"`)*: The directory where state JSON files are saved.

#### 2. Sandbox Executions (`sandbox`)
* **`timeout_seconds`** *(Float, Default: `8.0`)*: The maximum time allowed for executing Python math or rules scripts before timing out.

#### 3. Loop Orchestration (`langgraph`)
* **`max_iterations`** *(Integer, Default: `6`)*: The maximum round-trips (tool calling runs) the LLM can make in a single turn. Caps loop execution to prevent stuck prompts from draining API balances.

#### 4. Main AI Model Settings (`llm`)
* **`base_url`** *(String, Default: `"https://openrouter.ai/api/v1/chat/completions"`)*: Target URL of the completion API.
* **`default_model`** *(String, Default: `"google/gemini-3.5-flash"`)*: The model requested if the front-end client does not specify one.
* **`include_reasoning`** *(Boolean, Default: `true`)*: Enables deep-thinking and reasoning logic collection from models that support it (e.g., DeepSeek-R1, Gemini 2.0/3.5).
* **`reasoning_format`** *(String, Default: `"Open-Router"`)*: The output wrapper format for reasoning thoughts. Supported options: `Open-Router`, `OpenAI`, `Gemini`, `Anthropic`, `X.AI`, `Z.AI`, `DeepSeek`, or `custom` (custom configuration utilizes additional fields e.g., `reasoning_payload`).

#### 5. Story Pacing & Memory updates (`orchestration`)
Defines the automatic planning and summarization triggers. Planning keeps a record of story goals, and summarization provides a compressed rolling history.

* **`plan_summary_gap`** *(Integer, Default: `1`)*: Turn offset configuration for scheduling processes.
* **`plan` and `summary` Sections:**
  * **`trigger_type`** *(String)*: One of:
    * `"periodic"`: Triggers every `interval_turns` turns.
    * `"probabilistic"`: Triggers randomly using `trigger_probability` (e.g., `0.10` represents a 10% chance per turn).
    * `"disabled"`: Turns off the process.
  * **`interval_turns`** *(Integer, Default: `8`)*: Firing frequency when using `periodic` trigger.
  * **`trigger_probability`** *(Float, Default: `0.10`)*: Probability of firing when using `probabilistic` trigger.
  * **`bundle_llm`** *(Boolean, Default: `true`)*: If set to `true`, the plan/summary updates are executed inline as part of the main roleplay call (saving time and money). If `false`, updates run as isolated operations in the background utilizing the dedicated nested `llm` settings.
  * **`summary_target_words`** *(Integer, Default: `200`)*: Word length limit for the narrative summary text.
  * **`llm.model`**, **`llm.base_url`**, **`llm.temperature`** *(Defaults: `google/gemini-3.5-flash`, `0.9`)*: Configuration overrides used when `bundle_llm` is `false`.

---

## 🔀 Sessions, State & Turn Key Mechanics

Understanding the internal session and turn logic is key to understanding how RAB-CC handles retries, message edits, and non-linear paths.

### The 4-Element State Structure
A session file stores four distinct layers:
1. **`state`**: User-defined character metrics (gold, HP, modifiers, inventories, attributes). This block is mutated by sandboxed code calls.
2. **`plan`**: Upcoming story steps, objectives, and milestones monitored by the planning agent.
3. **`summary`**: A rolling story summary that grows as the conversation goes on, preserving older events without blowing up the context window.
4. **`hidden_state`**: System parameters hidden from the user but read by the AI (e.g., status effects, event counters, hidden NPC relationships).

### Session ID Resolution Hierarchy
When a request arrives, the proxy resolves the `session_id` using a 3-level fallback hierarchy:

```mermaid
graph TD
    A[Incoming Request] --> B{Explicit Session ID in URL or query parameter?}
    B -- Yes --> C[Use Explicit Session ID]
    B -- No --> D{OOC Tag [session: name] in message history?}
    D -- Yes --> E[Use Tag Name as Session ID]
    D -- No --> F[Fallback: MD5 Hash of system prompt suffix + Persona Username]
```

1. **Explicit ID (Highest):** Passed via path `/v1/{session_id}/chat/completions` or query string `?session_id=`.
2. **OOC Tag (Medium):** Searched newest-to-oldest in messages for the pattern `[session: session_name_here]`.
3. **Implicit Hash (Lowest):** MD5 hash calculated from the last 300 characters of the system prompt concatenated with the username/character prefix of the user message.

### Turn Key Cryptographic Isolation
Front-end clients allow users to swipe, retry, or edit previous messages. To prevent the state from becoming corrupted or double-counting, every event is assigned a **Turn Key**:

$$\text{turn\_key} = \text{SHA-256}[:24]\big(\text{session\_id} + \text{"\textbackslash 0"} + \text{last\_user\_message} + \text{"\textbackslash 0"} + \text{penultimate\_assistant\_message}\big)$$

* State data is indexed by this Turn Key.
* If a retry occurs, the Turn Key remains the same, reloading the exact state before that turn.
* If the user branches the chat (edits an older message), a new Turn Key is generated, isolating the new branch state from the old branch.

To verify synchronization, the active session ID and Turn Key are injected directly into the response text block:
```text
[proxy: session=my-session-id turn=abc123xyz789...]
```

---

## 🔌 Administrative API Endpoints (CRUD)

Admin endpoints allow managing states manually. All admin requests require authentication using your `RPG_AGENT_PROXY_KEY` via Bearer token:

`Authorization: Bearer <your-proxy-api-key>`

### 1. List Active Sessions
Lists all active session files stored on disk.
* **Method:** `GET`
* **Endpoint:** `/v1/sessions`
* **Response:**
  ```json
  {
    "sessions": ["campaign_1", "shan-yu-solo", "test-user"],
    "count": 3
  }
  ```

### 2. Get Session Details
Retrieves the complete state structure and turn history for a single session.
* **Method:** `GET`
* **Endpoint:** `/v1/sessions/{session_id}`
* **Response:**
  ```json
  {
    "session_id": "campaign_1",
    "current_state": {
      "state": {
        "gold": 100,
        "hp": 95
      },
      "plan": ["find dungeon key"],
      "summary": "The party entered the dungeon.",
      "hidden_state": {
        "poison_turns": 3
      }
    },
    "turn_count": 1,
    "turns": [
      {
        "turn_key": "abc123xyz...",
        "before": {
          "state": {},
          "plan": [],
          "summary": "",
          "hidden_state": {}
        },
        "after": {
          "state": {"gold": 100, "hp": 95},
          "plan": ["find dungeon key"],
          "summary": "The party entered the dungeon.",
          "hidden_state": {"poison_turns": 3}
        }
      }
    ]
  }
  ```

### 3. Reset Session History
Clears a session's turn history while keeping the session file intact.
* **Method:** `POST`
* **Endpoint:** `/v1/sessions/{session_id}/reset`
* **Response:**
  ```json
  {
    "status": "ok",
    "message": "Session campaign_1 has been reset."
  }
  ```

### 4. Delete Session
Deletes the session state file from disk. The next turn will start from a cold start.
* **Method:** `DELETE`
* **Endpoint:** `/v1/sessions/{session_id}`
* **Response:**
  ```json
  {
    "status": "ok",
    "message": "Session campaign_1 deleted."
  }
  ```
