# API and Job Queue Documentation

This document outlines the expected webhook payloads from Telegram and the format of the jobs that are inserted into the `jobs` table in the database.

## Telegram Webhook Payloads

The Vercel endpoint at `/api/webhook` expects POST requests from Telegram containing a standard `Update` object. The structure of this object varies depending on the event that triggered it.

### Example: /start Command

```json
{
  "update_id": 10000,
  "message": {
    "message_id": 1365,
    "from": {
      "id": 123456789,
      "is_bot": false,
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe",
      "language_code": "en"
    },
    "chat": {
      "id": 123456789,
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe",
      "type": "private"
    },
    "date": 1587403632,
    "text": "/start",
    "entities": [{ "offset": 0, "length": 6, "type": "bot_command" }]
  }
}
```

### Example: Callback Query (Button Click)

```json
{
    "update_id": 10001,
    "callback_query": {
        "id": "1234567890123456789",
        "from": {
            "id": 123456789,
            "is_bot": false,
            "first_name": "John",
            "username": "johndoe"
        },
        "message": { ... },
        "chat_instance": "-1234567890123456789",
        "data": "my_account"
    }
}
```

### Example: Chat Join Request

```json
{
    "update_id": 10002,
    "chat_join_request": {
        "chat": {
            "id": -1001234567890,
            "title": "Test Group",
            "type": "supergroup"
        },
        "from": {
            "id": 987654321,
            "is_bot": false,
            "first_name": "Jane",
            "username": "janedoe"
        },
        "date": 1630000000
    }
}
```

## Job Queue Format (`jobs` table)

When a webhook is received, a new row is inserted into the `jobs` table with the following structure:

-   **`job_id`**: (BIGSERIAL, PK) A unique identifier for the job.
-   **`job_type`**: (VARCHAR) A string that indicates the type of job. This is used by the worker to route the job to the correct handler.
-   **`payload`**: (JSONB) The full JSON payload of the Telegram `Update` object.
-   **`status`**: (VARCHAR) The current status of the job. Can be one of `pending`, `processing`, `completed`, or `failed`.
-   **`retries`**: (INTEGER) The number of times the job has been attempted.
-   **`created_at`**: (TIMESTAMPTZ) The timestamp when the job was created.
-   **`updated_at`**: (TIMESTAMPTZ) The timestamp when the job was last updated.

### Job Types

-   **`process_telegram_update`**: A generic job type for all incoming Telegram updates. The worker inspects the payload to determine the specific action to take (e.g., if it's a `/start` command, a button click, etc.).
-   **`broadcast_message`**: A job type for sending a message to all active groups. The payload for this job would be different, e.g., `{"text": "Hello, world!"}`.