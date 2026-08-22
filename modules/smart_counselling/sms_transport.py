from dataclasses import dataclass

from flask import current_app

from modules.core.sms import send_sms


class SmsDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmsDeliveryReceipt:
    message_id: str | None = None


class GatewaySmsTransport:
    def send(self, mobile, message):
        result = send_sms(mobile, message)
        if not result.get("success"):
            raise SmsDeliveryError("The verification message could not be delivered. Please try again.")
        return SmsDeliveryReceipt(message_id=str(result.get("message_id") or "") or None)


class DisabledSmsTransport:
    def send(self, mobile, message):
        raise SmsDeliveryError("OTP delivery is not enabled in this environment.")


def get_sms_transport():
    injected = current_app.config.get("SMART_COUNSELLING_SMS_TRANSPORT")
    if injected is not None:
        return injected() if isinstance(injected, type) else injected
    if current_app.config.get("SMART_COUNSELLING_OTP_DELIVERY_MODE") == "gateway":
        return GatewaySmsTransport()
    return DisabledSmsTransport()
