from collections import Counter

from fastapi import APIRouter

from app.database import get_reviews, get_review_status_rows
from app.services.reminders import process_due_reminders

router = APIRouter()


@router.get("/admin/reviews")
def get_all_reviews():
    return get_reviews(order_desc=True)


@router.get("/admin/analytics")
def review_analytics():
    rows = get_reviews(order_desc=True)
    ratings = [row["rating"] for row in rows if row.get("rating")]
    total_requests = len(rows)
    completed_reviews = len(
        [
            row
            for row in rows
            if row.get("status") in {"completed", "feedback_received"} or row.get("rating")
        ]
    )
    pending_requests = max(total_requests - completed_reviews, 0)

    if len(ratings) == 0:
        return {
            "average_rating": 0,
            "total_reviews": 0,
            "positive_reviews": 0,
            "negative_reviews": 0,
            "total_requests": total_requests,
            "requests_sent": len([row for row in rows if row.get("status") != "request_pending"]),
            "completed_reviews": completed_reviews,
            "pending_requests": pending_requests,
        }

    avg = sum(ratings) / len(ratings)
    positive_reviews = len([rating for rating in ratings if rating >= 4])
    negative_reviews = len([rating for rating in ratings if rating <= 3])

    return {
        "average_rating": round(avg, 2),
        "total_reviews": len(ratings),
        "positive_reviews": positive_reviews,
        "negative_reviews": negative_reviews,
        "total_requests": total_requests,
        "requests_sent": len([row for row in rows if row.get("status") != "request_pending"]),
        "completed_reviews": completed_reviews,
        "pending_requests": pending_requests,
    }


@router.get("/admin/request-status-summary")
def request_status_summary():
    rows = get_review_status_rows()
    statuses = [row.get("status") or "unknown" for row in rows]
    return dict(Counter(statuses))


@router.post("/admin/process-reminders")
def run_reminder_job():
    return process_due_reminders()
