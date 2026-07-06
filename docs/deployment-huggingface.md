# Deploying the RPG Agent to Hugging Face Spaces

This guide will walk you through deploying your own RPG Agent proxy to Hugging Face Spaces for free. You don't need any coding experience to follow these steps.

---

## Prerequisites
Before you start, make sure you have:
1. **A Hugging Face Account**: If you don't have one, sign up for free at [huggingface.co](https://huggingface.co/).
2. **An OpenRouter API Key**: This is required for the agent to use AI models. You can get one from the [OpenRouter Dashboard](https://openrouter.ai/keys).

---

## Step 1: Duplicate the Space template
Hugging Face allows you to "duplicate" an existing template so that it runs in your own account.

1. Go to the Hugging Face Space page where the template is hosted.
2. Click the **three vertical dots (⋮)** in the top-right corner of the page.
3. Select **Duplicate this Space** from the menu.
4. Fill in the options on the duplication screen:
   * **Owner**: Select your username.
   * **Space name**: You can leave the default name or choose something else (like `rpg-agent-proxy`).
   * **Visibility**: We highly recommend setting this to **Private** to ensure only you can access your proxy.
   * **Space Secrets**: You will see fields where you can add "Secrets" (these are settings that are hidden from the public).

---

## Step 2: Add your OpenRouter API Key
On the duplication screen (or under the **Settings** tab of your duplicated Space later):

1. Find the **Secrets** section.
2. Click **Add new secret** (if they are not already prompted).
3. Set the name of the secret to **`OPENROUTER_API_KEY`** and paste your OpenRouter key as the value.
4. *(Optional)* Set a custom password for your proxy: Add a second secret named **`RPG_AGENT_PROXY_KEY`** and set the value to a password of your choice (like `my-rpg-password`). If you don't set this, the system will generate a random one for you.
5. Click **Duplicate Space** (or **Save**).

Hugging Face will now start building your Space. This takes about 2–3 minutes. Once it's finished, you'll see a green **Running** badge at the top of the page.

---

## Step 3: Get your Proxy API Key
If you didn't set a custom `RPG_AGENT_PROXY_KEY` in Step 2, you need to find the password the system generated for you:

1. Go to your Space and click the **Logs** tab (usually found near the top center or under the settings).
2. Look at the startup text in the black logs console.
3. You will see a box that looks like this:
   ```text
   ============================================================
     Proxy API Key (use as Bearer token):
     <YOUR_GENERATED_API_KEY>
   ============================================================
   ```
4. Copy this key (it is your password for JanitorAI).

---

## Step 4: Configure JanitorAI
Now you need to point JanitorAI (or your chat client) to your new cloud proxy.

1. Find the **Direct URL** of your Space. It will look like this:
   `https://<your-username>-<space-name>.hf.space`
   *(You can find this URL by clicking the "Embed this Space" button or by copying the link format of the running app page).*
2. Open JanitorAI, go to the **API Settings** panel:
   * **API URL**: Paste `https://<your-username>-<space-name>.hf.space/v1` (make sure to add `/v1` at the end).
   * **API Key**: Paste the **Proxy API Key** (either the custom one you set in Step 2, or the generated one you copied from the logs in Step 3).
3. Click **Save Settings**.

You're done! Your chat client is now securely routed through your personal RPG Agent proxy on Hugging Face.
