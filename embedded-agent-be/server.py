from fastapi import FastAPI, HTTPException
import random
import logging
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, model_validator
import demo_history
import insights
import explain
from insights_types import Exchange

from agent import (
    InvalidPageData,
    LoanAskRequest,
    LoanSummaryRequest,
    TransactionsAskRequest,
    TransactionsSummaryRequest,
    generate_grounded_text,
    loan_context,
    transaction_context,
)

logger = logging.getLogger(__name__)


class ConversationRequest:
    @model_validator(mode="after")
    def bounded_conversation(self):
        if sum(len(item.question) + len(item.answer) for item in self.history) > 30000:
            raise ValueError("Conversation exceeds 30,000 characters; start a new conversation.")
        return self


class TransactionsConversationRequest(ConversationRequest, TransactionsAskRequest):
    history: list[Exchange] = Field(default_factory=list, max_length=10)


class LoanConversationRequest(ConversationRequest, LoanAskRequest):
    history: list[Exchange] = Field(default_factory=list, max_length=10)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for interview simplicity
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/assistant/config")
def assistant_config():
    return {"insights_enabled": insights.enabled()}


@app.post("/sections/explain")
def explain_section(request: explain.ExplainRequest):
    try:
        context = explain.build_context(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = explain.generate_explanation(context)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="The explanation is temporarily unavailable. Please try again.") from exc
    return {"section": request.section, **result.model_dump()}


@app.get("/credit/summary")
def credit_summary():
    current_score = random.randint(650, 850)
    previous_score = current_score + random.randint(-50, 50)
    change = current_score - previous_score
    last_refreshed = (datetime.now() - timedelta(hours=random.randint(1, 48))).isoformat()
    
    return {
        "score": current_score,
        "previous_score": previous_score,
        "change": change,
        "last_refreshed": last_refreshed
    }

@app.get("/credit/details")
def credit_details():
    return {
        "reasons":[
            "High credit utilization",
            "Late payment detected",
            "Recent hard inquiry"
        ],
        "breakdown": [
            {"label": "Payment History", "percent": 35, "color": "#22c55e"},
            {"label": "Credit Utilization", "percent": 30, "color": "#3b82f6"},
            {"label": "Credit History Length", "percent": 15, "color": "#f59e0b"},
            {"label": "Credit Mix", "percent": 10, "color": "#8b5cf6"},
            {"label": "New Credit", "percent": 10, "color": "#ec4899"}
        ]
    }

@app.get("/credit/history")
def credit_history():
    # Generate last 12 months of scores
    history = []
    current = random.randint(650, 850)
    now = datetime.now()
    for i in range(11, -1, -1):
        month_date = datetime(now.year, now.month, 1) - timedelta(days=30 * i)
        drift = random.randint(-10, 10)
        current = max(300, min(850, current + drift))
        history.append({
            "date": month_date.strftime("%Y-%m-01"),
            "score": current
        })
    return {"history": history}

@app.get("/transactions/top")
def txns_top():
    if insights.enabled():
        return sorted(demo_history.transactions(), key=lambda row: row["amount"], reverse=True)[:5]
    categories = ["Food", "Travel", "Shopping", "Entertainment", "Utilities", "Healthcare"]
    transactions = []
    
    for i in range(5):
        is_debit = random.choice([True, False])
        transactions.append({
            "id": f"TXN{1000 + i}",
            "date": (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "category": random.choice(categories),
            "type": "debit" if is_debit else "credit",
            "amount": random.randint(500, 5000),
            "merchant": random.choice(["Amazon", "Walmart", "Starbucks", "Shell", "Target", "Apple"])
        })
    
    # Sort by amount descending
    transactions.sort(key=lambda x: x["amount"], reverse=True)
    return transactions

@app.get("/transactions")
def txns(page:int=0):
    if insights.enabled():
        if page < 0:
            raise HTTPException(status_code=400, detail="Page must be nonnegative.")
        return demo_history.transactions(page)
    categories = ["Food", "Travel", "Shopping", "Entertainment", "Utilities", "Healthcare", "Groceries", "Gas"]
    transactions = []
    
    for i in range(20):
        is_debit = random.choice([True, True, False])  # More debits than credits
        transactions.append({
            "id": f"TXN{2000 + page * 20 + i}",
            "date": (datetime.now() - timedelta(days=random.randint(1, 180))).strftime("%Y-%m-%d"),
            "category": random.choice(categories),
            "type": "debit" if is_debit else "credit",
            "amount": random.randint(200, 5000),
            "merchant": random.choice(["Amazon", "Walmart", "Starbucks", "Shell", "Target", "Apple", "Netflix", "Uber"])
        })
    
    return transactions

@app.get("/loans/summary")
def loans_summary():
    """Returns all loans (active and closed) with L1 (summary) data"""
    if insights.enabled():
        return demo_history.loan_summaries()
    loans = [
        {
            "id": "LOAN001",
            "name": "Personal Loan",
            "type": "Personal",
            "outstanding": 50000,
            "original_amount": 100000,
            "interest_rate": 12.5,
            "emi": 4500,
            "next_due_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
            "tenure_remaining": "18 months",
            "status": "Active"
        },
        {
            "id": "LOAN002",
            "name": "Car Loan",
            "type": "Auto",
            "outstanding": 120000,
            "original_amount": 500000,
            "interest_rate": 9.5,
            "emi": 8500,
            "next_due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
            "tenure_remaining": "36 months",
            "status": "Active"
        },
        {
            "id": "LOAN003",
            "name": "Home Loan",
            "type": "Mortgage",
            "outstanding": 2500000,
            "original_amount": 3000000,
            "interest_rate": 8.0,
            "emi": 25000,
            "next_due_date": (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d"),
            "tenure_remaining": "120 months",
            "status": "Active"
        },
        {
            "id": "LOAN004",
            "name": "Education Loan",
            "type": "Education",
            "outstanding": 0,
            "original_amount": 200000,
            "interest_rate": 10.5,
            "emi": 0,
            "next_due_date": None,
            "tenure_remaining": "0 months",
            "status": "Closed",
            "closed_date": "2024-06-15"
        },
        {
            "id": "LOAN005",
            "name": "Business Loan",
            "type": "Business",
            "outstanding": 0,
            "original_amount": 750000,
            "interest_rate": 14.0,
            "emi": 0,
            "next_due_date": None,
            "tenure_remaining": "0 months",
            "status": "Closed",
            "closed_date": "2023-12-20"
        }
    ]
    return loans

@app.get("/loans/details/{loan_id}")
def loan_details(loan_id: str):
    """Returns L2 (detailed) data for a specific loan"""
    if insights.enabled():
        try:
            return demo_history.loan(loan_id, displayed=True)
        except KeyError:
            return {"error": "Loan not found"}
    # Generate payment history for last 18 months
    payment_history = []
    for i in range(18):
        payment_date = (datetime.now() - timedelta(days=30 * i)).strftime("%Y-%m-%d")
        month_year = (datetime.now() - timedelta(days=30 * i)).strftime("%B %Y")
        
        # Determine status - mostly paid, some late, occasional missed
        status_choice = random.choices(
            ["Paid", "Late", "Missed", "Pending"],
            weights=[85, 10, 3, 2],
            k=1
        )[0]
        
        # If paid or late, generate amounts
        if status_choice in ["Paid", "Late"]:
            amount = random.randint(4000, 9000)
            principal = random.randint(2000, 5000)
            interest = amount - principal
        else:
            amount = 0
            principal = 0
            interest = 0
        
        payment_history.append({
            "date": payment_date,
            "month_year": month_year,
            "amount": amount,
            "principal": principal,
            "interest": interest,
            "status": status_choice,
            "due_date": payment_date,
            "paid_date": payment_date if status_choice == "Paid" else (
                (datetime.now() - timedelta(days=30 * i) + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d") if status_choice == "Late" else None
            )
        })
    
    # Loan-specific details
    loan_details_map = {
        "LOAN001": {
            "id": "LOAN001",
            "name": "Personal Loan",
            "type": "Personal",
            "outstanding": 50000,
            "original_amount": 100000,
            "interest_rate": 12.5,
            "emi": 4500,
            "next_due_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
            "tenure_remaining": "18 months",
            "status": "Active",
            "disbursement_date": "2023-08-15",
            "maturity_date": "2026-08-15",
            "lender": "HDFC Bank",
            "account_number": "XXXX1234",
            "payment_history": payment_history,
            "total_paid": 50000,
            "total_interest_paid": 18500,
            "prepayment_charges": "2% of outstanding",
            "late_payment_fee": 500
        },
        "LOAN002": {
            "id": "LOAN002",
            "name": "Car Loan",
            "type": "Auto",
            "outstanding": 120000,
            "original_amount": 500000,
            "interest_rate": 9.5,
            "emi": 8500,
            "next_due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
            "tenure_remaining": "36 months",
            "status": "Active",
            "disbursement_date": "2022-02-01",
            "maturity_date": "2027-02-01",
            "lender": "ICICI Bank",
            "account_number": "XXXX5678",
            "payment_history": payment_history,
            "total_paid": 380000,
            "total_interest_paid": 95000,
            "prepayment_charges": "3% of outstanding",
            "late_payment_fee": 750,
            "vehicle_details": {
                "make": "Honda",
                "model": "City",
                "year": 2022,
                "registration": "MH01AB1234"
            }
        },
        "LOAN003": {
            "id": "LOAN003",
            "name": "Home Loan",
            "type": "Mortgage",
            "outstanding": 2500000,
            "original_amount": 3000000,
            "interest_rate": 8.0,
            "emi": 25000,
            "next_due_date": (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d"),
            "tenure_remaining": "120 months",
            "status": "Active",
            "disbursement_date": "2020-01-15",
            "maturity_date": "2035-01-15",
            "lender": "SBI",
            "account_number": "XXXX9012",
            "payment_history": payment_history,
            "total_paid": 500000,
            "total_interest_paid": 240000,
            "prepayment_charges": "1% of outstanding",
            "late_payment_fee": 1000,
            "property_details": {
                "address": "123 Main Street, Mumbai",
                "property_value": 4000000,
                "type": "Apartment"
            }
        },
        "LOAN004": {
            "id": "LOAN004",
            "name": "Education Loan",
            "type": "Education",
            "outstanding": 0,
            "original_amount": 200000,
            "interest_rate": 10.5,
            "emi": 0,
            "next_due_date": None,
            "tenure_remaining": "0 months",
            "status": "Closed",
            "disbursement_date": "2020-07-01",
            "maturity_date": "2024-07-01",
            "closed_date": "2024-06-15",
            "lender": "SBI",
            "account_number": "XXXX3456",
            "payment_history": payment_history,
            "total_paid": 200000,
            "total_interest_paid": 42000,
            "prepayment_charges": "Nil",
            "late_payment_fee": 0
        },
        "LOAN005": {
            "id": "LOAN005",
            "name": "Business Loan",
            "type": "Business",
            "outstanding": 0,
            "original_amount": 750000,
            "interest_rate": 14.0,
            "emi": 0,
            "next_due_date": None,
            "tenure_remaining": "0 months",
            "status": "Closed",
            "disbursement_date": "2021-01-15",
            "maturity_date": "2024-01-15",
            "closed_date": "2023-12-20",
            "lender": "HDFC Bank",
            "account_number": "XXXX7890",
            "payment_history": payment_history,
            "total_paid": 750000,
            "total_interest_paid": 157500,
            "prepayment_charges": "Nil",
            "late_payment_fee": 0
        }
    }
    
    return loan_details_map.get(loan_id, {"error": "Loan not found"})

@app.get("/loans/history")
def loans_history():
    return [
        {"date":"2025-"+str(random.randint(1,12)),"status":"Paid","amount":1500}
        for _ in range(40)
    ]

def _respond(context: dict, action: str, question: str | None = None) -> str:
    try:
        result = generate_grounded_text(context, action, question)
    except Exception as exc:
        logger.warning("Gemini request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="The assistant is temporarily unavailable. Please try again."
        ) from exc

    if not result.supported:
        if action == "ask":
            return "That information is not shown on this page."
        raise HTTPException(status_code=503, detail="A grounded summary could not be generated.")
    return result.text.strip()


def _answer(context, request, loan_id=None):
    question = request.question.strip()
    if not insights.enabled():
        return {"answer": _respond(context, "ask", question)}
    try:
        decision = insights.classify(question, context["page"], request.history)
        if decision.route == "insights":
            return insights.answer_insights(context, loan_id, question, request.history, decision)
    except InvalidPageData as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Insights request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The assistant is temporarily unavailable. Please try again.") from exc
    logger.info("assistant_route=direct scope=displayed")
    return {"answer": _respond(context, "ask", decision.resolved_question), "mode": "direct", "coverage": {"scope": "displayed"}}


@app.post("/loans/ask")
def ask_loan_question(request: LoanConversationRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Enter a question.")
    try:
        context = loan_context(request.loan_id, request.loan_data)
    except InvalidPageData as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _answer(context, request, request.loan_id)


@app.post("/loans/summarize")
def summarize_loan(request: LoanSummaryRequest):
    try:
        context = loan_context(request.loan_id, request.loan_data)
    except InvalidPageData as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"summary": _respond(context, "summarize")}


@app.post("/transactions/ask")
def ask_transactions_question(request: TransactionsConversationRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Enter a question.")
    try:
        context = transaction_context(request.transactions)
    except InvalidPageData as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _answer(context, request)


@app.post("/transactions/summarize")
def summarize_transactions(request: TransactionsSummaryRequest):
    try:
        context = transaction_context(request.transactions)
    except InvalidPageData as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"summary": _respond(context, "summarize")}
