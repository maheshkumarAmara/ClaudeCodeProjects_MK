# Jira Dashboard

A lightweight web dashboard for tracking Jira projects, sprints, issues, and QA progress. Built with FastAPI and vanilla JavaScript.

## Features

- View projects and sprints
- Track issues by type and sprint
- QA tracking view
- Create subtasks and epic sign-off tasks

## Prerequisites

- Python 3.8+
- A Jira Cloud account with API access

## Setup

1. **Clone the repository**

   ```bash
   git clone <repo-url>
   cd jira-dashboard
   ```

2. **Create a virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # macOS/Linux
   venv\Scripts\activate           # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root:

   ```
   JIRA_URL=https://yourcompany.atlassian.net
   JIRA_EMAIL=your-email@company.com
   JIRA_API_TOKEN=your-api-token
   JIRA_PROJECT_KEY=YOUR_PROJECT
   ```

   Generate an API token at: https://id.atlassian.com/manage-profile/security/api-tokens

5. **Run the server**

   ```bash
   uvicorn main:app --reload
   ```

6. **Open the dashboard**

   Go to http://127.0.0.1:8000 in your browser.

## Project Structure

```
jira-dashboard/
├── main.py            # FastAPI app and API routes
├── config.py          # Environment variable loading
├── jira_client.py     # Jira API client
├── requirements.txt   # Python dependencies
├── templates/
│   └── index.html     # Dashboard HTML template
└── static/
    ├── script.js      # Frontend logic
    └── style.css      # Styles
```
