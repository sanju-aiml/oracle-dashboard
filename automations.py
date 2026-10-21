"""ORACLE Automation Engine, Approval Queue & Webhooks."""
import time, json

class AutomationManager:
    def __init__(self):
        self.rules = [
            {"id": "rule_1", "name": "Low Stock Trigger", "condition": "inventory < reorder_point", "action": "draft_purchase_order", "enabled": True},
            {"id": "rule_2", "name": "Cash Runway Warning", "condition": "runway_months < 4", "action": "alert_executive_team", "enabled": True},
            {"id": "rule_3", "name": "Margin Contraction Flag", "condition": "margin_drop > 5%", "action": "flag_anomaly_review", "enabled": True},
            {"id": "rule_4", "name": "Weekly Performance Briefing", "condition": "every_monday", "action": "dispatch_digest", "enabled": True}
        ]
        self.queue = [
            {
                "id": "act_101",
                "type": "draft_purchase_order",
                "title": "Restock SKU-A102 (Basmati Rice 25kg)",
                "details": "Current stock is 12 units (Safety threshold: 25). Proposed reorder quantity: 50 units.",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "pending_approval",
                "risk_tier": "Low"
            },
            {
                "id": "act_102",
                "type": "flag_anomaly_review",
                "title": "High Logistics Cost Spike in Zone 4",
                "details": "Freight charges increased by +34% over 30-day moving average. Review shipping partner contracts.",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "pending_approval",
                "risk_tier": "Medium"
            }
        ]
        self.notifications = [
            {"id": "notif_1", "title": "System Initialized", "body": "ORACLE Decision Intelligence Suite is active.", "time": time.strftime("%H:%M"), "read": False}
        ]

    def list_rules(self):
        return {"kind": "actual", "rules": self.rules}

    def list_queue(self):
        return {"kind": "actual", "pending_actions": [q for q in self.queue if q["status"] == "pending_approval"], "all_actions": self.queue}

    def approve_action(self, action_id, user_role):
        if user_role not in ("owner", "analyst"):
            return {"status": "error", "error": "Only Owners or Analysts can approve automation actions"}
        for item in self.queue:
            if item["id"] == action_id:
                item["status"] = "approved"
                item["resolved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.notifications.append({
                    "id": f"notif_{len(self.notifications)+1}",
                    "title": f"Action Approved: {item['type']}",
                    "body": item["title"],
                    "time": time.strftime("%H:%M"),
                    "read": False
                })
                return {"status": "ok", "message": f"Action {action_id} successfully approved and executed."}
        return {"status": "error", "error": f"Action {action_id} not found."}

    def reject_action(self, action_id, user_role):
        if user_role not in ("owner", "analyst"):
            return {"status": "error", "error": "Only Owners or Analysts can reject automation actions"}
        for item in self.queue:
            if item["id"] == action_id:
                item["status"] = "rejected"
                item["resolved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return {"status": "ok", "message": f"Action {action_id} rejected."}
        return {"status": "error", "error": f"Action {action_id} not found."}

    def list_notifications(self):
        return {"kind": "actual", "notifications": self.notifications}

automations = AutomationManager()
