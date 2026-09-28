# Q-Hold demo application

Q-Hold is a Flask and SQLite demonstration app for quality-hold coordination, repair procedures, vehicle repair and independent VI inspection, production visibility, and sequential procedure approvals. Procedure repair instructions support basic rich-text formatting with server-side HTML sanitization. All bundled records and demo identities are fictional. The role selector is a prototype only; it is not authentication or production authorization.

## Run locally

Requirements: Python 3.10 or newer. `requirements.txt` lists the Flask dependency.

```powershell
.\run_qhold.bat
```

The launcher creates `.venv` when needed, installs dependencies from `requirements.txt`, and starts Flask. Open `http://127.0.0.1:5000`; keep the terminal window open while using the app and press Ctrl+C to stop it. You can also run the VS Code task **Q-Hold: start Flask server**. Do not use Live Server on a template under `qhold/templates`: Jinja templates require Flask to render their variables, links, and shared CSS/JavaScript. Opening the root `index.html` in a static server displays this startup guide only.

On first run the app initializes the SQLite schema and inserts demonstration records when the holds table is empty. The local database defaults to `qhold.db` in the project root, and uploaded procedure attachments default to the `uploads` folder.

For an isolated test run, `tests.py` creates a temporary database and upload directory automatically:

```powershell
python -m unittest -v tests
```

Set `SECRET_KEY` to a persistent random value for local multi-session use. `PORT`, `QHOLD_DATABASE_PATH`, and `QHOLD_UPLOAD_FOLDER` can be set to override the server port, SQLite file, and upload directory. Debug mode is disabled unless `FLASK_DEBUG=1` is explicitly set.

## Connecting production services

The persistence boundary is in `qhold/repositories/`; replace or adapt those repository implementations when connecting an enterprise database. Configure corporate identity and server-side role/permission mapping before exposing write workflows. Replace local attachment storage with controlled object storage, and add malware scanning, retention policy, audit controls, CSRF protection, and deployment-managed secrets. Do not use the demonstration role selector, local SQLite database, or demo records as organisational production controls or records.

Use only authorised Maruti Suzuki brand assets in the labelled placeholder area in the shared application header.
