# datasets_ui.py - the only dataset-specific part of the simple screens: how to explain an order and what to suggest.
# Reasons are checked in order; the first that applies decides the suggested action.
# Message templates are plain text for now (Phase 2 replaces them with AI drafts that use only these numbers).

UI = {
    "retail": {
        "order_noun": "order",
        "reasons": [
            ("cust_return_rate", ">=", 0.25, "this customer often returns or cancels items ({v:.0%} of earlier orders)", "confirm_quantities"),
            ("prod_rate_max", ">=", 0.15, "it contains a product that is often returned ({v:.0%})", "quality_check"),
            ("n_lines", ">=", 50, "it is a large order ({v:.0f} lines)", "confirm_details"),
            ("is_first_order", "==", 1, "it is this customer's first order", "confirm_details"),
        ],
        "default_action": "confirm_details",
        "actions": {
            "confirm_quantities": {
                "label": "Confirm quantities with the customer before dispatch",
                "audience": "customer",
                "template": "Hello, before we dispatch order {order_id}, could you confirm the quantities are as you need them?",
            },
            "quality_check": {
                "label": "Quality-check the often-returned item before dispatch",
                "audience": "warehouse",
                "template": "Order {order_id} contains an item with a high return rate. Please check it before it ships.",
            },
            "confirm_details": {
                "label": "Confirm the order details with the customer",
                "audience": "customer",
                "template": "Hello, thanks for order {order_id}. Could you take a moment to confirm the items and quantities before we ship?",
            },
        },
    },
}

GENERIC = {"order_noun": "order", "reasons": [], "default_action": "review",
           "actions": {"review": {"label": "Review this order", "audience": "team", "template": "Order {order_id} is flagged as high risk ({p:.0%})."}}}


def ui_for(key):
    return UI.get(key, GENERIC)
