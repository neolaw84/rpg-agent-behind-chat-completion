# Deploying the RPG Agent to Railway.com

This guide will walk you through deploying your own RPG Agent proxy to Railway.com. No coding experience or command-line usage is required.

---

## Prerequisites
Before you start, make sure you have:
1. **A GitHub Account**: Required to link your code. Sign up for free at [github.com](https://github.com/).
2. **A Railway Account**: Sign up at [railway.app](https://railway.app/) using your GitHub account.
3. **An OpenRouter API Key**: This is required for the agent to connect to AI models. You can get one from the [OpenRouter Dashboard](https://openrouter.ai/keys).

---

## Step 1: Deploy to Railway
Railway can deploy the code directly from GitHub with a few clicks.

1. Click the **Deploy on Railway** button in the repository's `README.md` file, or go directly to the Railway Dashboard.
2. If using the dashboard manually:
   * Click **New Project** in the top-right corner.
   * Select **Deploy from GitHub repo**.
   * Grant Railway access to your GitHub account if prompted, then search for and select the **`rpg-agent-behind-chat-completion`** repository.
3. Select **Deploy Now** to initiate the build process.

---

## Step 2: Configure Environment Variables
Before the proxy can start running, you need to add your API key settings.

1. Once the project is created, click on the service card in your Railway project canvas.
2. Go to the **Variables** tab at the top.
3. Click **New Variable** and add:
   * **Name**: `OPENROUTER_API_KEY`
   * **Value**: *Paste your OpenRouter API key here*
4. *(Optional)* If you want to use a custom password for your proxy, click **New Variable** again:
   * **Name**: `RPG_AGENT_PROXY_KEY`
   * **Value**: *Set this to any password/key of your choice* (e.g., `my-custom-proxy-password`). If you skip this, Railway will auto-generate a random key for you.
5. Click **Add** to save.

Railway will automatically restart and deploy your service with the new variables.

---

## Step 3: Get your Proxy API Key
If you did not define a custom `RPG_AGENT_PROXY_KEY` in Step 2, you need to find the password the system generated for you:

1. Click on the service card in your Railway dashboard.
2. Go to the **Logs** tab.
3. Look at the text output in the deployment logs.
4. You will see a box that looks like this:
   ```text
   ============================================================
     Proxy API Key (use as Bearer token):
     <YOUR_GENERATED_API_KEY>
   ============================================================
   ```
5. Copy this key (it is your password for JanitorAI).

---

## Step 4: Expose your App to the Public
To make the proxy reachable by JanitorAI, you need a public URL:

1. In your Railway service settings, go to the **Settings** tab.
2. Scroll down to the **Networking** section.
3. Click the **Generate Domain** button. Railway will create a public web address for your service, which looks like:
   `https://rpg-agent-behind-chat-completion-production.up.railway.app`

---

## Step 5: Configure JanitorAI
Now you need to link JanitorAI (or your chat client) to your new Railway cloud server.

1. Open JanitorAI, go to the **API Settings** panel:
   * **API URL**: Paste the public URL generated in Step 4, adding `/v1` to the end. For example:
     `https://rpg-agent-behind-chat-completion-production.up.railway.app/v1`
   * **API Key**: Paste the **Proxy API Key** (either the custom one you set in Step 2, or the generated one you copied from the logs in Step 3).
2. Click **Save Settings**.

You're done! Your chat client is now securely connected to your personal RPG Agent proxy hosted on Railway.
