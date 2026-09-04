# Meridian AML Copilot - Phase 0 Foundation

This is the initial engineering scaffold for the Meridian AML investigation copilot.

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd meridian
   ```

2. **Configure Environment:**
   Copy the example environment variables file to `.env`:
   ```bash
   cp .env.example .env
   ```
   (The placeholders in `.env.example` are sufficient for local development using `docker-compose.yml`)

3. **Start the Application:**
   Start the database and the FastAPI application using Docker Compose:
   ```bash
   docker compose up --build
   ```

4. **Verify Application Health (Success Case - HTTP 200):**
   In a new terminal, check the health endpoint:
   ```bash
   curl -i http://localhost:8000/health
   ```
   You should see `HTTP/1.1 200 OK` and `{"status":"ok","database":"connected"}`.

5. **Verify Database Failure Case (HTTP 503):**
   To observe the degraded state, stop the database service:
   ```bash
   docker compose stop db
   ```
   Then call the health endpoint again:
   ```bash
   curl -i http://localhost:8000/health
   ```
   You should see `HTTP/1.1 503 Service Unavailable` and `{"status":"degraded","database":"unavailable"}`.
