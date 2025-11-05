# Vercel App MVP

This project is the Minimum Viable Product (MVP) for a Telegram Bot System, designed to be deployed on Vercel with a background worker.

## Architecture

The MVP consists of two main components:

1.  **Vercel Ingress (`/api/webhook.py`)**: A serverless function that acts as the entry point for all Telegram webhooks. It validates incoming requests, queues them as jobs in a PostgreSQL database, and immediately returns a `200 OK` response.

2.  **Background Worker (`/worker/main.py`)**: A long-running process that polls the `jobs` table for new tasks. It processes these jobs asynchronously, handling all the core business logic such as user registration, point management, and group administration.

## Setup

### 1. Database

-   Create a new PostgreSQL database (e.g., using Supabase, as recommended in the MVP plan).
-   Run the `schema.sql` script to create the necessary tables.

### 2. Environment Variables

Create a `.env` file in the root of the project and add the following variables:

```
# Your Supabase/PostgreSQL connection string
DATABASE_URL="postgresql://user:password@host:port/database"

# Your main Telegram bot token from @BotFather
BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1uT0"

# (Optional) Telegram API credentials for Telethon
BOT_API_ID="1234567"
BOT_API_HASH="0123456789abcdef0123456789abcdef"
```

### 3. Vercel Deployment

-   Connect your Git repository to a new Vercel project.
-   Vercel will automatically detect the `vercel.json` file and configure the build and routes.
-   Add the `DATABASE_URL` and `BOT_TOKEN` as environment variables in the Vercel project settings.

### 4. Worker Deployment

-   Deploy the `/worker` directory to a service that supports long-running processes (e.g., Railway, Render).
-   Set the `DATABASE_URL` and `BOT_TOKEN` environment variables in the worker's deployment environment.
-   The worker is started by running `python worker/main.py`.

## Local Development

### Vercel Ingress

1.  Install the dependencies: `pip install -r vercel_app/requirements.txt`
2.  Set the environment variables.
3.  Run the Flask app: `python vercel_app/api/webhook.py`

### Worker

1.  Install the dependencies: `pip install -r worker/requirements.txt`
2.  Set the environment variables.
3.  Run the worker: `python worker/main.py`