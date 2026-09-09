# Screenshots — shot list

Referenced by the root `README.md`. Bring the stack up (`docker compose up
--build`) and run the demo `curl` block in *Using the API* first, so there is
real data on screen. Capture at ~1400 px wide, PNG, crop away browser chrome.

| file | capture |
|---|---|
| `swagger.png` | `http://localhost:8000/docs` — all six endpoints expanded (POST/GET `/cars`, PATCH/DELETE `/cars/{id}`, POST `/rentals`, POST `/rentals/{id}/end`). |
| `grafana.png` | `http://localhost:3000` → the **DriveNow** dashboard, after a few requests, so the fleet and request-rate panels show data. |
| `rabbitmq.png` | `http://localhost:15672` → Queues → **drivenow.event_logger** *detail* view: its binding to `drivenow.events` and the message-rate graph — not the overview page. |


