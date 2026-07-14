# Hosting Alternatives Research: RPG Agent Proxy Service (RAB-CC)

This document provides a research report on where end-users can host the **RPG Agent Behind Chat Completion (RAB-CC)** proxy service themselves. Given that Hugging Face no longer provides free-tier Dockerfile space, this analysis identifies **5 free** and **5 paid value** hosting providers, fact-checked for **July 2026**.

---

## 🆓 5 Free Hosting Providers

These platforms allow users to host the proxy service for $0/month, though most impose resource limits or implement auto-sleep configurations.

### 1. Google Cloud Run (Free Tier)
*   **Pricing:** $0/month (Always Free quota).
*   **Resource Limits:** 180,000 vCPU-seconds/month, 360,000 GiB-seconds/month, 2 million requests/month, and 1 GB egress bandwidth (North America traffic).
*   **How it Works:** Users deploy the Docker image natively. When configured to scale to zero instances, it only consumes compute time when actively handling a request. This makes it highly likely to stay within the free limit for personal/hobby usage.
*   **Pros:** Native container support, highly reliable, scales to zero.
*   **Cons:** Requires linking a valid credit card for identity verification/billing activation; short cold-start latency on wake-up.

### 2. Oracle Cloud Infrastructure (OCI) Always Free
*   **Pricing:** $0/month.
*   **Resource Limits:** Up to 2 OCPUs and 12 GB RAM on Ampere A1 (Arm) (limits adjusted from 4/24 in June 2026), or 2 AMD micro instances (1 GB RAM). Includes 200 GB of free block/boot storage.
*   **How it Works:** Provides a fully functional, persistent virtual machine (VM) running Linux. Users install Docker and Docker Compose on the VM and run the proxy.
*   **Pros:** Persistent VM (no auto-sleep/cold starts), generous resources, full control.
*   **Cons:** Requires credit card registration, and Arm capacity in many regions is frequently exhausted, making instances difficult to provision.

### 3. Zeabur (Free Plan)
*   **Pricing:** $0/month.
*   **Resource Limits:** Dynamic CPU/RAM allocation.
*   **How it Works:** Connects to a GitHub repository containing the `Dockerfile` and builds/deploys the service automatically.
*   **Pros:** Very easy to use, no credit card required to start, automatic SSL.
*   **Cons:** Service automatically sleeps after a period of inactivity (resulting in cold-start delay on next call); does not include advanced backup or database log features.

### 4. Render (Free Web Services)
*   **Pricing:** $0/month.
*   **Resource Limits:** 512 MB RAM, 0.1 shared CPU, 750 free instance hours per month across the workspace.
*   **How it Works:** Automatically builds and runs the proxy using the repository's `Dockerfile`.
*   **Pros:** Polished developer interface, no credit card required for standard free services, Git-integration.
*   **Cons:** Automatically spins down after 15 minutes of inactivity (30-60 second cold start); free databases expire after 30 days.

### 5. Koyeb (Free Web Service)
*   **Pricing:** $0/month.
*   **Resource Limits:** 512 MB RAM, 0.1 vCPU, 2 GB SSD storage (limited to Washington, D.C. or Frankfurt regions).
*   **How it Works:** Deploys pre-built containers from registries (Docker Hub/GHCR) or directly from Git.
*   **Pros:** Easy deployment, fast setup, robust globally-distributed edge routing.
*   **Cons:** Automatically scales down to zero after 1 hour of inactivity; persistent volumes cannot be attached to free-tier instances.

> [!TIP]
> **Alternative Gradio SDK Trick:** Hugging Face Spaces still offers a free tier for Python-based SDKs (Gradio/Streamlit). Because Gradio runs on FastAPI/Uvicorn under the hood, users can launch the RAB-CC FastAPI app inside a free Gradio SDK space using `gr.mount_gradio_app()`, bypassing the Dockerfile space restriction.

---

## 💵 5 Paid Value Hosting Providers

These platforms are cost-effective alternatives for hosting persistent containers without the constraints of auto-sleep or severe resource caps.

### 1. Fly.io (Pay-As-You-Go / Micro-VMs)
*   **Pricing:** ~$2.02/month for a 24/7 running instance.
*   **Resource limits:** 256 MB RAM, shared CPU (1x). Volume storage costs $0.15/GB/month.
*   **How it Works:** Deploys the application as a lightweight Firecracker Micro-VM.
*   **Pros:** Extremely cheap for always-on containers, scales quickly, robust global network.
*   **Cons:** Strictly pay-as-you-go (no permanent free tier for new accounts); egress bandwidth is metered and charged.

### 2. DigitalOcean (Basic Droplets)
*   **Pricing:** Starts at $4.00/month (transitioned to per-second billing with a $0.01 minimum charge on Jan 1, 2026).
*   **Resource Limits:** 512 MB RAM, 1 vCPU, 10 GB SSD, 500 GB free data transfer.
*   **How it Works:** A standard Linux virtual machine where users manually install Docker.
*   **Pros:** Fully persistent SSD storage, predictable billing, 100% control, no sleeping.
*   **Cons:** Unmanaged VPS, meaning the user is responsible for OS updates, Docker setup, and security patching.

### 3. Hetzner Cloud (CX23)
*   **Pricing:** Starts at ~€5.49/month (excluding VAT) (prices updated on June 15, 2026).
*   **Resource Limits:** 2 vCPUs (Intel/AMD), robust RAM and NVMe SSD space.
*   **How it Works:** High-performance, unmanaged cloud VPS. Users set up Linux and Docker.
*   **Pros:** Industry-leading price-to-performance ratio, excellent CPU performance, highly reliable.
*   **Cons:** Unmanaged server; Europe-based data centers (with slight premiums for US/Singapore locations).

### 4. Contabo (Cloud VPS S)
*   **Pricing:** Starts at ~€4.40/month (~$4.95/month).
*   **Resource Limits:** Large allocations of RAM and CPU core counts compared to competition.
*   **How it Works:** Standard unmanaged virtual private server.
*   **Pros:** Extremely high resource limits per dollar, excellent for hosting multiple containers or databases.
*   **Cons:** No free trial; support response times can be variable; hardware performance can be inconsistent due to virtualization density.

### 5. Railway (Hobby Plan)
*   **Pricing:** Starts at $5.00/month (flat plan fee including $5.00 of usage credits).
*   **Resource Limits:** Usage-based billing per second on CPU, RAM, and bandwidth.
*   **How it Works:** Fully managed PaaS. Connects to GitHub, detects the Dockerfile, and builds/serves automatically.
*   **Pros:** Simplest developer experience, automatic SSL/domain generation, no server maintenance.
*   **Cons:** Variable billing based on exact second-by-second consumption.
