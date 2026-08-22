class SmartCounsellingError(RuntimeError):
    def __init__(self, code, message, status=400, fields=None):
        self.code = code
        self.message = message
        self.status = int(status)
        self.fields = fields or {}
        super().__init__(message)


def validation_error(message, fields=None):
    return SmartCounsellingError("validation_error", message, 400, fields)
