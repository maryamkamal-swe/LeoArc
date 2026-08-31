```markdown
# My 10x Solution - Maryam Kamal

## 1. What problem are you solving?
In Pakistan, high electricity tariffs combined with daily load shedding (power outages) make household utility bills unpredictable. Families struggle to calculate how much power their appliances consume during available hours and lack tailored advice on how to reduce expenses during peak tariff windows. 

This API turns hours of manual power calculations into an instant analysis, automatically adjusting running costs based on load-shedding hours and providing AI-generated savings recommendations.

## 2. How did you implement your solution?
The system is built as a single-file FastAPI backend with an SQLite database. Users register, authenticate, and manage their household appliances. The core logic calculates monthly kWh and total costs in PKR based on dynamic local utility tariffs.

### 5 Implemented Concepts:
1. **API Endpoints:** Structured FastAPI routes with Pydantic schemas[cite: 6].
2. **Database:** SQLite persistence storing users, appliances, and tariffs[cite: 6].
3. **Authentication:** JWT bearer tokens protecting sensitive endpoints[cite: 6].
4. **LLM Integration:** Google Gemini API (`gemini-2.0-flash`) generating personalized energy advice[cite: 6].
5. **Rate Limiting (Swap):** `slowapi` limiting AI requests to 5/minute to avoid API spam.

*Swap Reason: Caching was replaced with Rate Limiting because protecting the LLM endpoint from quota abuse was more critical for a free-tier setup.*

### Run Steps:
1. `pip install -r requirements.txt`
2. Configure `GEMINI_API_KEY` inside `.env`
3. `python seed.py`
4. `uvicorn main:app --reload`