"""ORACLE Billing, Subscription Quotas, Invoicing & Razorpay/Stripe Handlers."""
import time, hmac, hashlib

PLANS = {
    "starter": {
        "id": "starter",
        "name": "Starter / Shopkeeper",
        "price_inr": 0,
        "price_usd": 0,
        "interval": "monthly",
        "features": [
            "Up to 5 CSV/Excel uploads",
            "Core forecasting models (ETS, Holt)",
            "3 Basic AI agents (Data Quality, Demand, Cash flow)",
            "Manual data entry & basic export",
            "Single user seat"
        ],
        "quota_forecasts_per_mo": 100,
        "quota_storage_mb": 50
    },
    "pro": {
        "id": "pro",
        "name": "Pro Growth / E-commerce",
        "price_inr": 2499,
        "price_usd": 29,
        "interval": "monthly",
        "features": [
            "Unlimited CSV, Excel & Webhook data sync",
            "All 6 Specialized AI Agents + Autonomous actions",
            "Walk-forward backtesting & error calibration",
            "Multi-SKU Inventory & EOQ Planner",
            "Live market & commodities tracking",
            "Up to 5 team seats with RBAC (Owner/Analyst/Viewer)"
        ],
        "quota_forecasts_per_mo": 2500,
        "quota_storage_mb": 2048
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise Intelligence",
        "price_inr": 9999,
        "price_usd": 119,
        "interval": "monthly",
        "features": [
            "Custom ML pipelines & fine-tuned models",
            "Dedicated PostgreSQL cluster & custom migrations",
            "Automated multi-channel notifications (WhatsApp/Slack/Email)",
            "Unlimited team members with granular audit logs",
            "Priority CA & Financial model review assistance",
            "99.9% uptime SLA"
        ],
        "quota_forecasts_per_mo": 50000,
        "quota_storage_mb": 50000
    }
}

def get_plans():
    return {"kind": "actual", "currency": "INR", "plans": list(PLANS.values())}

def verify_razorpay_webhook(payload_body: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def generate_invoice(user_email: str, plan_id: str, ws_id: int):
    plan = PLANS.get(plan_id, PLANS["starter"])
    base_price = plan["price_inr"]
    gst_rate = 18.0
    gst_amount = round(base_price * (gst_rate / 100.0), 2)
    total_amount = round(base_price + gst_amount, 2)
    inv_number = f"ORC-INV-{ws_id}-{int(time.time())}"
    
    return {
        "kind": "calculated",
        "invoice_number": inv_number,
        "date": time.strftime("%Y-%m-%d"),
        "customer": user_email,
        "workspace_id": ws_id,
        "plan_name": plan["name"],
        "subtotal": base_price,
        "gst_rate_pct": gst_rate,
        "cgst": round(gst_amount / 2, 2) if base_price > 0 else 0,
        "sgst": round(gst_amount / 2, 2) if base_price > 0 else 0,
        "total_payable": total_amount,
        "currency": "INR",
        "payment_status": "PAID" if base_price == 0 else "PENDING_GATEWAY",
        "terms": "Software as a Service subscription. Billed monthly in advance. SAC Code: 998315 (Hosting & IT Infrastructure)."
    }
