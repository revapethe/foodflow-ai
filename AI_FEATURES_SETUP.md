# FoodFlow AI — Review Intelligence and Natural-Language SQL

These features extend the existing **red-and-white Streamlit cloud dashboard**. They require Snowflake analytics marts (`dbt build`) and an OpenAI API key. The features are **not** a RAG chatbot.

## Git Bash on Windows

```bash
source .venv/Scripts/activate
python -m pip install -r requirements-cloud.txt
python -m pytest -q
cp .env.example .env  # only if you do not already have a configured .env
```

Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL=gpt-4o-mini` in your local `.env`. Never commit `.env` or real credentials. Make sure AWS/Snowflake ingestion and `dbt build --profiles-dir .` succeeded first.

```bash
python -m streamlit run cloud/dashboard.py
```

Choose **💬 Review intelligence** to process 1–50 *new* reviews at a time and view their sentiments and recommendations. The app creates `FOODFLOW.ANALYTICS.AI_REVIEW_INSIGHTS` on first use. The Snowflake role must have CREATE TABLE and INSERT/MERGE permissions on this schema. Reviews are sent to OpenAI for processing; use only synthetic or appropriately approved data.

Choose **🧠 Ask in English** to ask a question and display the generated validated SQL and its results. **IMPORTANT:** Set `NL_SQL_READONLY_ROLE=FOODFLOW_READER` in `.env` and grant that role to the Snowflake login. Configure the role with SELECT access only to the approved analytics tables (and warehouse USAGE). Do **not** use ACCOUNTADMIN or any write-enabled role for the NL-to-SQL app. The code validates one SELECT statement, allowlists tables, caps results at 100, and sets a 15-second statement timeout; these are defense-in-depth measures, not a substitute for database permissions. The app switches to the configured read-only role before executing generated SQL. For production, use a separate read-only Snowflake login for this page. Avoid granting access to sensitive personal information.

## Scope and limitations

- AI features use OpenAI API and can incur charges.
- Review processing is incremental based on `REVIEW_ID` and does not reprocess changed text unless records are removed from the insights table.
- Generated SQL can still be semantically incorrect. Inspect query and results.
- The features have offline unit tests but require a configured Snowflake account for live integration testing.
- The existing Airflow DAG does not schedule review enrichment. The review enrichment is currently triggered manually from Streamlit.
