"""RAG QA evaluation harness: 180 questions across 6 documents.

Usage:
    python scripts/eval_qa.py                       # run all 180 questions
    python scripts/eval_qa.py --filter cv           # run one document (30 questions)
    python scripts/eval_qa.py --range 0 90          # run first 90 questions
    python scripts/eval_qa.py --retry-failed        # re-run only previously failed questions

Scoring:
    - Each expected answer is a list of facts, ';'-separated (all must match).
    - Within a fact, '|' separates alternatives (any one may match).
    - Normalization: case/punctuation-insensitive; currency/commas stripped;
      numbers compared with tolerance (sign-aware for negatives).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.router import RouterAgent  # noqa: E402
from src.vector_store.chroma import VectorStore  # noqa: E402

RESULT_FILE = Path(__file__).resolve().parent / "eval_results.json"

QUESTION_BANK: dict[str, list[dict]] = {
    "cv": [
        {"q": "What is the candidate's full name?", "a": "Devano Jonathan"},
        {"q": "What is the candidate's email address?", "a": "devanojo2@gmail.com"},
        {"q": "What is the candidate's phone number?", "a": "65049457"},
        {"q": "What is the street address on the CV?", "a": "9 Lung Wah Street"},
        {"q": "Which university is the candidate attending?", "a": "University of Hong Kong"},
        {"q": "What degree is the candidate pursuing?", "a": "Bachelor of Engineering in Data Science and Engineering"},
        {"q": "When did the candidate start at the University of Hong Kong?", "a": "Sep 2022"},
        {"q": "What award did the candidate win in the Bloomberg trading challenge?", "a": "2nd Runner-up"},
        {"q": "What is the candidate's current role at Archbridge Capital Partners?", "a": "AI Engineer"},
        {"q": "By what percentage was manual processing time reduced by the AI agents at Archbridge?", "a": "60%"},
        {"q": "Which company hosted the candidate's software placement internship?", "a": "Hitachi Rail"},
        {"q": "How many candidates were screened per cycle at Career Hackers?", "a": "3,000"},
        {"q": "Which student association did the candidate co-found at HKU?", "a": "HKU Data Science Association"},
        {"q": "How many members does the HKU Data Science Association have?", "a": "50+"},
        {"q": "What is the candidate's personal website?", "a": "devoob.site"},
        {"q": "When did the Archbridge AI Engineer role begin?", "a": "Apr 2026"},
        {"q": "How many automation opportunities were identified through workflow audits?", "a": "10+"},
        {"q": "Which serving framework hosted the quantised VLMs at Hitachi?", "a": "vLLM"},
        {"q": "Which OCR library was integrated in the vision pipeline?", "a": "EasyOCR"},
        {"q": "By how many hours was HR workload reduced per batch at Career Hackers?", "a": "100 hours"},
        {"q": "By what percentage was detection accuracy improved by fine-tuning?", "a": "30%"},
        {"q": "Which sentence embedding model was fine-tuned?", "a": "Sentence-BERT|SBERT"},
        {"q": "What was the cheating detection system built on?", "a": "speech-to-text"},
        {"q": "Which statistics topic is listed in the relevant coursework?", "a": "Linear Statistical Analysis|Probability & Statistics"},
        {"q": "Which global trading challenge is mentioned under honors?", "a": "Bloomberg's 2024 Global Trading Challenge"},
        {"q": "What scholarship was awarded via the Informatics Olympiad National Finals?", "a": "Indonesia Maju Scholar"},
        {"q": "Which relational database is listed under technical skills?", "a": "SQL|MySQL"},
        {"q": "What was reduced by automating VM provisioning at Hitachi?", "a": "testing lifecycle duration"},
        {"q": "Which BI visualization tool is listed in the skills section?", "a": "Tableau|Google Looker Studio"},
        {"q": "What type of agents does the candidate build that navigate professional tools?", "a": "autonomous agents"},
    ],
    "dr_yip": [
        {"q": "Who is the digital transformation proposal prepared for?", "a": "Dr. Yip, Tze Hung|Dr. Yip"},
        {"q": "Who prepared the proposal?", "a": "Devano Jonathan"},
        {"q": "Which venture studio prepared the proposal?", "a": "Jonathan Simpson & Co."},
        {"q": "What is the contact email in the proposal?", "a": "devano@jonathansimpson.co"},
        {"q": "How long is the phased rollout timeline?", "a": "3-month|3 months"},
        {"q": "What do traditional digital agencies focus on exclusively?", "a": "surface-level aesthetic changes"},
        {"q": "What is the name of Pillar 1?", "a": "Premium Digital Infrastructure & Advanced Omnichannel Visibility|Premium Digital Infrastructure"},
        {"q": "What is the name of Pillar 2?", "a": "High-Compliance Automated Patient Operations"},
        {"q": "What is the name of Pillar 3?", "a": "Clinical Intelligence & Advanced Operational Analytics"},
        {"q": "Which encryption standard is used for PII at rest?", "a": "AES-256"},
        {"q": "Which Hong Kong privacy ordinance does the proposal align with?", "a": "Personal Data (Privacy) Ordinance|PDPO"},
        {"q": "What does the Phase 0 engagement consist of?", "a": "1-Day Clinical Workflow & Data Audit|Clinical Workflow & Data Audit"},
        {"q": "How many days of hyper-care technical support are provided after deployment?", "a": "30 days"},
        {"q": "What type of practice is Dr. Yip's clinic?", "a": "Specialist Medical Practice & Aesthetic Clinic|aesthetic clinic"},
        {"q": "What two search channels form the Discovery Blindspot?", "a": "Traditional & Generative Search|traditional search"},
        {"q": "What is the name of the operational leak involving the 'uncompleted course'?", "a": "Multi-Session Package Churn"},
        {"q": "What type of assets suffer from idle time when booking is unoptimized?", "a": "clinical machinery|treatment rooms|high-value assets"},
        {"q": "Which month focuses on Automated Booking & Discovery Optimization?", "a": "Month 2"},
        {"q": "What does Month 3 deliver for the clinic?", "a": "de-identified data pipelines|intelligence & data optimization"},
        {"q": "What does the Intelligent Appointment Engine allow patients to do?", "a": "view real-time availability|request slots"},
        {"q": "Which two channels do the automated alerts use?", "a": "SMS and email"},
        {"q": "What does calendar synchronization completely eliminate?", "a": "administrative double-bookings"},
        {"q": "What does Patient Retention Analytics automatically track?", "a": "multi-session treatment cycles"},
        {"q": "What does No-Show Risk Modeling help optimize?", "a": "waitlists"},
        {"q": "What type of data do the operational dashboards run on?", "a": "de-identified data|de-identified|anonymized|clean operational logs"},
        {"q": "What guarantee does the Phase 0 audit carry?", "a": "zero-disruption"},
        {"q": "What is the final deliverable following the audit?", "a": "Clinical Intelligence Blueprint"},
        {"q": "Where is Dr. Yip's practice located?", "a": "Hong Kong"},
        {"q": "What compliance standard does the Medical Council requirement ensure?", "a": "Medical Council of Hong Kong's Guidelines|Medical Council of Hong Kong"},
        {"q": "What is the core inventory of a specialized aesthetic practice according to the proposal?", "a": "clinical time"},
    ],
    "enosis": [
        {"q": "What is the name of the venture in the pitch deck?", "a": "Enosis"},
        {"q": "Which competition track is Enosis submitted to?", "a": "Life Sciences & Healthcare"},
        {"q": "Quote the Enosis mantra verbatim.", "a": "We don't build the AI|we enable it|We don't build the AI—we enable it|We don't build the AI - we enable it"},
        {"q": "By what percentage is clinical friction reduced?", "a": "98%"},
        {"q": "What is the hard deadline for the eHealth+ Connectivity Support Scheme?", "a": "March 31, 2026|31 March 2026"},
        {"q": "How much is the monthly government subsidy per doctor?", "a": "HK$500|500"},
        {"q": "How many outpatient visits do private Western clinics handle annually?", "a": "18 million|18 Million"},
        {"q": "What is the total addressable market for GBA digital health IT?", "a": "HK$45.0 Billion|HK$45 Billion|45 billion"},
        {"q": "What is the SAM for EMR translation and SaaS?", "a": "HK$5.5 Billion|5.5 billion"},
        {"q": "What is the Year 3 SOM target?", "a": "HK$36.0 Million|HK$36 Million|36 million"},
        {"q": "What is the monthly price of the Core Translation package?", "a": "HK$1,500|1500"},
        {"q": "What is the monthly price of the Bento add-on?", "a": "HK$500|500"},
        {"q": "What is the target average contract value per month?", "a": "HK$2,000|2000"},
        {"q": "What seed round is Enosis seeking?", "a": "HK$10 million|HK$10,000,000|10 million"},
        {"q": "Which in-process vector database does Enosis integrate?", "a": "ZVec"},
        {"q": "When was the Electronic Health Record Sharing System (Amendment) Ordinance gazetted?", "a": "December 1, 2025|1 December 2025"},
        {"q": "What is the name of the government scheme that subsidizes clinics?", "a": "eHealth+ Connectivity Support Scheme"},
        {"q": "What does the Bronze Mark certification require?", "a": "50+ records synchronized|50 records"},
        {"q": "What does the Gold Mark certification require?", "a": "500+ records synchronized|500 records"},
        {"q": "What is the RAM footprint of the ZVec edge database?", "a": "64MB|64 MB"},
        {"q": "What is the ZVec local query capacity?", "a": "8,000+ QPS|8000"},
        {"q": "What is the migration cost for clinics adopting Enosis?", "a": "HK$0|zero"},
        {"q": "What is the implementation time per clinic?", "a": "15 minutes|under 15"},
        {"q": "What is the Year 3 target revenue?", "a": "HK$36.0 Million|36 million"},
        {"q": "How many citizens are served by the GBA hospital network?", "a": "86 Million|86 million"},
        {"q": "How many private clinics are in the Hong Kong target pool?", "a": "3,000+|3000"},
        {"q": "How many small-to-medium factories are in the GBA pool?", "a": "600,000+|600000"},
        {"q": "Who is the Lead AI Architect on the team?", "a": "Dr. Alan Lau"},
        {"q": "Who serves as GBA Regulatory Counsel?", "a": "Professor Sarah Tsang|Sarah Tsang"},
        {"q": "Which industrial standard does the Edge Agent map to in manufacturing?", "a": "OPC-UA"},
    ],
    "syllabus": [
        {"q": "What is the course code?", "a": "JMSC2043"},
        {"q": "What is the course title?", "a": "Health Communication"},
        {"q": "Who is the course instructor?", "a": "Junhan Chen"},
        {"q": "What is the instructor's email?", "a": "junhanch@hku.hk"},
        {"q": "When does the lecture take place?", "a": "Tue 1000-1150|Tuesday 10:00|10:00"},
        {"q": "What is the course venue?", "a": "EH102"},
        {"q": "How many weeks does the course schedule span?", "a": "13"},
        {"q": "Which week is Reading Week?", "a": "Week 7|7"},
        {"q": "What percentage of the grade is class participation?", "a": "20%"},
        {"q": "What percentage is the in-class quizzes?", "a": "10%"},
        {"q": "How many in-class quiz sessions are there?", "a": "two|2"},
        {"q": "What is the weight of the final written project report?", "a": "30%"},
        {"q": "When is the project proposal due?", "a": "Oct 11|October 11"},
        {"q": "When is the final group presentation?", "a": "Nov 24|November 24"},
        {"q": "What platform is used for assignment submission?", "a": "Moodle"},
        {"q": "What is the weight of the peer evaluation?", "a": "10%"},
        {"q": "What is the weight of the Health in the Media presentation?", "a": "15%"},
        {"q": "What is the late submission penalty per day?", "a": "10%"},
        {"q": "How long is the Health in the Media presentation?", "a": "5-minute|5 minutes"},
        {"q": "What is the page limit for the project proposal?", "a": "2 pages"},
        {"q": "What is the page limit for the final report?", "a": "8 pages"},
        {"q": "What font and size are required for the proposal and report?", "a": "12pt Times New Roman|Times New Roman"},
        {"q": "What is the instructor's office location?", "a": "Eliot Hall 209"},
        {"q": "Which theory is covered in Week 2?", "a": "Theory of Planned Behavior|Health Belief Model|Theory of Reasoned Action"},
        {"q": "What is the Week 9 topic?", "a": "Health Misinformation"},
        {"q": "What is the Week 11 topic?", "a": "Doctor-patient communication"},
        {"q": "What does Week 8 cover?", "a": "Fear Appeals and Social Norms"},
        {"q": "What letter grade corresponds to 96-100 points?", "a": "A+|A plus"},
        {"q": "What letter grade corresponds to 83-85 points?", "a": "B"},
        {"q": "What is the date of the Reading Week no-class week?", "a": "Oct 13|October 13"},
    ],
    "annual_report": [
        {"q": "What is the company name in the annual report?", "a": "PDF Solutions"},
        {"q": "Which fiscal year does the annual report cover?", "a": "2025|December 31, 2025"},
        {"q": "What were total revenues for 2025?", "a": "$219 million|219.0 million|219"},
        {"q": "What was the year-over-year revenue growth?", "a": "22%"},
        {"q": "What was platform revenue for 2025?", "a": "$181 million|181"},
        {"q": "What was volume-based revenue for 2025?", "a": "$38 million|38"},
        {"q": "What was recurring revenue for 2025?", "a": "$205 million|205"},
        {"q": "What was the GAAP gross margin?", "a": "72%"},
        {"q": "What was the non-GAAP gross margin?", "a": "76%"},
        {"q": "What was GAAP diluted EPS?", "a": "-0.02|$(0.02)|(0.02)"},
        {"q": "What was non-GAAP diluted EPS?", "a": "$0.94|0.94"},
        {"q": "What was the year-end backlog?", "a": "$254 million|254"},
        {"q": "Who is the Chief Executive Officer?", "a": "John K. Kibarian"},
        {"q": "What is the trading symbol for the company?", "a": "PDFS"},
        {"q": "In which city is the company headquartered?", "a": "Santa Clara"},
        {"q": "What was the largest acquisition completed in 2025?", "a": "secureWISE"},
        {"q": "What is secureWISE?", "a": "remote connectivity network|remote connectivity"},
        {"q": "Which two new Exensio modules were announced?", "a": "Exensio Scalable Analytics; Exensio Studio AI"},
        {"q": "What was non-GAAP diluted EPS in 2024?", "a": "$0.84|0.84"},
        {"q": "What is the projected size of the semiconductor industry before 2030?", "a": "$1 trillion|1 trillion"},
        {"q": "What percentage of analysis can be automated by AI at scale?", "a": "90%"},
        {"q": "Who is the partner for the Sapience MHe deployment?", "a": "SAP"},
        {"q": "How many DirectScan systems were shipped to production fab users?", "a": "2|two"},
        {"q": "What type of inspection tool is the eProbe?", "a": "electron beam|non-contact electron beam|e-beam"},
        {"q": "What were cash and cash equivalents at year-end 2025?", "a": "$42.2 million|42.2"},
        {"q": "When was the 2025 Users Conference and Analyst Day held?", "a": "December"},
        {"q": "What is the fiscal year end date?", "a": "December 31, 2025|31 December 2025"},
        {"q": "What is the par value of the common stock?", "a": "$0.00015|0.00015"},
        {"q": "What is the commission file number?", "a": "000-31311"},
        {"q": "What was the year-over-year growth of volume-based revenue?", "a": "70%"},
    ],
    "lifexp": [
        {"q": "What is the name of the product in the PRD?", "a": "LifeXP"},
        {"q": "What is the PRD version?", "a": "v1.0|1.0"},
        {"q": "What is the product vision of LifeXP?", "a": "sustainable feedback loops for lifelong growth"},
        {"q": "Which two independent systems make up the product?", "a": "Maintenance; Growth"},
        {"q": "What are the five design principles?", "a": "No pressure; No streaks; No punishment; No red notifications; No guilt"},
        {"q": "How many ways are there to record an experience?", "a": "two|2"},
        {"q": "What is Method A for recording?", "a": "Chat naturally|chat"},
        {"q": "What is Method B for recording?", "a": "Structured entry|Template"},
        {"q": "What do skills accumulate instead of points or XP?", "a": "evidence"},
        {"q": "What is the current milestone example for Japanese?", "a": "JLPT N4|N4"},
        {"q": "Which hour thresholds form the Japanese milestone ladder?", "a": "150; 400; 800; 1300"},
        {"q": "What one question should the homepage answer?", "a": "How has my life grown"},
        {"q": "What is the monetisation model?", "a": "Freemium|freemium"},
        {"q": "How many active skills does the free tier allow?", "a": "3"},
        {"q": "What is Stage 0 of the roadmap?", "a": "Prototype"},
        {"q": "What is Stage 1 of the roadmap?", "a": "MVP"},
        {"q": "What is the first feature listed for Stage 2?", "a": "Calendar integration"},
        {"q": "What is Prototype A?", "a": "Natural language parser"},
        {"q": "What must the AI never do?", "a": "invent experiences"},
        {"q": "What does AI do after a chat recording?", "a": "Extract activities; Suggest skills; Estimate duration; Recommend milestones; Suggest duplicate merges"},
        {"q": "What is the maintenance example about bedsheets?", "a": "12 days"},
        {"q": "What does the chat recording example produce for Japanese?", "a": "1.5 hours"},
        {"q": "What does Learning Mode recommend to users?", "a": "books|YouTube playlists|courses|roadmap"},
        {"q": "What does the dashboard show instead of tasks completed?", "a": "3 skills; 18 hours; 5 new experiences"},
        {"q": "Which premium feature allows adding records to past days?", "a": "Backdate"},
        {"q": "Which app philosophy does the long-term possibility compare to?", "a": "Obsidian"},
        {"q": "What is Prototype E?", "a": "AI pipeline|LLM extraction"},
        {"q": "What are the example stats for the Japanese skill?", "a": "327 hours; 42 experiences"},
        {"q": "How many potential users should be interviewed?", "a": "5"},
        {"q": "What internal description should be avoided for LifeXP?", "a": "habit tracker alternative|habit tracker"},
    ],
}

ALTERNATIVE_SEP = "|"
FACT_SEP = ";"

# Words that don't carry meaning for substring matching
_SKIP_WORDS = {
    "the", "a", "an", "of", "and", "or", "for", "in", "on", "to", "with",
    "what", "is", "are", "was", "were", "be", "by", "at", "as", "per",
    "billion", "million", "thousand", "hk", "usd", "dollars",
}

_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')
_WORD_RE = re.compile(r'[a-z0-9]+')


def normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip punctuation, unify separators."""
    text = text.lower()
    text = re.sub(r'[$€£¥,\s]', '', text)
    text = re.sub(r'[^a-z0-9.%]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _numbers(text: str) -> list[float]:
    # Strip commas/currency first so "1,500" parses as one number
    cleaned = re.sub(r'[,$]', '', text)
    return [float(m) for m in _NUM_RE.findall(cleaned)]


def _num_match(expected: float, actual_list: list[float]) -> bool:
    """Match a number with tolerance. Negative expected matches by magnitude
    (so the model can write $(0.02) or -$0.02 for a loss). Also accepts
    scale-equivalent forms (18 vs 18,000,000 vs 18 million) and
    country-code-prefixed numbers (852 65049457 vs 65049457)."""
    import math

    expected_mag = abs(expected)
    if expected_mag == 0:
        return 0.0 in actual_list
    for actual in actual_list:
        actual_mag = abs(actual)
        if actual_mag == 0:
            continue
        ratio = actual_mag / expected_mag
        if abs(ratio - 1.0) < 0.01:
            return True
        # Accept multiples of 1000 (thousand/million/billion) within 1%
        exponent = round(math.log(ratio, 1000))
        if -3 <= exponent <= 3 and abs(math.log(ratio, 1000) - exponent) < 0.01:
            return True
    return False


_MONTH_WORDS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec", "january", "february", "march", "april", "june",
    "july", "august", "september", "october", "november", "december",
}

# Unit abbreviations accepted as equivalent to their full forms
_UNIT_FORMS = {
    "mb": ["mb", "megabyte", "megabytes"],
    "gb": ["gb", "gigabyte", "gigabytes"],
    "km": ["km", "kilometer", "kilometers", "kilometre", "kilometres"],
    "h": ["h", "hr", "hrs", "hour", "hours"],
    "min": ["min", "mins", "minute", "minutes"],
    "sec": ["sec", "secs", "second", "seconds"],
    "kg": ["kg", "kilogram", "kilograms"],
    "wk": ["wk", "wks", "week", "weeks"],
}


def _word_ok(word: str, answer_norm: str) -> bool:
    """Word containment with light plural tolerance (activities/activity, hours/hour)."""
    if word in answer_norm:
        return True
    if word.endswith('ies') and word[:-3] + 'y' in answer_norm:
        return True
    if word.endswith('s') and word[:-1] in answer_norm:
        return True
    return False


def _fact_matches(fact: str, answer_norm: str, answer_numbers: list[float]) -> bool:
    """Check a single (alternative-free) fact against the answer."""
    fact_norm = normalize(fact)
    if not fact_norm:
        return True
    fact_lower = fact.lower()
    fact_numbers = _numbers(fact_lower)
    if fact_numbers:
        # Numeric facts: number must match; remaining words must appear
        if not any(_num_match(n, answer_numbers) for n in fact_numbers):
            return False
        words = [w for w in _WORD_RE.findall(fact_lower)
                 if w not in _SKIP_WORDS and not w.lstrip('-').isdigit()]
        if len(fact_numbers) >= 2:
            # Date-like facts: numbers disambiguate, drop month names
            words = [w for w in words if w not in _MONTH_WORDS]
        for word in words:
            # A word may carry a unit abbreviation (e.g. "64mb"); otherwise the
            # full word must appear (handles verb conjugation, e.g. "extract" in
            # "extracts", "estimates")
            base = word.lstrip('0123456789.')
            if base in _UNIT_FORMS:
                if not any(form in answer_norm for form in _UNIT_FORMS[base]):
                    return False
            elif not _word_ok(word, answer_norm):
                return False
        return True
    # Non-numeric facts: every significant word must appear in the answer
    words = [w for w in _WORD_RE.findall(fact_lower)
             if w not in _SKIP_WORDS and not w.lstrip('-').isdigit() and len(w) > 1]
    return all(_word_ok(w, answer_norm) for w in words)


def score_answer(expected: str, actual: str) -> bool:
    """Return True if the model answer satisfies all expected facts."""
    if not actual or not actual.strip():
        return False
    answer_norm = normalize(actual)
    answer_numbers = _numbers(actual)
    # Guard: model explicitly says it couldn't find the answer.
    # NOTE: "insufficient data" is intentionally NOT a blocker — factual answers
    # are paired with a boilerplate "RECOMMENDATION: Insufficient data" section.
    lowered = actual.lower()
    if any(phrase in lowered for phrase in (
        "not found in documents", "not present in", "don't have information",
        "cannot answer", "no relevant documents",
    )):
        return False
    for fact in expected.split(FACT_SEP):
        fact = fact.strip()
        if not fact:
            continue
        alternatives = [alt.strip() for alt in fact.split(ALTERNATIVE_SEP) if alt.strip()]
        if not any(_fact_matches(alt, answer_norm, answer_numbers) for alt in alternatives):
            return False
    return True


def build_questions(filters: list[str] | None = None) -> list[dict]:
    """Flatten the question bank into question dicts."""
    questions = []
    for doc_key, items in QUESTION_BANK.items():
        if filters and doc_key not in filters:
            continue
        for i, item in enumerate(items, 1):
            questions.append({
                "id": f"{doc_key}_{i}",
                "doc": doc_key,
                "query": item["q"],
                "expected": item["a"],
            })
    return questions


def load_previous_results() -> dict[str, bool] | None:
    if not RESULT_FILE.exists():
        return None
    try:
        data = json.loads(RESULT_FILE.read_text())
        return {q["id"]: q.get("passed", False) for q in data.get("questions", [])}
    except (json.JSONDecodeError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG QA evaluation harness")
    parser.add_argument("--filter", nargs="+", default=None,
                        help="Document keys to test (cv, dr_yip, enosis, syllabus, annual_report, lifexp)")
    parser.add_argument("--range", nargs=2, type=int, default=None, metavar=("START", "END"),
                        help="Question index range (0-based, end exclusive)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Only run questions that previously failed")
    args = parser.parse_args()

    questions = build_questions(args.filter)
    if args.range:
        questions = questions[args.range[0]:args.range[1]]
    if args.retry_failed:
        previous = load_previous_results()
        if previous is None:
            print("No previous results found; running all questions.")
        else:
            questions = [q for q in questions if not previous.get(q["id"], False)]
            print(f"Retrying {len(questions)} previously failed questions.")

    if not questions:
        print("No questions to run.")
        return 0

    print(f"Running {len(questions)} questions...\n")
    vector_store = VectorStore()
    router = RouterAgent(vector_store)

    results = []
    passed_count = 0
    total_llm_nodes = Counter()
    run_start = time.monotonic()
    for idx, question in enumerate(questions, 1):
        query = question["query"]
        q_start = time.monotonic()
        trace: list[dict] = []
        try:
            response = router.invoke(query)
            trace = response.metadata.get("trace", [])
            if response.metadata.get("error"):
                actual = f"ERROR: {response.result}"
            else:
                # Score against the structured result + citations
                try:
                    parsed = json.loads(response.result)
                    parts = [parsed.get("summary", "")]
                    parts.extend(parsed.get("risks", []))
                    parts.extend(parsed.get("opportunities", []))
                    parts.append(parsed.get("recommendation", ""))
                    actual = "\n".join(parts)
                except (json.JSONDecodeError, AttributeError):
                    actual = response.result
                actual = f"{actual}\n{' '.join(response.citations)}"
        except Exception as exc:  # noqa: BLE001
            actual = f"EXCEPTION: {exc}"
        latency_ms = round((time.monotonic() - q_start) * 1000)

        for entry in trace:
            total_llm_nodes[entry["node"]] += 1

        passed = score_answer(question["expected"], actual)
        passed_count += 1 if passed else 0
        status = "PASS" if passed else "FAIL"
        print(
            f"[{idx:>3}/{len(questions)}] {status} {question['id']}: "
            f"{query[:70]} ({latency_ms}ms)"
        )
        if not passed:
            print(f"    expected: {question['expected']}")
            print(f"    actual:   {actual[:220]}")

        results.append({
            "id": question["id"],
            "doc": question["doc"],
            "query": question["query"],
            "expected": question["expected"],
            "actual": actual,
            "passed": passed,
            "trace": trace,
            "latency_ms": latency_ms,
        })

    total = len(results)
    pct = 100.0 * passed_count / total if total else 0.0
    run_ms = round((time.monotonic() - run_start) * 1000)
    avg_ms = round(run_ms / total) if total else 0
    llm_nodes = ("classify", "answer", "verify", "wide_search")
    llm_calls = sum(total_llm_nodes.get(n, 0) for n in llm_nodes)
    print(f"\n=== RESULT: {passed_count}/{total} ({pct:.0f}%) ===")
    print(f"Total time: {run_ms}ms ({avg_ms}ms/question) | LLM nodes hit: {llm_calls} "
          f"({llm_calls / total:.1f} per question)")
    if total_llm_nodes:
        print(f"Node usage: {dict(total_llm_nodes)}")

    # Per-document breakdown
    by_doc: dict[str, list[bool]] = {}
    for r in results:
        by_doc.setdefault(r["doc"], []).append(r["passed"])
    for doc_key, passes in sorted(by_doc.items()):
        print(f"  {doc_key}: {sum(passes)}/{len(passes)}")

    # Persist results (merge with previous) + run metadata
    previous = load_previous_results() or {}
    merged = {**previous, **{r["id"]: r["passed"] for r in results}}
    all_questions = build_questions()
    persisted = [
        {
            "id": q["id"],
            "doc": q["doc"],
            "query": q["query"],
            "expected": q["expected"],
            "passed": merged.get(q["id"], False),
        }
        for q in all_questions
    ]
    # Attach actual output only for questions run this session
    by_id = {r["id"]: r for r in results}
    for entry in persisted:
        if entry["id"] in by_id:
            entry["actual"] = by_id[entry["id"]]["actual"]
            entry["trace"] = by_id[entry["id"]]["trace"]
            entry["latency_ms"] = by_id[entry["id"]]["latency_ms"]

    payload = {
        "meta": {
            "timestamp": datetime.now(UTC).isoformat(),
            "questions": total,
            "passed": passed_count,
            "pct": pct,
            "run_ms": run_ms,
            "avg_ms_per_question": avg_ms,
            "llm_node_calls": llm_calls,
            "node_usage": dict(total_llm_nodes),
        },
        "questions": persisted,
    }
    RESULT_FILE.write_text(json.dumps(payload, indent=2))
    print(f"\nResults saved to {RESULT_FILE}")
    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
