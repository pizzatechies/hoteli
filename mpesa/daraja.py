"""Thin client for Safaricom's Daraja API (OAuth, STK push, STK query, C2B URL registration)."""

import base64
import hashlib
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from .utils import daraja_timestamp

logger = logging.getLogger("mpesa")

SANDBOX_URL = "https://sandbox.safaricom.co.ke"
PRODUCTION_URL = "https://api.safaricom.co.ke"
STILL_PROCESSING_CODE = "500.001.1001"


class DarajaError(Exception):
    def __init__(self, message, code=None, response=None, status=None):
        super().__init__(message)
        self.code = code
        self.response = response
        self.status = status


class DarajaClient:
    def __init__(self):
        self.environment = settings.MPESA_ENVIRONMENT
        self.base_url = PRODUCTION_URL if self.environment == "production" else SANDBOX_URL
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = str(settings.MPESA_SHORTCODE)
        self.passkey = settings.MPESA_PASSKEY
        self.transaction_type = settings.MPESA_TRANSACTION_TYPE
        self.till_number = str(settings.MPESA_TILL_NUMBER or "")
        self.timeout = settings.MPESA_REQUEST_TIMEOUT

    # ------------------------------------------------------------------ auth
    @property
    def _token_cache_key(self):
        digest = hashlib.sha256(f"{self.consumer_key}:{self.environment}".encode()).hexdigest()[:16]
        return f"mpesa:token:{digest}"

    def get_access_token(self, force_refresh=False):
        if not (self.consumer_key and self.consumer_secret):
            raise DarajaError("M-Pesa consumer key and secret are not configured.")
        if not force_refresh:
            token = cache.get(self._token_cache_key)
            if token:
                return token
        try:
            resp = requests.get(
                f"{self.base_url}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(self.consumer_key, self.consumer_secret),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DarajaError(f"Could not reach M-Pesa ({exc.__class__.__name__}).") from exc
        if resp.status_code != 200:
            raise DarajaError(
                f"M-Pesa authentication failed (HTTP {resp.status_code}). Check the consumer key/secret "
                f"and that MPESA_ENVIRONMENT ({self.environment}) matches your Daraja app.",
                status=resp.status_code,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise DarajaError("M-Pesa returned an unreadable authentication response.") from exc
        token = data.get("access_token")
        if not token:
            raise DarajaError("M-Pesa did not return an access token.")
        expires_in = int(data.get("expires_in") or 3599)
        cache.set(self._token_cache_key, token, max(expires_in - 60, 60))
        return token

    def _post(self, path, payload, retry_auth=True):
        token = self.get_access_token()
        try:
            resp = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise DarajaError("M-Pesa did not respond in time. Please try again.", code="timeout") from exc
        except requests.RequestException as exc:
            raise DarajaError(f"Could not reach M-Pesa ({exc.__class__.__name__}).") from exc
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:500]}
        if resp.status_code == 401 and retry_auth:
            cache.delete(self._token_cache_key)
            return self._post(path, payload, retry_auth=False)
        if resp.status_code >= 400:
            message = data.get("errorMessage") or data.get("ResponseDescription") or f"HTTP {resp.status_code}"
            raise DarajaError(message, code=data.get("errorCode"), response=data, status=resp.status_code)
        return data

    # ------------------------------------------------------------------ STK push
    def password(self, timestamp):
        return base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()

    @property
    def party_b(self):
        if self.transaction_type == "CustomerBuyGoodsOnline" and self.till_number:
            return self.till_number
        return self.shortcode

    def stk_push(self, *, phone, amount, account_reference, description, callback_url):
        timestamp = daraja_timestamp()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": self.password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": self.transaction_type,
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.party_b,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": description[:13],
        }
        logger.info("STK push %s KES %s ref=%s", phone[:6] + "***", payload["Amount"], account_reference)
        data = self._post("/mpesa/stkpush/v1/processrequest", payload)
        if str(data.get("ResponseCode")) != "0":
            raise DarajaError(
                data.get("ResponseDescription") or "M-Pesa rejected the payment request.",
                code=data.get("ResponseCode"), response=data,
            )
        return data

    def stk_query(self, checkout_request_id):
        timestamp = daraja_timestamp()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": self.password(timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        return self._post("/mpesa/stkpushquery/v1/query", payload)

    # ------------------------------------------------------------------ B2C (refunds)
    def b2c_payment(self, *, originator_id, phone, amount, remarks, result_url, timeout_url, occasion=""):
        payload = {
            "OriginatorConversationID": originator_id,
            "InitiatorName": settings.MPESA_B2C_INITIATOR_NAME,
            "SecurityCredential": settings.MPESA_B2C_SECURITY_CREDENTIAL,
            "CommandID": settings.MPESA_B2C_COMMAND_ID,
            "Amount": int(amount),
            "PartyA": str(settings.MPESA_B2C_SHORTCODE),
            "PartyB": phone,
            "Remarks": remarks[:100] or "Refund",
            "QueueTimeOutURL": timeout_url,
            "ResultURL": result_url,
            "Occassion": occasion[:100],  # (sic) Daraja's field name
        }
        data = self._post("/mpesa/b2c/v3/paymentrequest", payload)
        if str(data.get("ResponseCode")) != "0":
            raise DarajaError(data.get("ResponseDescription") or "M-Pesa rejected the refund request.",
                              code=data.get("ResponseCode"), response=data)
        return data

    # ------------------------------------------------------------------ C2B (Paybill)
    def register_c2b_urls(self, *, confirmation_url, validation_url, response_type="Completed"):
        payload = {
            "ShortCode": str(settings.MPESA_C2B_SHORTCODE),
            "ResponseType": response_type,
            "ConfirmationURL": confirmation_url,
            "ValidationURL": validation_url,
        }
        return self._post("/mpesa/c2b/v2/registerurl", payload)

    def simulate_c2b(self, *, amount, msisdn, bill_ref_number):
        """Sandbox only: make Safaricom send a C2B confirmation to the registered URL."""
        if self.environment == "production":
            raise DarajaError("C2B simulation is only available in the sandbox.")
        payload = {
            "ShortCode": str(settings.MPESA_C2B_SHORTCODE),
            "CommandID": "CustomerPayBillOnline",
            "Amount": int(amount),
            "Msisdn": msisdn,
            "BillRefNumber": bill_ref_number,
        }
        return self._post("/mpesa/c2b/v1/simulate", payload)
