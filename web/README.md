# Student Performance Intelligence Web Application

This folder contains the first web version of the project.

## Run
From the project root:

```bash
pip install -r requirements.txt
python web/app.py
```

Open `http://127.0.0.1:5000` in a browser.

## Demo accounts
- Teacher: `teacher` / `teacher123`
- Student: `ST0001` / `student123`

These credentials are for demonstration only. Change them before any real deployment.

## Current AI layer
The included assistants are a local prototype that uses the project's analytics data and predefined response logic. They demonstrate the AI-assistant workflow but are **not a connected generative AI model yet**. A later phase can connect an approved AI API/model while keeping role-based data access.
