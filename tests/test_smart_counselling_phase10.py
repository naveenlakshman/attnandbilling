import pytest

from config import Config


def test_production_configuration_requires_dedicated_otp_secret(monkeypatch):
    monkeypatch.setattr(Config,"APP_ENV","production")
    monkeypatch.setattr(Config,"SECRET_KEY","a"*40)
    monkeypatch.setattr(Config,"SMART_COUNSELLING_OTP_SECRET","a"*40)
    monkeypatch.setattr(Config,"DEBUG_MODE",False)
    monkeypatch.setattr(Config,"SESSION_COOKIE_SECURE",True)
    monkeypatch.setattr(Config,"RATELIMIT_STORAGE_URI","redis://redis:6379/0")
    monkeypatch.setattr(Config,"SMART_COUNSELLING_OTP_DELIVERY_MODE","gateway")
    monkeypatch.setattr(Config,"SMS_GATEWAY_USER","configured")
    monkeypatch.setattr(Config,"SMS_GATEWAY_PASSWORD","configured")
    monkeypatch.setattr(Config,"DB_TYPE","mysql")
    monkeypatch.setattr(Config,"STORAGE_PROVIDER","gcs")
    with pytest.raises(RuntimeError,match="SMART_COUNSELLING_OTP_SECRET"):
        Config.validate()


def test_production_configuration_accepts_separate_otp_secret(monkeypatch):
    monkeypatch.setattr(Config,"APP_ENV","production")
    monkeypatch.setattr(Config,"SECRET_KEY","a"*40)
    monkeypatch.setattr(Config,"SMART_COUNSELLING_OTP_SECRET","b"*40)
    monkeypatch.setattr(Config,"DEBUG_MODE",False)
    monkeypatch.setattr(Config,"SESSION_COOKIE_SECURE",True)
    monkeypatch.setattr(Config,"RATELIMIT_STORAGE_URI","redis://redis:6379/0")
    monkeypatch.setattr(Config,"SMART_COUNSELLING_OTP_DELIVERY_MODE","gateway")
    monkeypatch.setattr(Config,"SMS_GATEWAY_USER","configured")
    monkeypatch.setattr(Config,"SMS_GATEWAY_PASSWORD","configured")
    monkeypatch.setattr(Config,"DB_TYPE","mysql")
    monkeypatch.setattr(Config,"STORAGE_PROVIDER","gcs")
    Config.validate()
