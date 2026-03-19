from flask import Blueprint

billing_bp = Blueprint("billing", __name__)

@billing_bp.route("/")
def billing_home():
    return "Billing module working"