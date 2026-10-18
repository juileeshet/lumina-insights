# Lumina Insights

Lumina Insights is a data analytics web application that helps users explore datasets through automated analysis, statistical insights, and interactive visualizations.

## Features

- CSV and Excel data handling
- Automated data cleaning and analysis
- Interactive charts and visualizations
- KPI generation and statistical summaries
- Dataset querying and filtering
- Excel and PDF report export

## Tech Stack

- **Backend:** Python, Flask
- **Data Analysis:** Pandas, NumPy, SciPy
- **Visualization:** Plotly
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript, Bootstrap

## Getting Started

### Prerequisites

- Python 3.10 or later
- pip

### Installation

```bash
git clone https://github.com/juileeshet/lumina-insights.git
cd lumina-insights

python -m venv .venv
```

Activate the virtual environment on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies and start the application:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

## Project Structure

```text
lumina-insights/
├── app.py
├── database.py
├── index.html
├── requirements.txt
├── sample_sales.csv
├── uploads/
├── .gitignore
└── README.md
```
